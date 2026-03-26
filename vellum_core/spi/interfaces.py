"""Protocol interfaces defining pluggable framework runtime components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderProofResult:
    """Provider output payload containing proof object and public signals."""

    proof: dict[str, Any]
    public_signals: list[Any]


@dataclass(frozen=True)
class ArtifactPathsView:
    """Resolved artifact file paths for one circuit."""

    circuit_id: str
    wasm_path: str
    zkey_path: str
    verification_key_path: str


class ProofProvider(Protocol):
    """Protocol for proving backends (e.g. snarkjs)."""

    async def generate_proof(
        self, circuit_id: str, private_input: dict[str, Any]
    ) -> ProviderProofResult: ...

    async def verify_proof(
        self, circuit_id: str, proof: dict[str, Any], public_signals: list[Any]
    ) -> bool: ...

    async def ensure_artifacts(self, circuit_id: str) -> None: ...


class ArtifactStore(Protocol):
    """Protocol to resolve and validate artifact locations."""

    def get_artifact_paths(self, circuit_id: str) -> ArtifactPathsView: ...

    def artifacts_exist(self, circuit_id: str) -> bool: ...


class Signer(Protocol):
    """Protocol for signing payloads (typically backed by Vault Transit)."""

    async def sign(self, key_name: str, payload: bytes) -> str: ...


class JobBackend(Protocol):
    """Protocol for asynchronous task dispatch."""

    async def enqueue(self, task_name: str, args: list[Any], queue: str) -> None: ...


class EvidenceStore(Protocol):
    """Protocol for policy evidence persistence and retrieval."""

    async def put(self, *, run_id: str, payload: dict[str, Any]) -> str: ...

    async def get(self, *, reference: str) -> dict[str, Any]: ...


class AttestationSigner(Protocol):
    """Protocol for signing serialized attestation payloads."""

    async def sign_attestation(self, payload: bytes) -> str: ...
