"""Tests for V5 openapi contract."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from vellum_core.schemas import (
    AttestationExportResponse,
    PolicyRunAcceptedResponse,
    PolicyRunRequest,
    PolicyRunStatusResponse,
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
def test_v5_http_surface_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    prover_app = _load_service_app(module_name="prover_service", monkeypatch=monkeypatch)
    verifier_app = _load_service_app(module_name="verifier_service", monkeypatch=monkeypatch)
    prover_openapi = prover_app.openapi()
    verifier_openapi = verifier_app.openapi()

    snapshot_payload = {
        "prover": {
            "/v5/policy-runs#post": _openapi_operation(
                prover_openapi,
                path="/v5/policy-runs",
                method="post",
            ),
            "/v5/policy-runs/{run_id}#get": _openapi_operation(
                prover_openapi,
                path="/v5/policy-runs/{run_id}",
                method="get",
            ),
        },
        "verifier": {
            "/v5/attestations/{attestation_id}#get": _openapi_operation(
                verifier_openapi,
                path="/v5/attestations/{attestation_id}",
                method="get",
            ),
        },
    }
    _assert_snapshot("v5_http_surface.json", snapshot_payload)


@pytest.mark.unit
def test_v5_model_schema_snapshot() -> None:
    snapshot_payload = {
        "PolicyRunRequest": PolicyRunRequest.model_json_schema(),
        "PolicyRunAcceptedResponse": PolicyRunAcceptedResponse.model_json_schema(),
        "PolicyRunStatusResponse": PolicyRunStatusResponse.model_json_schema(),
        "AttestationExportResponse": AttestationExportResponse.model_json_schema(),
    }
    _assert_snapshot("v5_model_schemas.json", snapshot_payload)
