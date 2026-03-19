from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sentinel_zk.proof_store import ProofStore


def write_test_audit_keys(tmp_path: Path) -> tuple[Path, Path]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key()

    priv_path = tmp_path / "audit_private.pem"
    pub_path = tmp_path / "audit_public.pem"

    priv_path.write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_path.write_bytes(
        public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return priv_path, pub_path


def build_store(tmp_path: Path) -> ProofStore:
    store_file = tmp_path / "proof_audit.jsonl"
    priv, pub = write_test_audit_keys(tmp_path)
    return ProofStore(
        store_file,
        audit_private_key_path=priv,
        audit_public_key_path=pub,
    )


def test_proof_store_builds_hash_chain_and_signature(tmp_path: Path) -> None:
    store = build_store(tmp_path)

    first = store.append_event(
        proof_id="proof-1",
        circuit_id="credit_check",
        public_signals=["1"],
        status="queued",
    )
    second = store.append_event(
        proof_id="proof-1",
        circuit_id="credit_check",
        public_signals=["1"],
        status="completed",
        proof_payload={"a": 1},
    )

    assert first["previous_entry_hash"] == ""
    assert second["previous_entry_hash"] == first["entry_hash"]
    assert second["signature"]
    assert store.get_latest_event("proof-1")["status"] == "completed"

    report = store.verify_chain()
    assert report["valid"] is True
    assert report["checked_entries"] == 2


def test_verify_chain_detects_tampering(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    store.append_event(
        proof_id="proof-2",
        circuit_id="credit_check",
        public_signals=["1"],
        status="queued",
    )
    store.append_event(
        proof_id="proof-2",
        circuit_id="credit_check",
        public_signals=["2"],
        status="completed",
        proof_payload={"a": 2},
    )

    store_file = tmp_path / "proof_audit.jsonl"
    lines = store_file.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[1])
    payload["public_signals"] = ["999999"]  # tamper payload without re-signing
    lines[1] = json.dumps(payload, separators=(",", ":"))
    store_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = store.verify_chain()
    assert report["valid"] is False
    assert report["first_broken_index"] == 1
    assert "hash" in report["reason"].lower() or "signature" in report["reason"].lower()


def test_verify_chain_accepts_legacy_entries(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    store_file = tmp_path / "proof_audit.jsonl"

    legacy_1_payload = {
        "proof_id": "legacy-1",
        "created_at": "2026-03-19T10:00:00+00:00",
        "circuit_id": "credit_check",
        "public_signals": [],
        "status": "queued",
        "proof_path": None,
        "error": None,
        "metadata": {"request_id": "legacy"},
        "prev_hash": "",
    }
    legacy_1 = {
        **legacy_1_payload,
        "entry_hash": store._hash_record(legacy_1_payload),  # noqa: SLF001
    }

    legacy_2_payload = {
        "proof_id": "legacy-1",
        "created_at": "2026-03-19T10:00:01+00:00",
        "circuit_id": "credit_check",
        "public_signals": ["123"],
        "status": "completed",
        "proof_path": "/shared_assets/proofs/legacy-1.json",
        "error": None,
        "metadata": {},
        "prev_hash": legacy_1["entry_hash"],
    }
    legacy_2 = {
        **legacy_2_payload,
        "entry_hash": store._hash_record(legacy_2_payload),  # noqa: SLF001
    }

    store_file.write_text(
        "\n".join(
            [
                json.dumps(legacy_1, separators=(",", ":")),
                json.dumps(legacy_2, separators=(",", ":")),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store.append_event(
        proof_id="new-1",
        circuit_id="batch_credit_check",
        public_signals=["1", "1"],
        status="completed",
        proof_payload={"p": "v"},
    )

    report = store.verify_chain()
    assert report["valid"] is True
    assert report["checked_entries"] == 3
