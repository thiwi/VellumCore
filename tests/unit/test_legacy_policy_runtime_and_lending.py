"""Coverage tests for legacy policy runtime shim and lending reference policies."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vellum_core.api.errors import FrameworkError
from vellum_core import policy_runtime
from vellum_core.policies.generated.lending_risk_reference_v1 import GeneratedReferencePolicy
from vellum_core.policies.lending_risk import LendingRiskReferencePolicy, as_reference_policy


@pytest.mark.unit
def test_private_input_for_policy_unsupported_policy_raises() -> None:
    with pytest.raises(FrameworkError) as exc:
        policy_runtime.private_input_for_policy(
            policy_id="unknown_policy",
            evidence_payload={"balances": [1], "limits": [0]},
        )
    assert exc.value.code == "unsupported_policy_input"


@pytest.mark.unit
def test_private_input_for_policy_delegates_to_prepare_reference_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_prepare_reference_track(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(private_input={"balances": [10], "limits": [5], "active_count": 1})

    monkeypatch.setattr(policy_runtime, "prepare_reference_track", _fake_prepare_reference_track)

    out = policy_runtime.private_input_for_policy(
        policy_id="lending_risk_v1",
        evidence_payload={"balances": [10], "limits": [5]},
    )
    assert out == {"balances": [10], "limits": [5], "active_count": 1}
    assert captured["reference_policy"] == "lending_risk_reference_v1"
    assert isinstance(captured["differential_outputs"], dict)


@pytest.mark.unit
def test_decision_for_policy_uses_circuit_track_and_fails_for_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        policy_runtime.decision_for_policy(
            policy_id="missing",
            public_signals=["1"],
            verified=True,
            expected_attestation={"decision_signal_index": 0, "pass_signal_value": "1"},
        )
        == "fail"
    )

    monkeypatch.setattr(
        policy_runtime,
        "evaluate_circuit_track",
        lambda **_: SimpleNamespace(decision="pass"),
    )
    assert (
        policy_runtime.decision_for_policy(
            policy_id="lending_risk_v1",
            public_signals=["1"],
            verified=True,
            expected_attestation={"decision_signal_index": 0, "pass_signal_value": "1"},
        )
        == "pass"
    )


@pytest.mark.unit
def test_lending_risk_reference_policy_paths() -> None:
    policy = LendingRiskReferencePolicy()
    normalized = policy.normalize({"balances": [120, 230], "limits": [100, 200]})
    assert normalized["active_count"] == 2
    assert len(normalized["balances"]) == 250
    assert len(normalized["limits"]) == 250
    assert policy.evaluate_reference(normalized) == "pass"
    assert policy.project_public_outputs(normalized) == {
        "all_valid": True,
        "active_count_out": 2,
    }
    assert policy.to_private_input(normalized)["active_count"] == 2


@pytest.mark.unit
def test_lending_risk_reference_policy_private_input_and_error_paths() -> None:
    policy = LendingRiskReferencePolicy()
    valid_private = {
        "private_input": {
            "balances": [10] + [0] * 249,
            "limits": [9] + [0] * 249,
            "active_count": 1,
        }
    }
    normalized = policy.normalize(valid_private)
    assert normalized["active_count"] == 1

    with pytest.raises(FrameworkError) as exc_private:
        policy.normalize({"private_input": {"balances": [], "limits": [], "active_count": 0}})
    assert exc_private.value.code == "invalid_evidence_payload"

    with pytest.raises(FrameworkError) as exc_batch:
        policy.normalize({"balances": [], "limits": []})
    assert exc_batch.value.code == "invalid_evidence_payload"


@pytest.mark.unit
def test_generated_reference_policy_paths_and_error_branches() -> None:
    policy = GeneratedReferencePolicy()
    normalized = policy.normalize({"balances": [200, 310], "limits": [100, 300]})
    assert policy.evaluate_reference(normalized) == "pass"
    assert policy.project_public_outputs(normalized)["all_valid"] is True

    normalized_fail = policy.normalize({"balances": [90], "limits": [100]})
    assert policy.evaluate_reference(normalized_fail) == "fail"
    assert policy.project_public_outputs(normalized_fail)["all_valid"] is False
    policy.validate({"balances": [150], "limits": [100]})

    with pytest.raises(FrameworkError) as exc_private:
        policy.normalize({"private_input": {"balances": [], "limits": [], "active_count": 0}})
    assert exc_private.value.code == "invalid_evidence_payload"

    with pytest.raises(FrameworkError) as exc_batch:
        policy.normalize({"balances": [], "limits": []})
    assert exc_batch.value.code == "invalid_evidence_payload"


@pytest.mark.unit
def test_as_reference_policy_is_identity() -> None:
    policy = LendingRiskReferencePolicy()
    assert as_reference_policy(policy) is policy
