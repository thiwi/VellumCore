"""Tests for policy run explainability helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from vellum_core.logic.explainability import build_explainability


@pytest.mark.unit
def test_explainability_maps_failed_rule_for_lending_policy() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    payload = build_explainability(
        policy_id="lending_risk_v1",
        policy_packs_dir=repo_root / "policy_packs",
        private_input={
            "balances": [90, 150],
            "limits": [100, 100],
            "active_count": 2,
        },
        policy_parameters={},
        error_message="Constraint failed",
    )
    assert payload["reason"] == "policy_rule_failed"
    assert payload["rule_id"] == "rule_cmp_0"
    assert payload["failed_indices"] == [0]
    assert payload["provider_hint"]["class"] == "constraint_failed"


@pytest.mark.unit
def test_explainability_falls_back_to_provider_hint_without_private_input() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    payload = build_explainability(
        policy_id="lending_risk_v1",
        policy_packs_dir=repo_root / "policy_packs",
        private_input=None,
        policy_parameters={},
        error_message="grpc service unavailable",
    )
    assert payload["provider_hint"]["class"] == "dependency"

