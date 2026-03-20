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


def test_batch_schema_rejects_uneven_lengths() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate({"balances": [10, 20], "limits": [5]})


def test_batch_schema_accepts_source_ref_mode() -> None:
    payload = BatchProveRequest.model_validate({"source_ref": "legacy://batch/42"})
    assert payload.source_ref == "legacy://batch/42"
    assert payload.balances is None
    assert payload.limits is None


def test_batch_schema_rejects_mixed_modes() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate(
            {
                "source_ref": "legacy://batch/42",
                "balances": [10],
                "limits": [5],
            }
        )
