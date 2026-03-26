"""Tests for Artifact validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from vellum_core.api import CircuitManager
from vellum_core.registry import CircuitRegistry
from vellum_core.runtime.defaults import FilesystemArtifactStore


@pytest.mark.integration
def test_circuit_validation_uses_manifest_and_artifacts() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = CircuitRegistry(
        circuits_dir=root / "circuits",
        shared_assets_dir=root / "shared_assets",
    )
    manager = CircuitManager(
        registry=registry,
        artifact_store=FilesystemArtifactStore(registry),
    )

    circuits = manager.list_with_validation()
    ids = {entry.circuit_id for entry in circuits}
    assert "batch_credit_check" in ids
    assert all("wasm_path" in entry.artifact_paths for entry in circuits)
