"""Compatibility shims for legacy policy runtime helpers."""

from __future__ import annotations

from typing import Any, Literal

from vellum_core.api.errors import framework_error
from vellum_core.policies.dual_track import evaluate_circuit_track, prepare_reference_track


_REFERENCE_POLICY_BY_POLICY_ID: dict[str, str] = {
    "lending_risk_v1": "lending_risk_reference_v1",
}

_DEFAULT_DIFFERENTIAL_OUTPUTS: dict[str, dict[str, dict[str, object]]] = {
    "lending_risk_v1": {
        "all_valid": {"signal_index": 0, "value_type": "bool"},
        "active_count_out": {"signal_index": 1, "value_type": "int"},
    }
}


def private_input_for_policy(*, policy_id: str, evidence_payload: dict[str, Any]) -> dict[str, Any]:
    """Map evidence payloads to proving private_input for one policy."""
    reference_policy = _REFERENCE_POLICY_BY_POLICY_ID.get(policy_id)
    differential_outputs = _DEFAULT_DIFFERENTIAL_OUTPUTS.get(policy_id)
    if reference_policy is None or differential_outputs is None:
        raise framework_error(
            "unsupported_policy_input",
            "No policy input mapper defined",
            policy_id=policy_id,
        )
    prepared = prepare_reference_track(
        reference_policy=reference_policy,
        differential_outputs=differential_outputs,
        evidence_payload=evidence_payload,
    )
    return prepared.private_input


def decision_for_policy(
    *,
    policy_id: str,
    public_signals: list[Any],
    verified: bool,
    expected_attestation: dict[str, Any],
) -> Literal["pass", "fail"]:
    """Evaluate compliance decision using policy manifest and verify status."""
    differential_outputs = _DEFAULT_DIFFERENTIAL_OUTPUTS.get(policy_id)
    if differential_outputs is None:
        return "fail"
    circuit_result = evaluate_circuit_track(
        policy_id=policy_id,
        expected_attestation=expected_attestation,
        differential_outputs=differential_outputs,
        public_signals=public_signals,
        verified=verified,
    )
    return circuit_result.decision
