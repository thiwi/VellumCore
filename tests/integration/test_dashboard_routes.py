"""Tests for Dashboard routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import dashboard_service
from vellum_core.logic.batcher import MAX_BATCH_SIZE


@pytest.mark.integration
def test_framework_health_route(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "components": {"prover": {"status": "ok", "status_code": 200, "detail": "ok"}},
        }

    monkeypatch.setattr(dashboard_service, "_framework_health_snapshot", fake_health)
    client = TestClient(dashboard_service.app)
    response = client.get("/api/framework/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.integration
def test_framework_diagnostics_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_health() -> dict[str, Any]:
        return {
            "status": "degraded",
            "components": {
                "redis": {"status": "down", "status_code": None, "detail": "connection refused"}
            },
        }

    monkeypatch.setattr(dashboard_service, "_framework_health_snapshot", fake_health)
    client = TestClient(dashboard_service.app)
    response = client.get("/api/framework/diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "degraded_dependencies"
    assert "redis" in body["failed_components"]


@pytest.mark.integration
def test_framework_overview_route(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_health() -> dict[str, Any]:
        return {"status": "ok", "components": {}}

    async def fake_trust_speed() -> dict[str, Any]:
        return {"native_verify_ms": 1.0, "zk_batch_verify_ms": 2.0, "trust_speedup": 0.5}

    async def fake_list_proofs(*, status: str | None = None, circuit_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        _ = (status, circuit_id, limit)
        return {
            "items": [
                {
                    "proof_id": "a",
                    "status": "queued",
                    "circuit_id": "batch_credit_check",
                    "error": None,
                    "metadata": {},
                    "created_at": "2026-03-20T10:00:00Z",
                    "updated_at": "2026-03-20T10:00:00Z",
                },
                {
                    "proof_id": "b",
                    "status": "failed",
                    "circuit_id": "batch_credit_check",
                    "error": "boom",
                    "metadata": {},
                    "created_at": "2026-03-20T10:01:00Z",
                    "updated_at": "2026-03-20T10:01:00Z",
                },
            ],
            "count": 2,
            "filters": {"status": None, "circuit_id": None, "limit": 50},
        }

    monkeypatch.setattr(dashboard_service, "_framework_health_snapshot", fake_health)
    monkeypatch.setattr(dashboard_service, "demo_trust_speed", fake_trust_speed)
    monkeypatch.setattr(dashboard_service, "_list_proofs", fake_list_proofs)

    client = TestClient(dashboard_service.app)
    response = client.get("/api/framework/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["health"]["status"] == "ok"
    assert body["jobs"]["active"] == 1
    assert body["jobs"]["latest_failed"]["proof_id"] == "b"


@pytest.mark.integration
def test_demo_list_proofs_route(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list_proofs(*, status: str | None = None, circuit_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        return {
            "items": [],
            "count": 0,
            "filters": {"status": status, "circuit_id": circuit_id, "limit": limit},
        }

    monkeypatch.setattr(dashboard_service, "_list_proofs", fake_list_proofs)
    client = TestClient(dashboard_service.app)
    response = client.get("/api/demo/proofs?status=running&circuit_id=batch_credit_check&limit=25")
    assert response.status_code == 200
    body = response.json()
    assert body["filters"]["status"] == "running"
    assert body["filters"]["circuit_id"] == "batch_credit_check"
    assert body["filters"]["limit"] == 25


@pytest.mark.integration
def test_demo_prove_rejects_payload_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard_service.config, "dashboard_max_demo_prove_body_bytes", 128)
    client = TestClient(dashboard_service.app)
    response = client.post(
        "/api/demo/prove",
        json={"balances": [1] * 200, "limits": [0] * 200},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


@pytest.mark.integration
def test_demo_prove_rejects_batches_above_max_size() -> None:
    client = TestClient(dashboard_service.app)
    response = client.post(
        "/api/demo/prove",
        json={
            "balances": [1 for _ in range(MAX_BATCH_SIZE + 1)],
            "limits": [0 for _ in range(MAX_BATCH_SIZE + 1)],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.integration
def test_demo_prove_rejects_mixed_input_modes() -> None:
    client = TestClient(dashboard_service.app)
    response = client.post(
        "/api/demo/prove",
        json={"balances": [10], "limits": [1], "private_input": {"x": 1}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
