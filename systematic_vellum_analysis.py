from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import httpx
from sqlalchemy import text

from vellum_core.celery_app import celery_app
from vellum_core.config import Settings
from vellum_core.database import Database, ProofJob
from vellum_core.logic.batcher import MAX_BATCH_SIZE, batch_prepare_input
from vellum_core.proof_store import VellumAuditStore, VellumIntegrityService
from vellum_core.providers import SnarkJSProvider
from vellum_core.registry import CircuitRegistry
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


BATCH_CIRCUIT_ID = "batch_credit_check"
DEFAULT_VOLUMES = [100, 500, 1_000, 5_000, 10_000]
DEFAULT_OPS = [0, 1_000, 5_000, 10_000]


@dataclass(frozen=True)
class MatrixRow:
    n: int
    ops: int
    native_time_ms: float | None
    proving_time_ms: float | None
    verification_time_ms: float | None
    vault_latency_ms: float | None
    db_overhead_ms: float | None
    auditor_speedup: float | None
    realtime_speedup: float | None
    batch_count: int | None
    single_verify_ms: float | None
    status: str
    integrity_valid: bool | None
    integrity_checked_entries: int | None
    error: str | None


def heavy_risk_logic(balance: int, limit: int, iterations: int = 1000) -> bool:
    score = float(balance)
    for i in range(iterations):
        safe_score = score if score > 0.0 else 0.0
        interest_step = math.sqrt(safe_score) * math.log1p(i + 1)
        score = score + (interest_step * 0.01)
        if i % 10 == 0:
            score -= math.sin(i) * 10
    return score > limit


def parse_int_csv(raw: str) -> list[int]:
    values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    if not values:
        raise ValueError("At least one numeric value required")
    return values


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    lines = [border]
    lines.append("| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    lines.append(border)
    for row in rows:
        lines.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(row))) + " |")
    lines.append(border)
    return "\n".join(lines)


