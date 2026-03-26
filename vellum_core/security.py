"""Security helpers for payload sealing, input hashing, and event telemetry."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from vellum_core.database import Database
from vellum_core.metrics import observe_security_event
from vellum_core.vault import VaultTransitClient


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic JSON encoding used by hash and sealing helpers."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_input_fingerprint(*, source_mode: str, payload: dict[str, Any]) -> str:
    """Build deterministic SHA-256 fingerprint for sensitive request input."""
    if source_mode == "private_input":
        material: Any = payload.get("private_input")
    elif source_mode == "policy_run":
        material = {
            "policy_id": payload.get("policy_id"),
            "evidence_payload": payload.get("evidence_payload"),
            "evidence_ref": payload.get("evidence_ref"),
        }
    else:
        material = {
            "balances": payload.get("balances"),
            "limits": payload.get("limits"),
            "circuit_id": payload.get("circuit_id"),
        }
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def build_input_summary(*, source_mode: str, payload: dict[str, Any], circuit_id: str) -> dict[str, Any]:
    """Produce non-sensitive metadata describing input shape only."""
    summary: dict[str, Any] = {
        "source_mode": source_mode,
        "circuit_id": circuit_id,
    }
    if source_mode == "direct":
        balances = payload.get("balances")
        summary["batch_size"] = len(balances) if isinstance(balances, list) else None
    if source_mode == "private_input":
        private_input = payload.get("private_input")
        if isinstance(private_input, dict):
            summary["private_input_keys"] = sorted(str(k) for k in private_input.keys())[:25]
    if source_mode == "policy_run":
        summary["policy_id"] = payload.get("policy_id")
        evidence_payload = payload.get("evidence_payload")
        if isinstance(evidence_payload, dict):
            summary["evidence_keys"] = sorted(str(k) for k in evidence_payload.keys())[:25]
        summary["has_evidence_ref"] = bool(payload.get("evidence_ref"))
    return summary


async def seal_job_payload(
    *,
    vault_client: VaultTransitClient,
    key_name: str,
    request_payload: dict[str, Any],
    private_input: dict[str, Any] | None,
) -> str:
    """Encrypt sensitive request payload material for DB persistence."""
    plaintext = canonical_json_bytes(
        {
            "request_payload": request_payload,
            "private_input": private_input,
        }
    )
    return await vault_client.encrypt(key_name, plaintext)


async def unseal_job_payload(
    *,
    vault_client: VaultTransitClient,
    key_name: str,
    sealed_payload: str,
) -> dict[str, Any]:
    """Decrypt and parse sealed payload row into original request components."""
    plaintext = await vault_client.decrypt(key_name, sealed_payload)
    return json.loads(plaintext.decode("utf-8"))


class SecurityEventLogger:
    """Persistent and metric-backed security event sink."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(
        self,
        *,
        event_type: str,
        outcome: str,
        actor: str | None = None,
        source_ip: str | None = None,
        proof_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        observe_security_event(event_type, outcome)
        try:
            await self.db.append_security_event(
                event_type=event_type,
                outcome=outcome,
                actor=actor,
                source_ip=source_ip,
                proof_id=proof_id,
                details=_safe_details(details),
            )
        except Exception:
            # Metric already captured. Persistence failures should not break request handling.
            return


def _safe_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in {"token", "authorization", "private_input", "request_payload"}:
            continue
        sanitized[str(key)] = value
    return sanitized
