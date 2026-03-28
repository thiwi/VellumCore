"""Cutover gate evaluation for provider migration (shadow -> grpc primary)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CutoverGateInput:
    """Inputs required to evaluate grpc cutover readiness."""

    days_observed: int
    compared_runs: int
    functional_mismatches: int
    snarkjs_p95_ms: float
    grpc_p95_ms: float


@dataclass(frozen=True)
class CutoverGateResult:
    """Structured cutover gate decision and diagnostics."""

    pass_gate: bool
    speedup_p95: float | None
    reasons: list[str]


def evaluate_cutover_gate(inputs: CutoverGateInput) -> CutoverGateResult:
    """Evaluate hard gates required before grpc provider cutover."""
    reasons: list[str] = []

    if inputs.days_observed < 7:
        reasons.append(
            f"insufficient_shadow_days: required>=7 actual={inputs.days_observed}"
        )

    if inputs.compared_runs < 1000:
        reasons.append(
            f"insufficient_compared_runs: required>=1000 actual={inputs.compared_runs}"
        )

    if inputs.functional_mismatches != 0:
        reasons.append(
            f"functional_mismatch_detected: required=0 actual={inputs.functional_mismatches}"
        )

    speedup_p95: float | None
    if inputs.grpc_p95_ms <= 0:
        speedup_p95 = None
        reasons.append("invalid_grpc_p95_ms: grpc_p95_ms must be > 0")
    else:
        speedup_p95 = inputs.snarkjs_p95_ms / inputs.grpc_p95_ms
        if speedup_p95 < 2.0:
            reasons.append(
                f"insufficient_p95_speedup: required>=2.0 actual={speedup_p95:.4f}"
            )

    return CutoverGateResult(
        pass_gate=not reasons,
        speedup_p95=speedup_p95,
        reasons=reasons,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="vellum-cutover-gate",
        description="Evaluate grpc cutover gate from observed shadow/latency metrics.",
    )
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=None)
    return parser.parse_args(argv)


def _load_input(path: Path) -> CutoverGateInput:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return CutoverGateInput(
        days_observed=int(raw["days_observed"]),
        compared_runs=int(raw["compared_runs"]),
        functional_mismatches=int(raw["functional_mismatches"]),
        snarkjs_p95_ms=float(raw["snarkjs_p95_ms"]),
        grpc_p95_ms=float(raw["grpc_p95_ms"]),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    inputs = _load_input(args.summary_json)
    result = evaluate_cutover_gate(inputs)

    payload = {
        **asdict(inputs),
        **asdict(result),
    }
    rendered = json.dumps(payload, sort_keys=True)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result.pass_gate else 1


if __name__ == "__main__":
    sys.exit(main())
