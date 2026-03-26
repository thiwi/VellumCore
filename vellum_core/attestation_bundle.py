"""Utilities for deterministic attestation bundle export payloads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Protocol


class ArtifactPathsLike(Protocol):
    """Minimal artifact path contract required for digest generation."""

    wasm_path: str
    zkey_path: str
    verification_key_path: str


class AuditRowLike(Protocol):
    """Minimal audit row contract used for signature-chain serialization."""

    id: int
    timestamp: Any
    status: str
    entry_hash: str
    signature: str
    key_version: str


def sha256_json(payload: Any) -> str:
    """Return stable SHA256 of JSON-serializable payload."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def sha256_file(path_value: str) -> str:
    """Return file SHA256 or empty string when file is missing."""
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_digests(paths: ArtifactPathsLike) -> dict[str, str]:
    """Compute standard artifact digest map for one circuit artifact bundle."""
    return {
        "wasm_sha256": sha256_file(paths.wasm_path),
        "zkey_sha256": sha256_file(paths.zkey_path),
        "verification_key_sha256": sha256_file(paths.verification_key_path),
    }


def signature_chain(rows: Iterable[AuditRowLike]) -> list[dict[str, Any]]:
    """Serialize persisted audit rows into transport-safe signature-chain entries."""
    return [
        {
            "audit_id": row.id,
            "timestamp": row.timestamp.isoformat(),
            "status": row.status,
            "entry_hash": row.entry_hash,
            "signature": row.signature,
            "key_version": row.key_version,
        }
        for row in rows
    ]
