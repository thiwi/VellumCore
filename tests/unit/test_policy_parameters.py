"""Tests for policy parameter store and hashing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vellum_core.api.errors import FrameworkError
from vellum_core.policy_parameters import PolicyParameterStore, compute_policy_params_hash


@pytest.mark.unit
def test_compute_policy_params_hash_is_stable() -> None:
    a = compute_policy_params_hash({"x": 1, "y": 2})
    b = compute_policy_params_hash({"y": 2, "x": 1})
    assert a == b


@pytest.mark.unit
def test_store_resolves_json_params(tmp_path: Path) -> None:
    policy_dir = tmp_path / "demo_v1" / "params"
    policy_dir.mkdir(parents=True)
    (policy_dir / "bank_a.json").write_text(
        json.dumps({"max_dti_bps": 4300, "min_ratio_bps": 1200}),
        encoding="utf-8",
    )
    store = PolicyParameterStore(policy_packs_dir=tmp_path)
    resolved = store.resolve(policy_id="demo_v1", policy_params_ref="bank_a")
    assert resolved == {"max_dti_bps": 4300, "min_ratio_bps": 1200}


@pytest.mark.unit
def test_store_rejects_missing_ref_file(tmp_path: Path) -> None:
    store = PolicyParameterStore(policy_packs_dir=tmp_path)
    with pytest.raises(FrameworkError) as exc:
        store.resolve(policy_id="demo_v1", policy_params_ref="missing")
    assert exc.value.code == "unknown_policy_params_ref"


@pytest.mark.unit
def test_store_rejects_non_int_values(tmp_path: Path) -> None:
    policy_dir = tmp_path / "demo_v1" / "params"
    policy_dir.mkdir(parents=True)
    (policy_dir / "bad.json").write_text(json.dumps({"x": "oops"}), encoding="utf-8")
    store = PolicyParameterStore(policy_packs_dir=tmp_path)
    with pytest.raises(FrameworkError) as exc:
        store.resolve(policy_id="demo_v1", policy_params_ref="bad")
    assert exc.value.code == "invalid_policy_params_ref"

