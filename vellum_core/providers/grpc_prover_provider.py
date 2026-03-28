"""gRPC-based proof provider using the native prover microservice."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import grpc

from vellum_core.errors import APIError
from vellum_core.proto import vellum_prover_pb2, vellum_prover_pb2_grpc
from vellum_core.providers.base import ProofResult, ZKProvider
from vellum_core.registry import CircuitRegistry


class GrpcProofProvider(ZKProvider):
    """Proof provider backed by remote native prover service over gRPC."""

    def __init__(
        self,
        *,
        registry: CircuitRegistry,
        endpoint: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.registry = registry
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self._channel: grpc.aio.Channel | None = None
        self._stub: vellum_prover_pb2_grpc.ProverStub | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def ensure_artifacts(self, circuit_id: str) -> None:
        """Ensure required Groth16 artifacts are present locally before calling service."""
        artifacts = self.registry.get_artifact_paths(circuit_id)
        missing = [
            str(path)
            for path in (
                artifacts.wasm_path,
                artifacts.zkey_path,
                artifacts.verification_key_path,
            )
            if not path.exists()
        ]
        if missing:
            raise APIError(
                status_code=500,
                code="missing_artifacts",
                message="Required circuit artifacts are missing",
                details={"circuit_id": circuit_id, "missing": missing},
            )

    async def generate_proof(
        self, circuit_id: str, private_input: dict[str, Any]
    ) -> ProofResult:
        """Generate a proof via native gRPC prover."""
        await self.ensure_artifacts(circuit_id)
        artifacts = self.registry.get_artifact_paths(circuit_id)
        request = vellum_prover_pb2.GenerateProofRequest(
            circuit_id=circuit_id,
            private_input_json=json.dumps(
                self._normalize_json_value(private_input),
                sort_keys=True,
                separators=(",", ":"),
            ),
            wasm_path=str(artifacts.wasm_path),
            zkey_path=str(artifacts.zkey_path),
        )
        try:
            response = await self._call_generate(request)
        except grpc.RpcError as exc:
            raise APIError(
                status_code=500,
                code="provider_command_failed",
                message="gRPC native prover generate call failed",
                details={"circuit_id": circuit_id, "reason": str(exc)},
            ) from exc
        return ProofResult(
            proof=json.loads(response.proof_json),
            public_signals=json.loads(response.public_signals_json),
        )

    async def verify_proof(
        self, circuit_id: str, proof: dict[str, Any], public_signals: list[Any]
    ) -> bool:
        """Verify proof via native gRPC prover."""
        await self.ensure_artifacts(circuit_id)
        artifacts = self.registry.get_artifact_paths(circuit_id)
        request = vellum_prover_pb2.VerifyProofRequest(
            circuit_id=circuit_id,
            proof_json=json.dumps(proof, separators=(",", ":"), sort_keys=True),
            public_signals_json=json.dumps(public_signals, separators=(",", ":")),
            verification_key_path=str(artifacts.verification_key_path),
        )
        try:
            response = await self._call_verify(request)
        except grpc.RpcError as exc:
            raise APIError(
                status_code=500,
                code="provider_command_failed",
                message="gRPC native prover verify call failed",
                details={"circuit_id": circuit_id, "reason": str(exc)},
            ) from exc
        return bool(response.valid)

    async def _call_generate(
        self, request: vellum_prover_pb2.GenerateProofRequest
    ) -> vellum_prover_pb2.GenerateProofResponse:
        stub = await self._get_stub()
        return await stub.GenerateProof(request, timeout=self.timeout_seconds)

    async def _call_verify(
        self, request: vellum_prover_pb2.VerifyProofRequest
    ) -> vellum_prover_pb2.VerifyProofResponse:
        stub = await self._get_stub()
        return await stub.VerifyProof(request, timeout=self.timeout_seconds)

    async def _get_stub(self) -> vellum_prover_pb2_grpc.ProverStub:
        """Reuse one channel per event loop; recreate on loop changes."""
        current_loop = asyncio.get_running_loop()
        if self._stub is not None and self._loop is current_loop:
            return self._stub
        if self._channel is not None and self._loop is not None and self._loop is not current_loop:
            await self._channel.close()
            self._channel = None
            self._stub = None
            self._loop = None
        if self._stub is None:
            self._channel = grpc.aio.insecure_channel(self.endpoint)
            self._stub = vellum_prover_pb2_grpc.ProverStub(self._channel)
            self._loop = current_loop
        return self._stub

    def _normalize_json_value(self, value: Any) -> Any:
        """Convert integers to circuit-safe strings and recursively normalize JSON."""
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return [self._normalize_json_value(item) for item in value]
        if isinstance(value, dict):
            return {str(k): self._normalize_json_value(v) for k, v in value.items()}
        if value is None:
            return value
        raise APIError(
            status_code=422,
            code="invalid_private_input",
            message="Private input contains non-serializable value",
            details={"value_type": value.__class__.__name__},
        )
