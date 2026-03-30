"""Tests for job-attempt metadata helpers."""

from __future__ import annotations

import pytest

from vellum_core.logic.job_attempts import next_attempt_metadata


@pytest.mark.security
def test_next_attempt_metadata_increments_from_zero() -> None:
    metadata, exceeded = next_attempt_metadata(metadata=None, max_attempts=3)
    assert metadata == {"attempt_count": 1, "max_attempts": 3}
    assert exceeded is False


@pytest.mark.security
def test_next_attempt_metadata_handles_invalid_existing_value() -> None:
    metadata, exceeded = next_attempt_metadata(
        metadata={"attempt_count": "2"},
        max_attempts=3,
    )
    assert metadata == {"attempt_count": 1, "max_attempts": 3}
    assert exceeded is False


@pytest.mark.security
def test_next_attempt_metadata_reports_exceeded_after_limit() -> None:
    metadata, exceeded = next_attempt_metadata(
        metadata={"attempt_count": 3},
        max_attempts=3,
    )
    assert metadata == {"attempt_count": 4, "max_attempts": 3}
    assert exceeded is True

