"""Reference verifier service for proof checks, circuits, and audit integrity."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import Response

from vellum_core.attestation_bundle import (
    artifact_digests,
    sha256_json,
    signature_chain,
)
from vellum_core.api.types import VerificationRequest as EngineVerificationRequest
from vellum_core.auth import AuthManager
from vellum_core.config import Settings
from vellum_core.database import Database
from vellum_core.errors import APIError, register_exception_handlers
from vellum_core.http_auth import (
    build_optional_scoped_jwt_dependency,
    build_required_scoped_jwt_dependency,
)
from vellum_core.metrics import (
    observe_verify_duration,
    prometheus_payload,
    set_native_baseline,
    trust_speed_snapshot,
)
from vellum_core.observability import configure_logging, init_telemetry
from vellum_core.proof_store import VellumAuditStore, VellumIntegrityService
from vellum_core.security import SecurityEventLogger
from vellum_core.runtime import build_framework_client
from vellum_core.schemas import (
    AuditChainVerifyResponse,
    AttestationResponseV6,
    CircuitsResponse,
    HealthResponse,
    PolicyDescriptorV6,
    TrustSpeedResponse,
    VerifyRequest,
    VerifyResponse,
)
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient
from vellum_core.versioning import HTTP_API_PREFIX, PACKAGE_VERSION


settings = Settings.from_env()
configure_logging(settings.app_name)
logger = logging.getLogger(__name__)
db = Database(settings.database_url)
framework = build_framework_client(settings)
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
integrity_service = VellumIntegrityService(
    db=db,
    key_cache=key_cache,
    audit_key_name=settings.vault_audit_key,
)

app = FastAPI(title="Vellum Verifier Service", version=PACKAGE_VERSION)
register_exception_handlers(app)
init_telemetry(
    service_name=settings.app_name,
    fastapi_app=app,
    instrument_httpx=True,
    sql_engines=[db.engine],
)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize schema and baseline metrics at startup."""
    logger.info("verifier_startup_init")
    await db.init_models()
    set_native_baseline(settings.native_verify_baseline_seconds)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Close long-lived network clients."""
    await vault_client.aclose()


def require_jwt_with_scopes(*scopes: str):
    """Build a JWT dependency that enforces one set of required scopes."""
    return build_required_scoped_jwt_dependency(auth_manager, *scopes)


require_metrics_auth = build_optional_scoped_jwt_dependency(
    auth_manager,
    "audit:read",
    enabled=settings.metrics_require_auth,
)


def _unknown_run_id_error(run_id: str) -> APIError:
    """Return standardized unknown-run error payload."""
    return APIError(
        status_code=404,
        code="unknown_run_id",
        message="No run found for id",
        details={"run_id": run_id},
    )


def _policy_id_from_job_metadata(*, run_id: str, metadata: dict[str, Any]) -> str:
    """Resolve policy id from job metadata or raise standardized run error."""
    policy_id = metadata.get("policy_id")
    if not isinstance(policy_id, str) or policy_id == "":
        raise _unknown_run_id_error(run_id)
    return policy_id


@app.get("/healthz", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    """Liveness/readiness endpoint."""
    return HealthResponse(status="ok")


@app.get("/metrics")
async def metrics(
    _: dict[str, Any] | None = Depends(require_metrics_auth),
) -> Response:
    """Prometheus metrics endpoint."""
    payload, content_type = prometheus_payload()
    return Response(content=payload, media_type=content_type)


@app.post(f"{HTTP_API_PREFIX}/verify", response_model=VerifyResponse)
async def verify(
    payload: VerifyRequest,
    _: dict[str, Any] = Depends(require_jwt_with_scopes("proofs:write")),
) -> VerifyResponse:
    """Verify a proof tuple and append verification event to audit chain."""
    started = time.perf_counter()
    result = await framework.proof_engine.verify(
        EngineVerificationRequest(
            circuit_id=payload.circuit_id,
            proof=payload.proof,
            public_signals=payload.public_signals,
        )
    )
    verify_seconds = time.perf_counter() - started
    verification_ms = result.verification_ms
    observe_verify_duration(verify_seconds)

    await audit_store.append_event(
        proof_id=None,
        circuit_id=payload.circuit_id,
        public_signals=payload.public_signals,
        status="completed" if result.valid else "failed",
        proof_payload=payload.proof,
        metadata={"event": "verification", "result": "valid" if result.valid else "invalid"},
    )
    logger.info(
        "proof_verified",
        extra={
            "circuit_id": payload.circuit_id,
            "valid": result.valid,
            "verification_ms": verification_ms,
        },
    )

    return VerifyResponse(
        valid=result.valid,
        verified_at=datetime.now(timezone.utc),
        verification_ms=verification_ms,
    )


@app.get(f"{HTTP_API_PREFIX}/circuits", response_model=CircuitsResponse)
async def list_circuits(
    _: dict[str, Any] = Depends(require_jwt_with_scopes("proofs:read")),
) -> CircuitsResponse:
    """Return circuit artifact readiness list from framework manager."""
    return CircuitsResponse(
        circuits=[
            entry.model_dump()
            for entry in framework.circuit_manager.list_with_validation()
        ]
    )


@app.get(f"{HTTP_API_PREFIX}/audit/verify-chain", response_model=AuditChainVerifyResponse)
async def verify_audit_chain(
    _: dict[str, Any] = Depends(require_jwt_with_scopes("audit:read")),
) -> AuditChainVerifyResponse:
    """Verify full audit-chain integrity."""
    report = await integrity_service.verify_chain()
    return AuditChainVerifyResponse.model_validate(report)


@app.get(f"{HTTP_API_PREFIX}/trust-speed", response_model=TrustSpeedResponse)
async def trust_speed(
    _: dict[str, Any] = Depends(require_jwt_with_scopes("audit:read")),
) -> TrustSpeedResponse:
    """Return trust-speed snapshot from verification metrics."""
    return TrustSpeedResponse.model_validate(trust_speed_snapshot())


@app.get(f"{HTTP_API_PREFIX}/runs/{{run_id}}/attestation", response_model=AttestationResponseV6)
async def export_attestation(
    run_id: str,
    _: dict[str, Any] = Depends(require_jwt_with_scopes("audit:read")),
) -> AttestationResponseV6:
    """Export v6 attestation bundle for one completed run resource."""
    attestation_id = f"att-{run_id}"
    job = await db.get_proof_job(run_id)
    if job is None:
        raise _unknown_run_id_error(run_id)

    metadata = job.meta or {}
    policy_id = _policy_id_from_job_metadata(
        run_id=run_id,
        metadata=metadata,
    )
    decision = metadata.get("decision")
    if job.status != "completed":
        raise APIError(
            status_code=409,
            code="attestation_not_ready",
            message="Attestation not ready for incomplete run",
            details={"run_id": run_id, "status": job.status},
        )

    try:
        policy_manifest = framework.policy_registry.get_manifest(policy_id)
        policy_version = policy_manifest.policy_version
    except Exception:
        policy_version = str(metadata.get("policy_version") or "")

    paths = framework.artifact_store.get_artifact_paths(job.circuit_id)
    artifact_digest_map = artifact_digests(paths)
    rows = await db.list_audit_rows_for_proof(proof_id=run_id)
    completed_rows = [row for row in rows if row.status == "completed"]
    latest_completed = completed_rows[-1] if completed_rows else None
    if job.proof is not None:
        proof_hash = sha256_json(job.proof)
        public_signals_hash = sha256_json(job.public_signals or [])
    elif latest_completed is not None:
        proof_hash = latest_completed.proof_hash
        public_signals_hash = sha256_json(latest_completed.public_signals or [])
    else:
        raise APIError(
            status_code=409,
            code="attestation_not_ready",
            message="Attestation not available: proof payload was pruned and no audit fallback exists",
            details={"run_id": run_id},
        )
    chain = signature_chain(rows)

    return AttestationResponseV6(
        attestation_id=attestation_id,
        run_id=run_id,
        policy=PolicyDescriptorV6(id=policy_id, version=policy_version),
        circuit_id=job.circuit_id,
        decision="pass" if decision == "pass" else "fail",
        proof_hash=proof_hash,
        public_signals_hash=public_signals_hash,
        artifact_digests=artifact_digest_map,
        signature_chain=chain,
        metadata={
            "policy_params_ref": metadata.get("policy_params_ref"),
            "policy_params_hash": metadata.get("policy_params_hash"),
        },
        exported_at=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("verifier_service:app", host="0.0.0.0", port=8002, reload=False)
