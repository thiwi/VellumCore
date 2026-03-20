"""Micro-benchmark: native batch checks versus one batch-proof verification."""

from __future__ import annotations

import argparse
import asyncio
import random
import time
from dataclasses import dataclass

from vellum_core.logic.batcher import MAX_BATCH_SIZE, batch_prepare_input
from vellum_core.config import Settings
from vellum_core.providers import SnarkJSProvider
from vellum_core.registry import CircuitRegistry


BATCH_CIRCUIT_ID = "batch_credit_check"


@dataclass(frozen=True)
class CreditDecision:
    """Synthetic credit decision row used for benchmark generation."""

    balance: int
    limit: int


def generate_decisions(count: int, *, seed: int) -> list[CreditDecision]:
    """Generate deterministic valid decisions for benchmark consistency."""
    rng = random.Random(seed)
    decisions: list[CreditDecision] = []
    for _ in range(count):
        limit = rng.randint(10_000, 900_000)
        # Keep all decisions valid so the benchmark proof represents all checks passing.
        balance = limit + rng.randint(1, 100_000)
        decisions.append(CreditDecision(balance=balance, limit=limit))
    return decisions


def format_table(rows: list[tuple[str, str]]) -> str:
    """Render aligned ASCII table for CLI benchmark output."""
    col_a = max(len(k) for k, _ in rows)
    col_b = max(len(v) for _, v in rows)
    divider = f"+-{'-' * col_a}-+-{'-' * col_b}-+"
    lines = [divider]
    for key, value in rows:
        lines.append(f"| {key.ljust(col_a)} | {value.ljust(col_b)} |")
    lines.append(divider)
    return "\n".join(lines)


async def run_benchmark(*, seed: int) -> None:
    """Execute end-to-end benchmark and print summarized timings."""
    settings = Settings.from_env()
    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
    provider = SnarkJSProvider(registry=registry, snarkjs_bin=settings.snarkjs_bin)

    await provider.ensure_artifacts(BATCH_CIRCUIT_ID)

    decisions = generate_decisions(MAX_BATCH_SIZE, seed=seed)
    balances = [d.balance for d in decisions]
    limits = [d.limit for d in decisions]

    start_native = time.perf_counter()
    native_valid = True
    for item in decisions:
        native_valid = native_valid and (item.balance > item.limit)
    native_total_ms = (time.perf_counter() - start_native) * 1000.0

    prepared = batch_prepare_input(balances=balances, limits=limits, batch_size=MAX_BATCH_SIZE)

    start_prove = time.perf_counter()
    proof_result = await provider.generate_proof(
        BATCH_CIRCUIT_ID,
        prepared.to_circuit_input(),
    )
    operational_overhead_ms = (time.perf_counter() - start_prove) * 1000.0

    start_verify = time.perf_counter()
    zk_valid = await provider.verify_proof(
        BATCH_CIRCUIT_ID,
        proof_result.proof,
        proof_result.public_signals,
    )
    single_verify_ms = (time.perf_counter() - start_verify) * 1000.0

    speedup = native_total_ms / single_verify_ms if single_verify_ms > 0 else float("inf")

    rows = [
        ("Scenario", f"{MAX_BATCH_SIZE} credit decisions (single batch proof)"),
        (f"Native total ({MAX_BATCH_SIZE} checks)", f"{native_total_ms:.6f} ms"),
        ("ZK single verify", f"{single_verify_ms:.6f} ms"),
        ("Operational overhead (prove)", f"{operational_overhead_ms:.6f} ms"),
        ("Native checks valid", str(native_valid)),
        ("Batch proof valid", str(zk_valid)),
        ("Auditor speedup (Native / ZK verify)", f"{speedup:.6f}x"),
    ]
    print(format_table(rows))


def parse_args() -> argparse.Namespace:
    """Parse benchmark CLI arguments."""
    parser = argparse.ArgumentParser(
        description=f"Benchmark native {MAX_BATCH_SIZE} checks vs single batch proof verification."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260319,
        help="Deterministic RNG seed for input generation.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_benchmark(seed=args.seed))
