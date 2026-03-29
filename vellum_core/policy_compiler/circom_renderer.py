"""Circom renderer for policy DSL compiler."""

from __future__ import annotations

from dataclasses import dataclass

from vellum_core.api.errors import framework_error
from vellum_core.policy_compiler.models import DecisionExpr, PolicyDSLSpec, ValueRef


@dataclass(frozen=True)
class CircomComparisonNode:
    """One comparison node rendered into a primitive comparator component."""

    node_id: int
    op: str
    left: ValueRef
    right: ValueRef


@dataclass(frozen=True)
class CircomAggregateNode:
    """One aggregate block (`all`/`any`) for Circom output."""

    aggregate_id: int
    kind: str
    expression: str
    comparison_nodes: list[CircomComparisonNode]


class CircomExpressionBuilder:
    """Build aggregate/comparison tree for Circom code generation."""

    def __init__(self) -> None:
        self._next_aggregate_id = 0
        self._next_comparison_id = 0
        self._comparisons_by_aggregate: dict[int, list[CircomComparisonNode]] = {}
        self._aggregates: list[CircomAggregateNode] = []

    def build_root(self, *, kind: str, inner: DecisionExpr) -> tuple[int, list[CircomAggregateNode]]:
        root_id = self._register_aggregate(kind=kind, inner=inner)
        return root_id, list(self._aggregates)

    def _register_aggregate(self, *, kind: str, inner: DecisionExpr) -> int:
        aggregate_id = self._next_aggregate_id
        self._next_aggregate_id += 1
        idx_var = f"i_{aggregate_id}"
        expression = self._render_boolean_expr(
            inner,
            idx_var=idx_var,
            aggregate_id=aggregate_id,
        )
        self._aggregates.append(
            CircomAggregateNode(
                aggregate_id=aggregate_id,
                kind=kind,
                expression=expression,
                comparison_nodes=list(self._comparisons_by_aggregate.get(aggregate_id, [])),
            )
        )
        return aggregate_id

    def _render_boolean_expr(
        self,
        expr: DecisionExpr,
        *,
        idx_var: str,
        aggregate_id: int,
    ) -> str:
        if expr.kind == "comparison":
            assert expr.comparison is not None
            node_id = self._next_comparison_id
            self._next_comparison_id += 1
            node = CircomComparisonNode(
                node_id=node_id,
                op=expr.comparison.op,
                left=expr.comparison.left,
                right=expr.comparison.right,
            )
            self._comparisons_by_aggregate.setdefault(aggregate_id, []).append(node)
            return f"cmp_{node_id}[{idx_var}].out"

        if expr.kind == "and":
            parts = [
                self._render_boolean_expr(arg, idx_var=idx_var, aggregate_id=aggregate_id)
                for arg in expr.args
            ]
            return "(" + " * ".join(parts) + ")"

        if expr.kind == "or":
            parts = [
                self._render_boolean_expr(arg, idx_var=idx_var, aggregate_id=aggregate_id)
                for arg in expr.args
            ]
            acc = parts[0]
            for part in parts[1:]:
                acc = f"({acc} + {part} - ({acc} * {part}))"
            return acc

        if expr.kind == "not":
            assert expr.inner is not None
            inner = self._render_boolean_expr(
                expr.inner,
                idx_var=idx_var,
                aggregate_id=aggregate_id,
            )
            return f"(1 - ({inner}))"

        if expr.kind in {"all", "any"}:
            assert expr.inner is not None
            nested_id = self._register_aggregate(kind=expr.kind, inner=expr.inner)
            return f"agg_{nested_id}_value"

        raise framework_error(
            "policy_spec_unsupported",
            "Unsupported decision expression in Circom renderer",
            kind=expr.kind,
        )


def render_circom_source(spec: PolicyDSLSpec, *, spec_hash: str) -> str:
    """Render deterministic generated Circom source."""
    batch_size = spec.batch.batch_size
    assert spec.decision.inner is not None
    builder = CircomExpressionBuilder()
    root_aggregate_id, aggregates = builder.build_root(
        kind=spec.decision.kind,
        inner=spec.decision.inner,
    )

    declaration_lines: list[str] = []
    for aggregate in aggregates:
        declaration_lines.extend(
            [
                f"    signal agg_{aggregate.aggregate_id}_is_active[N];",
                f"    signal agg_{aggregate.aggregate_id}_decision_valid[N];",
                f"    signal agg_{aggregate.aggregate_id}_chain[N + 1];",
                f"    signal agg_{aggregate.aggregate_id}_value;",
                f"    component agg_{aggregate.aggregate_id}_active_flag[N];",
            ]
        )
        for comparison in aggregate.comparison_nodes:
            declaration_lines.append(f"    component cmp_{comparison.node_id}[N];")
        if aggregate.aggregate_id == root_aggregate_id:
            declaration_lines.extend(
                [
                    "    component root_balance_padding[N];",
                    "    component root_limit_padding[N];",
                ]
            )
    declarations = "\n".join(declaration_lines)

    blocks = "\n\n".join(
        render_circom_aggregate_block(
            aggregate=aggregate,
            include_zero_tail_constraints=aggregate.aggregate_id == root_aggregate_id,
        )
        for aggregate in aggregates
    )

    return f"""// Generated by vellum-compiler {spec.compiler_version}; do not edit manually.
// policy_id={spec.policy_id}
// spec_hash={spec_hash}
pragma circom 2.1.8;

include \"../../../circuits/library/banking_library.circom\";

template GeneratedLendingRisk(N) {{
    signal input limits[N];
    signal input active_count;
    signal input balances[N];

    signal output all_valid;
    signal output active_count_out;

    component active_count_bounds = ActiveCountBounds(N);
{declarations}

    active_count_bounds.active_count <== active_count;

{blocks}

    all_valid <== agg_{root_aggregate_id}_value;
    active_count_out <== active_count;
}}

component main {{public [limits, active_count]}} = GeneratedLendingRisk({batch_size});
"""


