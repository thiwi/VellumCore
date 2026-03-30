"""Tests for Security helpers."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from vellum_core.security import (
    SecurityEventLogger,
    build_input_summary,
    canonical_json_bytes,
    compute_input_fingerprint,
    seal_job_payload,
    unseal_job_payload,
)


class _FakeVault:
    async def encrypt(self, key_name: str, plaintext: bytes) -> str:
        _ = key_name
        return f"vault:v1:{base64.b64encode(plaintext).decode('utf-8')}"

    async def decrypt(self, key_name: str, ciphertext: str) -> bytes:
        _ = key_name
        payload = ciphertext.split(":", 2)[2]
        return base64.b64decode(payload)


class _FakeDB:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def append_security_event(
        self,
        *,
        event_type: str,
        outcome: str,
        actor: str | None = None,
        source_ip: str | None = None,
        proof_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "event_type": event_type,
            "outcome": outcome,
            "actor": actor,
            "source_ip": source_ip,
            "proof_id": proof_id,
            "details": details or {},
        }
        self.rows.append(row)
        return row


def test_canonical_json_bytes_is_stable() -> None:
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'


def test_compute_input_fingerprint_changes_by_mode_and_payload() -> None:
    direct_a = compute_input_fingerprint(
        source_mode="direct",
        payload={"circuit_id": "batch_credit_check", "balances": [1], "limits": [0]},
    )
    direct_b = compute_input_fingerprint(
        source_mode="direct",
        payload={"circuit_id": "batch_credit_check", "balances": [2], "limits": [0]},
    )
    private_a = compute_input_fingerprint(
        source_mode="private_input",
        payload={"private_input": {"x": 1}},
    )
    assert direct_a != direct_b
    assert direct_a != private_a


def test_build_input_summary_for_modes() -> None:
    direct = build_input_summary(
        source_mode="direct",
        payload={"balances": [1, 2, 3]},
        circuit_id="batch_credit_check",
    )
    private = build_input_summary(
        source_mode="private_input",
        payload={"private_input": {"a": 1, "b": 2}},
        circuit_id="credit_check",
    )
    assert direct["batch_size"] == 3
    assert private["private_input_keys"] == ["a", "b"]


def test_policy_run_summary_and_fingerprint_use_v6_evidence_shape() -> None:
    payload = {
        "policy_id": "lending_risk_v1",
        "evidence": {
            "type": "inline",
            "payload": {"balances": [10], "limits": [5]},
        },
    }
    summary = build_input_summary(
        source_mode="policy_run",
        payload=payload,
        circuit_id="batch_credit_check",
    )
    assert summary["policy_id"] == "lending_risk_v1"
    assert summary["evidence_type"] == "inline"
    assert summary["evidence_keys"] == ["balances", "limits"]
    assert summary["has_evidence_ref"] is False

    fingerprint = compute_input_fingerprint(source_mode="policy_run", payload=payload)
    assert isinstance(fingerprint, str)
    assert len(fingerprint) == 64


def test_seal_and_unseal_job_payload_roundtrip() -> None:
    vault = _FakeVault()
    sealed = asyncio.run(
        seal_job_payload(
            vault_client=vault,  # type: ignore[arg-type]
            key_name="vellum-data",
            request_payload={"circuit_id": "batch_credit_check"},
            private_input={"balances": [1], "limits": [0], "active_count": 1},
        )
    )
    unsealed = asyncio.run(
        unseal_job_payload(
            vault_client=vault,  # type: ignore[arg-type]
            key_name="vellum-data",
            sealed_payload=sealed,
        )
    )
    assert unsealed["request_payload"]["circuit_id"] == "batch_credit_check"
    assert unsealed["private_input"]["active_count"] == 1


def test_security_event_logger_sanitizes_sensitive_details() -> None:
    fake_db = _FakeDB()
    logger = SecurityEventLogger(fake_db)  # type: ignore[arg-type]
    asyncio.run(
        logger.record(
            event_type="jwt_invalid",
            outcome="denied",
            actor="alice",
            details={
                "reason": "bad-signature",
                "token": "secret",
                "private_input": {"x": 1},
                "request_payload": {"x": 2},
            },
        )
    )
    row = fake_db.rows[0]
    assert row["actor"] == "alice"
    assert row["details"] == {"reason": "bad-signature"}
