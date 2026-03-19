from __future__ import annotations

import base64
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class ProofStore:
    def __init__(
        self, store_file: Path, *, audit_private_key_path: Path, audit_public_key_path: Path
    ) -> None:
        self.store_file = store_file
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.store_file.touch(exist_ok=True)

        self.audit_private_key = self._load_private_key(audit_private_key_path)
        self.audit_public_key = self._load_public_key(audit_public_key_path)

    def append_event(
        self,
        *,
        proof_id: str,
        circuit_id: str,
        public_signals: list[Any],
        status: str,
        proof_path: str | None = None,
        proof_payload: dict[str, Any] | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        timestamp = now.isoformat()
        proof_hash = self._compute_proof_hash(proof_payload)

        with self._exclusive_file() as handle:
            previous_entry_hash = self._read_last_entry_hash(handle)

            link_payload: dict[str, Any] = {
                "schema_version": 2,
                "proof_id": proof_id,
                "timestamp": timestamp,
                "created_at": timestamp,
                "circuit_id": circuit_id,
                "public_signals": public_signals,
                "status": status,
                "proof_path": proof_path,
                "proof_hash": proof_hash,
                "previous_entry_hash": previous_entry_hash,
                "error": error,
                "metadata": metadata or {},
            }
            entry_hash = self._hash_record(link_payload)
            signature = self._sign_entry_hash(entry_hash)
            record = {
                **link_payload,
                "entry_hash": entry_hash,
                "signature": signature,
            }

            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return record

    def get_latest_event(self, proof_id: str) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        with self.store_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = line.strip()
                if not row:
                    continue
                payload = json.loads(row)
                if payload.get("proof_id") == proof_id:
                    latest = payload
        return latest

    def verify_chain(self) -> dict[str, Any]:
        previous_entry_hash = ""
        checked = 0

        with self.store_file.open("r", encoding="utf-8") as handle:
            for idx, line in enumerate(handle):
                row = line.strip()
                if not row:
                    continue
                checked += 1
                try:
                    record = json.loads(row)
                except json.JSONDecodeError:
                    return self._invalid_chain(
                        checked_entries=checked,
                        first_broken_index=idx,
                        reason="Invalid JSON entry",
                    )

                if "previous_entry_hash" in record or record.get("schema_version") == 2:
                    verify_result = self._verify_signed_entry(
                        record=record,
                        previous_entry_hash=previous_entry_hash,
                        checked_entries=checked,
                        index=idx,
                    )
                else:
                    verify_result = self._verify_legacy_entry(
                        record=record,
                        previous_entry_hash=previous_entry_hash,
                        checked_entries=checked,
                        index=idx,
                    )

                if not verify_result["valid"]:
                    return verify_result
                previous_entry_hash = verify_result["entry_hash"]

        return {
            "valid": True,
            "checked_entries": checked,
            "first_broken_index": None,
            "reason": None,
        }

    def _verify_signed_entry(
        self,
        *,
        record: dict[str, Any],
        previous_entry_hash: str,
        checked_entries: int,
        index: int,
    ) -> dict[str, Any]:
        if record.get("previous_entry_hash", "") != previous_entry_hash:
            return self._invalid_chain(
                checked_entries=checked_entries,
                first_broken_index=index,
                reason="Broken previous_entry_hash link",
            )

        signature_b64 = record.get("signature")
        entry_hash = record.get("entry_hash")
        if not isinstance(signature_b64, str) or not isinstance(entry_hash, str):
            return self._invalid_chain(
                checked_entries=checked_entries,
                first_broken_index=index,
                reason="Missing signature or entry_hash",
            )

        link_payload = {
            key: record.get(key)
            for key in (
                "schema_version",
                "proof_id",
                "timestamp",
                "created_at",
                "circuit_id",
                "public_signals",
                "status",
                "proof_path",
                "proof_hash",
                "previous_entry_hash",
                "error",
                "metadata",
            )
        }
        expected_hash = self._hash_record(link_payload)
        if expected_hash != entry_hash:
            return self._invalid_chain(
                checked_entries=checked_entries,
                first_broken_index=index,
                reason="Entry hash mismatch",
            )

        if not self._verify_signature(entry_hash, signature_b64):
            return self._invalid_chain(
                checked_entries=checked_entries,
                first_broken_index=index,
                reason="Invalid signature",
            )

        return {"valid": True, "entry_hash": entry_hash}

    def _verify_legacy_entry(
        self,
        *,
        record: dict[str, Any],
        previous_entry_hash: str,
        checked_entries: int,
        index: int,
    ) -> dict[str, Any]:
        if record.get("prev_hash", "") != previous_entry_hash:
            return self._invalid_chain(
                checked_entries=checked_entries,
                first_broken_index=index,
                reason="Broken legacy prev_hash link",
            )

        entry_hash = record.get("entry_hash")
        if not isinstance(entry_hash, str):
            return self._invalid_chain(
                checked_entries=checked_entries,
                first_broken_index=index,
                reason="Missing legacy entry_hash",
            )

        legacy_payload = {
            key: record.get(key)
            for key in (
                "proof_id",
                "created_at",
                "circuit_id",
                "public_signals",
                "status",
                "proof_path",
                "error",
                "metadata",
                "prev_hash",
            )
        }
        expected_hash = self._hash_record(legacy_payload)
        if expected_hash != entry_hash:
            return self._invalid_chain(
                checked_entries=checked_entries,
                first_broken_index=index,
                reason="Legacy entry hash mismatch",
            )

        return {"valid": True, "entry_hash": entry_hash}

    @staticmethod
    def _invalid_chain(
        *, checked_entries: int, first_broken_index: int, reason: str
    ) -> dict[str, Any]:
        return {
            "valid": False,
            "checked_entries": checked_entries,
            "first_broken_index": first_broken_index,
            "reason": reason,
        }

    @staticmethod
    def _compute_proof_hash(proof_payload: dict[str, Any] | None) -> str:
        if proof_payload is None:
            return ""
        serialized = json.dumps(proof_payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _read_last_entry_hash(self, handle: Any) -> str:
        handle.seek(0)
        last_hash = ""
        for line in handle:
            row = line.strip()
            if not row:
                continue
            payload = json.loads(row)
            last_hash = payload.get("entry_hash", "")
        return last_hash

    @staticmethod
    def _hash_record(record: dict[str, Any]) -> str:
        serialized = json.dumps(record, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _sign_entry_hash(self, entry_hash: str) -> str:
        signature = self.audit_private_key.sign(entry_hash.encode("utf-8"))
        return base64.b64encode(signature).decode("utf-8")

    def _verify_signature(self, entry_hash: str, signature_b64: str) -> bool:
        try:
            signature = base64.b64decode(signature_b64)
            self.audit_public_key.verify(signature, entry_hash.encode("utf-8"))
            return True
        except Exception:
            return False

    @staticmethod
    def _load_private_key(path: Path) -> Ed25519PrivateKey:
        raw = path.read_bytes()
        key = load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("audit private key must be Ed25519")
        return key

    @staticmethod
    def _load_public_key(path: Path) -> Ed25519PublicKey:
        raw = path.read_bytes()
        key = load_pem_public_key(raw)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("audit public key must be Ed25519")
        return key

    @contextmanager
    def _exclusive_file(self) -> Iterator[Any]:
        with self.store_file.open("r+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
