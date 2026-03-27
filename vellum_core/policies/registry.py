"""Reference-policy lookup helpers."""

from __future__ import annotations

from vellum_core.api.errors import framework_error
from vellum_core.policies.base import ReferencePolicy
from vellum_core.policies.lending_risk import LendingRiskReferencePolicy


_REFERENCE_POLICY_REGISTRY: dict[str, ReferencePolicy] = {
    LendingRiskReferencePolicy.reference_policy: LendingRiskReferencePolicy(),
}


def get_reference_policy(reference_policy: str) -> ReferencePolicy:
    """Resolve one reference-policy implementation by identifier."""
    policy = _REFERENCE_POLICY_REGISTRY.get(reference_policy)
    if policy is None:
        raise framework_error(
            "reference_policy_missing",
            "No Python reference policy implementation found",
            reference_policy=reference_policy,
        )
    return policy
