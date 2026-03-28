"""Tests for grpc cutover gate evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from vellum_core import cutover_gate


def test_cutover_gate_passes_when_all_thresholds_met() -> None:
    result = cutover_gate.evaluate_cutover_gate(
        cutover_gate.CutoverGateInput(
            days_observed=7,
            compared_runs=1000,
            functional_mismatches=0,
            snarkjs_p95_ms=1200.0,
            grpc_p95_ms=500.0,
        )
    )
    assert result.pass_gate is True
    assert result.speedup_p95 == 2.4
    assert result.reasons == []


def test_cutover_gate_fails_with_multiple_reasons() -> None:
    result = cutover_gate.evaluate_cutover_gate(
        cutover_gate.CutoverGateInput(
            days_observed=3,
            compared_runs=450,
            functional_mismatches=2,
            snarkjs_p95_ms=900.0,
            grpc_p95_ms=600.0,
        )
    )
    assert result.pass_gate is False
    assert len(result.reasons) == 4
    assert any("insufficient_shadow_days" in reason for reason in result.reasons)
    assert any("insufficient_compared_runs" in reason for reason in result.reasons)
    assert any("functional_mismatch_detected" in reason for reason in result.reasons)
    assert any("insufficient_p95_speedup" in reason for reason in result.reasons)


def test_cutover_gate_main_returns_nonzero_on_failure(tmp_path: Path, capsys: object) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "days_observed": 7,
                "compared_runs": 1200,
                "functional_mismatches": 0,
                "snarkjs_p95_ms": 500.0,
                "grpc_p95_ms": 350.0,
            }
        ),
        encoding="utf-8",
    )

    code = cutover_gate.main(["--summary-json", str(summary_path)])
    assert code == 1
    _ = capsys


def test_cutover_gate_main_writes_output_json(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    out_path = tmp_path / "result.json"
    summary_path.write_text(
        json.dumps(
            {
                "days_observed": 8,
                "compared_runs": 1200,
                "functional_mismatches": 0,
                "snarkjs_p95_ms": 800.0,
                "grpc_p95_ms": 300.0,
            }
        ),
        encoding="utf-8",
    )

    code = cutover_gate.main(
        [
            "--summary-json",
            str(summary_path),
            "--output-json",
            str(out_path),
        ]
    )
    assert code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["pass_gate"] is True
    assert payload["speedup_p95"] > 2.0
