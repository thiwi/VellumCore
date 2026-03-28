"""Evaluate grpc cutover gate from benchmark outputs and shadow comparison metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from vellum_core.cutover_gate import CutoverGateInput, evaluate_cutover_gate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate cutover gate using snarkjs/grpc benchmark JSON files."
    )
    parser.add_argument("--snarkjs-benchmark", type=Path, required=True)
    parser.add_argument("--grpc-benchmark", type=Path, required=True)
    parser.add_argument("--days-observed", type=int, required=True)
    parser.add_argument("--compared-runs", type=int, default=None)
    parser.add_argument("--functional-mismatches", type=int, default=None)
    parser.add_argument(
        "--shadow-summary",
        type=Path,
        default=None,
        help="Optional JSON from collect_shadow_metrics.py; supplies compared_runs/mismatches when flags are omitted.",
    )
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def _load_benchmark(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"benchmark file is not an object: {path}")
    if "p95_ms" not in data:
        raise RuntimeError(f"benchmark file missing p95_ms: {path}")
    return data


def _resolve_shadow_inputs(args: argparse.Namespace) -> tuple[int, int]:
    compared_runs = args.compared_runs
    functional_mismatches = args.functional_mismatches
    shadow_payload: dict[str, Any] | None = None
    if args.shadow_summary is not None:
        shadow_payload = json.loads(args.shadow_summary.read_text(encoding="utf-8"))
        if not isinstance(shadow_payload, dict):
            raise RuntimeError(f"shadow summary is not an object: {args.shadow_summary}")

    if compared_runs is None:
        if shadow_payload is None or "compared_runs" not in shadow_payload:
            raise RuntimeError("compared_runs missing: set --compared-runs or provide --shadow-summary")
        compared_runs = int(shadow_payload["compared_runs"])

    if functional_mismatches is None:
        if shadow_payload is None or "functional_mismatches" not in shadow_payload:
            raise RuntimeError(
                "functional_mismatches missing: set --functional-mismatches or provide --shadow-summary"
            )
        functional_mismatches = int(shadow_payload["functional_mismatches"])

    return int(compared_runs), int(functional_mismatches)


def main() -> int:
    args = _parse_args()
    snarkjs = _load_benchmark(args.snarkjs_benchmark)
    grpc = _load_benchmark(args.grpc_benchmark)
    compared_runs, functional_mismatches = _resolve_shadow_inputs(args)

    summary = CutoverGateInput(
        days_observed=args.days_observed,
        compared_runs=compared_runs,
        functional_mismatches=functional_mismatches,
        snarkjs_p95_ms=float(snarkjs["p95_ms"]),
        grpc_p95_ms=float(grpc["p95_ms"]),
    )
    result = evaluate_cutover_gate(summary)

    payload = {
        "summary": {
            "days_observed": summary.days_observed,
            "compared_runs": summary.compared_runs,
            "functional_mismatches": summary.functional_mismatches,
            "snarkjs_p95_ms": summary.snarkjs_p95_ms,
            "grpc_p95_ms": summary.grpc_p95_ms,
        },
        "benchmarks": {
            "snarkjs": {
                "path": str(args.snarkjs_benchmark),
                "runs_completed": snarkjs.get("runs_completed"),
                "p50_ms": snarkjs.get("p50_ms"),
                "p95_ms": snarkjs.get("p95_ms"),
                "p99_ms": snarkjs.get("p99_ms"),
            },
            "grpc": {
                "path": str(args.grpc_benchmark),
                "runs_completed": grpc.get("runs_completed"),
                "p50_ms": grpc.get("p50_ms"),
                "p95_ms": grpc.get("p95_ms"),
                "p99_ms": grpc.get("p99_ms"),
            },
        },
        "result": {
            "pass_gate": result.pass_gate,
            "speedup_p95": result.speedup_p95,
            "reasons": result.reasons,
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.pass_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
