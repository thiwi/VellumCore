"""Reference verifier service for proof checks, circuits, and audit integrity."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials

from vellum_core.api.types import VerificationRequest as EngineVerificationRequest
from vellum_core.auth import AuthManager, BEARER_SCHEME
from vellum_core.config import Settings
from vellum_core.database import Database
from vellum_core.errors import register_exception_handlers
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
    CircuitsResponse,
    HealthResponse,
    TrustSpeedResponse,
    VerifyRequest,
    VerifyResponse,
)
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


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

app = FastAPI(title="Vellum Verifier Service", version="4.0.0")
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
            required_scopes={"audit:read"},
        )
    payload, content_type = prometheus_payload()
    return Response(content=payload, media_type=content_type)


@app.post("/v1/verify", response_model=VerifyResponse)
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


@app.get("/v1/circuits", response_model=CircuitsResponse)
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


@app.get("/v1/audit/verify-chain", response_model=AuditChainVerifyResponse)
async def verify_audit_chain(
    _: dict[str, Any] = Depends(require_jwt_with_scopes("audit:read")),
) -> AuditChainVerifyResponse:
    """Verify full audit-chain integrity."""
    report = await integrity_service.verify_chain()
    return AuditChainVerifyResponse.model_validate(report)


@app.get("/v1/trust-speed", response_model=TrustSpeedResponse)
async def trust_speed(
    _: dict[str, Any] = Depends(require_jwt_with_scopes("audit:read")),
) -> TrustSpeedResponse:
    """Return trust-speed snapshot from verification metrics."""
    return TrustSpeedResponse.model_validate(trust_speed_snapshot())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("verifier_service:app", host="0.0.0.0", port=8002, reload=False)
