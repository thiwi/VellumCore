"""Compiler helpers for transpiling YAML policy specs into Python and Circom."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vellum_core.api.errors import framework_error
from vellum_core.policy_compiler.models import DecisionExpr, PolicyDSLSpec, ValueRef


@dataclass(frozen=True)
class CompilerArtifacts:
    """Generated source artifacts and deterministic spec hash."""

    spec_hash: str
    python_source: str
    circom_source: str


@dataclass(frozen=True)
class CompilerMetadata:
    """Manifest metadata describing one generated artifact set."""

    spec_version: str
    compiler_version: str
    generated_from_hash: str
    generated_python_path: str
    generated_circom_path: str

    def as_dict(self) -> dict[str, str]:
        """Serialize metadata for JSON manifest embedding."""
        return {
            "spec_version": self.spec_version,
            "compiler_version": self.compiler_version,
            "generated_from_hash": self.generated_from_hash,
            "generated_python_path": self.generated_python_path,
            "generated_circom_path": self.generated_circom_path,
        }


def load_policy_spec(path: Path) -> PolicyDSLSpec:
    """Load and validate one policy DSL file."""
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise framework_error(
            "policy_spec_invalid",
            "Policy spec YAML is invalid",
            path=str(path),
            reason=str(exc),
        ) from exc
    if not isinstance(parsed, dict):
        raise framework_error(
            "policy_spec_invalid",
            "Policy spec must decode to an object",
            path=str(path),
        )
    try:
        return PolicyDSLSpec.model_validate(parsed)
    except Exception as exc:
        raise framework_error(
            "policy_spec_invalid",
            "Policy spec validation failed",
            path=str(path),
            reason=str(exc),
        ) from exc


def generate_policy_artifacts(spec: PolicyDSLSpec) -> CompilerArtifacts:
    """Generate deterministic Python and Circom sources for one DSL spec."""
    _ensure_supported_decision(spec)
    canonical = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    spec_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    python_source = _render_python_source(spec, spec_hash=spec_hash)
    circom_source = _render_circom_source(spec, spec_hash=spec_hash)
    return CompilerArtifacts(
        spec_hash=spec_hash,
        python_source=python_source,
        circom_source=circom_source,
    )


def write_generated_artifacts(
    *,
    repo_root: Path,
    spec: PolicyDSLSpec,
    artifacts: CompilerArtifacts,
) -> tuple[Path, Path]:
    """Write generated artifacts to deterministic repo-relative target paths."""
    python_path = repo_root / spec.generated_python_path
    circom_path = repo_root / spec.generated_circom_path
    python_path.parent.mkdir(parents=True, exist_ok=True)
    circom_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text(artifacts.python_source, encoding="utf-8")
    circom_path.write_text(artifacts.circom_source, encoding="utf-8")
    return python_path, circom_path


def build_compiler_metadata(*, spec: PolicyDSLSpec, artifacts: CompilerArtifacts) -> CompilerMetadata:
    """Build manifest compiler metadata for one spec/artifact set."""
    return CompilerMetadata(
        spec_version=spec.spec_version,
        compiler_version=spec.compiler_version,
        generated_from_hash=artifacts.spec_hash,
        generated_python_path=spec.generated_python_path,
        generated_circom_path=spec.generated_circom_path,
    )


def sync_manifest_compiler_metadata(
    *,
    manifest_path: Path,
    metadata: CompilerMetadata,
) -> bool:
    """Update manifest compiler metadata and return True when file changed."""
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(manifest, dict):
        return False

    next_metadata = metadata.as_dict()
    current = manifest.get("compiler_metadata")
    if current == next_metadata:
        return False

    manifest["compiler_metadata"] = next_metadata
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def check_drift(
    *,
    repo_root: Path,
    spec: PolicyDSLSpec,
    artifacts: CompilerArtifacts,
    manifest_path: Path | None = None,
) -> bool:
    """Return True when generated artifacts are identical to committed files."""
    python_path = repo_root / spec.generated_python_path
    circom_path = repo_root / spec.generated_circom_path
    if not python_path.exists() or not circom_path.exists():
        return False
    committed_python = python_path.read_text(encoding="utf-8")
    committed_circom = circom_path.read_text(encoding="utf-8")
    artifacts_match = (
        committed_python == artifacts.python_source
        and committed_circom == artifacts.circom_source
    )
    if not artifacts_match:
        return False

    if manifest_path is None or not manifest_path.exists():
        return True
    return _manifest_metadata_matches(
        manifest_path=manifest_path,
        expected=build_compiler_metadata(spec=spec, artifacts=artifacts),
    )


def _manifest_metadata_matches(*, manifest_path: Path, expected: CompilerMetadata) -> bool:
    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(manifest, dict):
        return False
    return manifest.get("compiler_metadata") == expected.as_dict()


def _ensure_supported_decision(spec: PolicyDSLSpec) -> None:
    decision = spec.decision
    if decision.kind not in {"all", "any"} or decision.inner is None:
        raise framework_error(
            "policy_spec_unsupported",
            "Compiler currently supports `all`/`any` as top-level decision",
            policy_id=spec.policy_id,
        )
    _validate_boolean_expr(decision.inner, policy_id=spec.policy_id, indexed_context=True)


def _render_python_source(spec: PolicyDSLSpec, *, spec_hash: str) -> str:
    """Render deterministic generated Python reference policy."""
    batch_size = spec.batch.batch_size
    reference_policy = spec.reference_policy
    policy_id = spec.policy_id
    decision_agg = "all" if spec.decision.kind == "all" else "any"
    idx_counter = [1]
    decision_inner_expr = _render_python_boolean_expr(
        spec.decision.inner,
        idx_var="idx_0",
        idx_counter=idx_counter,
    )
    decision_expr = f'{decision_agg}(({decision_inner_expr}) for idx_0 in range(active_count))'
    return f'''"""Generated by vellum-compiler {spec.compiler_version}; do not edit manually."""

from __future__ import annotations

from typing import Any

from vellum_core.api.errors import framework_error
from vellum_core.logic.batcher import MAX_UINT32, batch_prepare_from_private_input, batch_prepare_input
from vellum_core.policies.base import PolicyDecision
from vellum_core.policies.normalization import require_integer_list


class GeneratedReferencePolicy:
    """Generated reference policy for `{policy_id}`."""

    reference_policy = "{reference_policy}"
    policy_id = "{policy_id}"
    spec_hash = "{spec_hash}"
    batch_size = {batch_size}

    def validate(self, evidence_payload: dict[str, Any]) -> None:
        _ = self.normalize(evidence_payload)

    def normalize(self, evidence_payload: dict[str, Any]) -> dict[str, Any]:
        private_input = evidence_payload.get("private_input")
        if isinstance(private_input, dict):
            try:
                prepared = batch_prepare_from_private_input(private_input)
            except ValueError as exc:
                raise framework_error(
                    "invalid_evidence_payload",
                    "Evidence payload failed batch validation",
                    reason=str(exc),
                ) from exc
            return prepared.to_circuit_input()

        balances = require_integer_list(
            field="balances",
            value=evidence_payload.get("balances"),
            minimum=0,
            maximum=MAX_UINT32,
        )
        limits = require_integer_list(
            field="limits",
            value=evidence_payload.get("limits"),
            minimum=0,
            maximum=MAX_UINT32,
        )
        try:
            prepared = batch_prepare_input(balances=balances, limits=limits, batch_size=self.batch_size)
        except ValueError as exc:
            raise framework_error(
                "invalid_evidence_payload",
                "Evidence payload failed batch validation",
                reason=str(exc),
            ) from exc
        return prepared.to_circuit_input()

    def to_private_input(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        return {{
            "balances": list(normalized_evidence["balances"]),
            "limits": list(normalized_evidence["limits"]),
            "active_count": int(normalized_evidence["active_count"]),
        }}

    def evaluate_reference(self, normalized_evidence: dict[str, Any]) -> PolicyDecision:
        active_count = int(normalized_evidence["active_count"])
        balances = list(normalized_evidence["balances"])
        limits = list(normalized_evidence["limits"])
        decision = {decision_expr}
        return "pass" if decision else "fail"

    def project_public_outputs(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        active_count = int(normalized_evidence["active_count"])
        balances = list(normalized_evidence["balances"])
        limits = list(normalized_evidence["limits"])
        all_valid = {decision_expr}
        return {{
            "all_valid": all_valid,
            "active_count_out": active_count,
        }}
'''


def _render_circom_source(spec: PolicyDSLSpec, *, spec_hash: str) -> str:
    """Render deterministic generated Circom source for lending-risk policy."""
    batch_size = spec.batch.batch_size
    assert spec.decision.inner is not None
    builder = _CircomExpressionBuilder()
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
        _render_circom_aggregate_block(
            aggregate=aggregate,
            include_zero_tail_constraints=aggregate.aggregate_id == root_aggregate_id,
        )
        for aggregate in aggregates
    )
    return f"""// Generated by vellum-compiler {spec.compiler_version}; do not edit manually.
