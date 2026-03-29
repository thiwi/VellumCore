"""Factory for constructing primary and shadow proof providers."""

from __future__ import annotations

from vellum_core.providers import (
    GrpcProofProvider,
    ShadowProofProvider,
    SnarkJSProvider,
    ZKProvider,
)
from vellum_core.registry import CircuitRegistry
from vellum_core.runtime.proof_provider_config import ProofProviderMode, ProofProviderRuntimeConfig


def build_proof_provider(
    *,
    registry: CircuitRegistry,
    snarkjs_bin: str,
    config: ProofProviderRuntimeConfig,
) -> ZKProvider:
    """Build provider graph from normalized runtime config."""
    primary = build_provider_for_mode(
        mode=config.primary_mode,
        registry=registry,
        snarkjs_bin=snarkjs_bin,
        config=config,
    )
    if not config.shadow_enabled:
        return primary

    shadow = build_provider_for_mode(
        mode=config.shadow_mode,
        registry=registry,
        snarkjs_bin=snarkjs_bin,
        config=config,
    )
    return ShadowProofProvider(
        primary=primary,
        shadow=shadow,
        compare_public_signals=config.shadow_compare_public_signals,
    )


def build_provider_for_mode(
    *,
    mode: ProofProviderMode,
    registry: CircuitRegistry,
    snarkjs_bin: str,
    config: ProofProviderRuntimeConfig,
) -> ZKProvider:
    """Build one provider for an explicit mode."""
    if mode == "snarkjs":
        return SnarkJSProvider(registry=registry, snarkjs_bin=snarkjs_bin)
    if mode == "grpc":
        return GrpcProofProvider(
            registry=registry,
            endpoint=config.grpc_endpoint,
            timeout_seconds=config.grpc_timeout_seconds,
        )
    raise ValueError(f"unsupported proof provider mode: {mode}")
