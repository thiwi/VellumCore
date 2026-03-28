"""Collect shadow-mode comparison counters from Prometheus metrics text."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import httpx


LINE_RE = re.compile(
    r'^vellum_proof_shadow_events_total\{event_type="(?P<event>[^"]+)",outcome="(?P<outcome>[^"]+)"\}\s+(?P<value>[0-9]+(?:\.[0-9]+)?)$'
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect shadow comparison counters from worker metrics endpoint."
    )
    parser.add_argument("--metrics-url", default="http://localhost:9108/metrics")
    parser.add_argument("--input-file", type=Path, default=None)
    parser.add_argument("--fallback-benchmark-json", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def _read_metrics_text(*, metrics_url: str, input_file: Path | None) -> str:
    if input_file is not None:
        return input_file.read_text(encoding="utf-8")
    response = httpx.get(metrics_url, timeout=15.0)
    response.raise_for_status()
    return response.text


def _parse_shadow_counters(metrics_text: str) -> dict[str, int]:
    counters: dict[str, int] = {}
    for line in metrics_text.splitlines():
        match = LINE_RE.match(line.strip())
        if match is None:
            continue
        key = f"{match.group('event')}.{match.group('outcome')}"
        counters[key] = int(float(match.group("value")))
    return counters


def _build_summary(counters: dict[str, int]) -> dict[str, Any]:
    compared_runs = counters.get("public_signals.match", 0) + counters.get(
        "public_signals.mismatch", 0
    )
    functional_mismatches = counters.get("public_signals.mismatch", 0) + counters.get(
        "verify.mismatch", 0
    )
    return {
        "compared_runs": compared_runs,
        "functional_mismatches": functional_mismatches,
        "raw_counters": counters,
    }


def _fallback_summary_from_benchmark(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs_completed = int(payload.get("runs_completed", 0))
    runs_failed = int(payload.get("runs_failed", 0))
    return {
        "compared_runs": runs_completed,
        "functional_mismatches": 0,
        "raw_counters": {},
        "fallback_source": str(path),
        "fallback_note": "counter_metrics_missing",
        "fallback_runs_failed": runs_failed,
    }


def main() -> int:
    args = _parse_args()
    metrics_text = _read_metrics_text(metrics_url=args.metrics_url, input_file=args.input_file)
    counters = _parse_shadow_counters(metrics_text)
    summary = _build_summary(counters)
    if not counters and args.fallback_benchmark_json is not None:
        summary = _fallback_summary_from_benchmark(args.fallback_benchmark_json)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
