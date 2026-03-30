"""Reference prover service: authenticated job intake and queue submission."""

from __future__ import annotations

import logging
from typing import Any, TypeVar
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ValidationError

from vellum_core.api.errors import FrameworkError
from vellum_core.auth import AuthManager, BEARER_SCHEME
from vellum_core.config import Settings
from vellum_core.database import Database
from vellum_core.errors import APIError, register_exception_handlers
from vellum_core.http_legacy import mark_legacy_api
from vellum_core.logic.batcher import MAX_BATCH_SIZE, batch_prepare_input
from vellum_core.logic.private_input_schema import validate_private_input_schema
from vellum_core.metrics import prometheus_payload
from vellum_core.observability import configure_logging, init_telemetry
from vellum_core.policies.dual_track import prepare_reference_track
from vellum_core.policy_registry import PolicyManifestError, PolicyNotFoundError
from vellum_core.proof_store import VellumAuditStore
from vellum_core.registry import CircuitNotFoundError
from vellum_core.runtime import build_framework_client
from vellum_core.security import (
    SecurityEventLogger,
    build_input_summary,
    compute_input_fingerprint,
    seal_job_payload,
)
from vellum_core.schemas import (
    DEFAULT_BATCH_CIRCUIT_ID,
    BatchProveRequest,
    HealthResponse,
    PolicyRunAcceptedResponse,
    PolicyRunRequest,
    PolicyRunStatusResponse,
    ProofStatusResponse,
    ProveAcceptedResponse,
)
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


PayloadModel = TypeVar("PayloadModel", bound=BaseModel)


settings = Settings.from_env()
configure_logging(settings.app_name)
logger = logging.getLogger(__name__)
framework = build_framework_client(settings)
db = Database(settings.database_url)
vault_client = VaultTransitClient(
    addr=settings.vault_addr,
    token=settings.vault_token,
    tls_ca_bundle=settings.tls_ca_bundle,
)
key_cache = VaultPublicKeyCache(
    client=vault_client,
    ttl_seconds=settings.vault_public_key_cache_ttl_seconds,
)
security_logger = SecurityEventLogger(db)
auth_manager = AuthManager(
    vault_client=vault_client,
    key_cache=key_cache,
    jwt_key_name=settings.vault_jwt_key,
    jwt_issuer=settings.jwt_issuer,
    jwt_audience=settings.jwt_audience,
    bank_key_mapping=settings.bank_key_mapping,
    redis_url=settings.redis_url,
    nonce_window_seconds=settings.nonce_window_seconds,
    jwt_max_ttl_seconds=settings.jwt_max_ttl_seconds,
    jwt_leeway_seconds=settings.jwt_leeway_seconds,
    submit_rate_limit_per_minute=settings.submit_rate_limit_per_minute,
    security_event_recorder=security_logger.record,
)
audit_store = VellumAuditStore(
    db=db,
    vault=vault_client,
    audit_key_name=settings.vault_audit_key,
)

