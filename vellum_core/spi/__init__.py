"""Service provider interface exports for framework extensibility."""

from vellum_core.spi.interfaces import (
    ArtifactPathsView,
    ArtifactStore,
    AttestationSigner,
    EvidenceStore,
    JobBackend,
    ProofProvider,
    ProviderProofResult,
    Signer,
)

__all__ = [
    "ArtifactPathsView",
    "ArtifactStore",
    "AttestationSigner",
    "EvidenceStore",
    "JobBackend",
    "ProofProvider",
    "ProviderProofResult",
    "Signer",
]
