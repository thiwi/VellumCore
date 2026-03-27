"""Tests for Batch prepare input."""

from __future__ import annotations

import pytest

from vellum_core.logic.batcher import (
    MAX_BATCH_SIZE,
    MAX_UINT32,
    batch_prepare_from_private_input,
    batch_prepare_input,
)


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


def test_batch_prepare_input_rejects_invalid_batch_size() -> None:
    with pytest.raises(ValueError, match="positive"):
        batch_prepare_input(balances=[1], limits=[1], batch_size=0)


def test_batch_prepare_input_rejects_empty_lists() -> None:
    with pytest.raises(ValueError, match="at least one"):
        batch_prepare_input(balances=[], limits=[])


def test_batch_prepare_input_rejects_non_integer_and_out_of_range_values() -> None:
    with pytest.raises(ValueError, match=r"balances\[0\] must be an integer"):
        batch_prepare_input(balances=["1"], limits=[1])  # type: ignore[list-item]

    with pytest.raises(ValueError, match=r"balances\[0\] must be an integer"):
        batch_prepare_input(balances=[True], limits=[1])  # type: ignore[list-item]

    with pytest.raises(ValueError, match=rf"between 0 and {MAX_UINT32}"):
        batch_prepare_input(balances=[MAX_UINT32 + 1], limits=[1])


def test_batch_prepare_from_private_input_roundtrip() -> None:
    balances = [12, 30] + [0] * (MAX_BATCH_SIZE - 2)
    limits = [20, 40] + [0] * (MAX_BATCH_SIZE - 2)
    prepared = batch_prepare_from_private_input(
        {"balances": balances, "limits": limits, "active_count": 2}
    )
    assert prepared.active_count == 2
    assert prepared.balances[:2] == [12, 30]
    assert prepared.to_circuit_input()["active_count"] == 2


def test_batch_prepare_from_private_input_validates_shape_and_bounds() -> None:
    with pytest.raises(ValueError, match="array balances and limits"):
        batch_prepare_from_private_input({"balances": "x", "limits": [], "active_count": 1})

    with pytest.raises(ValueError, match="integer active_count"):
        batch_prepare_from_private_input(
            {"balances": [0] * MAX_BATCH_SIZE, "limits": [0] * MAX_BATCH_SIZE, "active_count": "1"}
        )

    with pytest.raises(ValueError, match="already be padded"):
        batch_prepare_from_private_input({"balances": [1], "limits": [1], "active_count": 1})

    with pytest.raises(ValueError, match="between 1 and"):
        batch_prepare_from_private_input(
            {"balances": [0] * MAX_BATCH_SIZE, "limits": [0] * MAX_BATCH_SIZE, "active_count": 0}
        )


def test_batch_prepare_from_private_input_enforces_zero_tail() -> None:
    balances = [1, 2] + [0] * (MAX_BATCH_SIZE - 2)
    limits = [2, 3] + [0] * (MAX_BATCH_SIZE - 2)
    limits[20] = 9
    with pytest.raises(ValueError, match="anti-ghost invariant"):
        batch_prepare_from_private_input(
            {"balances": balances, "limits": limits, "active_count": 2}
        )
