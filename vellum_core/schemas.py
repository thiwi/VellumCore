"""Reference-service HTTP schema models and validation rules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from vellum_core.logic.batcher import MAX_BATCH_SIZE

DEFAULT_BATCH_CIRCUIT_ID = "batch_credit_check"


class CircuitManifest(BaseModel):
    """Manifest format used for circuit discovery and compatibility checks."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    input_schema: dict[str, Any]
    public_signals: list[str]
    version: str = Field(min_length=1)


class BatchProveRequest(BaseModel):
    """Prover submit request supporting direct or private-input mode."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(default=DEFAULT_BATCH_CIRCUIT_ID, min_length=1, max_length=128)
    balances: list[int] | None = Field(
        default=None, min_length=1, max_length=MAX_BATCH_SIZE
    )
    limits: list[int] | None = Field(
        default=None, min_length=1, max_length=MAX_BATCH_SIZE
    )
    private_input: dict[str, Any] | None = None
    request_id: str | None = None

    @model_validator(mode="after")
    def validate_input_mode(self) -> "BatchProveRequest":
        """Enforce exactly one input mode and batch-circuit-specific constraints."""
        using_balances_limits = self.balances is not None or self.limits is not None
        using_private_input = self.private_input is not None

        modes = int(using_balances_limits) + int(using_private_input)
        if modes != 1:
            raise ValueError(
                "Provide exactly one input mode: balances/limits or private_input"
            )

        if using_balances_limits:
            if self.balances is None or self.limits is None:
                raise ValueError("balances and limits must both be provided for direct mode")
            if len(self.balances) != len(self.limits):
                raise ValueError("balances and limits length mismatch")
            if self.circuit_id != DEFAULT_BATCH_CIRCUIT_ID:
                raise ValueError(
                    "balances/limits mode is only supported for circuit_id=batch_credit_check"
                )

        return self


class ProveAcceptedResponse(BaseModel):
    """Asynchronous prove submission acknowledgment."""

    proof_id: str
    status: str


class ProofStatusResponse(BaseModel):
    """Persisted proof job status payload."""

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
    """Verifier request schema for explicit proof tuple checks."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1)
    proof: dict[str, Any]
    public_signals: list[Any]


class VerifyResponse(BaseModel):
    """Verifier response schema with validity and timing."""

    valid: bool
    verified_at: datetime
    verification_ms: float


class TrustSpeedResponse(BaseModel):
    """Trust-speed snapshot comparing native and ZK verification times."""

    native_verify_ms: float | None
    zk_batch_verify_ms: float | None
    trust_speedup: float | None


class HealthResponse(BaseModel):
    """Simple health payload returned by service health endpoints."""

    status: str


class AuditChainVerifyResponse(BaseModel):
    """Audit-chain integrity result payload."""

    valid: bool
    checked_entries: int
    first_broken_index: int | None = None
    reason: str | None = None


class CircuitArtifactStatus(BaseModel):
    """Circuit artifact readiness row."""

    circuit_id: str
    version: str
    artifacts_ready: bool
    artifact_paths: dict[str, str]


class CircuitsResponse(BaseModel):
    """List wrapper for circuit artifact status rows."""

    circuits: list[CircuitArtifactStatus]


class PolicyRunRequest(BaseModel):
    """Policy-run submission request for v5 domain-oriented endpoints."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(default="lending_risk_v1", min_length=1, max_length=128)
    evidence_payload: dict[str, Any] | None = None
    evidence_ref: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None

    @model_validator(mode="after")
    def validate_evidence_input(self) -> "PolicyRunRequest":
        if self.evidence_payload is None and self.evidence_ref is None:
            raise ValueError("Provide evidence_payload or evidence_ref")
        return self


class PolicyRunAcceptedResponse(BaseModel):
    """Asynchronous policy-run submission acknowledgment."""

    run_id: str
    policy_id: str
    status: str
    attestation_id: str


class PolicyRunStatusResponse(BaseModel):
    """Status payload for one persisted policy run."""

    run_id: str
    policy_id: str
    status: str
    circuit_id: str
    decision: Literal["pass", "fail"] | None = None
    attestation_id: str
    evidence_ref: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class AttestationExportResponse(BaseModel):
    """Exportable attestation bundle payload for policy runs."""

    attestation_id: str
    run_id: str
    policy_id: str
    policy_version: str
    circuit_id: str
    decision: Literal["pass", "fail"]
    proof_hash: str
    public_signals_hash: str
    artifact_digests: dict[str, str]
    signature_chain: list[dict[str, Any]]
    metadata: dict[str, Any]
    exported_at: datetime
