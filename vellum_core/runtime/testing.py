"""Deterministic in-memory doubles used by unit/integration tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from vellum_core.spi import (
    ArtifactPathsView,
    ArtifactStore,
    AttestationSigner,
    EvidenceStore,
    JobBackend,
    ProviderProofResult,
    Signer,
)


class DeterministicProofProvider:
    """Predictable provider that hashes private input instead of real proving."""

    async def generate_proof(
        self, circuit_id: str, private_input: dict[str, Any]
    ) -> ProviderProofResult:
        digest = hashlib.sha256(
            json.dumps(private_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        proof = {"circuit_id": circuit_id, "digest": digest}
        return ProviderProofResult(proof=proof, public_signals=["1", digest[:16]])

    async def verify_proof(
        self, circuit_id: str, proof: dict[str, Any], public_signals: list[Any]
    ) -> bool:
        """Accept proofs produced by this deterministic provider shape."""
        _ = circuit_id
        return bool(proof.get("digest")) and len(public_signals) >= 1

    async def ensure_artifacts(self, circuit_id: str) -> None:
        """No-op artifact check for deterministic tests."""
        _ = circuit_id


class InMemoryArtifactStore(ArtifactStore):
    """In-memory artifact readiness tracker."""

    def __init__(self) -> None:
        self.ready: set[str] = set()

    def get_artifact_paths(self, circuit_id: str) -> ArtifactPathsView:
        """Return synthetic artifact paths for test assertions."""
        return ArtifactPathsView(
            circuit_id=circuit_id,
            wasm_path=f"/tmp/{circuit_id}/{circuit_id}.wasm",
            zkey_path=f"/tmp/{circuit_id}/final.zkey",
            verification_key_path=f"/tmp/{circuit_id}/verification_key.json",
        )

    def artifacts_exist(self, circuit_id: str) -> bool:
        """Return whether a circuit is marked ready in-memory."""
        return circuit_id in self.ready


class DeterministicSigner(Signer):
    """Signer that returns digest-based pseudo-signatures for tests."""

    async def sign(self, key_name: str, payload: bytes) -> str:
        return f"{key_name}:{hashlib.sha256(payload).hexdigest()}"


class InMemoryEvidenceStore(EvidenceStore):
    """Evidence store that keeps payloads in-memory keyed by run id."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def put(self, *, run_id: str, payload: dict[str, Any]) -> str:
        self._store[run_id] = payload
        return f"memory://{run_id}"

    async def get(self, *, reference: str) -> dict[str, Any]:
        run_id = reference.removeprefix("memory://")
        payload = self._store.get(run_id)
        if payload is None:
            raise KeyError(reference)
        return payload


class DeterministicAttestationSigner(AttestationSigner):
    """Attestation signer returning deterministic hash-based signatures."""

    async def sign_attestation(self, payload: bytes) -> str:
        return f"attestation:{hashlib.sha256(payload).hexdigest()}"


@dataclass
class InMemoryJobBackend(JobBackend):
    """Job backend collecting enqueue calls in-memory for assertions."""

    jobs: list[tuple[str, list[Any], str]] = field(default_factory=list)

    async def enqueue(self, task_name: str, args: list[Any], queue: str) -> None:
        """Record enqueued job tuple in insertion order."""
        self.jobs.append((task_name, args, queue))
