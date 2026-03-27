"""Tests for dual-track policy execution helpers."""

from __future__ import annotations

import random

import pytest

from vellum_core.api.errors import FrameworkError
from vellum_core.policies.dual_track import (
    DualTrackCircuitResult,
    assert_dual_track_consistency,
    evaluate_circuit_track,
    prepare_reference_track,
)


DIFF_OUTPUTS = {
    "all_valid": {"signal_index": 0, "value_type": "bool"},
    "active_count_out": {"signal_index": 1, "value_type": "int"},
}


@pytest.mark.unit
def test_prepare_reference_track_rejects_non_integer_values() -> None:
    with pytest.raises(FrameworkError) as exc:
        prepare_reference_track(
            reference_policy="lending_risk_reference_v1",
            differential_outputs=DIFF_OUTPUTS,
            evidence_payload={"balances": [10.5], "limits": [10]},
        )
    assert exc.value.code == "invalid_evidence_payload"


@pytest.mark.unit
def test_dual_track_randomized_lending_risk_consistency() -> None:
    rng = random.Random(42)
    for _ in range(40):
        size = rng.randint(1, 12)
        balances = [rng.randint(0, 5_000) for _ in range(size)]
        limits = [rng.randint(0, 5_000) for _ in range(size)]

        reference = prepare_reference_track(
            reference_policy="lending_risk_reference_v1",
            differential_outputs=DIFF_OUTPUTS,
            evidence_payload={"balances": balances, "limits": limits},
        )
        circuit = evaluate_circuit_track(
            policy_id="lending_risk_v1",
            expected_attestation={"decision_signal_index": 0, "pass_signal_value": "1"},
            differential_outputs=DIFF_OUTPUTS,
            public_signals=[
                "1" if reference.outputs["all_valid"] else "0",
                str(reference.outputs["active_count_out"]),
            ],
            verified=True,
        )
        assert_dual_track_consistency(
            policy_id="lending_risk_v1",
            reference=reference,
            circuit=circuit,
        )


@pytest.mark.unit
def test_dual_track_mismatch_raises_framework_error() -> None:
    reference = prepare_reference_track(
        reference_policy="lending_risk_reference_v1",
        differential_outputs=DIFF_OUTPUTS,
        evidence_payload={"balances": [200], "limits": [100]},
    )
    mismatched = DualTrackCircuitResult(
        decision="pass",
        outputs={"all_valid": True, "active_count_out": 9},
    )
    with pytest.raises(FrameworkError) as exc:
        assert_dual_track_consistency(
            policy_id="lending_risk_v1",
            reference=reference,
            circuit=mismatched,
        )
    assert exc.value.code == "dual_track_mismatch"
