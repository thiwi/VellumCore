"""Signed audit-chain persistence and integrity verification utilities."""

from __future__ import annotations

import hashlib
import json
import base64
from datetime import datetime, timezone
from typing import Any, Protocol

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


class AuditRow(Protocol):
    """Shape required from persisted audit rows."""

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


class AuditStoreDB(Protocol):
    """Storage interface required by audit store and integrity checker."""

    async def get_latest_audit_row(self) -> AuditRow | None: ...
    async def append_audit_row(self, payload: dict[str, Any]) -> AuditRow: ...
    async def list_audit_rows(self) -> list[AuditRow]: ...


class VellumAuditStore:
    """Writes signed, hash-linked audit events."""

    def __init__(
        self,
        *,
        db: AuditStoreDB,
        vault: VaultTransitClient,
        audit_key_name: str,
    ) -> None:
        self.db = db
        self.vault = vault
        self.audit_key_name = audit_key_name

    async def append_event(
        self,
        *,
        proof_id: str | None,
        circuit_id: str,
        status: str,
        public_signals: list[Any],
        proof_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Append one event to audit chain with optimistic conflict retry."""
        metadata_payload = metadata or {}
        proof_hash = _compute_proof_hash(proof_payload)
        row = None
        last_conflict: Exception | None = None
        for _ in range(8):
            latest = await self.db.get_latest_audit_row()
            previous_entry_hash = latest.entry_hash if latest is not None else ""

            timestamp = datetime.now(timezone.utc).replace(microsecond=0)
            link_payload = {
                "timestamp": timestamp.isoformat(),
                "proof_id": proof_id,
                "circuit_id": circuit_id,
                "status": status,
                "public_signals": public_signals,
                "proof_hash": proof_hash,
                "previous_entry_hash": previous_entry_hash,
                "metadata": metadata_payload,
                "error": error,
            }
            entry_hash = _hash_record(link_payload)
            signature = await self.vault.sign(self.audit_key_name, entry_hash.encode("utf-8"))

            try:
                row = await self.db.append_audit_row(
                    {
                        "timestamp": timestamp,
                        "proof_id": proof_id,
                        "circuit_id": circuit_id,
                        "status": status,
                        "public_signals": public_signals,
                        "proof_hash": proof_hash,
                        "previous_entry_hash": previous_entry_hash,
                        "entry_hash": entry_hash,
                        "signature": signature.encoded,
                        "key_version": signature.key_version,
                        "meta": metadata_payload,
                        "error": error,
                    }
                )
                break
            except RuntimeError as exc:
                if "audit_chain_conflict" not in str(exc):
                    raise
                last_conflict = exc

        if row is None:
            raise RuntimeError("Failed to append audit event due to persistent chain conflicts") from last_conflict

        return {
            "id": row.id,
            "timestamp": row.timestamp.isoformat(),
            "proof_id": row.proof_id,
            "circuit_id": row.circuit_id,
            "status": row.status,
            "public_signals": row.public_signals,
            "proof_hash": row.proof_hash,
            "previous_entry_hash": row.previous_entry_hash,
            "entry_hash": row.entry_hash,
            "signature": row.signature,
            "key_version": row.key_version,
            "metadata": row.meta,
            "error": row.error,
        }


class VellumIntegrityService:
    """Verifies integrity of persisted audit chain."""

    def __init__(
        self,
        *,
        db: AuditStoreDB,
        key_cache: VaultPublicKeyCache,
        audit_key_name: str,
    ) -> None:
        self.db = db
        self.key_cache = key_cache
        self.audit_key_name = audit_key_name

    async def verify_chain(self) -> dict[str, Any]:
        """Validate hash links and signatures for full audit log."""
        rows = await self.db.list_audit_rows()
        previous_entry_hash = ""

        for idx, row in enumerate(rows):
            if row.previous_entry_hash != previous_entry_hash:
                return _invalid_chain(
                    checked_entries=idx + 1,
                    first_broken_index=idx,
                    reason="Broken previous_entry_hash link",
                )

            payload = {
                "timestamp": row.timestamp.replace(microsecond=0).isoformat(),
                "proof_id": row.proof_id,
                "circuit_id": row.circuit_id,
                "status": row.status,
                "public_signals": row.public_signals,
                "proof_hash": row.proof_hash,
                "previous_entry_hash": row.previous_entry_hash,
                "metadata": row.meta,
                "error": row.error,
            }
            expected_hash = _hash_record(payload)
            if expected_hash != row.entry_hash:
                return _invalid_chain(
                    checked_entries=idx + 1,
                    first_broken_index=idx,
                    reason="Entry hash mismatch",
                )

            signature_raw, key_version = VaultTransitClient.decode_signature(row.signature)
            resolved_version = row.key_version or key_version
            public_key_pem = await self.key_cache.get_public_key(
                key_name=self.audit_key_name,
                key_version=resolved_version,
            )
            if not _verify_ed25519_signature(public_key_pem, row.entry_hash.encode("utf-8"), signature_raw):
                return _invalid_chain(
                    checked_entries=idx + 1,
                    first_broken_index=idx,
                    reason="Invalid signature",
                )

            previous_entry_hash = row.entry_hash

        return {
            "valid": True,
            "checked_entries": len(rows),
            "first_broken_index": None,
            "reason": None,
        }


def _invalid_chain(*, checked_entries: int, first_broken_index: int, reason: str) -> dict[str, Any]:
    """Build standardized invalid-chain report payload."""
    return {
        "valid": False,
        "checked_entries": checked_entries,
        "first_broken_index": first_broken_index,
        "reason": reason,
    }


def _hash_record(record: dict[str, Any]) -> str:
    """Hash one canonicalized JSON record with SHA-256."""
    serialized = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _compute_proof_hash(proof_payload: dict[str, Any] | None) -> str:
    """Compute deterministic proof payload hash used in audit entries."""
    if proof_payload is None:
        return ""
    serialized = json.dumps(proof_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _verify_ed25519_signature(public_key_pem: str, payload: bytes, signature: bytes) -> bool:
    """Verify Ed25519 signature against payload bytes."""
    try:
        key = _load_ed25519_public_key(public_key_pem)
        key.verify(signature, payload)
        return True
    except Exception:
        return False


def _load_ed25519_public_key(public_key_value: str) -> Ed25519PublicKey:
    """Load Ed25519 public key from PEM or raw base64 format."""
    try:
        key = load_pem_public_key(public_key_value.encode("utf-8"))
        if isinstance(key, Ed25519PublicKey):
            return key
    except Exception:
        pass

    raw = base64.b64decode(public_key_value)
    return Ed25519PublicKey.from_public_bytes(raw)
