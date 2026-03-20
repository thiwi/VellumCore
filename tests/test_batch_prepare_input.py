from __future__ import annotations

import pytest

from vellum_core.logic.batcher import MAX_BATCH_SIZE, batch_prepare_input


def test_batch_prepare_input_pads_to_max_batch_size() -> None:
    prepared = batch_prepare_input(balances=[101, 202], limits=[100, 200])

    assert prepared.active_count == 2
    assert len(prepared.balances) == MAX_BATCH_SIZE
    assert len(prepared.limits) == MAX_BATCH_SIZE
    assert prepared.balances[:2] == [101, 202]
    assert prepared.limits[:2] == [100, 200]
    assert prepared.balances[-1] == 0
    assert prepared.limits[-1] == 0


def test_batch_prepare_input_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        batch_prepare_input(balances=[101], limits=[100, 200])


def test_batch_prepare_input_rejects_more_than_max_batch_size() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        batch_prepare_input(
            balances=[1 for _ in range(MAX_BATCH_SIZE + 1)],
            limits=[0 for _ in range(MAX_BATCH_SIZE + 1)],
        )
