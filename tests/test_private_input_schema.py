"""Tests for manifest-driven private-input schema validation."""

from __future__ import annotations

import pytest

from vellum_core.logic.private_input_schema import validate_private_input_schema


@pytest.mark.security
def test_private_input_schema_accepts_valid_payload() -> None:
    schema = {
        "type": "object",
        "properties": {
            "credit_score": {"type": "integer", "minimum": 0, "maximum": 900},
            "debt_ratio": {"type": "integer", "minimum": 0, "maximum": 1000000},
        },
        "required": ["credit_score", "debt_ratio"],
        "additionalProperties": False,
    }
    validate_private_input_schema(
        input_schema=schema,
        private_input={"credit_score": 700, "debt_ratio": 200000},
    )


@pytest.mark.security
def test_private_input_schema_rejects_out_of_range_value() -> None:
    schema = {
        "type": "object",
        "properties": {
            "credit_score": {"type": "integer", "minimum": 0, "maximum": 900},
        },
        "required": ["credit_score"],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match=r"\$\.credit_score"):
        validate_private_input_schema(
            input_schema=schema,
            private_input={"credit_score": -1},
        )


@pytest.mark.security
def test_private_input_schema_rejects_missing_required() -> None:
    schema = {
        "type": "object",
        "properties": {
            "credit_score": {"type": "integer", "minimum": 0, "maximum": 900},
            "debt_ratio": {"type": "integer", "minimum": 0, "maximum": 1000000},
        },
        "required": ["credit_score", "debt_ratio"],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match=r"required property"):
        validate_private_input_schema(
            input_schema=schema,
            private_input={"credit_score": 700},
        )


@pytest.mark.security
def test_private_input_schema_rejects_additional_property() -> None:
    schema = {
        "type": "object",
        "properties": {"amount": {"type": "integer", "minimum": 0, "maximum": 100}},
        "required": ["amount"],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match=r"Additional properties are not allowed"):
        validate_private_input_schema(
            input_schema=schema,
            private_input={"amount": 10, "extra": 5},
        )

