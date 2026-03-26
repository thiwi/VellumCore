"""Tests for Registry."""

from pathlib import Path

from vellum_core.registry import CircuitRegistry


def test_registry_discovers_sample_circuits() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = CircuitRegistry(
        circuits_dir=root / "circuits",
        shared_assets_dir=root / "shared_assets",
    )
    circuits = registry.list_circuits()

    assert "credit_check" in circuits
    assert "aml_check" in circuits

