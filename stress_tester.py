"""Load/stress test harness for prover service throughput and thermal behavior."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import docker
import httpx
import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key


@dataclass(frozen=True)
class PhaseConfig:
    """One stress phase configuration tuple."""

    name: str
    circuit_id: str
    jobs: int
    concurrency: int


def parse_args() -> argparse.Namespace:
    """Parse stress-tester CLI arguments."""
    parser = argparse.ArgumentParser(description="Stress tester for Sentinel-ZK Prover")
    parser.add_argument(
        "--output",
        default="/app/stress_results/stress_report.json",
        help="Output path for JSON report",
    )
    parser.add_argument("--prover-url", default=os.getenv("PROVER_URL", "http://prover:8001"))
    parser.add_argument("--jwt-issuer", default=os.getenv("JWT_ISSUER", "bank.local"))
    parser.add_argument("--jwt-audience", default=os.getenv("JWT_AUDIENCE", "sentinel-zk"))
    parser.add_argument("--bank-key-id", default=os.getenv("BANK_KEY_ID", "bank-key-1"))
    parser.add_argument(
        "--jwt-private-key-path",
        default=os.getenv("JWT_PRIVATE_KEY_PATH", "/app/config/dev_jwt_private.pem"),
    )
    parser.add_argument(
        "--bank-private-key-path",
        default=os.getenv("BANK_PRIVATE_KEY_PATH", "/app/config/dev_bank_private.pem"),
    )
    return parser.parse_args()


def build_jwt_token(jwt_issuer: str, jwt_audience: str, private_key_path: Path) -> str:
    """Create short-lived JWT used to call authenticated service endpoints."""
    now = int(time.time())
    claims = {
        "iss": jwt_issuer,
        "aud": jwt_audience,
        "sub": "stress-tester",
        "iat": now,
        "exp": now + 3600,
    }
    key = private_key_path.read_text(encoding="utf-8")
    return jwt.encode(claims, key, algorithm="RS256")


def build_handshake_headers(
    *,
    method: str,
    path: str,
    body: bytes,
    bank_key_id: str,
    bank_private_key_path: Path,
) -> dict[str, str]:
    """Build bank-signature handshake headers for prover submit requests."""
    ts = str(int(time.time()))
    nonce = str(uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method}\n{path}\n{ts}\n{nonce}\n{body_hash}"
    key = load_pem_private_key(bank_private_key_path.read_bytes(), password=None)
    signature = key.sign(canonical.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return {
        "X-Bank-Key-Id": bank_key_id,
        "X-Bank-Timestamp": ts,
        "X-Bank-Nonce": nonce,
        "X-Bank-Signature": base64.b64encode(signature).decode("utf-8"),
    }


def detect_prover_container() -> str:
    """Resolve active prover container id via compose service label."""
    client = docker.from_env()
    containers = client.containers.list(
        all=True, filters={"label": "com.docker.compose.service=prover"}
    )
    if not containers:
        raise RuntimeError("Could not find prover container via Docker labels")
    return containers[0].id


def extract_cpu_percent(stats: dict[str, Any]) -> float:
    """Convert Docker stats payload into CPU percentage."""
    cpu_total = stats["cpu_stats"]["cpu_usage"]["total_usage"]
    precpu_total = stats["precpu_stats"]["cpu_usage"]["total_usage"]
    system = stats["cpu_stats"].get("system_cpu_usage", 0)
    presystem = stats["precpu_stats"].get("system_cpu_usage", 0)
    online = stats["cpu_stats"].get("online_cpus") or len(
        stats["cpu_stats"]["cpu_usage"].get("percpu_usage", []) or [1]
    )
    cpu_delta = cpu_total - precpu_total
    system_delta = system - presystem
    if system_delta <= 0:
        return 0.0
    return (cpu_delta / system_delta) * online * 100.0


def percentile(values: list[float], q: float) -> float:
    """Return nearest-rank percentile from float sample list."""
    if not values:
        return 0.0
    data = sorted(values)
    idx = int(round((len(data) - 1) * q))
    return data[idx]


async def monitor_resources(
    *, container_id: str, stop: asyncio.Event, interval_seconds: float = 1.0
) -> dict[str, float]:
    """Sample container CPU/RSS metrics until stop event is set."""
    client = docker.from_env()
    cpu_samples: list[float] = []
    rss_peak = 0.0

    while not stop.is_set():
        try:
            stats = client.api.stats(container_id, stream=False)
            cpu = extract_cpu_percent(stats)
            rss = float(stats["memory_stats"].get("usage", 0))
            cpu_samples.append(cpu)
            rss_peak = max(rss_peak, rss)
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)

    return {
        "cpu_peak_percent": max(cpu_samples) if cpu_samples else 0.0,
        "cpu_avg_percent": statistics.mean(cpu_samples) if cpu_samples else 0.0,
        "rss_peak_bytes": rss_peak,
    }


async def submit_and_wait(
    *,
    client: httpx.AsyncClient,
    prover_url: str,
    token: str,
    bank_key_id: str,
    bank_private_key_path: Path,
    circuit_id: str,
    private_input: dict[str, Any],
) -> tuple[float, str]:
    """Submit one proof request and poll until completed/failed."""
    path = "/v1/proofs"
    payload = {"circuit_id": circuit_id, "private_input": private_input}
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        **build_handshake_headers(
            method="POST",
            path=path,
            body=body,
            bank_key_id=bank_key_id,
            bank_private_key_path=bank_private_key_path,
        ),
    }

    start = time.perf_counter()
    response = await client.post(f"{prover_url}{path}", content=body, headers=headers)
    response.raise_for_status()
    proof_id = response.json()["proof_id"]

    status_path = f"/v1/proofs/{proof_id}"
    status_headers = {"Authorization": f"Bearer {token}"}
    while True:
        status_resp = await client.get(f"{prover_url}{status_path}", headers=status_headers)
        status_resp.raise_for_status()
        status = status_resp.json()["status"]
        if status in {"completed", "failed"}:
            end = time.perf_counter()
            return (end - start), status
        await asyncio.sleep(0.4)


def build_input_for_circuit(circuit_id: str, seed: int) -> dict[str, Any]:
    """Generate deterministic private input payload for selected test circuit."""
    if circuit_id == "complexity_1k":
        return {"seed": (seed % 9) + 1}
    if circuit_id == "complexity_10k":
        return {"seed": (seed % 9) + 1}
    if circuit_id == "complexity_100k":
        return {"seed": (seed % 9) + 1}
    return {"credit_score": 700, "debt_ratio": 200}


def compute_thermal_indicator(latencies: list[float], cpu_peak_percent: float) -> dict[str, Any]:
    """Estimate thermal throttling from latency drift under high CPU load."""
    if len(latencies) < 6:
        return {
            "degradation_percent": 0.0,
            "throttling_suspected": False,
            "reason": "Insufficient samples for degradation analysis",
        }
    window = len(latencies) // 3
    first_avg = statistics.mean(latencies[:window])
    last_avg = statistics.mean(latencies[-window:])
    degradation = ((last_avg - first_avg) / first_avg) * 100 if first_avg > 0 else 0.0
    throttling = degradation >= 20.0 and cpu_peak_percent >= 80.0
    return {
        "degradation_percent": degradation,
        "throttling_suspected": throttling,
        "reason": "Latency degradation under high CPU load",
    }


async def run_phase(
    *,
    cfg: PhaseConfig,
    prover_url: str,
    token: str,
    bank_key_id: str,
    bank_private_key_path: Path,
    container_id: str,
) -> dict[str, Any]:
    """Execute one stress phase and return aggregated performance report."""
    latencies: list[float] = []
    completed = 0
    failed = 0
    sem = asyncio.Semaphore(cfg.concurrency)
    stop_monitor = asyncio.Event()
    monitor_task = asyncio.create_task(
        monitor_resources(container_id=container_id, stop=stop_monitor)
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        async def one_job(index: int) -> None:
            nonlocal completed, failed
            async with sem:
                latency, status = await submit_and_wait(
                    client=client,
                    prover_url=prover_url,
                    token=token,
                    bank_key_id=bank_key_id,
                    bank_private_key_path=bank_private_key_path,
                    circuit_id=cfg.circuit_id,
                    private_input=build_input_for_circuit(cfg.circuit_id, index),
                )
                latencies.append(latency)
                if status == "completed":
                    completed += 1
                else:
                    failed += 1

        start = time.perf_counter()
        await asyncio.gather(*(one_job(i) for i in range(cfg.jobs)))
        total_seconds = time.perf_counter() - start

    stop_monitor.set()
    resources = await monitor_task

    thermal = compute_thermal_indicator(latencies, resources["cpu_peak_percent"])
    return {
        "phase": cfg.name,
        "circuit_id": cfg.circuit_id,
        "jobs": cfg.jobs,
        "concurrency": cfg.concurrency,
        "completed": completed,
        "failed": failed,
        "throughput_jobs_per_sec": completed / total_seconds if total_seconds > 0 else 0.0,
        "latency_seconds": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "avg": statistics.mean(latencies) if latencies else 0.0,
        },
        "resource_usage": resources,
        "thermal_indicator": thermal,
    }


async def main_async(args: argparse.Namespace) -> None:
    """Run all configured stress phases and write JSON report."""
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    token = build_jwt_token(
        jwt_issuer=args.jwt_issuer,
        jwt_audience=args.jwt_audience,
        private_key_path=Path(args.jwt_private_key_path),
    )
    prover_container_id = detect_prover_container()

    phases = [
        PhaseConfig(name="constraints_1k", circuit_id="complexity_1k", jobs=18, concurrency=6),
        PhaseConfig(name="constraints_10k", circuit_id="complexity_10k", jobs=12, concurrency=4),
        PhaseConfig(name="constraints_100k", circuit_id="complexity_100k", jobs=6, concurrency=2),
    ]

    phase_reports: list[dict[str, Any]] = []
    for phase in phases:
        report = await run_phase(
            cfg=phase,
            prover_url=args.prover_url,
            token=token,
            bank_key_id=args.bank_key_id,
            bank_private_key_path=Path(args.bank_private_key_path),
            container_id=prover_container_id,
        )
        phase_reports.append(report)

    final_report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prover_url": args.prover_url,
        "platform_hint": "ARM64 CPU-only",
        "phases": phase_reports,
    }
    output_path.write_text(json.dumps(final_report, indent=2), encoding="utf-8")

    print(f"Stress report written: {output_path}")
    for phase in phase_reports:
        print(
            f"{phase['phase']}: "
            f"p95={phase['latency_seconds']['p95']:.3f}s, "
            f"cpu_peak={phase['resource_usage']['cpu_peak_percent']:.1f}%, "
            f"rss_peak={int(phase['resource_usage']['rss_peak_bytes'] / (1024*1024))}MiB, "
            f"throttling={phase['thermal_indicator']['throttling_suspected']}"
        )


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
