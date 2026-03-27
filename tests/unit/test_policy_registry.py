"""Tests for Policy registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vellum_core.policy_registry import PolicyManifestError, PolicyNotFoundError, PolicyRegistry


@pytest.mark.unit
def test_policy_registry_discovers_manifest(tmp_path: Path) -> None:
    policy_dir = tmp_path / "policy_packs" / "lending_risk_v1"
    policy_dir.mkdir(parents=True)
    (policy_dir / "manifest.json").write_text(
        json.dumps(
            {
                "policy_id": "lending_risk_v1",
                "policy_version": "1.0.0",
                "circuit_id": "batch_credit_check",
                "input_contract": {},
                "evidence_contract": {},
                "reference_policy": "lending_risk_reference_v1",
                "primitives": ["SafeSub"],
                "differential_outputs": {"all_valid": {"signal_index": 0, "value_type": "bool"}},
                "expected_attestation": {},
            }
        ),
        encoding="utf-8",
    )

    registry = PolicyRegistry(tmp_path / "policy_packs")
    assert registry.list_policies() == ["lending_risk_v1"]
    manifest = registry.get_manifest("lending_risk_v1")
    assert manifest.circuit_id == "batch_credit_check"


@pytest.mark.unit
def test_policy_registry_raises_for_unknown_policy(tmp_path: Path) -> None:
    registry = PolicyRegistry(tmp_path / "policy_packs")
    with pytest.raises(PolicyNotFoundError):
        registry.get_manifest("missing")


@pytest.mark.unit
def test_policy_registry_rejects_unknown_primitives(tmp_path: Path) -> None:
    policy_dir = tmp_path / "policy_packs" / "lending_risk_v1"
    policy_dir.mkdir(parents=True)
    (policy_dir / "manifest.json").write_text(
        json.dumps(
            {
                "policy_id": "lending_risk_v1",
                "policy_version": "1.0.0",
                "circuit_id": "batch_credit_check",
                "input_contract": {},
                "evidence_contract": {},
                "reference_policy": "lending_risk_reference_v1",
                "primitives": ["UnknownPrimitive"],
                "differential_outputs": {"all_valid": {"signal_index": 0, "value_type": "bool"}},
                "expected_attestation": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PolicyManifestError, match="unknown primitives"):
        PolicyRegistry(tmp_path / "policy_packs")
