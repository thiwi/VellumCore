"""Tests for generated reference policy registry discovery."""

from __future__ import annotations

import pytest

from vellum_core.api.errors import FrameworkError
from vellum_core.policies.registry import (
    get_reference_policy,
    list_reference_policies,
    refresh_reference_policy_registry,
)


@pytest.mark.unit
def test_generated_reference_policies_are_discoverable() -> None:
    lending = get_reference_policy("lending_risk_reference_v1")
    assert getattr(lending, "policy_id", "") == "lending_risk_v1"

    portfolio = get_reference_policy("lending_risk_portfolio_reference_v1")
    assert getattr(portfolio, "policy_id", "") == "lending_risk_portfolio_v1"


@pytest.mark.unit
def test_missing_reference_policy_raises_framework_error() -> None:
    with pytest.raises(FrameworkError) as exc:
        get_reference_policy("does_not_exist_reference_policy")
    assert exc.value.code == "reference_policy_missing"


@pytest.mark.unit
def test_reference_policy_registry_refresh_supports_module_reload() -> None:
    refresh_reference_policy_registry(reload_modules=True)
    available = list_reference_policies()
    assert "lending_risk_reference_v1" in available
