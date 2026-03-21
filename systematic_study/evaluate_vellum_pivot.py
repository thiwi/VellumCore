"""Benchmark utility to locate pivot where batch verification beats native auditing."""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import statistics
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from vellum_core.celery_app import celery_app
from vellum_core.config import Settings
from vellum_core.database import Database, ProofJob
from vellum_core.logic.batcher import MAX_BATCH_SIZE, batch_prepare_input
from vellum_core.proof_store import VellumAuditStore, VellumIntegrityService
from vellum_core.providers import SnarkJSProvider
from vellum_core.registry import CircuitRegistry
from vellum_core.security import build_input_summary, compute_input_fingerprint, seal_job_payload
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


BATCH_CIRCUIT_ID = "batch_credit_check"
DEFAULT_COUNTS = [100, 1_000, 10_000, 100_000, 1_000_000]


def heavy_risk_logic(balance: int, limit: int, iterations: int = 1000) -> bool:
    """
    Simuliert eine komplexe bankenfachliche Risikopruefung.
    Anstatt eines einfachen Vergleichs werden iterative
    Zins- und Risiko-Simulationen durchgefuehrt.
    """
    score = float(balance)

    # Simulation von Zinseszins-Effekten und Risiko-Gewichtung.
    # Die Schleife erzwingt echte CPU-Arbeit mit linearem Aufwand O(I).
    for i in range(iterations):
        # Schutz gegen negative Werte fuer sqrt bei extremen Inputs.
        safe_score = score if score > 0.0 else 0.0
        interest_step = math.sqrt(safe_score) * math.log1p(i + 1)
        score = score + (interest_step * 0.01)

        # Kuenstlicher Chaos-Faktor zur Simulation von Marktvolatilitaet.
        if i % 10 == 0:
            score -= math.sin(i) * 10

    return score > limit


@dataclass(frozen=True)
class NativeTiming:
    """Native timing sample including extrapolation metadata."""

    total_seconds: float
    per_decision_seconds: float
    measured: bool


@dataclass(frozen=True)
class RowResult:
    """One result row for a transaction-count benchmark point."""

    n: int
    native_seconds: float
    vellum_verify_seconds: float
    vellum_realtime_seconds: float
    auditor_speedup: float
    realtime_speedup: float
    status: str


class NativeTimer:
    """Measures native workload directly and extrapolates for large N when configured."""

    def __init__(
        self,
        *,
        seed: int,
        heavy_ops: int,
        light_max_measured: int,
        heavy_max_measured: int,
    ) -> None:
        self.seed = seed
        self.heavy_ops = heavy_ops
        self.light_max_measured = light_max_measured
        self.heavy_max_measured = heavy_max_measured
        self._per_decision_cache: dict[str, float] = {}

    def measure(self, mode: str, n: int) -> NativeTiming:
        """Return native timing for mode/light-heavy and transaction volume."""
        mode_key = mode.lower()
        if mode_key not in {"light", "heavy"}:
            raise ValueError(f"Unsupported mode: {mode}")

        max_measured = (
            self.light_max_measured if mode_key == "light" else self.heavy_max_measured
        )

        if n <= max_measured:
            total = self._measure_exact(mode_key, n)
            return NativeTiming(
                total_seconds=total,
                per_decision_seconds=total / n,
                measured=True,
            )

        if mode_key not in self._per_decision_cache:
            calibration_total = self._measure_exact(mode_key, max_measured)
            self._per_decision_cache[mode_key] = calibration_total / max_measured

        per_decision = self._per_decision_cache[mode_key]
        return NativeTiming(
            total_seconds=per_decision * n,
            per_decision_seconds=per_decision,
            measured=False,
        )

    def _measure_exact(self, mode: str, n: int) -> float:
        """Run exact native simulation loop and return elapsed seconds."""
        rng = random.Random(self.seed + n + (17 if mode == "heavy" else 3))
        started = time.perf_counter()

        valid = 0
        for _ in range(n):
            limit = rng.randint(10_000, 900_000)
            balance = limit + rng.randint(-200_000, 400_000)

            if mode == "light":
                decision_ok = balance > limit
            else:
                decision_ok = self._heavy_check(balance, limit)

            if decision_ok:
                valid += 1

        _ = valid
        return time.perf_counter() - started

    def _heavy_check(self, balance: int, limit: int) -> bool:
        """Execute heavy business-logic simulation branch."""
        return heavy_risk_logic(balance, limit, self.heavy_ops)


