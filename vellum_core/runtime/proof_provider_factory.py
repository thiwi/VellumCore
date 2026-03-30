"""Factory for constructing primary and shadow proof providers."""

from __future__ import annotations

from vellum_core.providers import (
    GrpcProofProvider,
    ZKProvider,
)
from vellum_core.registry import CircuitRegistry
from vellum_core.runtime.proof_provider_config import ProofProviderRuntimeConfig


def build_proof_provider(
    *,
    registry: CircuitRegistry,
    config: ProofProviderRuntimeConfig,
) -> ZKProvider:
    """Build grpc-only runtime provider."""
    return GrpcProofProvider(
        registry=registry,
        endpoint=config.grpc_endpoint,
        timeout_seconds=config.grpc_timeout_seconds,
    )
