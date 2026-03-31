"""Reference policy for zk_kyc_v1."""

from __future__ import annotations

from typing import Any

from vellum_core.api.errors import framework_error
from vellum_core.policies.base import PolicyDecision


class GeneratedReferencePolicy:
    """Reference policy for `zk_kyc_v1`."""

    reference_policy = "zk_kyc_reference_v1"
    policy_id = "zk_kyc_v1"

    def validate(self, evidence_payload: dict[str, Any]) -> None:
        _ = self.normalize(evidence_payload)

    def normalize(self, evidence_payload: dict[str, Any]) -> dict[str, Any]:
        private_input = evidence_payload.get("private_input")
        if isinstance(private_input, dict):
            age = private_input.get("age")
            country_code = private_input.get("country_code")
            min_age = private_input.get("min_age")
            allowed_country_code = private_input.get("allowed_country_code")
        else:
            age = evidence_payload.get("age")
            country_code = evidence_payload.get("country_code")
            min_age = evidence_payload.get("min_age")
            allowed_country_code = evidence_payload.get("allowed_country_code")

        fields = {
            "age": age,
            "country_code": country_code,
            "min_age": min_age,
            "allowed_country_code": allowed_country_code,
        }
        for field, value in fields.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise framework_error(
                    "invalid_evidence_payload",
                    f"{field} must be integer",
                    field=field,
                )

        if not 0 <= int(age) <= 130:
            raise framework_error("invalid_evidence_payload", "age out of bounds", field="age")
        if not 0 <= int(min_age) <= 130:
            raise framework_error("invalid_evidence_payload", "min_age out of bounds", field="min_age")
        if not 0 <= int(country_code) <= 999:
            raise framework_error(
                "invalid_evidence_payload",
                "country_code out of bounds",
                field="country_code",
            )
        if not 0 <= int(allowed_country_code) <= 999:
            raise framework_error(
                "invalid_evidence_payload",
                "allowed_country_code out of bounds",
                field="allowed_country_code",
            )

        return {
            "age": int(age),
            "country_code": int(country_code),
            "min_age": int(min_age),
            "allowed_country_code": int(allowed_country_code),
        }

    def to_private_input(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "age": int(normalized_evidence["age"]),
            "country_code": int(normalized_evidence["country_code"]),
            "min_age": int(normalized_evidence["min_age"]),
            "allowed_country_code": int(normalized_evidence["allowed_country_code"]),
        }

    def evaluate_reference(self, normalized_evidence: dict[str, Any]) -> PolicyDecision:
        age = int(normalized_evidence["age"])
        country_code = int(normalized_evidence["country_code"])
        min_age = int(normalized_evidence["min_age"])
        allowed_country_code = int(normalized_evidence["allowed_country_code"])
        passed = age >= min_age and country_code == allowed_country_code
        return "pass" if passed else "fail"

    def project_public_outputs(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        age = int(normalized_evidence["age"])
        country_code = int(normalized_evidence["country_code"])
        min_age = int(normalized_evidence["min_age"])
        allowed_country_code = int(normalized_evidence["allowed_country_code"])
        return {"kyc_ok": age >= min_age and country_code == allowed_country_code}
