"""Python reference track for lending-risk policy."""

from __future__ import annotations

from typing import Any

from vellum_core.api.errors import framework_error
from vellum_core.logic.batcher import (
    MAX_UINT32,
    batch_prepare_from_private_input,
    batch_prepare_input,
)
from vellum_core.policies.base import PolicyDecision, ReferencePolicy
from vellum_core.policies.normalization import require_integer_list


class LendingRiskReferencePolicy:
    """Reference implementation for `lending_risk_v1`."""

    reference_policy = "lending_risk_reference_v1"

    def validate(self, evidence_payload: dict[str, Any]) -> None:
        _ = self.normalize(evidence_payload)

    def normalize(self, evidence_payload: dict[str, Any]) -> dict[str, Any]:
        private_input = evidence_payload.get("private_input")
        if isinstance(private_input, dict):
            try:
                prepared = batch_prepare_from_private_input(private_input)
            except ValueError as exc:
                raise framework_error(
                    "invalid_evidence_payload",
                    "Evidence payload failed batch validation",
                    reason=str(exc),
                ) from exc
            return prepared.to_circuit_input()

        balances = require_integer_list(
            field="balances",
            value=evidence_payload.get("balances"),
            minimum=0,
            maximum=MAX_UINT32,
        )
        limits = require_integer_list(
            field="limits",
            value=evidence_payload.get("limits"),
            minimum=0,
            maximum=MAX_UINT32,
        )
        try:
            prepared = batch_prepare_input(balances=balances, limits=limits)
        except ValueError as exc:
            raise framework_error(
                "invalid_evidence_payload",
                "Evidence payload failed batch validation",
                reason=str(exc),
            ) from exc
        return prepared.to_circuit_input()

    def to_private_input(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "balances": list(normalized_evidence["balances"]),
            "limits": list(normalized_evidence["limits"]),
            "active_count": int(normalized_evidence["active_count"]),
        }

    def evaluate_reference(self, normalized_evidence: dict[str, Any]) -> PolicyDecision:
        active_count = int(normalized_evidence["active_count"])
        balances = list(normalized_evidence["balances"])
        limits = list(normalized_evidence["limits"])
        is_valid = all(
            balances[idx] > limits[idx]
            for idx in range(active_count)
        )
        return "pass" if is_valid else "fail"

    def project_public_outputs(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        active_count = int(normalized_evidence["active_count"])
        balances = list(normalized_evidence["balances"])
        limits = list(normalized_evidence["limits"])
        all_valid = all(
            balances[idx] > limits[idx]
            for idx in range(active_count)
        )
        return {
            "all_valid": all_valid,
            "active_count_out": active_count,
        }


def as_reference_policy(policy: ReferencePolicy) -> ReferencePolicy:
    """Narrow helper for static typing around concrete class instances."""
    return policy
