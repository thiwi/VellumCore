"""Typed runtime configuration for proof-provider wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vellum_core.config import Settings

ProofProviderMode = Literal["snarkjs", "grpc"]


@dataclass(frozen=True)
class ProofProviderRuntimeConfig:
    """Normalized provider configuration parsed from settings."""

    primary_mode: ProofProviderMode
    grpc_endpoint: str
    grpc_timeout_seconds: float
    shadow_enabled: bool
    shadow_mode: ProofProviderMode
    shadow_compare_public_signals: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProofProviderRuntimeConfig":
        config = cls(
            primary_mode=_normalize_mode(settings.proof_provider_mode),
            grpc_endpoint=settings.grpc_prover_endpoint,
            grpc_timeout_seconds=settings.grpc_prover_timeout_seconds,
            shadow_enabled=settings.proof_shadow_mode,
            shadow_mode=_normalize_mode(settings.proof_shadow_provider_mode),
            shadow_compare_public_signals=settings.proof_shadow_compare_public_signals,
        )
        _validate_config(config)
        return config


def _normalize_mode(raw: str) -> ProofProviderMode:
    value = raw.strip().lower()
    if value in {"snarkjs", "grpc"}:
        return value
    raise ValueError(f"unsupported proof provider mode: {raw}")


def _validate_config(config: ProofProviderRuntimeConfig) -> None:
    if config.grpc_timeout_seconds <= 0:
        raise ValueError("GRPC_PROVER_TIMEOUT_SECONDS must be > 0")
    if not config.grpc_endpoint.strip():
        raise ValueError("GRPC_PROVER_ENDPOINT must not be empty")
