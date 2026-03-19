from __future__ import annotations

from dataclasses import dataclass


MAX_BATCH_SIZE = 100
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

    padded_balances = balances + [0] * (batch_size - len(balances))
    padded_limits = limits + [0] * (batch_size - len(limits))

    return PreparedBatchInput(
        balances=padded_balances,
        limits=padded_limits,
        active_count=len(balances),
    )


def _validate_u32_list(field_name: str, values: list[int]) -> None:
    for idx, value in enumerate(values):
        if not isinstance(value, int):
            raise ValueError(f"{field_name}[{idx}] must be an integer")
        if value < 0 or value > MAX_UINT32:
            raise ValueError(
                f"{field_name}[{idx}] must be between 0 and {MAX_UINT32}"
            )
