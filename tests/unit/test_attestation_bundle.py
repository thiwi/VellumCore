"""Tests for Attestation bundle."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from vellum_core.attestation_bundle import (
    artifact_digests,
    sha256_file,
    sha256_json,
    signature_chain,
)

pytestmark = pytest.mark.security


def test_sha256_json_is_stable_for_key_order() -> None:
    digest_a = sha256_json({"b": 2, "a": 1})
    digest_b = sha256_json({"a": 1, "b": 2})
    assert digest_a == digest_b


def test_sha256_file_returns_empty_for_missing_file(tmp_path) -> None:
    missing = tmp_path / "missing.txt"
    assert sha256_file(str(missing)) == ""


def test_artifact_digests_returns_expected_hashes(tmp_path) -> None:
    wasm = tmp_path / "demo.wasm"
    zkey = tmp_path / "final.zkey"
    vk = tmp_path / "verification_key.json"
    wasm.write_text("wasm", encoding="utf-8")
    zkey.write_text("zkey", encoding="utf-8")
    vk.write_text("vk", encoding="utf-8")

    digests = artifact_digests(
        SimpleNamespace(
            wasm_path=str(wasm),
            zkey_path=str(zkey),
            verification_key_path=str(vk),
        )
    )

    assert digests["wasm_sha256"] == hashlib.sha256(b"wasm").hexdigest()
    assert digests["zkey_sha256"] == hashlib.sha256(b"zkey").hexdigest()
    assert digests["verification_key_sha256"] == hashlib.sha256(b"vk").hexdigest()


def test_signature_chain_serializes_audit_rows() -> None:
    rows = [
        SimpleNamespace(
            id=1,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="completed",
            entry_hash="entry-hash",
            signature="vault:v1:sig",
            key_version="1",
        )
    ]

    chain = signature_chain(rows)
    assert chain == [
        {
            "audit_id": 1,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "status": "completed",
            "entry_hash": "entry-hash",
            "signature": "vault:v1:sig",
            "key_version": "1",
        }
    ]
