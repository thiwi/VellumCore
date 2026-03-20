from __future__ import annotations

import pytest
from pydantic import ValidationError

from vellum_core.api.types import DirectBatchInput


def test_direct_batch_input_accepts_matching_lengths() -> None:
    payload = DirectBatchInput(balances=[10, 20], limits=[1, 2])
    assert payload.balances == [10, 20]


def test_direct_batch_input_rejects_mismatch() -> None:
    with pytest.raises(ValidationError):
        DirectBatchInput(balances=[10, 20], limits=[1])
