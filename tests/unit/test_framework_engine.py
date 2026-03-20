from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from vellum_core.api import CircuitManager, ProofEngine
from vellum_core.api.errors import FrameworkError
from vellum_core.api.types import ProofGenerationRequest, VerificationRequest
from vellum_core.registry import CircuitRegistry
from vellum_core.runtime.testing import DeterministicProofProvider, InMemoryArtifactStore


@pytest.mark.unit
def test_proof_engine_generate_and_verify(tmp_path: Path) -> None:
    circuits_dir = tmp_path / "circuits"
    shared_assets_dir = tmp_path / "shared_assets"
    circuit_dir = circuits_dir / "demo"
    circuit_dir.mkdir(parents=True)
    shared_assets_dir.mkdir(parents=True)

    (circuit_dir / "manifest.json").write_text(
        json.dumps(
            {
                "circuit_id": "demo",
                "input_schema": {},
                "public_signals": ["ok"],
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    (circuit_dir / "demo.circom").write_text("template Demo(){} component main = Demo();", encoding="utf-8")

    registry = CircuitRegistry(circuits_dir=circuits_dir, shared_assets_dir=shared_assets_dir)
    artifacts = InMemoryArtifactStore()
    artifacts.ready.add("demo")

    manager = CircuitManager(registry=registry, artifact_store=artifacts)
    engine = ProofEngine(provider=DeterministicProofProvider(), circuit_manager=manager)

    generated = asyncio.run(
        engine.generate(
            ProofGenerationRequest(circuit_id="demo", private_input={"a": [1, 2, 3]})
        )
    )
    assert generated.circuit_id == "demo"

    verified = asyncio.run(
        engine.verify(
            VerificationRequest(
                circuit_id="demo",
                proof=generated.proof,
                public_signals=generated.public_signals,
            )
        )
    )
    assert verified.valid is True


@pytest.mark.unit
def test_proof_engine_rejects_unknown_circuit(tmp_path: Path) -> None:
    circuits_dir = tmp_path / "circuits"
    shared_assets_dir = tmp_path / "shared_assets"
    circuits_dir.mkdir(parents=True)
    shared_assets_dir.mkdir(parents=True)

    registry = CircuitRegistry(circuits_dir=circuits_dir, shared_assets_dir=shared_assets_dir)
    artifacts = InMemoryArtifactStore()
    manager = CircuitManager(registry=registry, artifact_store=artifacts)
    engine = ProofEngine(provider=DeterministicProofProvider(), circuit_manager=manager)

    with pytest.raises(FrameworkError) as exc:
        asyncio.run(
            engine.generate(ProofGenerationRequest(circuit_id="missing", private_input={"a": 1}))
        )
    assert exc.value.code == "unknown_circuit"
