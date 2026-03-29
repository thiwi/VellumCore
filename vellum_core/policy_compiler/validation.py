"""Compiler validation rules for supported DSL constructs."""

from __future__ import annotations

from vellum_core.api.errors import framework_error
from vellum_core.policy_compiler.models import DecisionExpr, PolicyDSLSpec, ValueRef


def ensure_supported_decision(spec: PolicyDSLSpec) -> None:
    """Validate the policy decision expression against compiler v1 capabilities."""
    decision = spec.decision
    if decision.kind not in {"all", "any"} or decision.inner is None:
        raise framework_error(
            "policy_spec_unsupported",
            "Compiler currently supports `all`/`any` as top-level decision",
            policy_id=spec.policy_id,
        )
    validate_boolean_expr(decision.inner, policy_id=spec.policy_id, indexed_context=True)


def validate_boolean_expr(
    expr: DecisionExpr,
    *,
    policy_id: str,
    indexed_context: bool,
) -> None:
    """Validate one boolean expression recursively."""
    if expr.kind == "comparison":
        if expr.comparison is None:
            raise framework_error(
                "policy_spec_unsupported",
                "Comparison node is missing comparison payload",
                policy_id=policy_id,
            )
        validate_value(expr.comparison.left, policy_id=policy_id, indexed_context=indexed_context)
        validate_value(expr.comparison.right, policy_id=policy_id, indexed_context=indexed_context)
        return

    if expr.kind in {"and", "or"}:
        for arg in expr.args:
            validate_boolean_expr(arg, policy_id=policy_id, indexed_context=indexed_context)
        return

    if expr.kind == "not":
        if expr.inner is None:
            raise framework_error(
                "policy_spec_unsupported",
                "`not` node must define inner expression",
                policy_id=policy_id,
            )
        validate_boolean_expr(expr.inner, policy_id=policy_id, indexed_context=indexed_context)
        return

    if expr.kind in {"all", "any"}:
        if expr.inner is None:
            raise framework_error(
                "policy_spec_unsupported",
                f"`{expr.kind}` node must define inner expression",
                policy_id=policy_id,
            )
        validate_boolean_expr(expr.inner, policy_id=policy_id, indexed_context=True)
        return

    raise framework_error(
        "policy_spec_unsupported",
        "Unsupported decision expression kind for compiler v1",
        policy_id=policy_id,
        kind=expr.kind,
    )


def validate_value(value: ValueRef, *, policy_id: str, indexed_context: bool) -> None:
    """Validate one value reference/constant."""
    if value.const_int is not None:
        if value.const_int < 0:
            raise framework_error(
                "policy_spec_unsupported",
                "Negative constants are not supported in compiler v1",
                policy_id=policy_id,
            )
        return

    ref = (value.ref or "").strip()
    if ref in {"balances", "limits"}:
        if indexed_context:
            return
        raise framework_error(
            "policy_spec_unsupported",
            "Array references require indexed context (inside all/any aggregation)",
            policy_id=policy_id,
            ref=ref,
        )
    if ref == "active_count":
        return

    raise framework_error(
        "policy_spec_unsupported",
        "Unsupported value reference in compiler v1",
        policy_id=policy_id,
        ref=ref,
    )
