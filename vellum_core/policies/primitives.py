"""Primitive catalog used by policy-manifest validation."""

from __future__ import annotations


ALLOWED_PRIMITIVES = frozenset(
    {
        "SafeSub",
        "InterestRateValidator",
        "MerkleProof",
        "BalanceGreaterThanLimit",
        "ActiveCountBounds",
        "ZeroPaddingInvariant",
    }
)


def unknown_primitives(primitives: list[str]) -> list[str]:
    """Return sorted primitive ids not present in catalog."""
    return sorted({primitive for primitive in primitives if primitive not in ALLOWED_PRIMITIVES})
