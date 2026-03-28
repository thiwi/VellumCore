"""Tests for policy DSL compiler and drift checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vellum_core.api.errors import FrameworkError
from vellum_core.policy_compiler.compiler import (
    build_compiler_metadata,
    check_drift,
    generate_policy_artifacts,
    load_policy_spec,
    sync_manifest_compiler_metadata,
    write_generated_artifacts,
)


def _write_lending_spec(
    path: Path,
    *,
    decision_kind: str = "all",
    decision_inner_lines: list[str] | None = None,
    op: str = ">",
    left_ref: str = "balances",
    right_ref: str = "limits",
) -> None:
    if decision_inner_lines is None:
        decision_inner_lines = [
            "    kind: comparison",
            "    comparison:",
            f'      op: "{op}"',
            "      left:",
            f"        ref: {left_ref}",
            "      right:",
            f"        ref: {right_ref}",
        ]
    path.write_text(
        "\n".join(
            [
                "policy_id: lending_risk_v1",
                'policy_version: "1.0.0"',
                "reference_policy: lending_risk_reference_v1",
                'spec_version: "1.0.0"',
                'compiler_version: "0.1.0"',
                "description: Test spec",
                "",
                "batch:",
                "  batch_size: 250",
                "",
                "inputs:",
                "  balances:",
                "    kind: uint32_array",
                "  limits:",
                "    kind: uint32_array",
                "",
                "decision:",
                f"  kind: {decision_kind}",
                "  inner:",
                *decision_inner_lines,
                "",
                "outputs:",
                "  all_valid:",
                "    expr: decision",
                "    value_type: bool",
                "    signal_index: 0",
                "  active_count_out:",
                "    expr: active_count",
                "    value_type: int",
                "    signal_index: 1",
                "",
                "primitives:",
                "  - SafeSub",
                "  - ActiveCountBounds",
                "",
                "expected_attestation:",
                "  decision_signal_index: 0",
                '  pass_signal_value: "1"',
                "",
                "generated_python_path: generated/lending_risk.py",
                "generated_circom_path: generated/lending_risk.circom",
                "circuit_id: batch_credit_check",
            ]
        ),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_generate_and_check_drift_roundtrip(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_lending_spec(spec_path)

    spec = load_policy_spec(spec_path)
    artifacts = generate_policy_artifacts(spec)
    assert artifacts.spec_hash
    assert "class GeneratedReferencePolicy" in artifacts.python_source
    assert "template GeneratedLendingRisk" in artifacts.circom_source

    assert check_drift(repo_root=tmp_path, spec=spec, artifacts=artifacts) is False
    python_path, circom_path = write_generated_artifacts(
        repo_root=tmp_path,
        spec=spec,
        artifacts=artifacts,
    )
    assert python_path.exists()
    assert circom_path.exists()
    assert check_drift(repo_root=tmp_path, spec=spec, artifacts=artifacts) is True

    python_path.write_text("drifted", encoding="utf-8")
    assert check_drift(repo_root=tmp_path, spec=spec, artifacts=artifacts) is False


@pytest.mark.unit
def test_invalid_yaml_raises_framework_error(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    spec_path.write_text("policy_id: [invalid", encoding="utf-8")

    with pytest.raises(FrameworkError) as exc:
        load_policy_spec(spec_path)

    assert exc.value.code == "policy_spec_invalid"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("op", "expected_ctor"),
    [
        (">", "PrimitiveGreaterThan32()"),
        ("<", "PrimitiveLessThan32()"),
        (">=", "PrimitiveGreaterEqThan32()"),
        ("<=", "PrimitiveLessEqThan32()"),
        ("==", "PrimitiveEqual()"),
    ],
)
def test_supported_comparison_operators_generate_expected_artifacts(
    tmp_path: Path, op: str, expected_ctor: str
) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_lending_spec(spec_path, op=op)

    spec = load_policy_spec(spec_path)
    artifacts = generate_policy_artifacts(spec)
    assert expected_ctor in artifacts.circom_source
    if op == "==":
        assert "balances[idx_0] == limits[idx_0]" in artifacts.python_source
    else:
        assert f"balances[idx_0] {op} limits[idx_0]" in artifacts.python_source


@pytest.mark.unit
def test_unsupported_comparison_refs_raise_framework_error(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_lending_spec(spec_path, left_ref="unknown_metric", right_ref="limits")

    spec = load_policy_spec(spec_path)
    with pytest.raises(FrameworkError) as exc:
        generate_policy_artifacts(spec)

    assert exc.value.code == "policy_spec_unsupported"


@pytest.mark.unit
def test_any_with_boolean_composition_and_constants_generates(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_lending_spec(
        spec_path,
        decision_kind="any",
        decision_inner_lines=[
            "    kind: and",
            "    args:",
            "      - kind: comparison",
            "        comparison:",
            '          op: ">"',
            "          left:",
            "            ref: balances",
            "          right:",
            "            const_int: 100",
            "      - kind: not",
            "        inner:",
            "          kind: comparison",
            "          comparison:",
            '            op: "<="',
            "            left:",
            "              ref: limits",
            "            right:",
            "              const_int: 50",
        ],
    )

    spec = load_policy_spec(spec_path)
    artifacts = generate_policy_artifacts(spec)
    assert "decision = any((" in artifacts.python_source
    assert "const_int" not in artifacts.python_source
    assert "not (" in artifacts.python_source
    assert 'include "../../../circuits/library/banking_library.circom";' in artifacts.circom_source
    assert "PrimitiveGreaterThan32()" in artifacts.circom_source
    assert "PrimitiveLessEqThan32()" in artifacts.circom_source
    assert "ActiveCountBounds(N)" in artifacts.circom_source
    assert "ActiveIndexFlag16()" in artifacts.circom_source
    assert "ZeroPaddingInvariant()" in artifacts.circom_source
    assert "agg_0_chain[0] <== 0;" in artifacts.circom_source
    assert "agg_0_chain[i_0 + 1] <== agg_0_chain[i_0] +" in artifacts.circom_source


@pytest.mark.unit
def test_nested_aggregate_is_supported(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_lending_spec(
        spec_path,
        decision_inner_lines=[
            "    kind: any",
            "    inner:",
            "      kind: and",
            "      args:",
            "        - kind: comparison",
            "          comparison:",
            '            op: ">"',
            "            left:",
            "              ref: balances",
            "            right:",
            "              ref: limits",
            "        - kind: all",
            "          inner:",
            "            kind: comparison",
            "            comparison:",
            '              op: ">="',
            "              left:",
            "                ref: balances",
            "              right:",
            "                const_int: 0",
        ],
    )

    spec = load_policy_spec(spec_path)
    artifacts = generate_policy_artifacts(spec)
    assert "for idx_1 in range(active_count)" in artifacts.python_source
    assert "all((" in artifacts.python_source
    assert "signal agg_1_value;" in artifacts.circom_source
    assert "signal agg_2_value;" in artifacts.circom_source
    assert "agg_2_chain[0] <== 1;" in artifacts.circom_source
    assert "agg_2_value" in artifacts.circom_source


@pytest.mark.unit
def test_negative_constant_is_rejected(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_lending_spec(
        spec_path,
        decision_inner_lines=[
            "    kind: comparison",
            "    comparison:",
            '      op: ">"',
            "      left:",
            "        ref: balances",
            "      right:",
            "        const_int: -1",
        ],
    )

    spec = load_policy_spec(spec_path)
    with pytest.raises(FrameworkError) as exc:
        generate_policy_artifacts(spec)
    assert exc.value.code == "policy_spec_unsupported"


@pytest.mark.unit
def test_repo_lending_risk_generated_artifacts_have_no_drift() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    spec_path = repo_root / "policy_packs" / "lending_risk_v1" / "policy_spec.yaml"
    spec = load_policy_spec(spec_path)
    artifacts = generate_policy_artifacts(spec)
    assert check_drift(repo_root=repo_root, spec=spec, artifacts=artifacts) is True


@pytest.mark.unit
def test_repo_lending_risk_portfolio_generated_artifacts_have_no_drift() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    spec_path = repo_root / "policy_packs" / "lending_risk_portfolio_v1" / "policy_spec.yaml"
    spec = load_policy_spec(spec_path)
    artifacts = generate_policy_artifacts(spec)
    assert check_drift(repo_root=repo_root, spec=spec, artifacts=artifacts) is True


@pytest.mark.unit
def test_check_drift_detects_manifest_metadata_mismatch(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    manifest_path = tmp_path / "manifest.json"
    _write_lending_spec(spec_path)
    manifest_path.write_text("{}", encoding="utf-8")

    spec = load_policy_spec(spec_path)
    artifacts = generate_policy_artifacts(spec)
    write_generated_artifacts(repo_root=tmp_path, spec=spec, artifacts=artifacts)
    sync_manifest_compiler_metadata(
        manifest_path=manifest_path,
        metadata=build_compiler_metadata(spec=spec, artifacts=artifacts),
    )
    assert check_drift(
        repo_root=tmp_path,
        spec=spec,
        artifacts=artifacts,
        manifest_path=manifest_path,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["compiler_metadata"]["generated_from_hash"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert (
        check_drift(
            repo_root=tmp_path,
            spec=spec,
            artifacts=artifacts,
            manifest_path=manifest_path,
        )
        is False
    )
