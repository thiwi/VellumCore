"""Tests for Policy engine."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from vellum_core.api import AttestationService, CircuitManager, PolicyEngine, ProofEngine
from vellum_core.api.errors import FrameworkError
from vellum_core.api.types import PolicyRunRequest
from vellum_core.policy_parameters import PolicyParameterStore
from vellum_core.policy_registry import PolicyRegistry
from vellum_core.registry import CircuitRegistry
from vellum_core.runtime.testing import (
    DeterministicAttestationSigner,
    DeterministicProofProvider,
    InMemoryArtifactStore,
    InMemoryEvidenceStore,
)
from vellum_core.spi import ProviderProofResult


@pytest.mark.unit
def test_policy_engine_run_and_export(tmp_path: Path) -> None:
    circuits_dir = tmp_path / "circuits"
    shared_assets_dir = tmp_path / "shared_assets"
    policy_packs_dir = tmp_path / "policy_packs"
    circuit_dir = circuits_dir / "batch_credit_check"
    policy_dir = policy_packs_dir / "lending_risk_v1"

    circuit_dir.mkdir(parents=True)
    shared_assets_dir.mkdir(parents=True)
    policy_dir.mkdir(parents=True)

    (circuit_dir / "manifest.json").write_text(
        json.dumps(
            {
                "circuit_id": "batch_credit_check",
                "input_schema": {},
                "public_signals": ["all_valid"],
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    (circuit_dir / "batch_credit_check.circom").write_text(
        "template Demo(){} component main = Demo();",
        encoding="utf-8",
    )
    (policy_dir / "manifest.json").write_text(
        json.dumps(
            {
                "policy_id": "lending_risk_v1",
                "policy_version": "1.0.0",
                "circuit_id": "batch_credit_check",
                "input_contract": {},
                "evidence_contract": {},
                "reference_policy": "lending_risk_reference_v1",
                "primitives": ["SafeSub"],
                "differential_outputs": {
                    "all_valid": {"signal_index": 0, "value_type": "bool"},
                    "active_count_out": {"signal_index": 1, "value_type": "int"},
                },
                "expected_attestation": {"decision_signal_index": 0, "pass_signal_value": "1"},
            }
        ),
        encoding="utf-8",
    )

    registry = CircuitRegistry(circuits_dir=circuits_dir, shared_assets_dir=shared_assets_dir)
    artifacts = InMemoryArtifactStore()
    manager = CircuitManager(registry=registry, artifact_store=artifacts)
    proof_engine = ProofEngine(provider=DeterministicProofProvider(), circuit_manager=manager)
    evidence_store = InMemoryEvidenceStore()
    attestation_service = AttestationService(
        artifact_store=artifacts,
        signer=DeterministicAttestationSigner(),
    )
    engine = PolicyEngine(
        proof_engine=proof_engine,
        policy_registry=PolicyRegistry(policy_packs_dir),
        policy_parameter_store=PolicyParameterStore(policy_packs_dir=policy_packs_dir),
        evidence_store=evidence_store,
        attestation_service=attestation_service,
    )

    result = asyncio.run(
        engine.run(
            PolicyRunRequest(
                policy_id="lending_risk_v1",
                evidence={"type": "inline", "payload": {"balances": [120], "limits": [100]}},
                context={"tenant": "acme"},
            )
        )
    )

    assert result.policy_id == "lending_risk_v1"
    assert result.decision == "pass"
    assert result.attestation_id.startswith("att-")

    bundle = asyncio.run(attestation_service.export(result.attestation_id))
    assert bundle.policy_id == "lending_risk_v1"
    assert bundle.decision == "pass"


@pytest.mark.unit
def test_policy_engine_rejects_unknown_policy(tmp_path: Path) -> None:
    circuits_dir = tmp_path / "circuits"
    shared_assets_dir = tmp_path / "shared_assets"
    policy_packs_dir = tmp_path / "policy_packs"
    circuits_dir.mkdir(parents=True)
    shared_assets_dir.mkdir(parents=True)
    policy_packs_dir.mkdir(parents=True)

    registry = CircuitRegistry(circuits_dir=circuits_dir, shared_assets_dir=shared_assets_dir)
    artifacts = InMemoryArtifactStore()
    manager = CircuitManager(registry=registry, artifact_store=artifacts)
    proof_engine = ProofEngine(provider=DeterministicProofProvider(), circuit_manager=manager)
    engine = PolicyEngine(
        proof_engine=proof_engine,
        policy_registry=PolicyRegistry(policy_packs_dir),
        policy_parameter_store=PolicyParameterStore(policy_packs_dir=policy_packs_dir),
        evidence_store=InMemoryEvidenceStore(),
        attestation_service=AttestationService(
            artifact_store=artifacts,
            signer=DeterministicAttestationSigner(),
        ),
    )

    with pytest.raises(FrameworkError) as exc:
        asyncio.run(
            engine.run(
                PolicyRunRequest(
                    policy_id="missing",
                    evidence={"type": "inline", "payload": {"balances": [1], "limits": [0]}},
                )
            )
        )

    assert exc.value.code == "unknown_policy"


@pytest.mark.unit
def test_policy_engine_hard_fails_on_dual_track_mismatch(tmp_path: Path) -> None:
    circuits_dir = tmp_path / "circuits"
    shared_assets_dir = tmp_path / "shared_assets"
    policy_packs_dir = tmp_path / "policy_packs"
    circuit_dir = circuits_dir / "batch_credit_check"
    policy_dir = policy_packs_dir / "lending_risk_v1"

    circuit_dir.mkdir(parents=True)
    shared_assets_dir.mkdir(parents=True)
    policy_dir.mkdir(parents=True)

    (circuit_dir / "manifest.json").write_text(
        json.dumps(
            {
                "circuit_id": "batch_credit_check",
                "input_schema": {},
                "public_signals": ["all_valid", "active_count_out"],
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    (circuit_dir / "batch_credit_check.circom").write_text(
        "template Demo(){} component main = Demo();",
        encoding="utf-8",
    )
    (policy_dir / "manifest.json").write_text(
        json.dumps(
            {
                "policy_id": "lending_risk_v1",
                "policy_version": "1.0.0",
                "circuit_id": "batch_credit_check",
                "input_contract": {},
                "evidence_contract": {},
                "reference_policy": "lending_risk_reference_v1",
                "primitives": ["SafeSub"],
                "differential_outputs": {
                    "all_valid": {"signal_index": 0, "value_type": "bool"},
                    "active_count_out": {"signal_index": 1, "value_type": "int"},
                },
                "expected_attestation": {"decision_signal_index": 0, "pass_signal_value": "1"},
            }
        ),
        encoding="utf-8",
    )

    class MismatchProvider:
        async def generate_proof(
            self,
            circuit_id: str,
            private_input: dict[str, object],
        ) -> ProviderProofResult:
            _ = (circuit_id, private_input)
            return ProviderProofResult(
                proof={"circuit_id": "batch_credit_check", "digest": "x"},
                public_signals=["0", "1"],
            )

        async def verify_proof(
            self,
            circuit_id: str,
            proof: dict[str, object],
            public_signals: list[object],
        ) -> bool:
            _ = (circuit_id, proof, public_signals)
            return True

        async def ensure_artifacts(self, circuit_id: str) -> None:
            _ = circuit_id

    registry = CircuitRegistry(circuits_dir=circuits_dir, shared_assets_dir=shared_assets_dir)
    artifacts = InMemoryArtifactStore()
    manager = CircuitManager(registry=registry, artifact_store=artifacts)
    proof_engine = ProofEngine(provider=MismatchProvider(), circuit_manager=manager)
    evidence_store = InMemoryEvidenceStore()
    attestation_service = AttestationService(
        artifact_store=artifacts,
        signer=DeterministicAttestationSigner(),
    )
    engine = PolicyEngine(
        proof_engine=proof_engine,
        policy_registry=PolicyRegistry(policy_packs_dir),
        policy_parameter_store=PolicyParameterStore(policy_packs_dir=policy_packs_dir),
        evidence_store=evidence_store,
        attestation_service=attestation_service,
    )

    with pytest.raises(FrameworkError) as exc:
        asyncio.run(
            engine.run(
                PolicyRunRequest(
                    policy_id="lending_risk_v1",
                    evidence={"type": "inline", "payload": {"balances": [120], "limits": [100]}},
                    context={"tenant": "acme"},
                )
            )
        )
    assert exc.value.code == "dual_track_mismatch"
