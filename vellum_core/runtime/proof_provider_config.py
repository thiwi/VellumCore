"""Typed runtime configuration for proof-provider wiring."""

from __future__ import annotations

from dataclasses import dataclass

from vellum_core.config import Settings


@dataclass(frozen=True)
class ProofProviderRuntimeConfig:
    """Normalized provider configuration parsed from settings."""

    grpc_endpoint: str
    grpc_timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProofProviderRuntimeConfig":
        config = cls(
            grpc_endpoint=settings.grpc_prover_endpoint,
            grpc_timeout_seconds=settings.grpc_prover_timeout_seconds,
        )
        _validate_config(config)
        return config


def _validate_config(config: ProofProviderRuntimeConfig) -> None:
    if config.grpc_timeout_seconds <= 0:
        raise ValueError("GRPC_PROVER_TIMEOUT_SECONDS must be > 0")
    if not config.grpc_endpoint.strip():
        raise ValueError("GRPC_PROVER_ENDPOINT must not be empty")
