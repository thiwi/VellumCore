"""Tests for V6 openapi contract."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from vellum_core.schemas import (
    AttestationResponseV6,
    RunCreateAcceptedResponseV6,
    RunCreateRequestV6,
    RunStatusResponseV6,
)

pytestmark = pytest.mark.contract

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def _assert_snapshot(snapshot_name: str, payload: dict[str, Any]) -> None:
    snapshot_path = SNAPSHOT_DIR / snapshot_name
    assert snapshot_path.exists(), f"Missing snapshot file: {snapshot_path}"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload == expected


def _load_service_app(
    *,
    module_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    monkeypatch.setenv("SECURITY_PROFILE", "dev")
    monkeypatch.setenv("VELLUM_DATA_KEY", "vellum-data")

    database_module = importlib.import_module("vellum_core.database")
    auth_module = importlib.import_module("vellum_core.auth")

    class FakeDatabase:
        def __init__(self, _database_url: str) -> None:
            self.engine = object()

        async def init_models(self) -> None:
            return None

    class FakeAuthManager:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def verify_jwt_credentials(
            self,
            _credentials: Any,
            *,
            required_scopes: set[str],
        ) -> dict[str, str]:
            _ = required_scopes
            return {"sub": "contract-user"}

        async def verify_handshake(self, _request: Any, _raw_body: bytes) -> str:
            return "bank-key-1"

    monkeypatch.setattr(database_module, "Database", FakeDatabase)
    monkeypatch.setattr(auth_module, "AuthManager", FakeAuthManager)
    module = importlib.import_module(module_name)
    return importlib.reload(module).app


def _openapi_operation(
    openapi: dict[str, Any],
    *,
    path: str,
    method: str,
) -> dict[str, Any]:
    operation = openapi["paths"][path][method]
    return {
        "operationId": operation.get("operationId"),
        "security": operation.get("security"),
        "requestBody": operation.get("requestBody"),
        "responses": operation.get("responses"),
    }


@pytest.mark.unit
def test_v6_http_surface_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    prover_app = _load_service_app(module_name="prover_service", monkeypatch=monkeypatch)
    verifier_app = _load_service_app(module_name="verifier_service", monkeypatch=monkeypatch)
    prover_openapi = prover_app.openapi()
    verifier_openapi = verifier_app.openapi()

    snapshot_payload = {
        "prover": {
            "/v6/runs#post": _openapi_operation(
                prover_openapi,
                path="/v6/runs",
                method="post",
            ),
            "/v6/runs/{run_id}#get": _openapi_operation(
                prover_openapi,
                path="/v6/runs/{run_id}",
                method="get",
            ),
        },
        "verifier": {
            "/v6/runs/{run_id}/attestation#get": _openapi_operation(
                verifier_openapi,
                path="/v6/runs/{run_id}/attestation",
                method="get",
            ),
        },
    }
    _assert_snapshot("v6_http_surface.json", snapshot_payload)


@pytest.mark.unit
def test_v6_model_schema_snapshot() -> None:
    snapshot_payload = {
        "RunCreateRequestV6": RunCreateRequestV6.model_json_schema(),
        "RunCreateAcceptedResponseV6": RunCreateAcceptedResponseV6.model_json_schema(),
        "RunStatusResponseV6": RunStatusResponseV6.model_json_schema(),
        "AttestationResponseV6": AttestationResponseV6.model_json_schema(),
    }
    _assert_snapshot("v6_model_schemas.json", snapshot_payload)
