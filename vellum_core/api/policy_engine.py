"""Policy-centric orchestration built on top of proof generation and verification."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from vellum_core.api.attestation_service import AttestationService
from vellum_core.api.errors import framework_error
from vellum_core.api.proof_engine import ProofEngine
from vellum_core.api.types import (
    PolicyRunRequest,
    PolicyRunResult,
    ProofGenerationRequest,
    VerificationRequest,
)
from vellum_core.policy_runtime import decision_for_policy, private_input_for_policy
from vellum_core.policy_registry import PolicyNotFoundError, PolicyRegistry
from vellum_core.spi import EvidenceStore


class PolicyEngine:
    """Execute policy runs against evidence payloads and emit attestations."""

    def __init__(
        self,
        *,
        proof_engine: ProofEngine,
        policy_registry: PolicyRegistry,
        evidence_store: EvidenceStore,
        attestation_service: AttestationService,
    ) -> None:
        self.proof_engine = proof_engine
        self.policy_registry = policy_registry
        self.evidence_store = evidence_store
        self.attestation_service = attestation_service

    async def run(self, request: PolicyRunRequest) -> PolicyRunResult:
        """Run one policy from evidence and return decision + attestation id."""
        try:
            manifest = self.policy_registry.get_manifest(request.policy_id)
        except PolicyNotFoundError as exc:
            raise framework_error(
                "unknown_policy",
                "Policy id not found",
                policy_id=request.policy_id,
            ) from exc

        run_id = str(uuid4())
        attestation_id = f"att-{run_id}"
        evidence_payload, evidence_ref = await self._resolve_evidence(run_id=run_id, request=request)

        private_input = private_input_for_policy(
            policy_id=request.policy_id,
            evidence_payload=evidence_payload,
        )

        started = time.perf_counter()
        generated = await self.proof_engine.generate(
            ProofGenerationRequest(
                circuit_id=manifest.circuit_id,
                private_input=private_input,
            )
        )
        generation_ms = (time.perf_counter() - started) * 1000.0

        verify_started = time.perf_counter()
        verified = await self.proof_engine.verify(
            VerificationRequest(
                circuit_id=manifest.circuit_id,
                proof=generated.proof,
                public_signals=generated.public_signals,
            )
        )
        verify_ms = (time.perf_counter() - verify_started) * 1000.0

        decision = decision_for_policy(
            policy_id=request.policy_id,
            public_signals=generated.public_signals,
            verified=verified.valid,
            expected_attestation=manifest.expected_attestation,
        )

        await self.attestation_service.create(
            attestation_id=attestation_id,
            run_id=run_id,
            policy_id=request.policy_id,
            policy_version=manifest.policy_version,
            circuit_id=manifest.circuit_id,
            decision=decision,
            proof=generated.proof,
            public_signals=generated.public_signals,
            metadata={
                "context": request.context,
                "evidence_ref": evidence_ref,
            },
        )

        return PolicyRunResult(
            run_id=run_id,
            policy_id=request.policy_id,
            decision=decision,
            attestation_id=attestation_id,
            timings={
                "generation_ms": generation_ms,
                "verification_ms": verify_ms,
                "total_ms": generation_ms + verify_ms,
            },
        )

    async def _resolve_evidence(
        self,
        *,
        run_id: str,
        request: PolicyRunRequest,
    ) -> tuple[dict[str, Any], str | None]:
        if request.evidence_payload is not None:
            evidence_ref = await self.evidence_store.put(run_id=run_id, payload=request.evidence_payload)
            return request.evidence_payload, evidence_ref
        assert request.evidence_ref is not None
        payload = await self.evidence_store.get(reference=request.evidence_ref)
        return payload, request.evidence_ref
