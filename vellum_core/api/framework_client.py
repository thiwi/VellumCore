"""High-level framework client object and construction helpers."""

from __future__ import annotations

from dataclasses import dataclass

from vellum_core.api.circuit_manager import CircuitManager
from vellum_core.api.config import FrameworkConfig
from vellum_core.api.proof_engine import ProofEngine
from vellum_core.api.policy_engine import PolicyEngine
from vellum_core.api.attestation_service import AttestationService
from vellum_core.config import Settings
from vellum_core.policy_parameters import PolicyParameterStore
from vellum_core.policy_registry import PolicyRegistry
from vellum_core.spi import (
    ArtifactStore,
    AttestationSigner,
    EvidenceStore,
    JobBackend,
    ProofProvider,
    Signer,
)


@dataclass(frozen=True)
class FrameworkClient:
    """Unified access point to framework capabilities and runtime dependencies."""

    config: FrameworkConfig
    circuit_manager: CircuitManager
    proof_engine: ProofEngine
    policy_engine: PolicyEngine
    attestation_service: AttestationService
    policy_registry: PolicyRegistry
    provider: ProofProvider
    artifact_store: ArtifactStore
    signer: Signer
    evidence_store: EvidenceStore
    attestation_signer: AttestationSigner
    job_backend: JobBackend
    policy_parameter_store: PolicyParameterStore

    @classmethod
    def from_settings(cls, settings: Settings) -> "FrameworkClient":
        """Build a fully wired client instance from an explicit settings object."""
        from vellum_core.runtime.defaults import build_framework_client

        return build_framework_client(settings)

    @classmethod
    def from_env(cls) -> "FrameworkClient":
        """Build a client from environment-derived settings."""
        return cls.from_settings(Settings.from_env())
