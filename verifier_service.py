from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials

from sentinel_zk.auth import AuthManager, BEARER_SCHEME
from sentinel_zk.config import Settings
from sentinel_zk.errors import APIError, register_exception_handlers
from sentinel_zk.proof_store import ProofStore
from sentinel_zk.providers import SnarkJSProvider
from sentinel_zk.registry import CircuitNotFoundError, CircuitRegistry
from sentinel_zk.schemas import (
    AuditChainVerifyResponse,
    HealthResponse,
    VerifyRequest,
    VerifyResponse,
)


settings = Settings.from_env()
registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
proof_store = ProofStore(
    settings.shared_store_file,
    audit_private_key_path=settings.audit_private_key_path,
    audit_public_key_path=settings.audit_public_key_path,
)
provider = SnarkJSProvider(registry=registry, snarkjs_bin=settings.snarkjs_bin)
auth_manager = AuthManager(
    jwt_public_key_path=settings.jwt_public_key_path,
    jwt_issuer=settings.jwt_issuer,
    jwt_audience=settings.jwt_audience,
    bank_public_keys_path=settings.bank_public_keys_path,
    nonce_window_seconds=settings.nonce_window_seconds,
)

app = FastAPI(title="Sentinel-ZK Verifier Service", version="2.0.0")
register_exception_handlers(app)


def require_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
) -> dict[str, Any]:
    return auth_manager.verify_jwt_credentials(credentials)


@app.get("/healthz", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/v1/verify", response_model=VerifyResponse)
async def verify(
    payload: VerifyRequest,
    _: dict[str, Any] = Depends(require_jwt),
) -> VerifyResponse:
    try:
        registry.get_manifest(payload.circuit_id)
    except CircuitNotFoundError as exc:
        raise APIError(
            status_code=404,
            code="unknown_circuit",
            message="Circuit id not found",
            details={"circuit_id": payload.circuit_id},
        ) from exc

    await provider.ensure_artifacts(payload.circuit_id)
    started = time.perf_counter()
    valid = await provider.verify_proof(
        circuit_id=payload.circuit_id,
        proof=payload.proof,
        public_signals=payload.public_signals,
    )
    verification_ms = (time.perf_counter() - started) * 1000.0

    proof_store.append_event(
        proof_id=f"verify-{uuid4()}",
        circuit_id=payload.circuit_id,
        public_signals=payload.public_signals,
        status="completed" if valid else "failed",
        proof_payload=payload.proof,
        metadata={"event": "verification", "result": "valid" if valid else "invalid"},
    )

    return VerifyResponse(
        valid=valid,
        verified_at=datetime.now(timezone.utc),
        verification_ms=verification_ms,
    )


@app.get("/v1/audit/verify-chain", response_model=AuditChainVerifyResponse)
async def verify_audit_chain(
    _: dict[str, Any] = Depends(require_jwt),
) -> AuditChainVerifyResponse:
    report = proof_store.verify_chain()
    return AuditChainVerifyResponse.model_validate(report)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("verifier_service:app", host="0.0.0.0", port=8002, reload=False)
