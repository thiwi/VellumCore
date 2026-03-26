"""Shared policy runtime helpers used by SDK and reference services."""

from __future__ import annotations

from typing import Any, Literal

from vellum_core.api.errors import framework_error
from vellum_core.logic.batcher import batch_prepare_input


def private_input_for_policy(*, policy_id: str, evidence_payload: dict[str, Any]) -> dict[str, Any]:
    """Map evidence payloads to proving private_input for one policy."""
    private_input = evidence_payload.get("private_input")
    if isinstance(private_input, dict):
        return private_input

    if policy_id == "lending_risk_v1":
        balances = evidence_payload.get("balances")
        limits = evidence_payload.get("limits")
        if not isinstance(balances, list) or not isinstance(limits, list):
            raise framework_error(
                "invalid_evidence_payload",
                "lending_risk_v1 requires balances and limits arrays",
            )
        try:
            prepared = batch_prepare_input(balances=balances, limits=limits)
        except ValueError as exc:
            raise framework_error(
                "invalid_evidence_payload",
                "Evidence payload failed batch validation",
                reason=str(exc),
            ) from exc
        return prepared.to_circuit_input()

    raise framework_error(
        "unsupported_policy_input",
        "No policy input mapper defined",
        policy_id=policy_id,
    )


def decision_for_policy(
    *,
    policy_id: str,
    public_signals: list[Any],
    verified: bool,
    expected_attestation: dict[str, Any],
) -> Literal["pass", "fail"]:
    """Evaluate compliance decision using policy manifest and verify status."""
    if not verified:
        return "fail"

    pass_signal_value = str(expected_attestation.get("pass_signal_value", "1"))
    signal_index = int(expected_attestation.get("decision_signal_index", 0))

    if signal_index < 0 or signal_index >= len(public_signals):
        return "fail"

    signal_value = str(public_signals[signal_index])
    if signal_value == pass_signal_value:
        return "pass"
    if policy_id == "lending_risk_v1":
        return "pass" if signal_value in {"1", "true", "True"} else "fail"
    return "fail"