def fmt_ms(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 1_000:
        return f"{value:.3f} ms"
    return f"{value / 1_000:.3f} s"


def progress_iter(items: list[tuple[int, int]]) -> Iterable[tuple[int, int]]:
    total = len(items)
    try:
        from tqdm import tqdm  # type: ignore

        return tqdm(items, total=total, desc="Vellum matrix")
    except Exception:
        def _fallback() -> Iterable[tuple[int, int]]:
            for idx, cell in enumerate(items, start=1):
                percent = (idx / total) * 100.0
                print(f"[{idx:02d}/{total:02d}] {percent:6.2f}% -> N={cell[0]} Ops={cell[1]}")
                yield cell

        return _fallback()


def build_decisions(*, n: int, seed: int) -> tuple[list[int], list[int]]:
    rng = random.Random(seed + n * 17)
    balances: list[int] = []
    limits: list[int] = []
    for _ in range(n):
        limit = rng.randint(10_000, 900_000)
        balance = limit + rng.randint(1, 200_000)
        limits.append(limit)
        balances.append(balance)
    return balances, limits


def measure_native_time_ms(*, balances: list[int], limits: list[int], ops: int) -> float:
    started = time.perf_counter()
    valid = 0
    for balance, limit in zip(balances, limits):
        if ops == 0:
            decision_ok = balance > limit
        else:
            decision_ok = heavy_risk_logic(balance, limit, iterations=ops)
        if decision_ok:
            valid += 1
    _ = valid
    return (time.perf_counter() - started) * 1000.0


def split_into_batches(*, balances: list[int], limits: list[int]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for start in range(0, len(balances), MAX_BATCH_SIZE):
        batch_balances = balances[start : start + MAX_BATCH_SIZE]
        batch_limits = limits[start : start + MAX_BATCH_SIZE]
        prepared = batch_prepare_input(balances=batch_balances, limits=batch_limits)
        payloads.append(prepared.to_circuit_input())
    return payloads


async def check_vault_unsealed(*, vault_addr: str, vault_token: str) -> None:
    url = f"{vault_addr.rstrip('/')}/v1/sys/health"
    headers = {"X-Vault-Token": vault_token}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url, headers=headers)
    response.raise_for_status()
    body = response.json()
    if body.get("sealed", True):
        raise RuntimeError("Vault is sealed")


async def check_database_reachable(db: Database) -> None:
    async with db.session_factory() as session:
        await session.execute(text("SELECT 1"))


async def enqueue_jobs(
    *,
    db: Database,
    settings: Settings,
    run_id: str,
    n: int,
    ops: int,
    payloads: list[dict[str, Any]],
) -> tuple[list[str], float]:
    proof_ids: list[str] = []
    db_overhead_ms = 0.0

    for idx, payload in enumerate(payloads):
        proof_id = str(uuid4())
        created_started = time.perf_counter()
        await db.create_proof_job(
            proof_id=proof_id,
            circuit_id=BATCH_CIRCUIT_ID,
            status="queued",
            request_payload={"benchmark": "systematic_vellum_analysis", "run_id": run_id},
            private_input=payload,
            source_ref=None,
            metadata={
                "benchmark": "systematic_vellum_analysis",
                "run_id": run_id,
                "n": n,
                "ops": ops,
                "batch_index": idx,
            },
        )
        db_overhead_ms += (time.perf_counter() - created_started) * 1000.0

        celery_app.send_task(
            "worker.process_proof_job",
            args=[proof_id],
            queue=settings.celery_queue,
        )
        proof_ids.append(proof_id)

    return proof_ids, db_overhead_ms


async def wait_for_jobs(
    *,
    db: Database,
    proof_ids: list[str],
    timeout_seconds: float,
    poll_interval: float,
) -> tuple[list[ProofJob], list[ProofJob], float]:
    pending = set(proof_ids)
    completed: list[ProofJob] = []
    failed: list[ProofJob] = []
    db_overhead_ms = 0.0
    deadline = time.time() + timeout_seconds

    while pending:
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for queued proof jobs")

        done_now: list[str] = []
        for proof_id in list(pending):
            fetch_started = time.perf_counter()
            job = await db.get_proof_job(proof_id)
            db_overhead_ms += (time.perf_counter() - fetch_started) * 1000.0
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

    return completed, failed, db_overhead_ms


async def measure_single_verify_ms(
    *,
    provider: SnarkJSProvider,
    proof: dict[str, Any],
    public_signals: list[Any],
    repeats: int,
) -> float:
    durations: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        valid = await provider.verify_proof(BATCH_CIRCUIT_ID, proof, public_signals)
        elapsed = (time.perf_counter() - started) * 1000.0
        if not valid:
            raise RuntimeError("Batch verification failed")
        durations.append(elapsed)
    return sum(durations) / len(durations)


async def measure_vault_sign_latency_ms(
    *,
    vault_client: VaultTransitClient,
    key_name: str,
    samples: int,
) -> float:
    durations: list[float] = []
    for idx in range(samples):
        payload = f"matrix-sign-{idx}-{time.time_ns()}".encode("utf-8")
        started = time.perf_counter()
        await vault_client.sign(key_name, payload)
        durations.append((time.perf_counter() - started) * 1000.0)
    return sum(durations) / len(durations)


def build_pivot_summary(rows: list[MatrixRow], ops_values: list[int]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for ops in ops_values:
        candidates = [
            row
            for row in rows
            if row.ops == ops and row.error is None and row.auditor_speedup is not None and row.auditor_speedup > 1.0
        ]
        candidates.sort(key=lambda row: row.n)
        if candidates:
            pivot = candidates[0]
            result.append(
                {
                    "ops": ops,
                    "pivot_n": pivot.n,
                    "auditor_speedup": pivot.auditor_speedup,
                    "realtime_speedup": pivot.realtime_speedup,
                    "native_time_ms": pivot.native_time_ms,
                    "verification_time_ms": pivot.verification_time_ms,
                    "status": pivot.status,
                }
            )
        else:
            result.append(
                {
                    "ops": ops,
                    "pivot_n": None,
                    "auditor_speedup": None,
                    "realtime_speedup": None,
                    "native_time_ms": None,
                    "verification_time_ms": None,
                    "status": "not_reached",
                }
            )
    return result


async def run() -> None:
    args = parse_args()
    volumes = parse_int_csv(args.volumes)
    ops_values = parse_int_csv(args.ops)

    settings = Settings.from_env()
    db = Database(settings.database_url)
    await db.init_models()

    await check_vault_unsealed(vault_addr=settings.vault_addr, vault_token=settings.vault_token)
    await check_database_reachable(db)

    if args.reset_audit_log:
        async with db.session_factory() as session:
            await session.execute(text("TRUNCATE TABLE audit_log"))
            await session.commit()

    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
    provider = SnarkJSProvider(registry=registry, snarkjs_bin=settings.snarkjs_bin)
    await provider.ensure_artifacts(BATCH_CIRCUIT_ID)

    vault_client = VaultTransitClient(addr=settings.vault_addr, token=settings.vault_token)
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

    vault_key_versions = {
        settings.vault_jwt_key: sorted((await vault_client.read_public_keys(settings.vault_jwt_key)).keys()),
        settings.vault_audit_key: sorted((await vault_client.read_public_keys(settings.vault_audit_key)).keys()),
        settings.vault_bank_key: sorted((await vault_client.read_public_keys(settings.vault_bank_key)).keys()),
    }

    run_id = str(uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    cells = [(n, ops) for ops in ops_values for n in volumes]
    rows: list[MatrixRow] = []

    await audit_store.append_event(
        proof_id=run_id,
        circuit_id=BATCH_CIRCUIT_ID,
        status="systematic_analysis_started",
        public_signals=[str(len(cells))],
        metadata={
            "benchmark": "systematic_vellum_analysis",
            "run_id": run_id,
            "volumes": volumes,
            "ops": ops_values,
            "vault_key_versions": vault_key_versions,
        },
    )

    for n, ops in progress_iter(cells):
        try:
            balances, limits = build_decisions(n=n, seed=args.seed + ops)
            native_time_ms = measure_native_time_ms(balances=balances, limits=limits, ops=ops)

            payloads = split_into_batches(balances=balances, limits=limits)
            batch_count = len(payloads)

            enqueue_db_ms = 0.0
            proving_started = time.perf_counter()
            proof_ids, enqueue_db_ms = await enqueue_jobs(
                db=db,
                settings=settings,
                run_id=run_id,
                n=n,
                ops=ops,
                payloads=payloads,
            )
            completed, failed, poll_db_ms = await wait_for_jobs(
                db=db,
                proof_ids=proof_ids,
                timeout_seconds=args.timeout_seconds,
                poll_interval=args.poll_interval,
            )
            proving_time_ms = (time.perf_counter() - proving_started) * 1000.0
            db_overhead_ms = enqueue_db_ms + poll_db_ms

            if failed:
                raise RuntimeError(f"{len(failed)} proof jobs failed")
            if not completed:
                raise RuntimeError("No completed jobs returned")

            sample_job = completed[0]
            if sample_job.proof is None or sample_job.public_signals is None:
                raise RuntimeError("Completed proof job missing proof/public_signals")

            single_verify_ms = await measure_single_verify_ms(
                provider=provider,
                proof=sample_job.proof,
                public_signals=sample_job.public_signals,
                repeats=args.verify_repeats,
            )
            verification_time_ms = single_verify_ms * batch_count

            avg_sign_ms = await measure_vault_sign_latency_ms(
                vault_client=vault_client,
                key_name=settings.vault_audit_key,
                samples=args.vault_sign_samples,
            )
            vault_latency_ms = avg_sign_ms * batch_count * args.audit_signatures_per_batch

            auditor_speedup = native_time_ms / verification_time_ms if verification_time_ms > 0 else float("inf")
            realtime_total_ms = verification_time_ms + proving_time_ms + vault_latency_ms + db_overhead_ms
            realtime_speedup = native_time_ms / realtime_total_ms if realtime_total_ms > 0 else float("inf")

            integrity_started = time.perf_counter()
            integrity_report = await integrity.verify_chain()
            db_overhead_ms += (time.perf_counter() - integrity_started) * 1000.0

            status = "vellum_advantage" if auditor_speedup > 1.0 else "native_faster"
            if not bool(integrity_report["valid"]):
                status = "integrity_invalid"

            row = MatrixRow(
                n=n,
                ops=ops,
                native_time_ms=native_time_ms,
                proving_time_ms=proving_time_ms,
                verification_time_ms=verification_time_ms,
                vault_latency_ms=vault_latency_ms,
                db_overhead_ms=db_overhead_ms,
                auditor_speedup=auditor_speedup,
                realtime_speedup=realtime_speedup,
                batch_count=batch_count,
                single_verify_ms=single_verify_ms,
                status=status,
                integrity_valid=bool(integrity_report["valid"]),
                integrity_checked_entries=int(integrity_report["checked_entries"]),
                error=None,
            )
            rows.append(row)

            await audit_store.append_event(
                proof_id=run_id,
                circuit_id=BATCH_CIRCUIT_ID,
                status="systematic_analysis_row",
                public_signals=[str(n), str(ops), f"{auditor_speedup:.6f}"],
                proof_payload={
                    "n": n,
                    "ops": ops,
                    "native_time_ms": native_time_ms,
                    "proving_time_ms": proving_time_ms,
                    "verification_time_ms": verification_time_ms,
                    "vault_latency_ms": vault_latency_ms,
                    "db_overhead_ms": db_overhead_ms,
                    "auditor_speedup": auditor_speedup,
                    "realtime_speedup": realtime_speedup,
                    "batch_count": batch_count,
                    "single_verify_ms": single_verify_ms,
                    "integrity_report": integrity_report,
                },
                metadata={
                    "benchmark": "systematic_vellum_analysis",
                    "run_id": run_id,
                    "n": n,
                    "ops": ops,
                },
            )
        except Exception as exc:
            rows.append(
                MatrixRow(
                    n=n,
                    ops=ops,
                    native_time_ms=None,
                    proving_time_ms=None,
                    verification_time_ms=None,
                    vault_latency_ms=None,
                    db_overhead_ms=None,
                    auditor_speedup=None,
                    realtime_speedup=None,
                    batch_count=None,
                    single_verify_ms=None,
                    status="failed",
                    integrity_valid=None,
                    integrity_checked_entries=None,
                    error=str(exc),
                )
            )
            try:
                await audit_store.append_event(
                    proof_id=run_id,
                    circuit_id=BATCH_CIRCUIT_ID,
                    status="systematic_analysis_row_failed",
                    public_signals=[str(n), str(ops)],
                    metadata={
                        "benchmark": "systematic_vellum_analysis",
                        "run_id": run_id,
                        "n": n,
                        "ops": ops,
                    },
                    error=str(exc),
                )
            except Exception:
                pass

    pivot_summary = build_pivot_summary(rows, ops_values)
    final_integrity = await integrity.verify_chain()

    output = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "environment": {
            "vault_addr": settings.vault_addr,
            "database_url": settings.database_url,
            "celery_queue": settings.celery_queue,
            "batch_size": MAX_BATCH_SIZE,
            "volumes": volumes,
            "ops_values": ops_values,
            "vault_key_versions": vault_key_versions,
        },
        "matrix": [asdict(row) for row in rows],
        "pivot_summary": pivot_summary,
        "final_integrity": final_integrity,
    }

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(output, indent=2), encoding="utf-8")

    summary_csv = Path(args.summary_csv)
    summary_csv.parent.mkdir(parents=True, exist_ok=True)
    with summary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ops",
                "pivot_n",
                "auditor_speedup",
                "realtime_speedup",
                "native_time_ms",
                "verification_time_ms",
                "status",
            ],
        )
        writer.writeheader()
        for row in pivot_summary:
            writer.writerow(row)

    await audit_store.append_event(
        proof_id=run_id,
        circuit_id=BATCH_CIRCUIT_ID,
        status="systematic_analysis_completed",
        public_signals=[str(int(bool(final_integrity["valid"])))],
        proof_payload={
            "run_id": run_id,
            "rows": len(rows),
            "output_json": str(output_json),
            "summary_csv": str(summary_csv),
            "pivot_summary": pivot_summary,
            "final_integrity": final_integrity,
        },
        metadata={
            "benchmark": "systematic_vellum_analysis",
            "run_id": run_id,
        },
    )

    result_rows = []
    for row in rows:
        result_rows.append(
            [
                str(row.n),
                str(row.ops),
                fmt_ms(row.native_time_ms),
                fmt_ms(row.verification_time_ms),
                "-" if row.auditor_speedup is None else f"{row.auditor_speedup:.4f}x",
                row.status,
            ]
        )

    print(f"Run ID: {run_id}")
    print(f"Output JSON: {output_json}")
    print(f"Summary CSV: {summary_csv}")
    print(
        render_table(
            [
                "N",
                "Ops",
                "Native Audit Time",
                "Vellum Verify Time",
                "Auditor Speedup",
                "Status",
            ],
            result_rows,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a systemic scalability matrix for Vellum and export JSON/CSV raw data."
    )
    parser.add_argument(
        "--volumes",
        default=",".join(str(v) for v in DEFAULT_VOLUMES),
        help="Comma-separated transaction counts (default: 100,500,1000,5000,10000)",
    )
    parser.add_argument(
        "--ops",
        default=",".join(str(v) for v in DEFAULT_OPS),
        help="Comma-separated logic complexity operations (default: 0,1000,5000,10000)",
    )
    parser.add_argument("--seed", type=int, default=20260319)
    parser.add_argument("--verify-repeats", type=int, default=3)
    parser.add_argument("--vault-sign-samples", type=int, default=5)
    parser.add_argument("--audit-signatures-per-batch", type=int, default=2)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--output-json", default="/app/vellum_performance_matrix.json")
    parser.add_argument("--summary-csv", default="/app/summary.csv")
    parser.add_argument(
        "--reset-audit-log",
        action="store_true",
        help="Truncate audit_log before test run.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run())
