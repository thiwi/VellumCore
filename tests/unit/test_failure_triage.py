"""Tests for deterministic failure triage classification."""

from __future__ import annotations

import pytest

from vellum_core.logic.failure_triage import classify_failure


@pytest.mark.unit
def test_classify_timeout_as_retryable() -> None:
    triage = classify_failure(
        failure_reason="soft_time_limit_exceeded",
        error_message="proof job exceeded celery soft time limit",
    )
    assert triage.error_class == "timeout"
    assert triage.retryable is True


@pytest.mark.unit
def test_classify_artifact_failure() -> None:
    triage = classify_failure(
        failure_reason="runtime_exception",
        error_message="Required circuit artifacts are missing",
    )
    assert triage.error_class == "artifact"
    assert triage.retryable is True


@pytest.mark.unit
def test_classify_crypto_failure() -> None:
    triage = classify_failure(
        failure_reason="runtime_exception",
        error_message="proof verification failed",
    )
    assert triage.error_class == "crypto"
    assert triage.retryable is False
