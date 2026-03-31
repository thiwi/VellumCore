"""Debug-trace renderer for compiler-generated explainability metadata."""

from __future__ import annotations

import json
from typing import Any

from vellum_core.policy_compiler.models import DecisionExpr, PolicyDSLSpec, ValueRef


def render_debug_trace(spec: PolicyDSLSpec, *, spec_hash: str) -> str:
    """Render deterministic JSON debug metadata for explainability tooling."""
    rules: list[dict[str, Any]] = []
    assert spec.decision.inner is not None
    _collect_rules(spec.decision.inner, rules=rules, path="decision.inner")

    payload = {
        "policy_id": spec.policy_id,
        "reference_policy": spec.reference_policy,
        "spec_hash": spec_hash,
        "decision_kind": spec.decision.kind,
        "policy_parameters": [
            {
                "name": name,
                "index": idx,
                "minimum": spec_item.minimum,
                "maximum": spec_item.maximum,
                "default": spec_item.default,
            }
            for idx, (name, spec_item) in enumerate(spec.policy_parameters.items())
        ],
        "rules": rules,
    }
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _collect_rules(expr: DecisionExpr, *, rules: list[dict[str, Any]], path: str) -> None:
    if expr.kind == "comparison":
        assert expr.comparison is not None
        rules.append(
            {
                "rule_id": f"rule_cmp_{len(rules)}",
                "policy_path": path,
                "operator": expr.comparison.op,
                "left": _serialize_value(expr.comparison.left),
                "right": _serialize_value(expr.comparison.right),
                "input_refs": _input_refs(expr.comparison.left, expr.comparison.right),
            }
        )
        return

    if expr.kind in {"and", "or"}:
        for idx, arg in enumerate(expr.args):
            _collect_rules(arg, rules=rules, path=f"{path}.args[{idx}]")
        return

    if expr.kind in {"not", "all", "any"} and expr.inner is not None:
        _collect_rules(expr.inner, rules=rules, path=f"{path}.inner")


def _serialize_value(value: ValueRef) -> dict[str, Any]:
    if value.const_int is not None:
        return {"const_int": value.const_int}
    if value.param is not None:
        return {"param": value.param}
    return {"ref": value.ref}


def _input_refs(left: ValueRef, right: ValueRef) -> list[str]:
    refs: list[str] = []
    for value in (left, right):
        if value.ref is not None:
            refs.append(value.ref)
        elif value.param is not None:
            refs.append(f"param:{value.param}")
    return refs