app = FastAPI(title="Vellum Prover Service", version="5.0.0")
register_exception_handlers(app)
init_telemetry(
    service_name=settings.app_name,
    fastapi_app=app,
    instrument_httpx=True,
    sql_engines=[db.engine],
)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize database schema on service startup."""
    logger.info("prover_startup_db_init")
    await db.init_models()


def require_jwt_with_scopes(*scopes: str):
    """Build a JWT dependency that enforces one set of required scopes."""

    async def _dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
    ) -> dict[str, Any]:
        return await auth_manager.verify_jwt_credentials(
            credentials,
            required_scopes=set(scopes),
        )

    return _dependency


async def _decode_and_authenticate(request: Request) -> tuple[BatchProveRequest, str]:
    """Verify bank handshake over raw body and validate request schema."""
    return await _decode_and_authenticate_payload(
        request,
        payload_model=BatchProveRequest,
        validation_message="Request body does not match schema",
    )


async def _decode_and_authenticate_payload(
    request: Request,
    *,
    payload_model: type[PayloadModel],
    validation_message: str,
) -> tuple[PayloadModel, str]:
    """Verify bank handshake and parse payload into one Pydantic model."""
    raw_body = await request.body()
    _enforce_submit_body_size(raw_body=raw_body, path=request.url.path)
    bank_key_id = await auth_manager.verify_handshake(request, raw_body)
    try:
        payload = payload_model.model_validate_json(raw_body)
    except ValidationError as exc:
        raise APIError(
            status_code=422,
            code="invalid_request",
            message=validation_message,
            details={"reason": str(exc)},
        ) from exc
    return payload, bank_key_id


def _enforce_submit_body_size(*, raw_body: bytes, path: str) -> None:
    """Reject oversized submit payloads before auth/model decoding work."""
    if len(raw_body) <= settings.max_submit_body_bytes:
        return
    raise APIError(
        status_code=413,
        code="payload_too_large",
        message="Request payload exceeds configured size limit",
        details={
            "path": path,
            "limit_bytes": settings.max_submit_body_bytes,
            "received_bytes": len(raw_body),
        },
    )


def _validate_private_input_schema_or_raise(
    *,
    circuit_id: str,
    private_input: dict[str, Any],
) -> None:
    """Validate private_input against the selected circuit's manifest schema."""
    try:
        manifest = framework.circuit_manager.registry.get_manifest(circuit_id)
    except CircuitNotFoundError as exc:
        raise APIError(
            status_code=404,
            code="unknown_circuit",
            message="Circuit id not found",
            details={"circuit_id": circuit_id},
        ) from exc

    try:
        validate_private_input_schema(
            input_schema=manifest.input_schema,
            private_input=private_input,
        )
    except ValueError as exc:
        raise APIError(
            status_code=422,
            code="invalid_private_input_schema",
            message="private_input does not satisfy circuit input_schema",
            details={"circuit_id": circuit_id, "reason": str(exc)},
        ) from exc


async def _decode_and_authenticate_policy(request: Request) -> tuple[PolicyRunRequest, str]:
    """Verify bank handshake over raw body and validate v5 policy-run schema."""
    return await _decode_and_authenticate_payload(
        request,
        payload_model=PolicyRunRequest,
        validation_message="Request body does not match policy-run schema",
    )


def _load_policy_manifest(policy_id: str) -> Any:
    """Resolve policy manifest or raise standardized unknown-policy error."""
    try:
        return framework.policy_registry.get_manifest(policy_id)
    except PolicyNotFoundError as exc:
        raise APIError(
            status_code=404,
            code="unknown_policy",
            message="Policy id not found",
            details={"policy_id": policy_id},
        ) from exc
    except PolicyManifestError as exc:
        raise APIError(
            status_code=422,
            code="policy_manifest_invalid",
            message="Policy manifest failed validation",
            details={"policy_id": policy_id, "reason": str(exc)},
        ) from exc


async def _resolve_policy_evidence(
    *,
    run_id: str,
    payload: PolicyRunRequest,
) -> tuple[dict[str, Any], str | None]:
    """Resolve policy evidence payload and canonical evidence reference."""
    if payload.evidence_payload is not None:
        evidence_ref = await framework.evidence_store.put(
            run_id=run_id,
            payload=payload.evidence_payload,
        )
        return payload.evidence_payload, evidence_ref

    assert payload.evidence_ref is not None
    try:
        evidence_payload = await framework.evidence_store.get(reference=payload.evidence_ref)
    except Exception as exc:
        raise APIError(
            status_code=422,
            code="invalid_evidence_ref",
            message="Unable to resolve evidence_ref",
            details={"evidence_ref": payload.evidence_ref, "reason": str(exc)},
        ) from exc
    return evidence_payload, payload.evidence_ref


