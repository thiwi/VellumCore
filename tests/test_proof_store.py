"""Tests for Proof store."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vellum_core.proof_store import VellumAuditStore, VellumIntegrityService
from vellum_core.vault import VaultSignature

pytestmark = pytest.mark.security


@dataclass
class FakeAuditRow:
    id: int
    timestamp: datetime
    proof_id: str | None
    circuit_id: str
    status: str
    public_signals: list[Any]
    proof_hash: str
    previous_entry_hash: str
    entry_hash: str
    signature: str
    key_version: str
    meta: dict[str, Any]
    error: str | None


class FakeDatabase:
    def __init__(self) -> None:
        self.rows: list[FakeAuditRow] = []

    async def get_latest_audit_row(self) -> FakeAuditRow | None:
        return self.rows[-1] if self.rows else None

    async def append_audit_row(self, payload: dict[str, Any]) -> FakeAuditRow:
        row = FakeAuditRow(
            id=len(self.rows) + 1,
            timestamp=payload["timestamp"],
            proof_id=payload.get("proof_id"),
            circuit_id=payload["circuit_id"],
            status=payload["status"],
            public_signals=list(payload.get("public_signals", [])),
            proof_hash=payload.get("proof_hash", ""),
            previous_entry_hash=payload.get("previous_entry_hash", ""),
            entry_hash=payload["entry_hash"],
            signature=payload["signature"],
            key_version=payload.get("key_version", "1"),
            meta=dict(payload.get("meta", {})),
            error=payload.get("error"),
        )
        self.rows.append(row)
        return row

    async def list_audit_rows(self) -> list[FakeAuditRow]:
        return list(self.rows)


class FakeVaultClient:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self.private_key = private_key

    async def sign(self, key_name: str, payload: bytes) -> VaultSignature:
        _ = key_name
        sig = self.private_key.sign(payload)
        encoded = "vault:v1:" + base64.b64encode(sig).decode("utf-8")
        return VaultSignature(raw=sig, encoded=encoded, key_version="1")


class FakeKeyCache:
    def __init__(self, public_key_pem: str) -> None:
        self.public_key_pem = public_key_pem

    async def get_public_key(self, *, key_name: str, key_version: str | None = None) -> str:
        _ = (key_name, key_version)
        return self.public_key_pem


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _build_services() -> tuple[FakeDatabase, VellumAuditStore, VellumIntegrityService]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    db = FakeDatabase()
    store = VellumAuditStore(
        db=db,  # type: ignore[arg-type]
        vault=FakeVaultClient(private_key),  # type: ignore[arg-type]
        audit_key_name="vellum-audit",
    )
    integrity = VellumIntegrityService(
        db=db,  # type: ignore[arg-type]
        key_cache=FakeKeyCache(public_pem),  # type: ignore[arg-type]
        audit_key_name="vellum-audit",
    )
    return db, store, integrity


def test_audit_store_chain_and_signature_valid() -> None:
    db, store, integrity = _build_services()

    first = _run(
        store.append_event(
            proof_id="proof-1",
            circuit_id="batch_credit_check",
            status="queued",
            public_signals=[],
        )
    )
    second = _run(
        store.append_event(
            proof_id="proof-1",
            circuit_id="batch_credit_check",
            status="completed",
            public_signals=["1", "3"],
            proof_payload={"proof": "payload"},
        )
    )

    assert first["previous_entry_hash"] == ""
    assert second["previous_entry_hash"] == first["entry_hash"]
    assert len(db.rows) == 2

    report = _run(integrity.verify_chain())
    assert report["valid"] is True
    assert report["checked_entries"] == 2
    assert report["first_broken_index"] is None


def test_integrity_detects_payload_tampering() -> None:
    db, store, integrity = _build_services()

    _run(
        store.append_event(
            proof_id="proof-2",
            circuit_id="batch_credit_check",
            status="queued",
            public_signals=[],
        )
    )
    _run(
        store.append_event(
            proof_id="proof-2",
            circuit_id="batch_credit_check",
            status="completed",
            public_signals=["1", "2"],
            proof_payload={"proof": "payload"},
        )
    )

    db.rows[1].public_signals = ["999"]
    report = _run(integrity.verify_chain())
    assert report["valid"] is False
    assert report["first_broken_index"] == 1
    assert "hash" in str(report["reason"]).lower()


def test_integrity_detects_signature_tampering() -> None:
    db, store, integrity = _build_services()

    _run(
        store.append_event(
            proof_id="proof-3",
            circuit_id="batch_credit_check",
            status="completed",
            public_signals=["1"],
            proof_payload={"proof": "payload"},
            metadata={"at": datetime.now(timezone.utc).isoformat()},
        )
    )

    db.rows[0].signature = "vault:v1:" + base64.b64encode(b"bad-signature").decode("utf-8")
    report = _run(integrity.verify_chain())
    assert report["valid"] is False
    assert report["first_broken_index"] == 0
    assert "signature" in str(report["reason"]).lower()
