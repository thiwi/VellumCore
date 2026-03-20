"""Reference prover service: authenticated job intake and queue submission."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from vellum_core.auth import AuthManager, BEARER_SCHEME
from vellum_core.config import Settings
from vellum_core.database import Database
from vellum_core.errors import APIError, register_exception_handlers
from vellum_core.logic.batcher import MAX_BATCH_SIZE, batch_prepare_input
from vellum_core.metrics import prometheus_payload
from vellum_core.proof_store import VellumAuditStore
from vellum_core.runtime import build_framework_client
from vellum_core.schemas import (
    DEFAULT_BATCH_CIRCUIT_ID,
    BatchProveRequest,
    HealthResponse,
    ProofStatusResponse,
    ProveAcceptedResponse,
)
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


settings = Settings.from_env()
framework = build_framework_client(settings)
db = Database(settings.database_url)
vault_client = VaultTransitClient(addr=settings.vault_addr, token=settings.vault_token)
key_cache = VaultPublicKeyCache(
    client=vault_client,
    ttl_seconds=settings.vault_public_key_cache_ttl_seconds,
)
auth_manager = AuthManager(
    vault_client=vault_client,
    key_cache=key_cache,
    jwt_key_name=settings.vault_jwt_key,
    jwt_issuer=settings.jwt_issuer,
    jwt_audience=settings.jwt_audience,
    bank_key_mapping=settings.bank_key_mapping,
    redis_url=settings.redis_url,
    nonce_window_seconds=settings.nonce_window_seconds,
)
audit_store = VellumAuditStore(
    db=db,
    vault=vault_client,
    audit_key_name=settings.vault_audit_key,
)

app = FastAPI(title="Vellum Prover Service", version="4.0.0")
register_exception_handlers(app)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize database schema on service startup."""
    await db.init_models()


async def require_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
) -> dict[str, Any]:
    """FastAPI dependency that validates bearer JWT and returns claims."""
    return await auth_manager.verify_jwt_credentials(credentials)


async def _decode_and_authenticate(request: Request) -> BatchProveRequest:
    """Verify bank handshake over raw body and validate request schema."""
    raw_body = await request.body()
    await auth_manager.verify_handshake(request, raw_body)
    try:
        return BatchProveRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        raise APIError(
            status_code=422,
            code="invalid_request",
            message="Request body does not match schema",
            details={"reason": str(exc)},
        ) from exc


@app.get("/healthz", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    """Liveness/readiness endpoint."""
    return HealthResponse(status="ok")


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    payload, content_type = prometheus_payload()
    return Response(content=payload, media_type=content_type)


@app.post("/v1/proofs/batch", status_code=202, response_model=ProveAcceptedResponse)
async def create_batch_proof(
    request: Request,
    _: dict[str, Any] = Depends(require_jwt),
) -> ProveAcceptedResponse:
    """Create asynchronous proof job for one circuit/request mode payload."""
    payload = await _decode_and_authenticate(request)
    circuit_id = payload.circuit_id

    private_input: dict[str, Any] | None = None
    source_ref: str | None = payload.source_ref

    if payload.private_input is not None:
        private_input = payload.private_input
    elif payload.source_ref is None:
        assert payload.balances is not None
        assert payload.limits is not None
        try:
            prepared = batch_prepare_input(
                balances=payload.balances,
                limits=payload.limits,
            )
        except ValueError as exc:
            raise APIError(
                status_code=422,
                code="invalid_batch_input",
                message="Batch payload invalid",
                details={"reason": str(exc)},
            ) from exc
        private_input = prepared.to_circuit_input()

    metadata: dict[str, Any] = {
        "mode": "batch",
        "request_id": payload.request_id,
        "source_mode": (
            "source_ref"
            if source_ref is not None
            else ("private_input" if payload.private_input is not None else "direct")
        ),
    }
    if circuit_id == DEFAULT_BATCH_CIRCUIT_ID:
        metadata["batch_size"] = (
            len(payload.balances)
            if payload.balances is not None
            else MAX_BATCH_SIZE
        )

    proof_id = str(uuid4())

    await db.create_proof_job(
        proof_id=proof_id,
        circuit_id=circuit_id,
        status="queued",
        request_payload=payload.model_dump(),
        private_input=private_input,
        source_ref=source_ref,
        metadata=metadata,
    )

    await audit_store.append_event(
        proof_id=proof_id,
        circuit_id=circuit_id,
        status="queued",
        public_signals=[],
        metadata=metadata,
    )

    await framework.job_backend.enqueue(
        task_name="worker.process_proof_job",
        args=[proof_id],
        queue=settings.celery_queue,
    )

    return ProveAcceptedResponse(proof_id=proof_id, status="queued")


@app.get("/v1/proofs/{proof_id}", response_model=ProofStatusResponse)
async def get_proof_status(
    proof_id: str,
    _: dict[str, Any] = Depends(require_jwt),
) -> ProofStatusResponse:
    """Return persisted status and optional outputs for one proof job."""
    job = await db.get_proof_job(proof_id)
    if job is None:
        raise APIError(
            status_code=404,
            code="unknown_proof_id",
            message="No proof found for id",
            details={"proof_id": proof_id},
        )

    return ProofStatusResponse(
        proof_id=job.proof_id,
        status=job.status,
        circuit_id=job.circuit_id,
        public_signals=job.public_signals or [],
        proof=job.proof,
        error=job.error,
        metadata=job.meta,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@app.get("/v1/proofs")
async def list_proofs(
    _: dict[str, Any] = Depends(require_jwt),
    status: str | None = Query(default=None),
    circuit_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List recent proof jobs with optional status/circuit filters."""
    jobs = await db.list_proof_jobs(
        status=status,
        circuit_id=circuit_id,
        limit=limit,
    )
    return {
        "items": [
            {
                "proof_id": job.proof_id,
                "status": job.status,
                "circuit_id": job.circuit_id,
                "error": job.error,
                "metadata": job.meta,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            }
            for job in jobs
        ],
        "count": len(jobs),
        "filters": {
            "status": status,
            "circuit_id": circuit_id,
            "limit": limit,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("prover_service:app", host="0.0.0.0", port=8001, reload=False)
