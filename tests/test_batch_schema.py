from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel_zk.schemas import BatchProveRequest


def test_batch_schema_accepts_up_to_hundred_items() -> None:
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


def test_batch_schema_rejects_more_than_hundred_items() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate(
            {
                "balances": [1 for _ in range(101)],
                "limits": [0 for _ in range(101)],
            }
        )


def test_batch_schema_rejects_missing_limits() -> None:
    with pytest.raises(ValidationError):
        BatchProveRequest.model_validate({"balances": [1, 2, 3]})


def test_batch_schema_accepts_uneven_lengths_for_service_validation() -> None:
    payload = BatchProveRequest.model_validate(
        {"balances": [10, 20], "limits": [5]}
    )
    assert len(payload.balances) == 2
    assert len(payload.limits) == 1
