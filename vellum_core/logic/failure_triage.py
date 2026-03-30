"""Deterministic failure triage classification for dead-letter handling."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureTriage:
    """Normalized failure classification persisted with DLQ records."""

    error_class: str
    retryable: bool
    detail: str


def classify_failure(*, failure_reason: str, error_message: str) -> FailureTriage:
    """Map runtime failure metadata to a stable class + retryability decision."""
    reason = (failure_reason or "").strip().lower()
    message = (error_message or "").strip().lower()
    combined = f"{reason} {message}".strip()

    if "soft_time_limit_exceeded" in reason or "time limit" in combined or "timeout" in combined:
        return FailureTriage(
            error_class="timeout",
            retryable=True,
            detail="Execution exceeded timeout budget.",
        )

    if (
        "connection refused" in combined
        or "temporarily unavailable" in combined
        or "service unavailable" in combined
        or "grpc" in combined
        or "redis" in combined
        or "postgres" in combined
        or "database" in combined
        or "network" in combined
    ):
        return FailureTriage(
            error_class="dependency",
            retryable=True,
            detail="External dependency/network failure detected.",
        )

    if (
        "missing_artifacts" in combined
        or "required circuit artifacts are missing" in combined
        or "no such file" in combined
        or "final.zkey" in combined
        or ".wasm" in combined
    ):
        return FailureTriage(
            error_class="artifact",
            retryable=True,
            detail="Required proving artifacts are missing or unreadable.",
        )

    if (
        "invalid_private_input_schema" in combined
        or "private_input does not satisfy" in combined
        or "validation failed" in combined
        or "dual_track_reference" in combined
    ):
        return FailureTriage(
            error_class="schema",
            retryable=False,
            detail="Input/schema validation failure.",
        )

    if (
        "decrypt" in combined
        or "vault" in combined
        or "signature" in combined
        or "invalid proof" in combined
        or "proof verification failed" in combined
        or "dual_track_mismatch" in combined
        or "snarkjs" in combined
        or "rapidsnark" in combined
    ):
        return FailureTriage(
            error_class="crypto",
            retryable=False,
            detail="Cryptographic/proving pipeline failure.",
        )

    if "max_attempts_exceeded" in reason:
        return FailureTriage(
            error_class="retry_exhausted",
            retryable=False,
            detail="Maximum attempts exceeded.",
        )

    return FailureTriage(
        error_class="unknown",
        retryable=False,
        detail="Unclassified runtime exception.",
    )
