"""Circuit manifest registry and artifact path resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from vellum_core.schemas import CircuitManifest


class CircuitNotFoundError(Exception):
    """Raised when a circuit id is requested but not present in registry."""

    pass


@dataclass(frozen=True)
class ArtifactPaths:
    """Filesystem artifact locations derived from a circuit id."""

    circuit_dir: Path
    wasm_path: Path
    zkey_path: Path
    verification_key_path: Path


class CircuitRegistry:
    """Discovers circuit manifests and resolves artifact paths."""

    def __init__(self, circuits_dir: Path, shared_assets_dir: Path) -> None:
        self.circuits_dir = circuits_dir
        self.shared_assets_dir = shared_assets_dir
        self._manifests: dict[str, CircuitManifest] = {}
        self.refresh()

    def refresh(self) -> None:
        """Rebuild in-memory manifest cache from the circuits directory."""
        self._manifests.clear()
        if not self.circuits_dir.exists():
            return

        for candidate in self.circuits_dir.iterdir():
            if not candidate.is_dir():
                continue
            manifest_path = candidate / "manifest.json"
            if not manifest_path.exists():
                continue
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = CircuitManifest.model_validate(raw_manifest)
            circuit_file = candidate / f"{manifest.circuit_id}.circom"
            if not circuit_file.exists():
                raise ValueError(
                    f"Missing circuit file for {manifest.circuit_id}: {circuit_file}"
                )
            self._manifests[manifest.circuit_id] = manifest

    def list_circuits(self) -> list[str]:
        """Return sorted discovered circuit identifiers."""
        return sorted(self._manifests.keys())

    def get_manifest(self, circuit_id: str) -> CircuitManifest:
        """Return validated manifest for a circuit id."""
        manifest = self._manifests.get(circuit_id)
        if manifest is None:
            raise CircuitNotFoundError(circuit_id)
        return manifest

    def get_artifact_paths(self, circuit_id: str) -> ArtifactPaths:
        """Return expected shared-assets paths for a circuit."""
        _ = self.get_manifest(circuit_id)
        artifact_dir = self.shared_assets_dir / circuit_id
        return ArtifactPaths(
            circuit_dir=artifact_dir,
            wasm_path=artifact_dir / f"{circuit_id}.wasm",
            zkey_path=artifact_dir / "final.zkey",
            verification_key_path=artifact_dir / "verification_key.json",
        )
