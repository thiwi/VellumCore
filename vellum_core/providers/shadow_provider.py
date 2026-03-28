"""Shadow mode provider that compares primary and secondary proving backends."""

from __future__ import annotations

import logging
from typing import Any

from vellum_core.metrics import observe_shadow_event
from vellum_core.providers.base import ProofResult, ZKProvider


logger = logging.getLogger(__name__)


class ShadowProofProvider(ZKProvider):
    """Run primary provider and shadow provider side-by-side for comparison."""

    def __init__(
        self,
        *,
        primary: ZKProvider,
        shadow: ZKProvider,
        compare_public_signals: bool = True,
    ) -> None:
        self.primary = primary
        self.shadow = shadow
        self.compare_public_signals = compare_public_signals

    async def ensure_artifacts(self, circuit_id: str) -> None:
        await self.primary.ensure_artifacts(circuit_id)
        await self.shadow.ensure_artifacts(circuit_id)

    async def generate_proof(
        self, circuit_id: str, private_input: dict[str, Any]
    ) -> ProofResult:
        primary_result = await self.primary.generate_proof(circuit_id, private_input)
        observe_shadow_event("generate", "primary_success")
        try:
            shadow_result = await self.shadow.generate_proof(circuit_id, private_input)
            self._compare_generate(
                circuit_id=circuit_id,
                primary=primary_result,
                shadow=shadow_result,
            )
        except Exception as exc:
            observe_shadow_event("generate", "shadow_failed")
            logger.warning(
                "proof_shadow_generate_failed",
                extra={"circuit_id": circuit_id, "reason": str(exc)},
            )
        return primary_result

    async def verify_proof(
        self, circuit_id: str, proof: dict[str, Any], public_signals: list[Any]
    ) -> bool:
        primary_valid = await self.primary.verify_proof(circuit_id, proof, public_signals)
        try:
            shadow_valid = await self.shadow.verify_proof(circuit_id, proof, public_signals)
            if shadow_valid != primary_valid:
                observe_shadow_event("verify", "mismatch")
                logger.warning(
                    "proof_shadow_verify_mismatch",
                    extra={
                        "circuit_id": circuit_id,
                        "primary_valid": primary_valid,
                        "shadow_valid": shadow_valid,
                    },
                )
            else:
                observe_shadow_event("verify", "match")
        except Exception as exc:
            observe_shadow_event("verify", "shadow_failed")
            logger.warning(
                "proof_shadow_verify_failed",
                extra={"circuit_id": circuit_id, "reason": str(exc)},
            )
        return primary_valid

    def _compare_generate(
        self,
        *,
        circuit_id: str,
        primary: ProofResult,
        shadow: ProofResult,
    ) -> None:
        if not self.compare_public_signals:
            return
        if primary.public_signals != shadow.public_signals:
            observe_shadow_event("public_signals", "mismatch")
            logger.warning(
                "proof_shadow_public_signal_mismatch",
                extra={
                    "circuit_id": circuit_id,
                    "primary_public_signals": primary.public_signals,
                    "shadow_public_signals": shadow.public_signals,
                },
            )
            return
        observe_shadow_event("public_signals", "match")
