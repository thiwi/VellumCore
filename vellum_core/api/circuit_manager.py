"""Circuit metadata and artifact validation utilities for framework clients."""

from __future__ import annotations

from vellum_core.api.errors import FrameworkError, framework_error
from vellum_core.api.types import CircuitStatus
from vellum_core.registry import CircuitNotFoundError, CircuitRegistry
from vellum_core.spi import ArtifactStore, ProofProvider


class CircuitManager:
    """Read/validate circuit metadata and artifact availability."""

    def __init__(self, *, registry: CircuitRegistry, artifact_store: ArtifactStore) -> None:
        self.registry = registry
        self.artifact_store = artifact_store

    def list(self) -> list[str]:
        """Return all discovered circuit identifiers."""
        return self.registry.list_circuits()

    def get_manifest_version(self, circuit_id: str) -> str:
        """Return manifest version for a known circuit id."""
        try:
            manifest = self.registry.get_manifest(circuit_id)
        except CircuitNotFoundError as exc:
            raise framework_error("unknown_circuit", "Circuit id not found", circuit_id=circuit_id) from exc
        return manifest.version

    def validate(self, circuit_id: str) -> CircuitStatus:
        """Return artifact readiness and path information for one circuit."""
        version = self.get_manifest_version(circuit_id)
        paths = self.artifact_store.get_artifact_paths(circuit_id)
        return CircuitStatus(
            circuit_id=circuit_id,
            version=version,
            artifacts_ready=self.artifact_store.artifacts_exist(circuit_id),
            artifact_paths={
                "wasm_path": paths.wasm_path,
                "zkey_path": paths.zkey_path,
                "verification_key_path": paths.verification_key_path,
            },
        )

    async def ensure_artifacts(self, circuit_id: str, provider: ProofProvider) -> None:
        """Fail fast if circuit metadata is unknown or runtime artifacts are missing."""
        try:
            self.registry.get_manifest(circuit_id)
        except CircuitNotFoundError as exc:
            raise framework_error("unknown_circuit", "Circuit id not found", circuit_id=circuit_id) from exc
        try:
            await provider.ensure_artifacts(circuit_id)
        except Exception as exc:
            raise FrameworkError(
                code="missing_artifacts",
                message="Required circuit artifacts are missing or invalid",
                details={"circuit_id": circuit_id, "reason": str(exc)},
            ) from exc

    def list_with_validation(self) -> list[CircuitStatus]:
        """Return validation data for all discovered circuits."""
        return [self.validate(circuit_id) for circuit_id in self.list()]
