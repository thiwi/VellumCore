from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProofResult:
    proof: dict[str, Any]
    public_signals: list[Any]


class ZKProvider(ABC):
    @abstractmethod
    async def generate_proof(
        self, circuit_id: str, private_input: dict[str, Any]
    ) -> ProofResult:
        raise NotImplementedError

    @abstractmethod
    async def verify_proof(
        self, circuit_id: str, proof: dict[str, Any], public_signals: list[Any]
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def ensure_artifacts(self, circuit_id: str) -> None:
        raise NotImplementedError

