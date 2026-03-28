"""Reference-policy lookup helpers."""

from __future__ import annotations

import importlib
import os
import pkgutil

from vellum_core.api.errors import framework_error
from vellum_core.policies.base import ReferencePolicy
from vellum_core.policies import generated as generated_policies_pkg
from vellum_core.policies.lending_risk import LendingRiskReferencePolicy

LEGACY_FALLBACK_ENV = "POLICY_REFERENCE_LEGACY_FALLBACK"


def _legacy_fallback_enabled() -> bool:
    raw = os.getenv(LEGACY_FALLBACK_ENV, "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _build_reference_registry() -> dict[str, ReferencePolicy]:
    registry: dict[str, ReferencePolicy] = _load_generated_reference_policies()
    if _legacy_fallback_enabled():
        registry.setdefault(
            LendingRiskReferencePolicy.reference_policy,
            LendingRiskReferencePolicy(),
        )
    return registry


def _load_generated_reference_policies() -> dict[str, ReferencePolicy]:
    registry: dict[str, ReferencePolicy] = {}
    package_prefix = f"{generated_policies_pkg.__name__}."
    for module_info in pkgutil.iter_modules(generated_policies_pkg.__path__, package_prefix):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        cls = getattr(module, "GeneratedReferencePolicy", None)
        if cls is None:
            continue
        policy = cls()
        reference_policy = getattr(policy, "reference_policy", None)
        if isinstance(reference_policy, str) and reference_policy.strip():
            registry[reference_policy] = policy
    return registry


_REFERENCE_POLICY_REGISTRY = _build_reference_registry()


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
