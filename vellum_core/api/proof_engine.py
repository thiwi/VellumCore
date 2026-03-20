"""Proof generation/verification orchestration over provider implementations."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from vellum_core.api.errors import FrameworkError, framework_error
from vellum_core.api.types import ProofGenerationRequest, ProofGenerationResult, VerificationRequest, VerificationResult
from vellum_core.spi import ProofProvider
from vellum_core.api.circuit_manager import CircuitManager


class ProofEngine:
    """High-level proof generation and verification orchestration."""

    def __init__(self, *, provider: ProofProvider, circuit_manager: CircuitManager) -> None:
        self.provider = provider
        self.circuit_manager = circuit_manager

    async def generate(self, request: ProofGenerationRequest) -> ProofGenerationResult:
        """Generate a proof for a circuit-specific private input payload."""
        await self.circuit_manager.ensure_artifacts(request.circuit_id, self.provider)
        try:
            result = await self.provider.generate_proof(request.circuit_id, request.private_input)
        except Exception as exc:
            raise framework_error(
                "proof_generation_failed",
                "Proof generation failed",
                circuit_id=request.circuit_id,
                reason=str(exc),
            ) from exc

        return ProofGenerationResult.create(
            circuit_id=request.circuit_id,
            proof=result.proof,
            public_signals=result.public_signals,
        )

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        """Verify a proof/public-signal tuple and return timing metadata."""
        await self.circuit_manager.ensure_artifacts(request.circuit_id, self.provider)
        started = time.perf_counter()
        try:
            valid = await self.provider.verify_proof(
                request.circuit_id,
                request.proof,
                request.public_signals,
            )
        except Exception as exc:
            raise FrameworkError(
                code="proof_verification_failed",
                message="Proof verification failed",
                details={"circuit_id": request.circuit_id, "reason": str(exc)},
            ) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return VerificationResult(
            circuit_id=request.circuit_id,
            valid=valid,
            verification_ms=elapsed_ms,
            verified_at=datetime.now(timezone.utc),
        )
