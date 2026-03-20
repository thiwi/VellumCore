"""Built-in proof provider implementations and provider base aliases."""

from vellum_core.providers.base import ProofResult, ZKProvider
from vellum_core.providers.snarkjs_provider import SnarkJSProvider

__all__ = ["ProofResult", "SnarkJSProvider", "ZKProvider"]
