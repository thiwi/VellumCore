"""Attempt-counter helpers for queue job retry resilience."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def next_attempt_metadata(
    *,
    metadata: Mapping[str, Any] | None,
    max_attempts: int,
) -> tuple[dict[str, int], bool]:
    """Return normalized attempt metadata and whether max attempts is exceeded."""
    previous_attempts = 0
    if metadata is not None:
        raw = metadata.get("attempt_count")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
            previous_attempts = raw

    attempt_count = previous_attempts + 1
    attempt_metadata = {
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
    }
    return attempt_metadata, attempt_count > max_attempts

