"""Tests for vellum-compiler CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vellum_core.policy_compiler import cli


def _write_spec(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "policy_id: lending_risk_v1",
                'policy_version: "1.0.0"',
                "reference_policy: lending_risk_reference_v1",
                'spec_version: "1.0.0"',
                'compiler_version: "0.1.0"',
                "batch:",
                "  batch_size: 250",
                "inputs:",
                "  balances:",
                "    kind: uint32_array",
                "  limits:",
                "    kind: uint32_array",
                "decision:",
                "  kind: all",
                "  inner:",
                "    kind: comparison",
                "    comparison:",
                '      op: ">"',
                "      left:",
                "        ref: balances",
                "      right:",
                "        ref: limits",
                "outputs:",
                "  all_valid:",
                "    expr: decision",
                "    value_type: bool",
                "    signal_index: 0",
                "  active_count_out:",
                "    expr: active_count",
                "    value_type: int",
                "    signal_index: 1",
                "primitives:",
                "  - SafeSub",
                "expected_attestation:",
                "  decision_signal_index: 0",
                '  pass_signal_value: "1"',
                "generated_python_path: generated/lending_risk.py",
                "generated_circom_path: generated/lending_risk.circom",
                "circuit_id: batch_credit_check",
            ]
        ),
        encoding="utf-8",
    )


def _write_manifest(path: Path, *, generated_from_hash: str = "stale") -> None:
    path.write_text(
        json.dumps(
            {
                "policy_id": "lending_risk_v1",
                "compiler_metadata": {
                    "spec_version": "1.0.0",
                    "compiler_version": "0.1.0",
                    "generated_from_hash": generated_from_hash,
                    "generated_python_path": "generated/lending_risk.py",
                    "generated_circom_path": "generated/lending_risk.circom",
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_cli_validate_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_spec(spec_path)

    code = cli.main(["validate", str(spec_path)])
    assert code == 0
    assert "valid:" in capsys.readouterr().out


@pytest.mark.unit
def test_cli_generate_and_check_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    _write_spec(spec_path)

    code = cli.main(
        [
            "generate",
            str(spec_path),
            "--repo-root",
            str(tmp_path),
            "--print-metadata-json",
        ]
    )
    assert code == 0
    metadata = json.loads(capsys.readouterr().out)
    assert metadata["policy_id"] == "lending_risk_v1"

    drift_code = cli.main(["check-drift", str(spec_path), "--repo-root", str(tmp_path)])
    assert drift_code == 0
    assert "drift:none" in capsys.readouterr().out

    generated_python = tmp_path / metadata["generated_python_path"]
    generated_python.write_text("changed", encoding="utf-8")

    drift_code = cli.main(["check-drift", str(spec_path), "--repo-root", str(tmp_path)])
    assert drift_code == 1
    assert "drift:detected" in capsys.readouterr().out


@pytest.mark.unit
def test_cli_generate_updates_manifest_metadata(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    manifest_path = tmp_path / "manifest.json"
    _write_spec(spec_path)
    _write_manifest(manifest_path, generated_from_hash="old-hash")

    code = cli.main(
        [
            "generate",
            str(spec_path),
            "--repo-root",
            str(tmp_path),
            "--print-metadata-json",
        ]
    )
    assert code == 0
    metadata = json.loads(capsys.readouterr().out)
    assert metadata["manifest_updated"] is True

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    compiler_metadata = manifest["compiler_metadata"]
    assert compiler_metadata["generated_from_hash"] == metadata["generated_from_hash"]
    assert compiler_metadata["generated_python_path"] == "generated/lending_risk.py"
    assert compiler_metadata["generated_circom_path"] == "generated/lending_risk.circom"


@pytest.mark.unit
def test_cli_check_drift_detects_manifest_metadata_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_path = tmp_path / "policy_spec.yaml"
    manifest_path = tmp_path / "manifest.json"
    _write_spec(spec_path)
    _write_manifest(manifest_path)

    code = cli.main(
        [
            "generate",
            str(spec_path),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    _ = capsys.readouterr()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["compiler_metadata"]["generated_from_hash"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    drift_code = cli.main(["check-drift", str(spec_path), "--repo-root", str(tmp_path)])
    assert drift_code == 1
    assert "drift:detected" in capsys.readouterr().out
