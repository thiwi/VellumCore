"""Dual-track policy execution helpers (reference track + circuit track)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vellum_core.api.errors import framework_error
from vellum_core.policies.base import PolicyDecision
from vellum_core.policies.registry import get_reference_policy


@dataclass(frozen=True)
class DualTrackReferenceResult:
    """Prepared reference-track outputs used before and after proving."""

    private_input: dict[str, Any]
    decision: PolicyDecision
    outputs: dict[str, Any]


@dataclass(frozen=True)
class DualTrackCircuitResult:
    """Circuit-track output projection used for differential checks."""

    decision: PolicyDecision
    outputs: dict[str, Any]


def prepare_reference_track(
    *,
    reference_policy: str,
    differential_outputs: dict[str, Any],
    evidence_payload: dict[str, Any],
) -> DualTrackReferenceResult:
    """Prepare canonical private input and expected outputs from reference track."""
    policy = get_reference_policy(reference_policy)
    policy.validate(evidence_payload)
    normalized = policy.normalize(evidence_payload)
    decision = policy.evaluate_reference(normalized)
    projected_outputs = policy.project_public_outputs(normalized)

    normalized_outputs: dict[str, Any] = {}
    for output_name, output_spec in differential_outputs.items():
        if output_name not in projected_outputs:
            raise framework_error(
                "policy_manifest_invalid",
                "Differential output missing in reference policy projection",
                reference_policy=reference_policy,
                output_name=output_name,
            )
        value_type = str(_spec_value(output_spec, "value_type"))
        normalized_outputs[output_name] = _normalize_reference_value(
            output_name=output_name,
            value=projected_outputs[output_name],
            value_type=value_type,
        )

    return DualTrackReferenceResult(
        private_input=policy.to_private_input(normalized),
        decision=decision,
        outputs=normalized_outputs,
    )


def evaluate_circuit_track(
    *,
    policy_id: str,
    expected_attestation: dict[str, Any],
    differential_outputs: dict[str, Any],
    public_signals: list[Any],
    verified: bool,
) -> DualTrackCircuitResult:
    """Project decision and configured outputs from circuit public signals."""
    if not verified:
        decision: PolicyDecision = "fail"
    else:
        signal_index = int(expected_attestation.get("decision_signal_index", 0))
        pass_signal_value = str(expected_attestation.get("pass_signal_value", "1"))
        decision_signal = _signal_at(
            policy_id=policy_id,
            output_name="decision",
            signal_index=signal_index,
            public_signals=public_signals,
        )
        decision = "pass" if str(decision_signal) == pass_signal_value else "fail"

    outputs: dict[str, Any] = {}
    for output_name, output_spec in differential_outputs.items():
        signal_index = int(_spec_value(output_spec, "signal_index"))
        value_type = str(_spec_value(output_spec, "value_type"))
        raw_value = _signal_at(
            policy_id=policy_id,
            output_name=output_name,
            signal_index=signal_index,
            public_signals=public_signals,
        )
        outputs[output_name] = _normalize_signal_value(
            output_name=output_name,
            signal_value=raw_value,
            value_type=value_type,
        )

    return DualTrackCircuitResult(decision=decision, outputs=outputs)


def assert_dual_track_consistency(
    *,
    policy_id: str,
    reference: DualTrackReferenceResult,
    circuit: DualTrackCircuitResult,
) -> None:
    """Raise FrameworkError when reference-track and circuit-track diverge."""
    if reference.decision != circuit.decision or reference.outputs != circuit.outputs:
        raise framework_error(
            "dual_track_mismatch",
            "Reference-track and circuit-track results diverged",
            policy_id=policy_id,
            reference_decision=reference.decision,
            circuit_decision=circuit.decision,
            reference_outputs=reference.outputs,
            circuit_outputs=circuit.outputs,
        )


def _signal_at(
    *,
    policy_id: str,
    output_name: str,
    signal_index: int,
    public_signals: list[Any],
) -> Any:
    if signal_index < 0 or signal_index >= len(public_signals):
        raise framework_error(
            "dual_track_mismatch",
            "Circuit output signal index out of range",
            policy_id=policy_id,
            output_name=output_name,
            signal_index=signal_index,
            available_signals=len(public_signals),
        )
    return public_signals[signal_index]


def _normalize_signal_value(
    *,
    output_name: str,
    signal_value: Any,
    value_type: str,
) -> Any:
    if value_type == "int":
        if isinstance(signal_value, bool):
            raise framework_error(
                "dual_track_mismatch",
                "Signal type mismatch, expected int",
                output_name=output_name,
                value_type=value_type,
                signal_value=signal_value,
            )
        try:
            return int(str(signal_value))
        except ValueError as exc:
            raise framework_error(
                "dual_track_mismatch",
                "Signal value cannot be parsed as int",
                output_name=output_name,
                value_type=value_type,
                signal_value=signal_value,
            ) from exc
    if value_type == "bool":
        normalized = str(signal_value).strip()
        if normalized in {"1", "true", "True"}:
            return True
        if normalized in {"0", "false", "False"}:
            return False
        raise framework_error(
            "dual_track_mismatch",
            "Signal value cannot be parsed as bool",
            output_name=output_name,
            value_type=value_type,
            signal_value=signal_value,
        )
    if value_type == "string":
        return str(signal_value)
    raise framework_error(
        "policy_manifest_invalid",
        "Unsupported differential output value_type",
        output_name=output_name,
        value_type=value_type,
    )


def _normalize_reference_value(*, output_name: str, value: Any, value_type: str) -> Any:
    if value_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise framework_error(
                "policy_manifest_invalid",
                "Reference output type mismatch, expected int",
                output_name=output_name,
                value_type=value_type,
                reference_value=value,
            )
        return value
    if value_type == "bool":
        if not isinstance(value, bool):
            raise framework_error(
                "policy_manifest_invalid",
                "Reference output type mismatch, expected bool",
                output_name=output_name,
                value_type=value_type,
                reference_value=value,
            )
        return value
    if value_type == "string":
        if not isinstance(value, str):
            raise framework_error(
                "policy_manifest_invalid",
                "Reference output type mismatch, expected string",
                output_name=output_name,
                value_type=value_type,
                reference_value=value,
            )
        return value
    raise framework_error(
        "policy_manifest_invalid",
        "Unsupported differential output value_type",
        output_name=output_name,
        value_type=value_type,
    )


def _spec_value(output_spec: Any, field: str) -> Any:
    if isinstance(output_spec, dict):
        return output_spec.get(field)
    return getattr(output_spec, field)
