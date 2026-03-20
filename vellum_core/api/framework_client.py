"""High-level framework client object and construction helpers."""

from __future__ import annotations

from dataclasses import dataclass

from vellum_core.api.circuit_manager import CircuitManager
from vellum_core.api.config import FrameworkConfig
from vellum_core.api.proof_engine import ProofEngine
from vellum_core.config import Settings
from vellum_core.spi import ArtifactStore, InputAdapter, JobBackend, ProofProvider, Signer


@dataclass(frozen=True)
class FrameworkClient:
    """Unified access point to framework capabilities and runtime dependencies."""

    config: FrameworkConfig
    circuit_manager: CircuitManager
    proof_engine: ProofEngine
    provider: ProofProvider
    artifact_store: ArtifactStore
    input_adapter: InputAdapter
    signer: Signer
    job_backend: JobBackend

    @classmethod
    def from_settings(cls, settings: Settings) -> "FrameworkClient":
        """Build a fully wired client instance from an explicit settings object."""
        from vellum_core.runtime.defaults import build_framework_client

        return build_framework_client(settings)

    @classmethod
    def from_env(cls) -> "FrameworkClient":
        """Build a client from environment-derived settings."""
        return cls.from_settings(Settings.from_env())