async def fetch_vault_key_versions(
    vault: VaultTransitClient,
    key_names: list[str],
) -> dict[str, list[str]]:
    """Fetch available Vault public-key versions for supplied key names."""
    versions: dict[str, list[str]] = {}
    for key_name in key_names:
        keys = await vault.read_public_keys(key_name)
        versions[key_name] = sorted(keys.keys(), key=lambda k: int(k))
    return versions


def build_valid_batch_input(seed: int) -> dict[str, Any]:
    """Build deterministic valid batch payload compatible with batch circuit."""
    rng = random.Random(seed)
    balances: list[int] = []
    limits: list[int] = []
    for _ in range(MAX_BATCH_SIZE):
        limit = rng.randint(10_000, 900_000)
        balance = limit + rng.randint(1, 100_000)
        balances.append(balance)
        limits.append(limit)

    return batch_prepare_input(
        balances=balances,
        limits=limits,
        batch_size=MAX_BATCH_SIZE,
    ).to_circuit_input()


async def enqueue_benchmark_jobs(
    *,
    db: Database,
    audit_store: VellumAuditStore,
    vault_client: VaultTransitClient,
    settings: Settings,
    run_id: str,
    batches: int,
    private_input: dict[str, Any],
) -> list[str]:
    """Create and enqueue calibration jobs used for proving throughput measurement."""
    proof_ids: list[str] = []
    for i in range(batches):
        proof_id = str(uuid4())
        metadata = {
            "benchmark": True,
            "run_id": run_id,
            "phase": "proving_calibration",
            "index": i,
        }
        request_payload = {"benchmark": True, "run_id": run_id}
        sealed_payload = await seal_job_payload(
            vault_client=vault_client,
            key_name=settings.vellum_data_key,
            request_payload=request_payload,
            private_input=private_input,
        )
        await db.create_proof_job(
            proof_id=proof_id,
            circuit_id=BATCH_CIRCUIT_ID,
            status="queued",
            sealed_job_payload=sealed_payload,
            input_fingerprint=compute_input_fingerprint(
                source_mode="private_input",
                payload={"private_input": private_input},
            ),
            input_summary=build_input_summary(
                source_mode="private_input",
                payload={"private_input": private_input},
                circuit_id=BATCH_CIRCUIT_ID,
            ),
            metadata=metadata,
        )
        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=BATCH_CIRCUIT_ID,
            status="queued",
            public_signals=[],
            metadata=metadata,
        )
        celery_app.send_task(
            "worker.process_proof_job",
            args=[proof_id],
            queue=settings.celery_queue,
        )
        proof_ids.append(proof_id)
    return proof_ids


async def wait_for_jobs(
    *,
    db: Database,
    proof_ids: list[str],
    poll_interval: float,
    timeout_seconds: float,
) -> tuple[list[ProofJob], list[ProofJob]]:
    """Wait until all queued calibration jobs are completed or failed."""
    pending = set(proof_ids)
    completed: list[ProofJob] = []
    failed: list[ProofJob] = []
    deadline = time.time() + timeout_seconds

    while pending:
        if time.time() > deadline:
            raise TimeoutError("Timed out while waiting for benchmark proof jobs")

        done_now: list[str] = []
        for proof_id in list(pending):
            job = await db.get_proof_job(proof_id)
            if job is None:
                continue
            if job.status == "completed":
                completed.append(job)
                done_now.append(proof_id)
            elif job.status == "failed":
                failed.append(job)
                done_now.append(proof_id)

        for proof_id in done_now:
            pending.discard(proof_id)

        if pending:
            await asyncio.sleep(poll_interval)

    return completed, failed


