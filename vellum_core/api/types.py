"""Stable typed request/response contracts for the framework API surface."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DirectBatchInput(BaseModel):
    """Direct batch payload before fixed-size padding."""

    balances: list[int] = Field(min_length=1)
    limits: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_lengths(self) -> "DirectBatchInput":
        if len(self.balances) != len(self.limits):
            raise ValueError("balances and limits length mismatch")
        return self


class ProofGenerationRequest(BaseModel):
    """Request model for generating one circuit proof."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    private_input: dict[str, Any]


class VerificationRequest(BaseModel):
    """Request model for verifying one proof tuple."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    proof: dict[str, Any]
    public_signals: list[Any]


class ProofGenerationResult(BaseModel):
    """Proof generation output model."""

    circuit_id: str
    proof: dict[str, Any]
    public_signals: list[Any]
    generated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        circuit_id: str,
        proof: dict[str, Any],
        public_signals: list[Any],
    ) -> "ProofGenerationResult":
        return cls(
            circuit_id=circuit_id,
            proof=proof,
            public_signals=public_signals,
            generated_at=datetime.now(timezone.utc),
        )


class VerificationResult(BaseModel):
    """Verification output model with timing metadata."""

    circuit_id: str
    valid: bool
    verification_ms: float
    verified_at: datetime


class AuditResult(BaseModel):
    """Audit chain verification result model."""

    valid: bool
    checked_entries: int
    first_broken_index: int | None = None
    reason: str | None = None


class CircuitStatus(BaseModel):
    """Artifact readiness and metadata for one circuit."""

    circuit_id: str
    version: str
    artifacts_ready: bool
    artifact_paths: dict[str, str]


class FrameworkHealth(BaseModel):
    """Runtime health snapshot model used by framework surfaces."""

    status: str
    components: dict[str, dict[str, Any]]
