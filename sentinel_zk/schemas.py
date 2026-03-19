from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CircuitManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    input_schema: dict[str, Any]
    public_signals: list[str]
    version: str = Field(min_length=1)


class ProveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    private_input: dict[str, Any]
    request_id: str | None = None


class BatchProveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balances: list[int] = Field(min_length=1, max_length=100)
    limits: list[int] = Field(min_length=1, max_length=100)
    request_id: str | None = None


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


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    proof: dict[str, Any]
    public_signals: list[Any]


class VerifyResponse(BaseModel):
    valid: bool
    verified_at: datetime
    verification_ms: float


class HealthResponse(BaseModel):
    status: str


class AuditChainVerifyResponse(BaseModel):
    valid: bool
    checked_entries: int
    first_broken_index: int | None = None
    reason: str | None = None