async def measure_verification_seconds(
    *,
    provider: SnarkJSProvider,
    proof: dict[str, Any],
    public_signals: list[Any],
    repeats: int,
) -> float:
    """Average repeated verification calls for one proof/public-signal tuple."""
    durations: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        valid = await provider.verify_proof(
            BATCH_CIRCUIT_ID,
            proof,
            public_signals,
        )
        elapsed = time.perf_counter() - started
        if not valid:
            raise RuntimeError("Verification failed during benchmark calibration")
        durations.append(elapsed)

    return statistics.mean(durations)


def compute_pivot(
    *,
    native_per_decision: float,
    verify_per_batch: float,
    max_n: int,
) -> int | None:
    """Return first N where modeled native cost exceeds batched verification cost."""
    for n in range(1, max_n + 1):
        native = n * native_per_decision
        vellum = math.ceil(n / MAX_BATCH_SIZE) * verify_per_batch
        if native > vellum:
            return n
    return None


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render aligned ASCII table from headers/rows."""
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    border = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    lines = [border]
    lines.append(
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |"
    )
    lines.append(border)
    for row in rows:
        lines.append(
            "| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(row))) + " |"
        )
    lines.append(border)
    return "\n".join(lines)


def format_seconds(value: float) -> str:
    """Format seconds into human-readable ms/s/min/h string."""
    if value < 1:
        return f"{value * 1000:.3f} ms"
    if value < 60:
        return f"{value:.3f} s"
    if value < 3600:
        return f"{value / 60:.2f} min"
    return f"{value / 3600:.2f} h"


async def run() -> None:
    """Execute full pivot benchmark workflow and print summary tables."""
    args = parse_args()
    tx_counts = [int(part.strip()) for part in args.tx_counts.split(",") if part.strip()]
    if tx_counts != sorted(tx_counts):
        raise ValueError("--tx-counts must be sorted ascending")

    settings = Settings.from_env()
    db = Database(settings.database_url)
    await db.init_models()
    if args.reset_audit_log:
        async with db.session_factory() as session:
            await session.execute(text("TRUNCATE TABLE audit_log"))
            await session.commit()

    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
    provider = SnarkJSProvider(registry=registry, snarkjs_bin=settings.snarkjs_bin)
    await provider.ensure_artifacts(BATCH_CIRCUIT_ID)

    vault_client = VaultTransitClient(
        addr=settings.vault_addr,
        token=settings.vault_token,
        tls_ca_bundle=settings.tls_ca_bundle,
    )
    key_cache = VaultPublicKeyCache(
        client=vault_client,
        ttl_seconds=settings.vault_public_key_cache_ttl_seconds,
    )
    audit_store = VellumAuditStore(
        db=db,
        vault=vault_client,
        audit_key_name=settings.vault_audit_key,
    )
    integrity = VellumIntegrityService(
        db=db,
        key_cache=key_cache,
        audit_key_name=settings.vault_audit_key,
    )

    run_id = str(uuid4())
    run_started = time.perf_counter()

    key_versions = await fetch_vault_key_versions(
        vault_client,
        [settings.vault_jwt_key, settings.vault_audit_key, settings.vault_bank_key],
    )

    await audit_store.append_event(
        proof_id=run_id,
        circuit_id=BATCH_CIRCUIT_ID,
        status="benchmark_started",
        public_signals=[str(count) for count in tx_counts],
        metadata={
            "benchmark": "evaluate_vellum_pivot",
            "run_id": run_id,
            "tx_counts": tx_counts,
            "heavy_ops": args.heavy_ops,
            "vault_key_versions": key_versions,
        },
    )

    private_input = build_valid_batch_input(args.seed)

    calibration_started = time.perf_counter()
    proof_ids = await enqueue_benchmark_jobs(
        db=db,
        audit_store=audit_store,
        vault_client=vault_client,
        settings=settings,
        run_id=run_id,
        batches=args.calibration_batches,
        private_input=private_input,
    )
    completed_jobs, failed_jobs = await wait_for_jobs(
        db=db,
        proof_ids=proof_ids,
        poll_interval=args.poll_interval,
        timeout_seconds=args.timeout_seconds,
    )
    calibration_wall = time.perf_counter() - calibration_started

    if not completed_jobs:
        raise RuntimeError("No completed proof jobs in calibration; cannot continue")

    throughput_batches_per_second = len(completed_jobs) / calibration_wall

    sample_job = completed_jobs[0]
    if sample_job.proof is None or sample_job.public_signals is None:
        raise RuntimeError("Completed calibration job missing proof payload")

    verify_per_batch_seconds = await measure_verification_seconds(
        provider=provider,
        proof=sample_job.proof,
        public_signals=sample_job.public_signals,
        repeats=args.verify_repeats,
    )

    native_timer = NativeTimer(
        seed=args.seed,
        heavy_ops=args.heavy_ops,
        light_max_measured=args.light_max_measured,
        heavy_max_measured=args.heavy_max_measured,
    )

    all_results: dict[str, list[RowResult]] = {}
    per_mode_native_per_decision: dict[str, float] = {}

    for mode in ("light", "heavy"):
        mode_results: list[RowResult] = []
        pivot_seen = False
        for n in tx_counts:
            native = native_timer.measure(mode, n)
            per_mode_native_per_decision[mode] = native.per_decision_seconds

            batches = math.ceil(n / MAX_BATCH_SIZE)
            vellum_verify_total = batches * verify_per_batch_seconds

            prove_total_seconds = batches / throughput_batches_per_second
            vellum_realtime_total = vellum_verify_total + prove_total_seconds

            auditor_speedup = (
                native.total_seconds / vellum_verify_total if vellum_verify_total > 0 else float("inf")
            )
            realtime_speedup = (
                native.total_seconds / vellum_realtime_total if vellum_realtime_total > 0 else float("inf")
            )

            if auditor_speedup > 1.0 and not pivot_seen:
                status = "PIVOT (>1.0x)"
                pivot_seen = True
            elif auditor_speedup > 1.0:
                status = "Vellum Advantage"
            else:
                status = "Native Faster"

            row = RowResult(
                n=n,
                native_seconds=native.total_seconds,
                vellum_verify_seconds=vellum_verify_total,
                vellum_realtime_seconds=vellum_realtime_total,
                auditor_speedup=auditor_speedup,
                realtime_speedup=realtime_speedup,
                status=status,
            )
            mode_results.append(row)

            await audit_store.append_event(
                proof_id=run_id,
                circuit_id=BATCH_CIRCUIT_ID,
                status="benchmark_row",
                public_signals=[str(n), f"{auditor_speedup:.6f}"],
                proof_payload={
                    "mode": mode,
                    "n": n,
                    "native_seconds": native.total_seconds,
                    "vellum_verify_seconds": vellum_verify_total,
                    "vellum_realtime_seconds": vellum_realtime_total,
                    "auditor_speedup": auditor_speedup,
                    "realtime_speedup": realtime_speedup,
                    "native_measured": native.measured,
                },
                metadata={
                    "benchmark": "evaluate_vellum_pivot",
                    "run_id": run_id,
                    "mode": mode,
                    "n": n,
                    "native_measured": native.measured,
                    "batches": batches,
                },
            )

        all_results[mode] = mode_results

    integrity_report = await integrity.verify_chain()

    await audit_store.append_event(
        proof_id=run_id,
        circuit_id=BATCH_CIRCUIT_ID,
        status="benchmark_completed",
        public_signals=[str(int(integrity_report["valid"]))],
        proof_payload={
            "run_id": run_id,
            "duration_seconds": time.perf_counter() - run_started,
            "verify_per_batch_seconds": verify_per_batch_seconds,
            "throughput_batches_per_second": throughput_batches_per_second,
            "completed_calibration_jobs": len(completed_jobs),
            "failed_calibration_jobs": len(failed_jobs),
            "integrity_report": integrity_report,
        },
        metadata={
            "benchmark": "evaluate_vellum_pivot",
            "run_id": run_id,
            "integrity_valid": integrity_report["valid"],
        },
    )

    print(f"Vellum Pivot Benchmark Run: {run_id}")
    print(f"Vault key versions: {key_versions}")
    print(
        "Calibration: "
        f"{len(completed_jobs)}/{args.calibration_batches} completed in {format_seconds(calibration_wall)}; "
        f"throughput={throughput_batches_per_second:.3f} batch/s"
    )
    print(f"Mean batch verify time: {format_seconds(verify_per_batch_seconds)}")
    if failed_jobs:
        print(f"Warning: {len(failed_jobs)} calibration jobs failed")

    for mode in ("light", "heavy"):
        mode_results = all_results[mode]
        print(f"\n=== {mode.upper()} logic ===")
        rows = [
            [
                f"{row.n}",
                format_seconds(row.native_seconds),
                format_seconds(row.vellum_verify_seconds),
                f"{row.auditor_speedup:.3f}x",
                row.status,
            ]
            for row in mode_results
        ]
        print(
            render_table(
                [
                    "Transaction Count (N)",
                    "Native Audit Time (Total)",
                    "Vellum Audit Time (Total Verifications)",
                    "Auditor Speedup (x-factor)",
                    "Status",
                ],
                rows,
            )
        )

        realtime_rows = [
            [
                f"{row.n}",
                format_seconds(row.native_seconds),
                format_seconds(row.vellum_realtime_seconds),
                f"{row.realtime_speedup:.3f}x",
                "Vellum E2E > Native" if row.realtime_speedup > 1.0 else "Native E2E Faster",
            ]
            for row in mode_results
        ]
        print("\nReal-Time view (includes proving overhead):")
        print(
            render_table(
                [
                    "Transaction Count (N)",
                    "Native Audit Time (Total)",
                    "Vellum Real-Time (Prove+Verify)",
                    "Real-Time Speedup",
                    "Status",
                ],
                realtime_rows,
            )
        )

        pivot_n = compute_pivot(
            native_per_decision=per_mode_native_per_decision[mode],
            verify_per_batch=verify_per_batch_seconds,
            max_n=max(tx_counts),
        )
        if pivot_n is None:
            print(f"Pivot point ({mode}): not reached up to N={max(tx_counts)}")
        else:
            print(f"Pivot point ({mode}): N={pivot_n}")

    heavy_million = next((r for r in all_results["heavy"] if r.n == 1_000_000), None)
    if heavy_million is not None:
        saved_verify_hours = (heavy_million.native_seconds - heavy_million.vellum_verify_seconds) / 3600.0
        saved_realtime_hours = (heavy_million.native_seconds - heavy_million.vellum_realtime_seconds) / 3600.0
        print("\nBoard Summary")
        print(
            "Vellum is slower for a single check, "
            f"but at 1,000,000 heavy daily transactions it saves about {saved_verify_hours:.2f}h/day "
            "of auditor verification effort."
        )
        print(
            "Including proving overhead with queued parallel workers, "
            f"the net daily gain is {saved_realtime_hours:.2f}h/day."
        )

    print(
        "\nAudit chain integrity: "
        f"valid={integrity_report['valid']}, checked_entries={integrity_report['checked_entries']}, "
        f"first_broken_index={integrity_report['first_broken_index']}"
    )


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for pivot benchmark execution."""
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the Vellum pivot point where batch O(1) verification per proof "
            "outperforms native O(N) auditing."
        )
    )
    parser.add_argument(
        "--tx-counts",
        default=",".join(str(v) for v in DEFAULT_COUNTS),
        help="Comma-separated transaction counts (default: 100,1000,10000,100000,1000000)",
    )
    parser.add_argument("--seed", type=int, default=20260319)
    parser.add_argument("--heavy-ops", type=int, default=1000)
    parser.add_argument(
        "--calibration-batches",
        type=int,
        default=6,
        help="How many proof jobs to enqueue for proving throughput calibration",
    )
    parser.add_argument(
        "--verify-repeats",
        type=int,
        default=5,
        help="How many repeated verify calls to average for one batch",
    )
    parser.add_argument(
        "--light-max-measured",
        type=int,
        default=1_000_000,
        help="Max N measured directly for light native logic",
    )
    parser.add_argument(
        "--heavy-max-measured",
        type=int,
        default=500,
        help="Max N measured directly for heavy native logic before linear extrapolation",
    )
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument(
        "--reset-audit-log",
        action="store_true",
        help="Truncate audit_log before benchmark run (useful for clean board demos).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run())
