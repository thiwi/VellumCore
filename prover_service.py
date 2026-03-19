from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.security import HTTPAuthorizationCredentials
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate as validate_jsonschema
from pydantic import BaseModel, ValidationError

from sentinel_zk.auth import AuthManager, BEARER_SCHEME
from sentinel_zk.batching import batch_prepare_input
from sentinel_zk.config import Settings
from sentinel_zk.errors import APIError, register_exception_handlers
from sentinel_zk.proof_store import ProofStore
from sentinel_zk.providers import SnarkJSProvider
from sentinel_zk.registry import CircuitNotFoundError, CircuitRegistry
from sentinel_zk.schemas import (
    BatchProveRequest,
    HealthResponse,
    ProofStatusResponse,
    ProveAcceptedResponse,
    ProveRequest,
)


BATCH_CIRCUIT_ID = "batch_credit_check"
TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(frozen=True)
class ProofJobPayload:
    circuit_id: str
    private_input: dict[str, Any]
    request_id: str | None
    metadata: dict[str, Any]


class ProofOrchestrator:
    def __init__(
        self,
        *,
        registry: CircuitRegistry,
        provider: SnarkJSProvider,
        store: ProofStore,
        proof_output_dir: Path,
        max_parallel_proofs: int,
    ) -> None:
        self.registry = registry
        self.provider = provider
        self.store = store
        self.proof_output_dir = proof_output_dir
        self.proof_output_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: set[asyncio.Task[Any]] = set()
        self._prove_semaphore = asyncio.Semaphore(max_parallel_proofs)

    async def submit(self, payload: ProofJobPayload) -> str:
        try:
            manifest = self.registry.get_manifest(payload.circuit_id)
        except CircuitNotFoundError as exc:
            raise APIError(
                status_code=404,
                code="unknown_circuit",
                message="Circuit id not found",
                details={"circuit_id": payload.circuit_id},
            ) from exc

        try:
            validate_jsonschema(payload.private_input, manifest.input_schema)
        except JSONSchemaValidationError as exc:
            raise APIError(
                status_code=422,
                code="invalid_private_input",
                message="Private input does not satisfy manifest schema",
                details={"reason": exc.message},
            ) from exc

        await self.provider.ensure_artifacts(payload.circuit_id)

        proof_id = str(uuid4())
        queued_meta = {
            **payload.metadata,
            "request_id": payload.request_id,
            "mode": payload.metadata.get("mode", "single"),
        }
        self.store.append_event(
            proof_id=proof_id,
            circuit_id=payload.circuit_id,
            public_signals=[],
            status="queued",
            metadata=queued_meta,
        )

        task = asyncio.create_task(self._run_proof_job(proof_id, payload))
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)
        return proof_id

    async def get_status(self, proof_id: str) -> ProofStatusResponse:
        record = self.store.get_latest_event(proof_id)
        if record is None:
            raise APIError(
                status_code=404,
                code="unknown_proof_id",
                message="No proof found for id",
                details={"proof_id": proof_id},
            )

        proof_payload: dict[str, Any] | None = None
        proof_path = record.get("proof_path")
        if record.get("status") == "completed" and isinstance(proof_path, str):
            path = Path(proof_path)
            if path.exists():
                proof_blob = json.loads(path.read_text(encoding="utf-8"))
                proof_payload = proof_blob.get("proof")

        created_at_raw = record.get("created_at") or record.get("timestamp")
        created_at = datetime.fromisoformat(created_at_raw)
        return ProofStatusResponse(
            proof_id=record["proof_id"],
            status=record["status"],
            circuit_id=record["circuit_id"],
            public_signals=record.get("public_signals", []),
            proof=proof_payload,
            error=record.get("error"),
            metadata=record.get("metadata"),
            created_at=created_at,
        )

    async def _run_proof_job(self, proof_id: str, payload: ProofJobPayload) -> None:
        running_meta = {**payload.metadata, "request_id": payload.request_id}
        self.store.append_event(
            proof_id=proof_id,
            circuit_id=payload.circuit_id,
            public_signals=[],
            status="running",
            metadata=running_meta,
        )
        try:
            async with self._prove_semaphore:
                result = await self.provider.generate_proof(
                    payload.circuit_id, payload.private_input
                )
            proof_path = self.proof_output_dir / f"{proof_id}.json"
            proof_file_payload = {
                "proof": result.proof,
                "public_signals": result.public_signals,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            proof_path.write_text(
                json.dumps(proof_file_payload, separators=(",", ":")),
                encoding="utf-8",
            )
            self.store.append_event(
                proof_id=proof_id,
                circuit_id=payload.circuit_id,
                public_signals=result.public_signals,
                status="completed",
                proof_path=str(proof_path),
                proof_payload=result.proof,
                metadata=running_meta,
            )
        except APIError as exc:
            self.store.append_event(
                proof_id=proof_id,
                circuit_id=payload.circuit_id,
                public_signals=[],
                status="failed",
                error=exc.message,
                metadata={
                    **running_meta,
                    "error_code": exc.code,
                    "error_details": exc.details,
                },
            )
        except Exception as exc:  # pragma: no cover
            self.store.append_event(
                proof_id=proof_id,
                circuit_id=payload.circuit_id,
                public_signals=[],
                status="failed",
                error=str(exc),
                metadata={
                    **running_meta,
                    "error_type": exc.__class__.__name__,
                },
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
orchestrator = ProofOrchestrator(
    registry=registry,
    provider=provider,
    store=proof_store,
    proof_output_dir=settings.proof_output_dir,
    max_parallel_proofs=settings.max_parallel_proofs,
)

app = FastAPI(title="Sentinel-ZK Prover Service", version="2.0.0")
register_exception_handlers(app)


def require_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
) -> dict[str, Any]:
    return auth_manager.verify_jwt_credentials(credentials)


def _build_batch_private_input(payload: BatchProveRequest) -> dict[str, Any]:
    try:
        prepared = batch_prepare_input(
            balances=payload.balances,
            limits=payload.limits,
            batch_size=100,
        )
    except ValueError as exc:
        raise APIError(
            status_code=422,
            code="invalid_batch_input",
            message="Batch payload invalid",
            details={"reason": str(exc)},
        ) from exc
    return prepared.to_circuit_input()


async def _decode_and_authenticate(request: Request, model_type: type[TModel]) -> TModel:
    raw_body = await request.body()
    await auth_manager.verify_handshake(request, raw_body)
    try:
        return model_type.model_validate_json(raw_body)
    except ValidationError as exc:
        raise APIError(
            status_code=422,
            code="invalid_request",
            message="Request body does not match schema",
            details={"reason": str(exc)},
        ) from exc


@app.get("/healthz", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/v1/proofs", status_code=202, response_model=ProveAcceptedResponse)
async def create_proof(
    request: Request,
    _: dict[str, Any] = Depends(require_jwt),
) -> ProveAcceptedResponse:
    payload = await _decode_and_authenticate(request, ProveRequest)
    proof_id = await orchestrator.submit(
        ProofJobPayload(
            circuit_id=payload.circuit_id,
            private_input=payload.private_input,
            request_id=payload.request_id,
            metadata={"mode": "single"},
        )
    )
    return ProveAcceptedResponse(proof_id=proof_id, status="queued")


@app.post("/v1/proofs/batch", status_code=202, response_model=ProveAcceptedResponse)
async def create_batch_proof(
    request: Request,
    _: dict[str, Any] = Depends(require_jwt),
) -> ProveAcceptedResponse:
    payload = await _decode_and_authenticate(request, BatchProveRequest)
    private_input = _build_batch_private_input(payload)
    proof_id = await orchestrator.submit(
        ProofJobPayload(
            circuit_id=BATCH_CIRCUIT_ID,
            private_input=private_input,
            request_id=payload.request_id,
            metadata={"mode": "batch", "batch_size": len(payload.balances)},
        )
    )
    return ProveAcceptedResponse(proof_id=proof_id, status="queued")


@app.get("/v1/proofs/{proof_id}", response_model=ProofStatusResponse)
async def get_proof_status(
    proof_id: str,
    _: dict[str, Any] = Depends(require_jwt),
) -> ProofStatusResponse:
    return await orchestrator.get_status(proof_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("prover_service:app", host="0.0.0.0", port=8001, reload=False)