// policy_id={spec.policy_id}
// spec_hash={spec_hash}
pragma circom 2.1.8;

include "../../../circuits/library/banking_library.circom";

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


def _python_operator_token(op: str) -> str:
    if op in {"<", ">", "<=", ">=", "=="}:
        return op
    raise framework_error(
        "policy_spec_unsupported",
        "Compiler received unsupported comparison operator",
        operator=op,
    )


def _primitive_comparator_template(op: str) -> str:
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


def _validate_boolean_expr(
    expr: DecisionExpr,
    *,
    policy_id: str,
    indexed_context: bool,
) -> None:
    if expr.kind == "comparison":
        if expr.comparison is None:
            raise framework_error(
                "policy_spec_unsupported",
                "Comparison node is missing comparison payload",
                policy_id=policy_id,
            )
        _validate_value(expr.comparison.left, policy_id=policy_id, indexed_context=indexed_context)
        _validate_value(expr.comparison.right, policy_id=policy_id, indexed_context=indexed_context)
        return
    if expr.kind in {"and", "or"}:
        for arg in expr.args:
            _validate_boolean_expr(arg, policy_id=policy_id, indexed_context=indexed_context)
        return
    if expr.kind == "not":
        if expr.inner is None:
            raise framework_error(
                "policy_spec_unsupported",
                "`not` node must define inner expression",
                policy_id=policy_id,
            )
        _validate_boolean_expr(expr.inner, policy_id=policy_id, indexed_context=indexed_context)
        return
    if expr.kind in {"all", "any"}:
        if expr.inner is None:
            raise framework_error(
                "policy_spec_unsupported",
                f"`{expr.kind}` node must define inner expression",
                policy_id=policy_id,
            )
        _validate_boolean_expr(expr.inner, policy_id=policy_id, indexed_context=True)
        return
    raise framework_error(
        "policy_spec_unsupported",
        "Unsupported decision expression kind for compiler v1",
        policy_id=policy_id,
        kind=expr.kind,
    )


