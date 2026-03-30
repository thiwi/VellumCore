"""Reference-policy lookup helpers."""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field

from vellum_core.api.errors import framework_error
from vellum_core.policies import generated as generated_policies_pkg
from vellum_core.policies.base import ReferencePolicy


@dataclass
class ReferencePolicyRegistry:
    """Lazy and refreshable registry for reference-policy implementations."""

    _registry: dict[str, ReferencePolicy] | None = field(default=None, init=False)

    def get(self, reference_policy: str) -> ReferencePolicy:
        """Resolve one reference policy by id, loading lazily on first access."""
        registry = self._get_or_load()
        policy = registry.get(reference_policy)
        if policy is None:
            raise framework_error(
                "reference_policy_missing",
                "No Python reference policy implementation found",
                reference_policy=reference_policy,
            )
        return policy

    def refresh(self, *, reload_modules: bool = False) -> None:
        """Rebuild registry from generated policy modules."""
        self._registry = _build_reference_registry(reload_modules=reload_modules)

    def list_reference_policies(self) -> list[str]:
        """Return sorted known reference policy ids."""
        return sorted(self._get_or_load().keys())

    def _get_or_load(self) -> dict[str, ReferencePolicy]:
        if self._registry is None:
            self.refresh(reload_modules=False)
        assert self._registry is not None
        return self._registry


def _build_reference_registry(*, reload_modules: bool) -> dict[str, ReferencePolicy]:
    return _load_generated_reference_policies(
        reload_modules=reload_modules
    )


def _load_generated_reference_policies(*, reload_modules: bool) -> dict[str, ReferencePolicy]:
    registry: dict[str, ReferencePolicy] = {}
    package_prefix = f"{generated_policies_pkg.__name__}."
    importlib.invalidate_caches()
    for module_info in pkgutil.iter_modules(generated_policies_pkg.__path__, package_prefix):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        if reload_modules:
            module = importlib.reload(module)
        cls = getattr(module, "GeneratedReferencePolicy", None)
        if cls is None:
            continue
        policy = cls()
        reference_policy = getattr(policy, "reference_policy", None)
        if isinstance(reference_policy, str) and reference_policy.strip():
            registry[reference_policy] = policy
    return registry


_REFERENCE_POLICY_REGISTRY = ReferencePolicyRegistry()


def get_reference_policy(reference_policy: str) -> ReferencePolicy:
    """Resolve one reference-policy implementation by identifier."""
    return _REFERENCE_POLICY_REGISTRY.get(reference_policy)


def refresh_reference_policy_registry(*, reload_modules: bool = False) -> None:
    """Force a registry reload, optionally reloading generated modules."""
    _REFERENCE_POLICY_REGISTRY.refresh(reload_modules=reload_modules)


def list_reference_policies() -> list[str]:
    """List known reference policy identifiers."""
    return _REFERENCE_POLICY_REGISTRY.list_reference_policies()
