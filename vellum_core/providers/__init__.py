"""Built-in proof provider implementations and provider base aliases."""

from vellum_core.providers.base import ProofResult, ZKProvider
from vellum_core.providers.grpc_prover_provider import GrpcProofProvider
from vellum_core.providers.shadow_provider import ShadowProofProvider
from vellum_core.providers.snarkjs_provider import SnarkJSProvider

__all__ = [
    "GrpcProofProvider",
    "ProofResult",
    "ShadowProofProvider",
    "SnarkJSProvider",
    "ZKProvider",
]
