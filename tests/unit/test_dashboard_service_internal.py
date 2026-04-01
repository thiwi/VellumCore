"""Internal tests for dashboard auth/performance helpers."""

from __future__ import annotations

import asyncio

import pytest

import dashboard_service


class _FakeSigner:
    def __init__(self) -> None:
        self.calls = 0

    async def sign(self, **kwargs: object) -> str:
        _ = kwargs
        self.calls += 1
        return f"token-{self.calls}"


@pytest.mark.unit
def test_dashboard_jwt_cache_reuses_token_before_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr(dashboard_service.time, "time", lambda: now)
    signer = _FakeSigner()
    cache = dashboard_service._DashboardJWTCache(
        signer=signer,  # type: ignore[arg-type]
        subject="dashboard-demo-user",
        scopes={"dashboard:read"},
        ttl_seconds=600,
        refresh_skew_seconds=60,
    )

    first = asyncio.run(cache.get_token())
    second = asyncio.run(cache.get_token())

    assert first == "token-1"
    assert second == "token-1"
    assert signer.calls == 1


@pytest.mark.unit
def test_dashboard_jwt_cache_refreshes_when_token_near_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = {"value": 1000.0}
    monkeypatch.setattr(dashboard_service.time, "time", lambda: current["value"])
    signer = _FakeSigner()
    cache = dashboard_service._DashboardJWTCache(
        signer=signer,  # type: ignore[arg-type]
        subject="dashboard-demo-user",
        scopes={"dashboard:read"},
        ttl_seconds=600,
        refresh_skew_seconds=60,
    )

    first = asyncio.run(cache.get_token())
    current["value"] = 1545.0
    second = asyncio.run(cache.get_token())

    assert first == "token-1"
    assert second == "token-2"
    assert signer.calls == 2


@pytest.mark.unit
def test_dashboard_shared_http_client_reused() -> None:
    asyncio.run(dashboard_service._close_shared_http_client())
    first = asyncio.run(dashboard_service._get_shared_http_client())
    second = asyncio.run(dashboard_service._get_shared_http_client())

    assert first is second

    asyncio.run(dashboard_service._close_shared_http_client())
    assert first.is_closed
