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
from vellum_core.policies.dual_track import (
    assert_dual_track_consistency,
    evaluate_circuit_track,
    prepare_reference_track,
)
from vellum_core.policy_registry import PolicyNotFoundError, PolicyRegistry
from vellum_core.run_contract import EvidenceInlineV6, EvidenceRefV6
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

        reference_result = prepare_reference_track(
            reference_policy=manifest.reference_policy,
            differential_outputs=manifest.differential_outputs,
            evidence_payload=evidence_payload,
        )

        started = time.perf_counter()
        generated = await self.proof_engine.generate(
            ProofGenerationRequest(
                circuit_id=manifest.circuit_id,
                private_input=reference_result.private_input,
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

        circuit_result = evaluate_circuit_track(
            policy_id=request.policy_id,
            expected_attestation=manifest.expected_attestation,
            differential_outputs=manifest.differential_outputs,
            public_signals=generated.public_signals,
            verified=verified.valid,
        )
        assert_dual_track_consistency(
            policy_id=request.policy_id,
            reference=reference_result,
            circuit=circuit_result,
        )
        decision = circuit_result.decision

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
                "dual_track": {
                    "reference_outputs": reference_result.outputs,
                    "circuit_outputs": circuit_result.outputs,
                },
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
        if isinstance(request.evidence, EvidenceInlineV6):
            evidence_ref = await self.evidence_store.put(
                run_id=run_id,
                payload=request.evidence.payload,
            )
            return request.evidence.payload, evidence_ref

        assert isinstance(request.evidence, EvidenceRefV6)
        payload = await self.evidence_store.get(reference=request.evidence.ref)
        return payload, request.evidence.ref
