"""Abstract provider contract helpers used by concrete ZK backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from vellum_core.spi import ProofProvider, ProviderProofResult

ProofResult = ProviderProofResult


class ZKProvider(ProofProvider, ABC):
    """Abstract base class for zero-knowledge provider implementations."""

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
