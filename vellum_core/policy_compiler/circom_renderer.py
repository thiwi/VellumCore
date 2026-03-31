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
    parameter_order = list(spec.policy_parameters.keys())
    parameter_index = {name: idx for idx, name in enumerate(parameter_order)}

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
    if parameter_order:
        declaration_lines.extend(
            [
                "    signal computed_policy_params_hash;",
                f"    component policy_params_hasher = Poseidon({len(parameter_order)});",
            ]
        )
    declarations = "\n".join(declaration_lines)

    blocks = "\n\n".join(
        render_circom_aggregate_block(
            aggregate=aggregate,
            include_zero_tail_constraints=aggregate.aggregate_id == root_aggregate_id,
            parameter_index=parameter_index,
        )
        for aggregate in aggregates
    )

    output_declarations = _render_output_declarations(spec)
    output_assignments = _render_output_assignments(
        spec=spec,
        root_aggregate_id=root_aggregate_id,
        has_parameters=bool(parameter_order),
    )
    parameter_inputs = ""
    parameter_constraints = ""
    main_public_tail = ""
    if parameter_order:
        parameter_inputs = (
            f"    signal input policy_params[{len(parameter_order)}];\n"
            "    signal input expected_policy_params_hash;\n"
        )
        parameter_constraints = (
            f"    for (var p = 0; p < {len(parameter_order)}; p++) {{\n"
            "        policy_params_hasher.inputs[p] <== policy_params[p];\n"
            "    }\n"
            "    computed_policy_params_hash <== policy_params_hasher.out;\n"
            "    computed_policy_params_hash === expected_policy_params_hash;\n"
        )
        main_public_tail = ", policy_params, expected_policy_params_hash"

    return f"""// Generated by vellum-compiler {spec.compiler_version}; do not edit manually.
// policy_id={spec.policy_id}
// spec_hash={spec_hash}
pragma circom 2.1.8;

include "../../../circuits/library/banking_library.circom";

template GeneratedLendingRisk(N) {{
    signal input limits[N];
    signal input active_count;
    signal input balances[N];
{parameter_inputs}
{output_declarations}

    component active_count_bounds = ActiveCountBounds(N);
{declarations}

    active_count_bounds.active_count <== active_count;
{parameter_constraints}
{blocks}

{output_assignments}
}}

component main {{public [limits, active_count{main_public_tail}]}} = GeneratedLendingRisk({batch_size});
"""


def render_circom_aggregate_block(
    *,
    aggregate: CircomAggregateNode,
    include_zero_tail_constraints: bool,
    parameter_index: dict[str, int],
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
                    f"{render_circom_value(node.left, idx_var=loop_var, parameter_index=parameter_index)};"
                ),
                (
                    f"        cmp_{node.node_id}[{loop_var}].rhs <== "
                    f"{render_circom_value(node.right, idx_var=loop_var, parameter_index=parameter_index)};"
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


def render_circom_value(
    value: ValueRef,
    *,
    idx_var: str,
    parameter_index: dict[str, int],
) -> str:
    """Render one value node as Circom expression."""
    if value.const_int is not None:
        return str(value.const_int)
    if value.param is not None:
        if value.param not in parameter_index:
            raise framework_error(
                "policy_spec_unsupported",
                "Unknown policy parameter in Circom renderer",
                param=value.param,
            )
        return f"policy_params[{parameter_index[value.param]}]"
    ref = value.ref
    if ref == "balances":
        return f"balances[{idx_var}]"
    if ref == "limits":
        return f"limits[{idx_var}]"
    if ref == "active_count":
        return "active_count"
    if isinstance(ref, str) and ref.startswith("policy_params."):
        param_name = ref.split(".", 1)[1]
        if param_name not in parameter_index:
            raise framework_error(
                "policy_spec_unsupported",
                "Unknown policy parameter in Circom renderer",
                param=param_name,
            )
        return f"policy_params[{parameter_index[param_name]}]"
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


def _render_output_declarations(spec: PolicyDSLSpec) -> str:
    lines: list[str] = []
    for name in spec.outputs:
        lines.append(f"    signal output {name};")
    return "\n".join(lines)


def _render_output_assignments(
    *,
    spec: PolicyDSLSpec,
    root_aggregate_id: int,
    has_parameters: bool,
) -> str:
    lines: list[str] = []
    for output_name, output in spec.outputs.items():
        if output.expr == "decision":
            lines.append(f"    {output_name} <== agg_{root_aggregate_id}_value;")
            continue
        if output.expr == "active_count":
            lines.append(f"    {output_name} <== active_count;")
            continue
        if output.expr == "policy_params_hash":
            if has_parameters:
                lines.append(f"    {output_name} <== computed_policy_params_hash;")
            else:
                lines.append(f"    {output_name} <== 0;")
            continue
        raise framework_error(
            "policy_spec_unsupported",
            "Unsupported output expression in Circom renderer",
            output=output_name,
            expr=output.expr,
        )
    return "\n".join(lines)

