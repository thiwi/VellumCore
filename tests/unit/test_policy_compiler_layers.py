"""Layer-level tests for policy compiler internals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vellum_core.api.errors import FrameworkError
from vellum_core.policy_compiler.artifacts import CompilerArtifacts, CompilerMetadata
from vellum_core.policy_compiler.circom_renderer import primitive_comparator_template, render_circom_source
from vellum_core.policy_compiler.drift import check_drift, write_generated_artifacts
from vellum_core.policy_compiler.manifest import manifest_metadata_matches, sync_manifest_compiler_metadata
from vellum_core.policy_compiler.python_renderer import python_operator_token, render_python_source
from vellum_core.policy_compiler.spec_loader import load_policy_spec
from vellum_core.policy_compiler.validation import ensure_supported_decision


def _write_spec(path: Path, *, decision_kind: str = "all") -> None:
    path.write_text(
        "\n".join(
            [
                "policy_id: lending_risk_v1",
                'policy_version: "1.0.0"',
                "reference_policy: lending_risk_reference_v1",
                'spec_version: "1.0.0"',
                'compiler_version: "0.1.0"',
                "description: Layer test spec",
                "",
                "batch:",
                "  batch_size: 8",
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
                "    kind: comparison",
                "    comparison:",
                '      op: ">="',
                "      left:",
                "        ref: balances",
                "      right:",
                "        ref: limits",
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
def test_validation_rejects_unsupported_root_aggregate(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_spec(spec_path)
    spec = load_policy_spec(spec_path)
    assert spec.decision.inner is not None
    assert spec.decision.inner.comparison is not None
    spec.decision.inner.comparison.left.ref = "unknown_metric"

    with pytest.raises(FrameworkError) as exc:
        ensure_supported_decision(spec)

    assert exc.value.code == "policy_spec_unsupported"


@pytest.mark.unit
def test_renderer_operator_guards_reject_unknown_operator() -> None:
    with pytest.raises(FrameworkError):
        python_operator_token("!==")
    with pytest.raises(FrameworkError):
        primitive_comparator_template("!==")


@pytest.mark.unit
def test_renderers_emit_expected_markers(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_spec(spec_path)
    spec = load_policy_spec(spec_path)

    py = render_python_source(spec, spec_hash="abc")
    circom = render_circom_source(spec, spec_hash="abc")

    assert "class GeneratedReferencePolicy" in py
    assert "decision = all((" in py
    assert "template GeneratedLendingRisk" in circom
    assert "PrimitiveGreaterEqThan32()" in circom


@pytest.mark.unit
def test_manifest_sync_and_drift_helpers_roundtrip(tmp_path: Path) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_spec(spec_path)
    spec = load_policy_spec(spec_path)

    artifacts = CompilerArtifacts(
        spec_hash="abc123",
        python_source="print('py')\n",
        circom_source="template T(){}\n",
    )
    write_generated_artifacts(repo_root=tmp_path, spec=spec, artifacts=artifacts)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    metadata = CompilerMetadata(
        spec_version=spec.spec_version,
        compiler_version=spec.compiler_version,
        generated_from_hash=artifacts.spec_hash,
        generated_python_path=spec.generated_python_path,
        generated_circom_path=spec.generated_circom_path,
    )
    assert sync_manifest_compiler_metadata(manifest_path=manifest_path, metadata=metadata) is True
    assert sync_manifest_compiler_metadata(manifest_path=manifest_path, metadata=metadata) is False
    assert manifest_metadata_matches(manifest_path=manifest_path, expected=metadata)

    assert check_drift(
        repo_root=tmp_path,
        spec=spec,
        artifacts=artifacts,
        manifest_path=manifest_path,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["compiler_metadata"]["generated_from_hash"] = "tampered"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        check_drift(
            repo_root=tmp_path,
            spec=spec,
            artifacts=artifacts,
            manifest_path=manifest_path,
        )
        is False
    )
