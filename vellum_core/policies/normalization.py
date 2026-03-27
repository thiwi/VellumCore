"""Shared integer-only normalization helpers for dual-track policy execution."""

from __future__ import annotations

from typing import Any

from vellum_core.api.errors import framework_error


def require_integer(*, field: str, value: Any, minimum: int | None = None, maximum: int | None = None) -> int:
    """Return value as integer after strict integer-only validation."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise framework_error(
            "invalid_evidence_payload",
            "Field must be an integer",
            field=field,
        )
    if minimum is not None and value < minimum:
        raise framework_error(
            "invalid_evidence_payload",
            "Field is below minimum",
            field=field,
            minimum=minimum,
            value=value,
        )
    if maximum is not None and value > maximum:
        raise framework_error(
            "invalid_evidence_payload",
            "Field exceeds maximum",
            field=field,
            maximum=maximum,
            value=value,
        )
    return value


def require_integer_list(
    *,
    field: str,
    value: Any,
    minimum: int | None = None,
    maximum: int | None = None,
) -> list[int]:
    """Return canonical integer list after strict per-item validation."""
    if not isinstance(value, list):
        raise framework_error(
            "invalid_evidence_payload",
            "Field must be an array",
            field=field,
        )
    return [
        require_integer(
            field=f"{field}[{idx}]",
            value=item,
            minimum=minimum,
            maximum=maximum,
        )
        for idx, item in enumerate(value)
    ]
