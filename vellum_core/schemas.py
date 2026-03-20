from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from vellum_core.logic.batcher import MAX_BATCH_SIZE


class CircuitManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    input_schema: dict[str, Any]
    public_signals: list[str]
    version: str = Field(min_length=1)


class BatchProveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balances: list[int] | None = Field(
        default=None, min_length=1, max_length=MAX_BATCH_SIZE
    )
    limits: list[int] | None = Field(
        default=None, min_length=1, max_length=MAX_BATCH_SIZE
    )
    source_ref: str | None = Field(default=None, min_length=1, max_length=256)
    request_id: str | None = None

    @model_validator(mode="after")
    def validate_input_mode(self) -> "BatchProveRequest":
        using_direct = self.balances is not None or self.limits is not None
        using_source = self.source_ref is not None

        if using_direct and using_source:
            raise ValueError("Provide either direct balances/limits or source_ref, not both")
        if not using_direct and not using_source:
            raise ValueError("Either balances/limits or source_ref must be provided")

        if using_direct:
            if self.balances is None or self.limits is None:
                raise ValueError("balances and limits must both be provided for direct mode")
            if len(self.balances) != len(self.limits):
                raise ValueError("balances and limits length mismatch")

        return self


class ProveAcceptedResponse(BaseModel):
    proof_id: str
    status: str


class ProofStatusResponse(BaseModel):
    proof_id: str
    status: str
    circuit_id: str
    public_signals: list[Any]
    proof: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    proof: dict[str, Any]
    public_signals: list[Any]


class VerifyResponse(BaseModel):
    valid: bool
    verified_at: datetime
    verification_ms: float


class TrustSpeedResponse(BaseModel):
    native_verify_ms: float | None
    zk_batch_verify_ms: float | None
    trust_speedup: float | None


class HealthResponse(BaseModel):
    status: str


class AuditChainVerifyResponse(BaseModel):
    valid: bool
    checked_entries: int
    first_broken_index: int | None = None
    reason: str | None = None
