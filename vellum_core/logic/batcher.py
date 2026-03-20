from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MAX_BATCH_SIZE = 250
MAX_UINT32 = 4_294_967_295


@dataclass(frozen=True)
class PreparedBatchInput:
    balances: list[int]
    limits: list[int]
    active_count: int

    def to_circuit_input(self) -> dict[str, object]:
        return {
            "balances": self.balances,
            "limits": self.limits,
            "active_count": self.active_count,
        }


def batch_prepare_input(
    *, balances: list[int], limits: list[int], batch_size: int = MAX_BATCH_SIZE
) -> PreparedBatchInput:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if len(balances) == 0 or len(limits) == 0:
        raise ValueError("balances and limits must contain at least one item")
    if len(balances) != len(limits):
        raise ValueError("balances and limits length mismatch")
    if len(balances) > batch_size:
        raise ValueError(f"batch size exceeds limit ({batch_size})")

    _validate_u32_list("balances", balances)
    _validate_u32_list("limits", limits)

    active_count = len(balances)
    padded_balances = balances + [0] * (batch_size - active_count)
    padded_limits = limits + [0] * (batch_size - active_count)

    # Anti-ghost invariant: all padded rows must remain deterministic zero rows.
    _assert_zero_tail(padded_balances, active_count)
    _assert_zero_tail(padded_limits, active_count)

    return PreparedBatchInput(
        balances=padded_balances,
        limits=padded_limits,
        active_count=active_count,
    )


def batch_prepare_from_private_input(private_input: dict[str, Any]) -> PreparedBatchInput:
    balances_raw = private_input.get("balances")
    limits_raw = private_input.get("limits")
    active_count_raw = private_input.get("active_count")

    if not isinstance(balances_raw, list) or not isinstance(limits_raw, list):
        raise ValueError("private_input must contain array balances and limits")
    if not isinstance(active_count_raw, int):
        raise ValueError("private_input must contain integer active_count")

    if len(balances_raw) != MAX_BATCH_SIZE or len(limits_raw) != MAX_BATCH_SIZE:
        raise ValueError(
            f"private_input balances/limits must already be padded to {MAX_BATCH_SIZE}"
        )
    if active_count_raw < 1 or active_count_raw > MAX_BATCH_SIZE:
        raise ValueError(f"active_count must be between 1 and {MAX_BATCH_SIZE}")

    _validate_u32_list("balances", balances_raw)
    _validate_u32_list("limits", limits_raw)

    _assert_zero_tail(balances_raw, active_count_raw)
    _assert_zero_tail(limits_raw, active_count_raw)

    return PreparedBatchInput(
        balances=list(balances_raw),
        limits=list(limits_raw),
        active_count=active_count_raw,
    )


def _assert_zero_tail(values: list[int], active_count: int) -> None:
    for idx, value in enumerate(values[active_count:], start=active_count):
        if value != 0:
            raise ValueError(
                f"anti-ghost invariant violated: padded index {idx} must be zero"
            )


def _validate_u32_list(field_name: str, values: list[int]) -> None:
    for idx, value in enumerate(values):
        if not isinstance(value, int):
            raise ValueError(f"{field_name}[{idx}] must be an integer")
        if value < 0 or value > MAX_UINT32:
            raise ValueError(
                f"{field_name}[{idx}] must be between 0 and {MAX_UINT32}"
            )
