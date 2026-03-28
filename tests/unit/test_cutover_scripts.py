"""Tests for cutover helper scripts in systematic_study."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_collect_shadow_metrics_from_file(tmp_path: Path) -> None:
    input_path = tmp_path / "metrics.txt"
    output_path = tmp_path / "summary.json"
    input_path.write_text(
        "\n".join(
            [
                '# HELP vellum_proof_shadow_events_total Shadow-mode proof backend comparison events.',
                '# TYPE vellum_proof_shadow_events_total counter',
                'vellum_proof_shadow_events_total{event_type="public_signals",outcome="match"} 1200',
                'vellum_proof_shadow_events_total{event_type="public_signals",outcome="mismatch"} 0',
                'vellum_proof_shadow_events_total{event_type="verify",outcome="mismatch"} 0',
            ]
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "systematic_study" / "collect_shadow_metrics.py"),
            "--input-file",
            str(input_path),
            "--output-json",
            str(output_path),
        ],
        check=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["compared_runs"] == 1200
    assert payload["functional_mismatches"] == 0


@pytest.mark.unit
def test_collect_shadow_metrics_uses_benchmark_fallback_when_counters_missing(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "metrics.txt"
    benchmark_path = tmp_path / "shadow_benchmark.json"
    output_path = tmp_path / "summary.json"
    input_path.write_text(
        "\n".join(
            [
                '# HELP vellum_proof_shadow_events_total Shadow-mode proof backend comparison events.',
                '# TYPE vellum_proof_shadow_events_total counter',
            ]
        ),
        encoding="utf-8",
    )
    benchmark_path.write_text(
        json.dumps({"runs_completed": 42, "runs_failed": 3}),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "systematic_study" / "collect_shadow_metrics.py"),
            "--input-file",
            str(input_path),
            "--fallback-benchmark-json",
            str(benchmark_path),
            "--output-json",
            str(output_path),
        ],
        check=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["compared_runs"] == 42
    assert payload["functional_mismatches"] == 0
    assert payload["fallback_source"] == str(benchmark_path)
    assert payload["fallback_runs_failed"] == 3


@pytest.mark.unit
def test_evaluate_cutover_gate_script_fails_when_speedup_below_threshold(tmp_path: Path) -> None:
    snark = tmp_path / "snark.json"
    grpc = tmp_path / "grpc.json"
    out = tmp_path / "gate.json"
    snark.write_text(json.dumps({"p95_ms": 1000.0}), encoding="utf-8")
    grpc.write_text(json.dumps({"p95_ms": 800.0}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "systematic_study" / "evaluate_cutover_gate.py"),
            "--snarkjs-benchmark",
            str(snark),
            "--grpc-benchmark",
            str(grpc),
            "--days-observed",
            "7",
            "--compared-runs",
            "1000",
            "--functional-mismatches",
            "0",
            "--output-json",
            str(out),
        ],
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["result"]["pass_gate"] is False


@pytest.mark.unit
def test_evaluate_cutover_gate_script_uses_shadow_summary_when_provided(tmp_path: Path) -> None:
    snark = tmp_path / "snark.json"
    grpc = tmp_path / "grpc.json"
    shadow = tmp_path / "shadow.json"
    out = tmp_path / "gate.json"
    snark.write_text(json.dumps({"p95_ms": 1000.0}), encoding="utf-8")
    grpc.write_text(json.dumps({"p95_ms": 400.0}), encoding="utf-8")
    shadow.write_text(
        json.dumps({"compared_runs": 1200, "functional_mismatches": 0}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "systematic_study" / "evaluate_cutover_gate.py"),
            "--snarkjs-benchmark",
            str(snark),
            "--grpc-benchmark",
            str(grpc),
            "--days-observed",
            "7",
            "--shadow-summary",
            str(shadow),
            "--output-json",
            str(out),
        ],
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["compared_runs"] == 1200
    assert payload["summary"]["functional_mismatches"] == 0
    assert payload["result"]["pass_gate"] is True


@pytest.mark.unit
def test_benchmark_percentile_helper() -> None:
    module = _load_module(
        ROOT / "systematic_study" / "benchmark_policy_runs.py",
        "benchmark_policy_runs",
    )
    values = [1.0, 2.0, 3.0, 4.0]
    assert module.percentile(values, 50) == 2.5
    assert module.percentile(values, 95) > 3.0
