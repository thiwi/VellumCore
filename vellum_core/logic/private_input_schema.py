"""JSON-schema validation helpers for circuit private input payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


def validate_private_input_schema(
    *,
    input_schema: Mapping[str, Any],
    private_input: Mapping[str, Any],
) -> None:
    """Raise ValueError when private_input violates the circuit input schema."""
    schema_obj = dict(input_schema)
    try:
        Draft202012Validator.check_schema(schema_obj)
    except SchemaError as exc:
        raise ValueError(f"invalid manifest input_schema: {exc.message}") from exc

    validator = Draft202012Validator(schema_obj)
    errors = sorted(validator.iter_errors(private_input), key=_validation_error_sort_key)
    if not errors:
        return

    first = errors[0]
    location = _json_path(first.absolute_path)
    raise ValueError(f"{location}: {first.message}")


def _validation_error_sort_key(err: ValidationError) -> tuple[int, str]:
    """Stable sorting key to keep validation errors deterministic."""
    return (len(list(err.absolute_path)), _json_path(err.absolute_path))


def _json_path(path: Sequence[Any]) -> str:
    """Render jsonschema absolute path sequence as JSONPath-style string."""
    if not path:
        return "$"
    rendered = "$"
    for item in path:
        if isinstance(item, int):
            rendered += f"[{item}]"
        else:
            rendered += f".{item}"
    return rendered

