"""Spec loading and pydantic validation for policy DSL files."""

from __future__ import annotations

from pathlib import Path

import yaml

from vellum_core.api.errors import framework_error
from vellum_core.policy_compiler.models import PolicyDSLSpec


def load_policy_spec(path: Path) -> PolicyDSLSpec:
    """Load and validate one policy DSL file."""
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise framework_error(
            "policy_spec_invalid",
            "Policy spec YAML is invalid",
            path=str(path),
            reason=str(exc),
        ) from exc
    if not isinstance(parsed, dict):
        raise framework_error(
            "policy_spec_invalid",
            "Policy spec must decode to an object",
            path=str(path),
        )
    try:
        return PolicyDSLSpec.model_validate(parsed)
    except Exception as exc:
        raise framework_error(
            "policy_spec_invalid",
            "Policy spec validation failed",
            path=str(path),
            reason=str(exc),
        ) from exc
