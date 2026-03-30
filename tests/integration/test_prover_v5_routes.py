"""Tests for Prover v5 routes."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vellum_core.policy_registry import PolicyNotFoundError


def _load_prover_service(monkeypatch: pytest.MonkeyPatch):
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

        async def verify_handshake(self, _request: Any, _raw_body: bytes) -> str:
            return "bank-key-1"

    monkeypatch.setattr(database_module, "Database", FakeDatabase)
    monkeypatch.setattr(auth_module, "AuthManager", FakeAuthManager)
    module = importlib.import_module("prover_service")
    return importlib.reload(module)


def _patch_auth(
    monkeypatch: pytest.MonkeyPatch,
    prover_service: Any,
    *,
    required_scope: str,
) -> None:
    async def fake_verify_jwt_credentials(
        _credentials: Any,
        *,
        required_scopes: set[str],
    ) -> dict[str, str]:
        assert required_scope in required_scopes
        return {"sub": "integration-user"}

    async def fake_verify_handshake(_request: Any, _raw_body: bytes) -> str:
        return "bank-key-1"

    monkeypatch.setattr(
        prover_service.auth_manager,
        "verify_jwt_credentials",
        fake_verify_jwt_credentials,
    )
    monkeypatch.setattr(
        prover_service.auth_manager,
        "verify_handshake",
        fake_verify_handshake,
    )


@pytest.mark.integration
def test_v5_policy_run_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    prover_service = _load_prover_service(monkeypatch)

    calls: dict[str, Any] = {}
    _patch_auth(monkeypatch, prover_service, required_scope="proofs:write")

    async def fake_evidence_put(*, run_id: str, payload: dict[str, Any]) -> str:
        calls["evidence"] = {"run_id": run_id, "payload": payload}
        return f"memory://{run_id}"

    async def fake_create_proof_job(**kwargs: Any) -> Any:
        calls["create_proof_job"] = kwargs
        return SimpleNamespace(proof_id=kwargs["proof_id"])

    async def fake_append_event(**kwargs: Any) -> dict[str, Any]:
        calls["append_event"] = kwargs
        return {"id": 1}

    async def fake_enqueue(*, task_name: str, args: list[Any], queue: str) -> None:
        calls["enqueue"] = {"task_name": task_name, "args": args, "queue": queue}

    async def fake_seal_job_payload(**_kwargs: Any) -> str:
        return "sealed-payload"

    monkeypatch.setattr(
        prover_service.framework.policy_registry,
        "get_manifest",
        lambda _policy_id: SimpleNamespace(
            circuit_id="batch_credit_check",
            policy_version="1.0.0",
            reference_policy="lending_risk_reference_v1",
            primitives=["SafeSub"],
            differential_outputs={
                "all_valid": SimpleNamespace(signal_index=0, value_type="bool"),
                "active_count_out": SimpleNamespace(signal_index=1, value_type="int"),
            },
            expected_attestation={"decision_signal_index": 0, "pass_signal_value": "1"},
        ),
    )
    monkeypatch.setattr(prover_service.framework.evidence_store, "put", fake_evidence_put)
    monkeypatch.setattr(prover_service, "seal_job_payload", fake_seal_job_payload)
    monkeypatch.setattr(prover_service.db, "create_proof_job", fake_create_proof_job, raising=False)
    monkeypatch.setattr(prover_service.audit_store, "append_event", fake_append_event, raising=False)
    monkeypatch.setattr(prover_service.framework.job_backend, "enqueue", fake_enqueue)

    client = TestClient(prover_service.app)
    response = client.post(
        "/v5/policy-runs",
        json={
            "policy_id": "lending_risk_v1",
            "evidence_payload": {"balances": [120], "limits": [100]},
            "context": {"tenant": "acme"},
        },
        headers={"Authorization": "Bearer demo"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["policy_id"] == "lending_risk_v1"
    assert body["status"] == "queued"
    assert body["attestation_id"].startswith("att-")
    assert calls["enqueue"]["task_name"] == "worker.process_proof_job"
    assert calls["create_proof_job"]["circuit_id"] == "batch_credit_check"


@pytest.mark.integration
def test_v1_proof_list_returns_legacy_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    prover_service = _load_prover_service(monkeypatch)
    _patch_auth(monkeypatch, prover_service, required_scope="proofs:read")

    async def fake_list_proof_jobs(**_kwargs: Any) -> list[Any]:
        return []

    monkeypatch.setattr(prover_service.db, "list_proof_jobs", fake_list_proof_jobs, raising=False)

    client = TestClient(prover_service.app)
    response = client.get("/v1/proofs", headers={"Authorization": "Bearer demo"})

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == "Tue, 30 Sep 2026 00:00:00 GMT"
    assert "MIGRATION_V4_TO_V5" in response.headers["Link"]


@pytest.mark.integration
def test_v5_policy_run_submit_with_evidence_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    prover_service = _load_prover_service(monkeypatch)
    _patch_auth(monkeypatch, prover_service, required_scope="proofs:write")

    calls: dict[str, Any] = {}

    async def fake_evidence_get(*, reference: str) -> dict[str, Any]:
        calls["evidence_get"] = reference
        return {"balances": [250], "limits": [200]}

    async def fail_evidence_put(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("evidence_store.put should not be called for evidence_ref flow")

    async def fake_create_proof_job(**kwargs: Any) -> Any:
        calls["create_proof_job"] = kwargs
        return SimpleNamespace(proof_id=kwargs["proof_id"])

    async def fake_append_event(**kwargs: Any) -> dict[str, Any]:
        calls["append_event"] = kwargs
        return {"id": 1}

    async def fake_enqueue(*, task_name: str, args: list[Any], queue: str) -> None:
        calls["enqueue"] = {"task_name": task_name, "args": args, "queue": queue}

    async def fake_seal_job_payload(**_kwargs: Any) -> str:
        return "sealed-payload"

    monkeypatch.setattr(
        prover_service.framework.policy_registry,
        "get_manifest",
        lambda _policy_id: SimpleNamespace(
            circuit_id="batch_credit_check",
            policy_version="1.0.1",
            reference_policy="lending_risk_reference_v1",
            primitives=["SafeSub"],
            differential_outputs={
                "all_valid": SimpleNamespace(signal_index=0, value_type="bool"),
                "active_count_out": SimpleNamespace(signal_index=1, value_type="int"),
            },
            expected_attestation={"decision_signal_index": 0, "pass_signal_value": "1"},
        ),
    )
    monkeypatch.setattr(prover_service.framework.evidence_store, "get", fake_evidence_get)
    monkeypatch.setattr(prover_service.framework.evidence_store, "put", fail_evidence_put)
    monkeypatch.setattr(prover_service, "seal_job_payload", fake_seal_job_payload)
    monkeypatch.setattr(prover_service.db, "create_proof_job", fake_create_proof_job, raising=False)
    monkeypatch.setattr(prover_service.audit_store, "append_event", fake_append_event, raising=False)
    monkeypatch.setattr(prover_service.framework.job_backend, "enqueue", fake_enqueue)

    client = TestClient(prover_service.app)
    response = client.post(
        "/v5/policy-runs",
        json={
            "policy_id": "lending_risk_v1",
            "evidence_ref": "memory://existing-evidence",
            "context": {"tenant": "acme"},
        },
        headers={"Authorization": "Bearer demo"},
    )

    assert response.status_code == 202
    assert calls["evidence_get"] == "memory://existing-evidence"
    assert calls["enqueue"]["task_name"] == "worker.process_proof_job"
    assert calls["create_proof_job"]["metadata"]["evidence_ref"] == "memory://existing-evidence"


@pytest.mark.integration
def test_v5_policy_run_unknown_policy_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    prover_service = _load_prover_service(monkeypatch)
    _patch_auth(monkeypatch, prover_service, required_scope="proofs:write")

    monkeypatch.setattr(
        prover_service.framework.policy_registry,
        "get_manifest",
        lambda _policy_id: (_ for _ in ()).throw(PolicyNotFoundError("missing")),
    )

    client = TestClient(prover_service.app)
    response = client.post(
        "/v5/policy-runs",
        json={
            "policy_id": "unknown_policy",
            "evidence_payload": {"balances": [120], "limits": [100]},
        },
        headers={"Authorization": "Bearer demo"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_policy"


@pytest.mark.integration
def test_v1_batch_submit_rejects_oversized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_SUBMIT_BODY_BYTES", "128")
    prover_service = _load_prover_service(monkeypatch)
    _patch_auth(monkeypatch, prover_service, required_scope="proofs:write")

    client = TestClient(prover_service.app)
    response = client.post(
        "/v1/proofs/batch",
        json={"balances": [1] * 200, "limits": [0] * 200},
        headers={"Authorization": "Bearer demo"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


@pytest.mark.integration
def test_v1_batch_submit_rejects_private_input_schema_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prover_service = _load_prover_service(monkeypatch)
    _patch_auth(monkeypatch, prover_service, required_scope="proofs:write")

    client = TestClient(prover_service.app)
    response = client.post(
        "/v1/proofs/batch",
        json={
            "circuit_id": "credit_check",
            "private_input": {"credit_score": -1, "debt_ratio": 10},
        },
        headers={"Authorization": "Bearer demo"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_private_input_schema"
