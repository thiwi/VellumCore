"""Tests for shadow proof provider behavior."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from vellum_core.providers.base import ProofResult, ZKProvider
from vellum_core.providers.shadow_provider import ShadowProofProvider


class _FakeProvider(ZKProvider):
    def __init__(
        self,
        *,
        generate_result: ProofResult,
        verify_result: bool = True,
        generate_error: Exception | None = None,
        verify_error: Exception | None = None,
    ) -> None:
        self.generate_result = generate_result
        self.verify_result = verify_result
        self.generate_error = generate_error
        self.verify_error = verify_error
        self.ensure_calls: list[str] = []

    async def ensure_artifacts(self, circuit_id: str) -> None:
        self.ensure_calls.append(circuit_id)

    async def generate_proof(
        self,
        circuit_id: str,
        private_input: dict[str, Any],
    ) -> ProofResult:
        _ = (circuit_id, private_input)
        if self.generate_error is not None:
            raise self.generate_error
        return self.generate_result

    async def verify_proof(
        self,
        circuit_id: str,
        proof: dict[str, Any],
        public_signals: list[Any],
    ) -> bool:
        _ = (circuit_id, proof, public_signals)
        if self.verify_error is not None:
            raise self.verify_error
        return self.verify_result


def test_shadow_provider_delegates_artifact_checks() -> None:
    primary = _FakeProvider(generate_result=ProofResult(proof={"p": 1}, public_signals=["1"]))
    shadow = _FakeProvider(generate_result=ProofResult(proof={"p": 2}, public_signals=["1"]))
    provider = ShadowProofProvider(primary=primary, shadow=shadow)

    asyncio.run(provider.ensure_artifacts("batch_credit_check"))
    assert primary.ensure_calls == ["batch_credit_check"]
    assert shadow.ensure_calls == ["batch_credit_check"]


def test_shadow_provider_logs_public_signal_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    primary = _FakeProvider(generate_result=ProofResult(proof={"p": 1}, public_signals=["1"]))
    shadow = _FakeProvider(generate_result=ProofResult(proof={"p": 2}, public_signals=["0"]))
    provider = ShadowProofProvider(primary=primary, shadow=shadow, compare_public_signals=True)

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(provider.generate_proof("batch_credit_check", {"x": 1}))

    assert result.public_signals == ["1"]
    assert "proof_shadow_public_signal_mismatch" in caplog.text


def test_shadow_provider_generate_fail_open_on_shadow_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = _FakeProvider(generate_result=ProofResult(proof={"p": 1}, public_signals=["1"]))
    shadow = _FakeProvider(
        generate_result=ProofResult(proof={"p": 2}, public_signals=["1"]),
        generate_error=RuntimeError("boom"),
    )
    provider = ShadowProofProvider(primary=primary, shadow=shadow)

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(provider.generate_proof("batch_credit_check", {"x": 1}))

    assert result.proof == {"p": 1}
    assert "proof_shadow_generate_failed" in caplog.text


def test_shadow_provider_logs_verify_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    primary = _FakeProvider(
        generate_result=ProofResult(proof={"p": 1}, public_signals=["1"]),
        verify_result=True,
    )
    shadow = _FakeProvider(
        generate_result=ProofResult(proof={"p": 2}, public_signals=["1"]),
        verify_result=False,
    )
    provider = ShadowProofProvider(primary=primary, shadow=shadow)

    with caplog.at_level(logging.WARNING):
        valid = asyncio.run(provider.verify_proof("batch_credit_check", {"p": 1}, ["1"]))

    assert valid is True
    assert "proof_shadow_verify_mismatch" in caplog.text


def test_shadow_provider_verify_fail_open_on_shadow_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = _FakeProvider(
        generate_result=ProofResult(proof={"p": 1}, public_signals=["1"]),
        verify_result=True,
    )
    shadow = _FakeProvider(
        generate_result=ProofResult(proof={"p": 2}, public_signals=["1"]),
        verify_error=RuntimeError("timeout"),
    )
    provider = ShadowProofProvider(primary=primary, shadow=shadow)

    with caplog.at_level(logging.WARNING):
        valid = asyncio.run(provider.verify_proof("batch_credit_check", {"p": 1}, ["1"]))

    assert valid is True
    assert "proof_shadow_verify_failed" in caplog.text
