from __future__ import annotations

import pytest
from pydantic import ValidationError

from vellum_core.logic.batcher import MAX_BATCH_SIZE
from vellum_core.schemas import BatchProveRequest


def test_batch_schema_accepts_up_to_max_batch_size_items() -> None:
    payload = BatchProveRequest.model_validate(
        {
            "balances": [101, 202, 303],
            "limits": [100, 200, 300],
        }
    )
    assert payload.circuit_id == "batch_credit_check"
    assert len(payload.balances) == 3
    assert len(payload.limits) == 3


def test_batch_schema_rejects_empty_batch() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate({"balances": [], "limits": []})


def test_batch_schema_rejects_more_than_max_batch_size_items() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate(
            {
                "balances": [1 for _ in range(MAX_BATCH_SIZE + 1)],
                "limits": [0 for _ in range(MAX_BATCH_SIZE + 1)],
            }
        )


def test_batch_schema_rejects_missing_limits() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate({"balances": [1, 2, 3]})


def test_batch_schema_rejects_missing_all_input_modes() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate({})


def test_batch_schema_rejects_uneven_lengths() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate({"balances": [10, 20], "limits": [5]})


def test_batch_schema_rejects_mixed_modes() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate(
            {
                "balances": [10],
                "limits": [5],
                "private_input": {"balance": 10, "limit": 5},
            }
        )


def test_batch_schema_accepts_private_input_mode_for_any_circuit() -> None:
    payload = BatchProveRequest.model_validate(
        {
            "circuit_id": "credit_check",
            "private_input": {"balance": 120, "limit": 100},
        }
    )
    assert payload.circuit_id == "credit_check"
    assert payload.private_input == {"balance": 120, "limit": 100}


def test_batch_schema_rejects_balances_mode_for_non_batch_circuit() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate(
            {
                "circuit_id": "credit_check",
                "balances": [10],
                "limits": [5],
            }
        )


def test_batch_schema_rejects_private_input_mixed_with_direct_mode() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate(
            {
                "balances": [10],
                "limits": [5],
                "private_input": {"balance": 10, "limit": 5},
            }
        )


def test_batch_schema_rejects_source_ref_field() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate({"source_ref": "legacy://batch/42"})
