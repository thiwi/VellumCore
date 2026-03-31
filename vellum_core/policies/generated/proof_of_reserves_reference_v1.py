"""Reference policy for proof_of_reserves_v1."""

from __future__ import annotations

from typing import Any

from vellum_core.api.errors import framework_error
from vellum_core.policies.base import PolicyDecision


class GeneratedReferencePolicy:
    """Reference policy for `proof_of_reserves_v1`."""

    reference_policy = "proof_of_reserves_reference_v1"
    policy_id = "proof_of_reserves_v1"

    def validate(self, evidence_payload: dict[str, Any]) -> None:
        _ = self.normalize(evidence_payload)

    def normalize(self, evidence_payload: dict[str, Any]) -> dict[str, Any]:
        private_input = evidence_payload.get("private_input")
        if isinstance(private_input, dict):
            liabilities = private_input.get("liabilities")
            assets = private_input.get("assets")
        else:
            liabilities = evidence_payload.get("liabilities")
            assets = evidence_payload.get("assets")

        if isinstance(liabilities, bool) or not isinstance(liabilities, int):
            raise framework_error(
                "invalid_evidence_payload",
                "liabilities must be integer",
                field="liabilities",
            )
        if isinstance(assets, bool) or not isinstance(assets, int):
            raise framework_error(
                "invalid_evidence_payload",
                "assets must be integer",
                field="assets",
            )
        if liabilities < 0 or assets < 0:
            raise framework_error(
                "invalid_evidence_payload",
                "liabilities/assets must be non-negative",
            )
        return {"liabilities": liabilities, "assets": assets}

    def to_private_input(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "liabilities": int(normalized_evidence["liabilities"]),
            "assets": int(normalized_evidence["assets"]),
        }

    def evaluate_reference(self, normalized_evidence: dict[str, Any]) -> PolicyDecision:
        liabilities = int(normalized_evidence["liabilities"])
        assets = int(normalized_evidence["assets"])
        return "pass" if liabilities <= assets else "fail"

    def project_public_outputs(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        liabilities = int(normalized_evidence["liabilities"])
        assets = int(normalized_evidence["assets"])
        return {"solvency_ok": liabilities <= assets}