def _validate_value(value: ValueRef, *, policy_id: str, indexed_context: bool) -> None:
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


def _render_python_boolean_expr(
    expr: DecisionExpr,
    *,
    idx_var: str,
    idx_counter: list[int],
) -> str:
    if expr.kind == "comparison":
        assert expr.comparison is not None
        left = _render_python_value(expr.comparison.left, idx_var=idx_var)
        right = _render_python_value(expr.comparison.right, idx_var=idx_var)
        return f"({left} {_python_operator_token(expr.comparison.op)} {right})"
    if expr.kind == "and":
        return (
            "("
            + " and ".join(
                _render_python_boolean_expr(arg, idx_var=idx_var, idx_counter=idx_counter)
                for arg in expr.args
            )
            + ")"
        )
    if expr.kind == "or":
        return (
            "("
            + " or ".join(
                _render_python_boolean_expr(arg, idx_var=idx_var, idx_counter=idx_counter)
                for arg in expr.args
            )
            + ")"
        )
    if expr.kind == "not":
        assert expr.inner is not None
        return (
            f"(not ({_render_python_boolean_expr(expr.inner, idx_var=idx_var, idx_counter=idx_counter)}))"
        )
    if expr.kind in {"all", "any"}:
        assert expr.inner is not None
        nested_var = f"idx_{idx_counter[0]}"
        idx_counter[0] += 1
        agg_token = "all" if expr.kind == "all" else "any"
        inner = _render_python_boolean_expr(expr.inner, idx_var=nested_var, idx_counter=idx_counter)
        return f"{agg_token}(({inner}) for {nested_var} in range(active_count))"
    raise framework_error(
        "policy_spec_unsupported",
        "Unsupported decision expression in Python renderer",
        kind=expr.kind,
    )


