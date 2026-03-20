"""Typed framework error model shared across API/runtime layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FrameworkError(Exception):
    """Framework-level typed error propagated through API/service layers."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def framework_error(
    code: str,
    message: str,
    **details: Any,
) -> FrameworkError:
    """Helper to construct a FrameworkError with free-form details."""
    return FrameworkError(code=code, message=message, details=details)
