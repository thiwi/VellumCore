"""Deterministic stand-in adapter for legacy mainframe credit sources."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

from vellum_core.logic.batcher import MAX_BATCH_SIZE


@dataclass(frozen=True)
class MainframeBatchSignals:
    """Normalized batch payload returned by the mainframe adapter."""

    balances: list[int]
    limits: list[int]


class MainframeAdapter:
    """Simulated secure connector for legacy/mainframe records."""

    async def fetch_credit_batch(
        self, source_ref: str, batch_size: int = MAX_BATCH_SIZE
    ) -> MainframeBatchSignals:
        if not source_ref or not source_ref.strip():
            raise ValueError("source_ref must be a non-empty string")

        # Simulate network/connector latency in async flow.
        await asyncio.sleep(0.05)

        # Deterministic pseudo-data from source reference for repeatable proofs.
        seed = hashlib.sha256(source_ref.encode("utf-8")).digest()
        balances: list[int] = []
        limits: list[int] = []

        for idx in range(batch_size):
            a = seed[idx % len(seed)]
            b = seed[(idx * 7) % len(seed)]
            limit = 10_000 + ((a * 257 + b * 13 + idx * 17) % 500_000)
            # Ensure valid batch rows: balance must be strictly greater than limit.
            balance = limit + 1_000 + ((a * 31 + b * 11 + idx * 5) % 50_000)
            limits.append(limit)
            balances.append(balance)

        return MainframeBatchSignals(balances=balances, limits=limits)