def _render_python_value(value: ValueRef, *, idx_var: str) -> str:
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
        "Unsupported value reference in Python renderer",
        ref=ref,
    )


@dataclass(frozen=True)
class _CircomComparisonNode:
    node_id: int
    op: str
    left: ValueRef
    right: ValueRef


@dataclass(frozen=True)
class _CircomAggregateNode:
    aggregate_id: int
    kind: str
    expression: str
    comparison_nodes: list[_CircomComparisonNode]


class _CircomExpressionBuilder:
    def __init__(self) -> None:
        self._next_aggregate_id = 0
        self._next_comparison_id = 0
        self._comparisons_by_aggregate: dict[int, list[_CircomComparisonNode]] = {}
        self._aggregates: list[_CircomAggregateNode] = []

    def build_root(self, *, kind: str, inner: DecisionExpr) -> tuple[int, list[_CircomAggregateNode]]:
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
            _CircomAggregateNode(
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
            node = _CircomComparisonNode(
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


def _render_circom_value(value: ValueRef, *, idx_var: str) -> str:
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


def _render_circom_aggregate_block(
    *,
    aggregate: _CircomAggregateNode,
    include_zero_tail_constraints: bool,
) -> str:
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
                f"        cmp_{node.node_id}[{loop_var}] = {_primitive_comparator_template(node.op)};",
                (
                    f"        cmp_{node.node_id}[{loop_var}].lhs <== "
                    f"{_render_circom_value(node.left, idx_var=loop_var)};"
                ),
                (
                    f"        cmp_{node.node_id}[{loop_var}].rhs <== "
                    f"{_render_circom_value(node.right, idx_var=loop_var)};"
                ),
            ]
        )

    zero_tail_lines: list[str] = []
    if include_zero_tail_constraints:
        zero_tail_lines.extend(
            [
                (
                    f"        root_balance_padding[{loop_var}] = ZeroPaddingInvariant();"
                ),
                (
                    f"        root_balance_padding[{loop_var}].value <== balances[{loop_var}];"
                ),
                (
                    f"        root_balance_padding[{loop_var}].is_active <== "
                    f"agg_{agg_id}_is_active[{loop_var}];"
                ),
                (
                    f"        root_limit_padding[{loop_var}] = ZeroPaddingInvariant();"
                ),
                (
                    f"        root_limit_padding[{loop_var}].value <== limits[{loop_var}];"
                ),
                (
                    f"        root_limit_padding[{loop_var}].is_active <== "
                    f"agg_{agg_id}_is_active[{loop_var}];"
                ),
            ]
        )

    body_lines = [
        f"    agg_{agg_id}_chain[0] <== {chain_init};",
        f"    for (var {loop_var} = 0; {loop_var} < N; {loop_var}++) {{",
        (
            f"        agg_{agg_id}_active_flag[{loop_var}] = ActiveIndexFlag16();"
        ),
        (
            f"        agg_{agg_id}_active_flag[{loop_var}].active_count <== active_count;"
        ),
        (
            f"        agg_{agg_id}_active_flag[{loop_var}].index <== {loop_var};"
        ),
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
