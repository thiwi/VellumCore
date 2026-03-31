"""Deterministic explainability helpers for failed policy runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vellum_core.policy_compiler.models import DecisionExpr, ValueRef
from vellum_core.policy_compiler.spec_loader import load_policy_spec


@dataclass(frozen=True)
class _ComparisonRule:
    rule_id: str
    policy_path: str
    operator: str
    left: ValueRef
    right: ValueRef

    @property
    def input_refs(self) -> list[str]:
        refs: list[str] = []
        for value in (self.left, self.right):
            if value.ref:
                refs.append(value.ref)
            elif value.param:
                refs.append(f"param:{value.param}")
        return refs


@dataclass(frozen=True)
class _EvalOutcome:
    value: bool
    failed_rule_ids: list[str]


def build_explainability(
    *,
    policy_id: str,
    policy_packs_dir: Path,
    private_input: dict[str, Any] | None,
    policy_parameters: dict[str, int] | None,
    error_message: str,
) -> dict[str, Any]:
    """Build explainability payload from policy replay and provider error hints."""
    provider_hint = _parse_provider_hint(error_message)

    primary: dict[str, Any] | None = None
    if private_input is not None:
        primary = _evaluate_policy_trace(
            policy_id=policy_id,
            policy_packs_dir=policy_packs_dir,
            private_input=private_input,
            policy_parameters=policy_parameters or {},
        )

    payload: dict[str, Any] = {"version": "v1"}
    if primary is not None:
        payload.update(primary)
    if provider_hint:
        payload["provider_hint"] = provider_hint
    if primary is None and not provider_hint:
        payload["reason"] = "explainability_unavailable"
    return payload


def _evaluate_policy_trace(
    *,
    policy_id: str,
    policy_packs_dir: Path,
    private_input: dict[str, Any],
    policy_parameters: dict[str, int],
) -> dict[str, Any] | None:
    spec_path = policy_packs_dir / policy_id / "policy_spec.yaml"
    if not spec_path.exists():
        return None

    try:
        spec = load_policy_spec(spec_path)
    except Exception:
        return None

    decision = spec.decision
    if decision.inner is None:
        return None

    rules: list[_ComparisonRule] = []
    _collect_rules(decision.inner, rules=rules, path="decision.inner")
    rules_by_id = {rule.rule_id: rule for rule in rules}

    active_count = _as_int(private_input.get("active_count"), default=0)
    if active_count <= 0:
        return {
            "reason": "policy_trace_unavailable",
            "detail": "active_count missing or invalid",
        }

    failed_indices: list[int] = []
    failed_rule_ids: list[str] = []
    for idx in range(active_count):
        outcome = _eval_expr(
            decision.inner,
            idx=idx,
            private_input=private_input,
            policy_parameters=policy_parameters,
            rules_by_id=rules_by_id,
            rules=rules,
        )
        if not outcome.value:
            failed_indices.append(idx)
            failed_rule_ids.extend(outcome.failed_rule_ids)

    if decision.kind == "all":
        decision_failed = len(failed_indices) > 0
    else:
        decision_failed = len(failed_indices) == active_count
    if not decision_failed:
        return {
            "reason": "policy_trace_passed",
            "failed_indices": [],
            "failed_rule_ids": [],
        }

    first_rule: _ComparisonRule | None = None
    for rule_id in failed_rule_ids:
        first_rule = rules_by_id.get(rule_id)
        if first_rule is not None:
            break

    payload: dict[str, Any] = {
        "reason": "policy_rule_failed",
        "failed_indices": failed_indices[:25],
        "failed_rule_ids": sorted(set(failed_rule_ids)),
    }
    if first_rule is not None:
        payload.update(
            {
                "rule_id": first_rule.rule_id,
                "policy_path": first_rule.policy_path,
                "operator": first_rule.operator,
                "input_refs": first_rule.input_refs,
            }
        )
    return payload


def _collect_rules(expr: DecisionExpr, *, rules: list[_ComparisonRule], path: str) -> None:
    if expr.kind == "comparison":
        assert expr.comparison is not None
        rule_id = f"rule_cmp_{len(rules)}"
        rules.append(
            _ComparisonRule(
                rule_id=rule_id,
                policy_path=path,
                operator=expr.comparison.op,
                left=expr.comparison.left,
                right=expr.comparison.right,
            )
        )
        return

    if expr.kind in {"and", "or"}:
        for idx, arg in enumerate(expr.args):
            _collect_rules(arg, rules=rules, path=f"{path}.args[{idx}]")
        return

    if expr.kind in {"not", "all", "any"} and expr.inner is not None:
        _collect_rules(expr.inner, rules=rules, path=f"{path}.inner")


def _eval_expr(
    expr: DecisionExpr,
    *,
    idx: int,
    private_input: dict[str, Any],
    policy_parameters: dict[str, int],
    rules_by_id: dict[str, _ComparisonRule],
    rules: list[_ComparisonRule],
) -> _EvalOutcome:
    if expr.kind == "comparison":
        assert expr.comparison is not None
        rule = rules[_comparison_index(rules_by_id, expr.comparison.left, expr.comparison.right, expr.comparison.op)]
        left = _resolve_value(
            expr.comparison.left,
            idx=idx,
            private_input=private_input,
            policy_parameters=policy_parameters,
        )
        right = _resolve_value(
            expr.comparison.right,
            idx=idx,
            private_input=private_input,
            policy_parameters=policy_parameters,
        )
        value = _compare(expr.comparison.op, left=left, right=right)
        return _EvalOutcome(value=value, failed_rule_ids=[] if value else [rule.rule_id])

    if expr.kind == "and":
        child_outcomes = [
            _eval_expr(
                arg,
                idx=idx,
                private_input=private_input,
                policy_parameters=policy_parameters,
                rules_by_id=rules_by_id,
                rules=rules,
            )
            for arg in expr.args
        ]
        return _EvalOutcome(
            value=all(outcome.value for outcome in child_outcomes),
            failed_rule_ids=[rule for outcome in child_outcomes for rule in outcome.failed_rule_ids],
        )

    if expr.kind == "or":
        child_outcomes = [
            _eval_expr(
                arg,
                idx=idx,
                private_input=private_input,
                policy_parameters=policy_parameters,
                rules_by_id=rules_by_id,
                rules=rules,
            )
            for arg in expr.args
        ]
        value = any(outcome.value for outcome in child_outcomes)
        if value:
            return _EvalOutcome(value=True, failed_rule_ids=[])
        return _EvalOutcome(
            value=False,
            failed_rule_ids=[rule for outcome in child_outcomes for rule in outcome.failed_rule_ids],
        )

    if expr.kind == "not":
        assert expr.inner is not None
        child = _eval_expr(
            expr.inner,
            idx=idx,
            private_input=private_input,
            policy_parameters=policy_parameters,
            rules_by_id=rules_by_id,
            rules=rules,
        )
        return _EvalOutcome(value=not child.value, failed_rule_ids=child.failed_rule_ids)

    if expr.kind in {"all", "any"}:
        assert expr.inner is not None
        active_count = _as_int(private_input.get("active_count"), default=0)
        child_outcomes = [
            _eval_expr(
                expr.inner,
                idx=nested_idx,
                private_input=private_input,
                policy_parameters=policy_parameters,
                rules_by_id=rules_by_id,
                rules=rules,
            )
            for nested_idx in range(active_count)
        ]
        if expr.kind == "all":
            return _EvalOutcome(
                value=all(outcome.value for outcome in child_outcomes),
                failed_rule_ids=[rule for outcome in child_outcomes for rule in outcome.failed_rule_ids],
            )
        value = any(outcome.value for outcome in child_outcomes)
        if value:
            return _EvalOutcome(value=True, failed_rule_ids=[])
        return _EvalOutcome(
            value=False,
            failed_rule_ids=[rule for outcome in child_outcomes for rule in outcome.failed_rule_ids],
        )

    return _EvalOutcome(value=False, failed_rule_ids=[])


def _comparison_index(
    rules_by_id: dict[str, _ComparisonRule],
    left: ValueRef,
    right: ValueRef,
    op: str,
) -> int:
    for rule_id, rule in rules_by_id.items():
        if (
            rule.left == left
            and rule.right == right
            and rule.operator == op
            and rule_id.startswith("rule_cmp_")
        ):
            return int(rule_id.removeprefix("rule_cmp_"))
    return 0


def _resolve_value(
    value: ValueRef,
    *,
    idx: int,
    private_input: dict[str, Any],
    policy_parameters: dict[str, int],
) -> int:
    if value.const_int is not None:
        return int(value.const_int)
    if value.param:
        return int(policy_parameters.get(value.param, 0))
    ref = value.ref
    if ref == "active_count":
        return _as_int(private_input.get("active_count"), default=0)
    if ref == "balances":
        balances = private_input.get("balances")
        if isinstance(balances, list) and idx < len(balances):
            return _as_int(balances[idx], default=0)
        return 0
    if ref == "limits":
        limits = private_input.get("limits")
        if isinstance(limits, list) and idx < len(limits):
            return _as_int(limits[idx], default=0)
        return 0
    if isinstance(ref, str) and ref.startswith("policy_params."):
        return int(policy_parameters.get(ref.split(".", 1)[1], 0))
    return 0


def _compare(op: str, *, left: int, right: int) -> bool:
    if op == "<":
        return left < right
    if op == ">":
        return left > right
    if op == "<=":
        return left <= right
    if op == ">=":
        return left >= right
    if op == "==":
        return left == right
    return False


def _as_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_provider_hint(error_message: str) -> dict[str, Any] | None:
    msg = (error_message or "").lower()
    if msg == "":
        return None
    if "constraint" in msg and "failed" in msg:
        return {"class": "constraint_failed", "reason": "Constraint failed in proving backend."}
    if "invalid proof" in msg:
        return {"class": "invalid_proof", "reason": "Verifier rejected proof payload."}
    if "grpc" in msg or "connection refused" in msg:
        return {"class": "dependency", "reason": "gRPC/prover dependency failure."}
    if "wtns calculate failed" in msg:
        return {"class": "witness_generation", "reason": "Witness generation failed."}
    if "timeout" in msg or "time limit" in msg:
        return {"class": "timeout", "reason": "Proof job timed out."}
    return {"class": "runtime_exception", "reason": error_message[:240]}

