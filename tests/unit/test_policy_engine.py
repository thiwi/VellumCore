"""Tests for Policy engine."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from vellum_core.api import AttestationService, CircuitManager, PolicyEngine, ProofEngine
from vellum_core.api.errors import FrameworkError
from vellum_core.api.types import PolicyRunRequest
from vellum_core.policy_registry import PolicyRegistry
from vellum_core.registry import CircuitRegistry
from vellum_core.runtime.testing import (
    DeterministicAttestationSigner,
    DeterministicProofProvider,
    InMemoryArtifactStore,
    InMemoryEvidenceStore,
)


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
        evidence_store=evidence_store,
        attestation_service=attestation_service,
    )

    result = asyncio.run(
        engine.run(
            PolicyRunRequest(
                policy_id="lending_risk_v1",
                evidence_payload={"balances": [120], "limits": [100]},
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
                    evidence_payload={"balances": [1], "limits": [0]},
                )
            )
        )

    assert exc.value.code == "unknown_policy"
