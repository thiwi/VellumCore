"""Base contracts for Python reference-track policy implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


PolicyDecision = Literal["pass", "fail"]


@dataclass(frozen=True)
class ReferenceTrackResult:
    """Reference-track output used for differential checks."""

    private_input: dict[str, Any]
    decision: PolicyDecision
    outputs: dict[str, Any]


class ReferencePolicy(Protocol):
    """Protocol implemented by every policy-specific Python reference track."""

    reference_policy: str

    def validate(self, evidence_payload: dict[str, Any]) -> None:
        """Validate evidence payload shape and numeric domain."""

    def normalize(self, evidence_payload: dict[str, Any]) -> dict[str, Any]:
        """Return canonical policy-specific normalized evidence."""

    def to_private_input(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        """Render proving private input from normalized evidence."""

    def evaluate_reference(self, normalized_evidence: dict[str, Any]) -> PolicyDecision:
        """Evaluate policy decision in pure Python."""

    def project_public_outputs(self, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        """Project manifest-declared output values used for differential checks."""
