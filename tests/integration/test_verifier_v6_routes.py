"""Tests for Verifier v6 routes."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _load_verifier_service(monkeypatch: pytest.MonkeyPatch):
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

        async def verify_jwt_credentials(self, _credentials: Any, *, required_scopes: set[str]) -> dict[str, str]:
            _ = required_scopes
            return {"sub": "integration-user"}

    monkeypatch.setattr(database_module, "Database", FakeDatabase)
    monkeypatch.setattr(auth_module, "AuthManager", FakeAuthManager)
    module = importlib.import_module("verifier_service")
    return importlib.reload(module)


def _patch_audit_read_auth(monkeypatch: pytest.MonkeyPatch, verifier_service: Any) -> None:
    async def fake_verify_jwt_credentials(
        _credentials: Any,
        *,
        required_scopes: set[str],
    ) -> dict[str, str]:
        assert "audit:read" in required_scopes
        return {"sub": "integration-user"}

    monkeypatch.setattr(
        verifier_service.auth_manager,
        "verify_jwt_credentials",
        fake_verify_jwt_credentials,
    )


@pytest.mark.integration
def test_v6_attestation_export(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    verifier_service = _load_verifier_service(monkeypatch)
    _patch_audit_read_auth(monkeypatch, verifier_service)

    wasm_path = tmp_path / "demo.wasm"
    zkey_path = tmp_path / "final.zkey"
    vk_path = tmp_path / "verification_key.json"
    wasm_path.write_text("wasm", encoding="utf-8")
    zkey_path.write_text("zkey", encoding="utf-8")
    vk_path.write_text("vk", encoding="utf-8")

    async def fake_get_proof_job(_run_id: str) -> Any:
        return SimpleNamespace(
            status="completed",
            proof={"pi_a": ["1"]},
            public_signals=["1"],
            circuit_id="batch_credit_check",
            meta={"policy_id": "lending_risk_v1", "decision": "pass"},
        )

    async def fake_list_audit_rows_for_proof(*, proof_id: str) -> list[Any]:
        _ = proof_id
        return [
            SimpleNamespace(
                id=1,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                status="completed",
                entry_hash="entry-hash",
                signature="vault:v1:sig",
                key_version="1",
            )
        ]

    monkeypatch.setattr(verifier_service.db, "get_proof_job", fake_get_proof_job, raising=False)
    monkeypatch.setattr(
        verifier_service.db,
        "list_audit_rows_for_proof",
        fake_list_audit_rows_for_proof,
        raising=False,
    )
    monkeypatch.setattr(
        verifier_service.framework.policy_registry,
        "get_manifest",
        lambda _policy_id: SimpleNamespace(policy_version="1.0.0"),
    )
    monkeypatch.setattr(
        verifier_service.framework.artifact_store,
        "get_artifact_paths",
        lambda _circuit_id: SimpleNamespace(
            wasm_path=str(wasm_path),
            zkey_path=str(zkey_path),
            verification_key_path=str(vk_path),
        ),
    )

    client = TestClient(verifier_service.app)
    response = client.get(
        "/v6/runs/run-1/attestation",
        headers={"Authorization": "Bearer demo"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["attestation_id"] == "att-run-1"
    assert body["decision"] == "pass"
    assert body["policy"]["version"] == "1.0.0"
    assert body["artifact_digests"]["wasm_sha256"]
    assert body["signature_chain"][0]["entry_hash"] == "entry-hash"


@pytest.mark.integration
def test_v6_trust_speed(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier_service = _load_verifier_service(monkeypatch)
    _patch_audit_read_auth(monkeypatch, verifier_service)

    client = TestClient(verifier_service.app)
    response = client.get("/v6/trust-speed", headers={"Authorization": "Bearer demo"})

    assert response.status_code == 200


@pytest.mark.integration
def test_v6_attestation_export_rejects_unknown_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier_service = _load_verifier_service(monkeypatch)
    _patch_audit_read_auth(monkeypatch, verifier_service)
    async def fake_get_proof_job(_run_id: str) -> Any:
        return None

    monkeypatch.setattr(verifier_service.db, "get_proof_job", fake_get_proof_job, raising=False)

    client = TestClient(verifier_service.app)
    response = client.get(
        "/v6/runs/not-a-run/attestation",
        headers={"Authorization": "Bearer demo"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_run_id"


@pytest.mark.integration
def test_v6_attestation_export_requires_policy_id_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier_service = _load_verifier_service(monkeypatch)
    _patch_audit_read_auth(monkeypatch, verifier_service)

    async def fake_get_proof_job(_run_id: str) -> Any:
        return SimpleNamespace(
            status="completed",
            proof={"pi_a": ["1"]},
            public_signals=["1"],
            circuit_id="batch_credit_check",
            meta={},
        )

    monkeypatch.setattr(verifier_service.db, "get_proof_job", fake_get_proof_job, raising=False)

    client = TestClient(verifier_service.app)
    response = client.get(
        "/v6/runs/run-2/attestation",
        headers={"Authorization": "Bearer demo"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_run_id"