def _policy_run_metadata(
    *,
    payload: PolicyRunRequest,
    claims: dict[str, Any],
    bank_key_id: str,
    policy_version: str,
    attestation_id: str,
    evidence_ref: str | None,
) -> dict[str, Any]:
    """Build normalized metadata persisted for policy-run lifecycle tracking."""
    return {
        "mode": "policy_run",
        "api_version": "v5",
        "request_id": payload.request_id,
        "auth_subject": claims.get("sub"),
        "bank_key_id": bank_key_id,
        "policy_id": payload.policy_id,
        "policy_version": policy_version,
        "attestation_id": attestation_id,
        "evidence_ref": evidence_ref,
        "decision": None,
        "context": payload.context,
    }


def _unknown_run_id_error(run_id: str) -> APIError:
    """Return standardized unknown-run error payload for v5 status lookups."""
    return APIError(
        status_code=404,
        code="unknown_run_id",
        message="No policy run found for id",
        details={"run_id": run_id},
    )


async def _persist_and_enqueue_job(
    *,
    proof_id: str,
    circuit_id: str,
    request_payload: dict[str, Any],
    source_mode: str,
    sealed_payload: str,
    metadata: dict[str, Any],
) -> None:
    """Persist queued job state, append audit event, and enqueue worker task."""
    await db.create_proof_job(
        proof_id=proof_id,
        circuit_id=circuit_id,
        status="queued",
        sealed_job_payload=sealed_payload,
        input_fingerprint=compute_input_fingerprint(
            source_mode=source_mode,
            payload=request_payload,
        ),
        input_summary=build_input_summary(
            source_mode=source_mode,
            payload=request_payload,
            circuit_id=circuit_id,
        ),
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


@app.get("/healthz", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    """Liveness/readiness endpoint."""
    return HealthResponse(status="ok")


@app.get("/metrics")
async def metrics(
    credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
) -> Response:
    """Prometheus metrics endpoint."""
    if settings.metrics_require_auth:
        await auth_manager.verify_jwt_credentials(
            credentials,
            required_scopes={"proofs:read"},
        )
    payload, content_type = prometheus_payload()
    return Response(content=payload, media_type=content_type)


@app.post("/v1/proofs/batch", status_code=202, response_model=ProveAcceptedResponse)
async def create_batch_proof(
    request: Request,
    response: Response,
    claims: dict[str, Any] = Depends(require_jwt_with_scopes("proofs:write")),
) -> ProveAcceptedResponse:
    """Create asynchronous proof job for one circuit/request mode payload."""
    mark_legacy_api(response)
    payload, bank_key_id = await _decode_and_authenticate(request)
    circuit_id = payload.circuit_id

    private_input: dict[str, Any] | None = None

    if payload.private_input is not None:
        private_input = payload.private_input
    else:
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

    assert private_input is not None
    _validate_private_input_schema_or_raise(
        circuit_id=circuit_id,
        private_input=private_input,
    )

    metadata: dict[str, Any] = {
        "mode": "batch",
        "request_id": payload.request_id,
        "auth_subject": claims.get("sub"),
        "bank_key_id": bank_key_id,
        "source_mode": (
            "private_input" if payload.private_input is not None else "direct"
        ),
    }
    if circuit_id == DEFAULT_BATCH_CIRCUIT_ID:
        metadata["batch_size"] = (
            len(payload.balances)
            if payload.balances is not None
            else MAX_BATCH_SIZE
        )

    proof_id = str(uuid4())
    request_payload = payload.model_dump()
    source_mode = str(metadata["source_mode"])
    sealed_payload = await seal_job_payload(
        vault_client=vault_client,
        key_name=settings.vellum_data_key,
        request_payload=request_payload,
        private_input=private_input,
    )

    await _persist_and_enqueue_job(
        proof_id=proof_id,
        circuit_id=circuit_id,
        request_payload=request_payload,
        source_mode=source_mode,
        sealed_payload=sealed_payload,
        metadata=metadata,
    )

    logger.info(
        "proof_job_queued",
        extra={
            "proof_id": proof_id,
            "circuit_id": circuit_id,
            "source_mode": metadata.get("source_mode"),
            "auth_subject": claims.get("sub"),
        },
    )

    return ProveAcceptedResponse(proof_id=proof_id, status="queued")


@app.get("/v1/proofs/{proof_id}", response_model=ProofStatusResponse)
async def get_proof_status(
    proof_id: str,
    response: Response,
    _: dict[str, Any] = Depends(require_jwt_with_scopes("proofs:read")),
) -> ProofStatusResponse:
    """Return persisted status and optional outputs for one proof job."""
    mark_legacy_api(response)
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
    response: Response,
    _: dict[str, Any] = Depends(require_jwt_with_scopes("proofs:read")),
    status: str | None = Query(default=None),
    circuit_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List recent proof jobs with optional status/circuit filters."""
    mark_legacy_api(response)
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


@app.post("/v5/policy-runs", status_code=202, response_model=PolicyRunAcceptedResponse)
async def create_policy_run(
    request: Request,
    claims: dict[str, Any] = Depends(require_jwt_with_scopes("proofs:write")),
) -> PolicyRunAcceptedResponse:
    """Create asynchronous v5 policy run for lending-risk compliance workflows."""
    payload, bank_key_id = await _decode_and_authenticate_policy(request)
    policy_manifest = _load_policy_manifest(payload.policy_id)

    run_id = str(uuid4())
    attestation_id = f"att-{run_id}"
    evidence_payload, evidence_ref = await _resolve_policy_evidence(
        run_id=run_id,
        payload=payload,
    )

    try:
        reference_result = prepare_reference_track(
            reference_policy=policy_manifest.reference_policy,
            differential_outputs=policy_manifest.differential_outputs,
            evidence_payload=evidence_payload,
        )
    except FrameworkError as exc:
        raise APIError(
            status_code=422,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        ) from exc

    metadata = _policy_run_metadata(
        payload=payload,
        claims=claims,
        bank_key_id=bank_key_id,
        policy_version=policy_manifest.policy_version,
        attestation_id=attestation_id,
        evidence_ref=evidence_ref,
    )

    request_payload = payload.model_dump()
    _validate_private_input_schema_or_raise(
        circuit_id=policy_manifest.circuit_id,
        private_input=reference_result.private_input,
    )
    sealed_payload = await seal_job_payload(
        vault_client=vault_client,
        key_name=settings.vellum_data_key,
        request_payload=request_payload,
        private_input=reference_result.private_input,
        dual_track_reference={
            "decision": reference_result.decision,
            "outputs": reference_result.outputs,
        },
    )

    await _persist_and_enqueue_job(
        proof_id=run_id,
        circuit_id=policy_manifest.circuit_id,
        request_payload=request_payload,
        source_mode="policy_run",
        sealed_payload=sealed_payload,
        metadata=metadata,
    )

    logger.info(
        "policy_run_queued",
        extra={
            "run_id": run_id,
            "policy_id": payload.policy_id,
            "circuit_id": policy_manifest.circuit_id,
            "auth_subject": claims.get("sub"),
        },
    )

    return PolicyRunAcceptedResponse(
        run_id=run_id,
        policy_id=payload.policy_id,
        status="queued",
        attestation_id=attestation_id,
    )


@app.get("/v5/policy-runs/{run_id}", response_model=PolicyRunStatusResponse)
async def get_policy_run_status(
    run_id: str,
    _: dict[str, Any] = Depends(require_jwt_with_scopes("proofs:read")),
) -> PolicyRunStatusResponse:
    """Return status and decision metadata for one v5 policy run."""
    job = await db.get_proof_job(run_id)
    if job is None:
        raise _unknown_run_id_error(run_id)

    metadata = job.meta or {}
    policy_id = metadata.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id:
        raise _unknown_run_id_error(run_id)

    decision_value = metadata.get("decision")
    decision = decision_value if decision_value in {"pass", "fail"} else None

    return PolicyRunStatusResponse(
        run_id=run_id,
        policy_id=policy_id,
        status=job.status,
        circuit_id=job.circuit_id,
        decision=decision,
        attestation_id=str(metadata.get("attestation_id") or f"att-{run_id}"),
        evidence_ref=metadata.get("evidence_ref"),
        metadata=metadata,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("prover_service:app", host="0.0.0.0", port=8001, reload=False)
