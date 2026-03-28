"""Validation tests for policy compiler DSL models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vellum_core.policy_compiler.models import DecisionExpr, PolicyDSLSpec, ValueRef


def _base_spec_dict() -> dict[str, object]:
    return {
        "policy_id": "demo_v1",
        "policy_version": "1.0.0",
        "reference_policy": "demo_reference_v1",
        "spec_version": "1.0.0",
        "compiler_version": "0.1.0",
        "batch": {"batch_size": 16},
        "inputs": {
            "balances": {"kind": "uint32_array"},
            "limits": {"kind": "uint32_array"},
        },
        "decision": {
            "kind": "all",
            "inner": {
                "kind": "comparison",
                "comparison": {
                    "op": ">",
                    "left": {"ref": "balances"},
                    "right": {"ref": "limits"},
                },
            },
        },
        "outputs": {
            "all_valid": {"expr": "decision", "value_type": "bool", "signal_index": 0},
            "active_count_out": {"expr": "active_count", "value_type": "int", "signal_index": 1},
        },
        "primitives": ["SafeSub"],
        "expected_attestation": {"decision_signal_index": 0, "pass_signal_value": "1"},
        "generated_python_path": "generated/demo.py",
        "generated_circom_path": "generated/demo.circom",
        "circuit_id": "batch_credit_check",
    }


@pytest.mark.unit
def test_value_ref_requires_exactly_one_of_ref_or_const_int() -> None:
    with pytest.raises(ValidationError):
        ValueRef()
    with pytest.raises(ValidationError):
        ValueRef(ref="balances", const_int=1)
    assert ValueRef(ref="active_count").ref == "active_count"
    assert ValueRef(const_int=42).const_int == 42


@pytest.mark.unit
def test_decision_expr_shape_validation() -> None:
    with pytest.raises(ValidationError):
        DecisionExpr(kind="comparison")
    with pytest.raises(ValidationError):
        DecisionExpr(kind="and", args=[{"kind": "comparison", "comparison": {"op": ">", "left": {"ref": "balances"}, "right": {"ref": "limits"}}}])
    with pytest.raises(ValidationError):
        DecisionExpr(kind="or", args=[])
    with pytest.raises(ValidationError):
        DecisionExpr(kind="not")
    with pytest.raises(ValidationError):
        DecisionExpr(kind="all")
    with pytest.raises(ValidationError):
        DecisionExpr(kind="any")


@pytest.mark.unit
def test_policy_spec_rejects_unsupported_output_expr() -> None:
    data = _base_spec_dict()
    data["outputs"] = {
        "bad": {"expr": "unsupported_output", "value_type": "bool", "signal_index": 0}
    }
    with pytest.raises(ValidationError):
        PolicyDSLSpec.model_validate(data)