def render_circom_aggregate_block(
    *,
    aggregate: CircomAggregateNode,
    include_zero_tail_constraints: bool,
) -> str:
    """Render one aggregate (`all`/`any`) block."""
    agg_id = aggregate.aggregate_id
    loop_var = f"i_{agg_id}"
    if aggregate.kind == "all":
        chain_init = "1"
        decision_assignment = (
            f"        agg_{agg_id}_decision_valid[{loop_var}] <== ({aggregate.expression}) * "
            f"agg_{agg_id}_is_active[{loop_var}] + (1 - agg_{agg_id}_is_active[{loop_var}]);"
        )
        chain_update = (
            f"        agg_{agg_id}_chain[{loop_var} + 1] <== agg_{agg_id}_chain[{loop_var}] * "
            f"agg_{agg_id}_decision_valid[{loop_var}];"
        )
    elif aggregate.kind == "any":
        chain_init = "0"
        decision_assignment = (
            f"        agg_{agg_id}_decision_valid[{loop_var}] <== ({aggregate.expression}) * "
            f"agg_{agg_id}_is_active[{loop_var}];"
        )
        chain_update = (
            f"        agg_{agg_id}_chain[{loop_var} + 1] <== agg_{agg_id}_chain[{loop_var}] + "
            f"agg_{agg_id}_decision_valid[{loop_var}] - "
            f"(agg_{agg_id}_chain[{loop_var}] * agg_{agg_id}_decision_valid[{loop_var}]);"
        )
    else:
        raise framework_error(
            "policy_spec_unsupported",
            "Unsupported aggregate kind in Circom renderer",
            kind=aggregate.kind,
        )

    cmp_lines: list[str] = []
    for node in aggregate.comparison_nodes:
        cmp_lines.extend(
            [
                f"        cmp_{node.node_id}[{loop_var}] = {primitive_comparator_template(node.op)};",
                (
                    f"        cmp_{node.node_id}[{loop_var}].lhs <== "
                    f"{render_circom_value(node.left, idx_var=loop_var)};"
                ),
                (
                    f"        cmp_{node.node_id}[{loop_var}].rhs <== "
                    f"{render_circom_value(node.right, idx_var=loop_var)};"
                ),
            ]
        )

    zero_tail_lines: list[str] = []
    if include_zero_tail_constraints:
        zero_tail_lines.extend(
            [
                f"        root_balance_padding[{loop_var}] = ZeroPaddingInvariant();",
                f"        root_balance_padding[{loop_var}].value <== balances[{loop_var}];",
                (
                    f"        root_balance_padding[{loop_var}].is_active <== "
                    f"agg_{agg_id}_is_active[{loop_var}];"
                ),
                f"        root_limit_padding[{loop_var}] = ZeroPaddingInvariant();",
                f"        root_limit_padding[{loop_var}].value <== limits[{loop_var}];",
                (
                    f"        root_limit_padding[{loop_var}].is_active <== "
                    f"agg_{agg_id}_is_active[{loop_var}];"
                ),
            ]
        )

    body_lines = [
        f"    agg_{agg_id}_chain[0] <== {chain_init};",
        f"    for (var {loop_var} = 0; {loop_var} < N; {loop_var}++) {{",
        f"        agg_{agg_id}_active_flag[{loop_var}] = ActiveIndexFlag16();",
        f"        agg_{agg_id}_active_flag[{loop_var}].active_count <== active_count;",
        f"        agg_{agg_id}_active_flag[{loop_var}].index <== {loop_var};",
        (
            f"        agg_{agg_id}_is_active[{loop_var}] <== "
            f"agg_{agg_id}_active_flag[{loop_var}].is_active;"
        ),
        *cmp_lines,
        decision_assignment,
        *zero_tail_lines,
        chain_update,
        "    }",
        f"    agg_{agg_id}_value <== agg_{agg_id}_chain[N];",
    ]
    return "\n".join(body_lines)


def render_circom_value(value: ValueRef, *, idx_var: str) -> str:
    """Render one value node as Circom expression."""
    if value.const_int is not None:
        return str(value.const_int)
    ref = value.ref
    if ref == "balances":
        return f"balances[{idx_var}]"
    if ref == "limits":
        return f"limits[{idx_var}]"
    if ref == "active_count":
        return "active_count"
    raise framework_error(
        "policy_spec_unsupported",
        "Unsupported value reference in Circom renderer",
        ref=ref,
    )


def primitive_comparator_template(op: str) -> str:
    """Map operator to comparator primitive constructor."""
    mapping = {
        "<": "PrimitiveLessThan32()",
        ">": "PrimitiveGreaterThan32()",
        "<=": "PrimitiveLessEqThan32()",
        ">=": "PrimitiveGreaterEqThan32()",
        "==": "PrimitiveEqual()",
    }
    constructor = mapping.get(op)
    if constructor is None:
        raise framework_error(
            "policy_spec_unsupported",
            "Compiler received unsupported comparison operator",
            operator=op,
        )
    return constructor
