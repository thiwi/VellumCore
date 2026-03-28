"""Benchmark v5 policy-run latency distribution for one active provider mode."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


def percentile(values: list[float], p: float) -> float:
    """Compute percentile using linear interpolation between nearest ranks."""
    if not values:
        raise ValueError("values must not be empty")
    if p < 0 or p > 100:
        raise ValueError("percentile must be in [0, 100]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark end-to-end policy-run latency via dashboard proxy APIs."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Dashboard base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--payload-json",
        type=Path,
        required=True,
        help="Path to one realistic policy-run payload JSON.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=40,
        help="Number of policy runs to submit (default: 40).",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=0.5,
        help="Poll interval while waiting for run completion.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=180.0,
        help="Max time per run before timeout failure.",
    )
    parser.add_argument(
        "--mode-label",
        default="unknown",
        help="Label included in output (for example: snarkjs, grpc).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="Output JSON file path.",
    )
    return parser.parse_args()


def _wait_health(base_url: str, *, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/healthz", timeout=5.0)
            if response.status_code < 400:
                return
        except Exception:
            pass
        time.sleep(1.0)
    raise RuntimeError(f"timeout waiting for dashboard health at {base_url}/healthz")


def _submit_policy_run(client: httpx.Client, base_url: str, payload: dict[str, Any]) -> str:
    response = client.post(f"{base_url}/api/v5/policy-runs", json=payload, timeout=30.0)
    if response.status_code != 200:
        raise RuntimeError(
            f"policy submit failed: status={response.status_code} body={response.text}"
        )
    body = response.json()
    run_id = body.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError(f"policy submit response missing run_id: {body}")
    return run_id


def _wait_policy_run(
    client: httpx.Client,
    base_url: str,
    *,
    run_id: str,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"{base_url}/api/v5/policy-runs/{run_id}", timeout=20.0)
        if response.status_code != 200:
            raise RuntimeError(
                f"status lookup failed for run_id={run_id}: "
                f"status={response.status_code} body={response.text}"
            )
        body = response.json()
        if body.get("status") in {"completed", "failed"}:
            return body
        time.sleep(poll_interval_seconds)
    raise RuntimeError(f"timeout waiting for policy run completion: {run_id}")


def main() -> int:
    args = _parse_args()
    payload = json.loads(args.payload_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("payload-json must decode to object")

    _wait_health(args.base_url, timeout_seconds=180.0)

    started_at = datetime.now(timezone.utc).isoformat()
    latencies_ms: list[float] = []
    failed_runs: list[dict[str, Any]] = []

    with httpx.Client() as client:
        for index in range(args.runs):
            run_payload = json.loads(json.dumps(payload))
            run_payload["request_id"] = f"bench-{args.mode_label}-{index}-{uuid4()}"

            start = time.perf_counter()
            run_id = _submit_policy_run(client, args.base_url, run_payload)
            status = _wait_policy_run(
                client,
                args.base_url,
                run_id=run_id,
                poll_interval_seconds=args.poll_interval_seconds,
                timeout_seconds=args.timeout_seconds,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            if status.get("status") == "completed":
                latencies_ms.append(elapsed_ms)
            else:
                failed_runs.append(
                    {
                        "run_id": run_id,
                        "status": status.get("status"),
                        "metadata": status.get("metadata"),
                    }
                )

    completed = len(latencies_ms)
    failed = len(failed_runs)
    finished_at = datetime.now(timezone.utc).isoformat()

    result: dict[str, Any] = {
        "mode_label": args.mode_label,
        "base_url": args.base_url,
        "payload_json": str(args.payload_json),
        "runs_requested": args.runs,
        "runs_completed": completed,
        "runs_failed": failed,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "latencies_ms": latencies_ms,
        "failed_runs": failed_runs,
    }
    if latencies_ms:
        result.update(
            {
                "p50_ms": percentile(latencies_ms, 50),
                "p95_ms": percentile(latencies_ms, 95),
                "p99_ms": percentile(latencies_ms, 99),
            }
        )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))

    return 1 if failed_runs else 0


if __name__ == "__main__":
    raise SystemExit(main())
