from __future__ import annotations

import argparse
import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any

from sentinel_zk.config import Settings
from sentinel_zk.providers import SnarkJSProvider
from sentinel_zk.registry import CircuitRegistry


@dataclass(frozen=True)
class CreditDecision:
    credit_score: int
    debt_ratio: int


def compute_credit_risk(decision: CreditDecision) -> int:
    return decision.credit_score * 1000 - decision.debt_ratio


def generate_decisions(count: int, *, seed: int) -> list[CreditDecision]:
    rng = random.Random(seed)
    return [
        CreditDecision(
            credit_score=rng.randint(50, 850),
            debt_ratio=rng.randint(0, 200_000),
        )
        for _ in range(count)
    ]


def format_table(rows: list[tuple[str, str]]) -> str:
    col_a = max(len(k) for k, _ in rows)
    col_b = max(len(v) for _, v in rows)
    divider = f"+-{'-' * col_a}-+-{'-' * col_b}-+"
    lines = [divider]
    for key, value in rows:
        lines.append(f"| {key.ljust(col_a)} | {value.ljust(col_b)} |")
    lines.append(divider)
    return "\n".join(lines)


async def run_benchmark(sample_size: int, seed: int) -> None:
    settings = Settings.from_env()
    registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
    provider = SnarkJSProvider(registry=registry, snarkjs_bin=settings.snarkjs_bin)
    circuit_id = "credit_check"

    await provider.ensure_artifacts(circuit_id)
    decisions = generate_decisions(sample_size, seed=seed)

    computed_results = [compute_credit_risk(item) for item in decisions]

    start_native = time.perf_counter()
    audit_ok = True
    for idx, item in enumerate(decisions):
        if compute_credit_risk(item) != computed_results[idx]:
            audit_ok = False
    native_verify_seconds = time.perf_counter() - start_native

    prepared_proofs: list[tuple[dict[str, Any], list[Any]]] = []
    for item in decisions:
        proof = await provider.generate_proof(
            circuit_id,
            {
                "credit_score": item.credit_score,
                "debt_ratio": item.debt_ratio,
            },
        )
        prepared_proofs.append((proof.proof, proof.public_signals))

    start_zk_verify = time.perf_counter()
    zk_valid_count = 0
    for proof, public_signals in prepared_proofs:
        if await provider.verify_proof(circuit_id, proof, public_signals):
            zk_valid_count += 1
    zk_verify_seconds = time.perf_counter() - start_zk_verify

    if zk_verify_seconds == 0:
        speedup = float("inf")
    else:
        speedup = native_verify_seconds / zk_verify_seconds

    rows = [
        ("Scenario", f"{sample_size} credit decisions"),
        ("Native auditor verify", f"{native_verify_seconds:.6f}s"),
        ("ZK auditor verify", f"{zk_verify_seconds:.6f}s"),
        ("ZK proofs valid", f"{zk_valid_count}/{sample_size}"),
        ("Native checks valid", str(audit_ok)),
        ("Verification speedup (Native/ZK)", f"{speedup:.4f}x"),
        ("Note", "Proof generation excluded from verify timing"),
    ]
    print(format_table(rows))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare native auditor re-calculation vs ZK proof verification."
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=1000,
        help="Number of credit decisions to benchmark (default: 1000).",
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
    asyncio.run(run_benchmark(sample_size=args.sample_size, seed=args.seed))

