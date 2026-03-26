"""Tests for Compose e2e."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import httpx


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.yml"
RUN_E2E = os.getenv("RUN_E2E", "0") == "1"

pytestmark = [pytest.mark.e2e]
if not RUN_E2E:
    pytestmark.append(pytest.mark.skip(reason="Set RUN_E2E=1 to execute compose E2E suite"))


@pytest.fixture(scope="module")
def compose_stack() -> None:
    _compose("down", "--remove-orphans")
    _compose("up", "--build", "-d")
    _wait_http("http://localhost:8000/healthz", timeout=240)
    yield
    _compose("down", "--remove-orphans")


def _compose(*args: str) -> None:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    subprocess.run(cmd, check=True)


def _compose_capture(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _wait_http(url: str, timeout: int = 120) -> None:
    started = time.time()
    while time.time() - started < timeout:
        try:
            response = httpx.get(url, timeout=3.0)
            if response.status_code < 400:
                return
        except Exception:
            pass
        time.sleep(2)
    raise AssertionError(f"timeout waiting for {url}")


def _submit_proof(payload: dict[str, Any]) -> str:
    response = httpx.post("http://localhost:8000/api/demo/prove", json=payload, timeout=30.0)
    assert response.status_code == 200, response.text
    return response.json()["proof_id"]


def _wait_proof_status(proof_id: str, timeout: int = 180) -> dict[str, Any]:
    started = time.time()
    while time.time() - started < timeout:
        response = httpx.get(f"http://localhost:8000/api/demo/proofs/{proof_id}", timeout=20.0)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in {"completed", "failed"}:
            return body
        time.sleep(2)
    raise AssertionError(f"proof {proof_id} did not complete")


@pytest.mark.critical
def test_happy_path_compose(compose_stack: None) -> None:
    proof_id = _submit_proof({"balances": [120, 220, 330], "limits": [100, 200, 300]})
    job = _wait_proof_status(proof_id)
    assert job["status"] == "completed"

    verify = httpx.post(
        "http://localhost:8000/api/demo/verify",
        json={
            "circuit_id": job["circuit_id"],
            "proof": job["proof"],
            "public_signals": job["public_signals"],
        },
        timeout=30.0,
    )
    assert verify.status_code == 200
    assert verify.json()["valid"] is True

    audit = httpx.get("http://localhost:8000/api/framework/audit-chain", timeout=20.0)
    assert audit.status_code == 200
    assert audit.json()["checked_entries"] >= 1


@pytest.mark.critical
def test_invalid_payload_rejected(compose_stack: None) -> None:
    response = httpx.post(
        "http://localhost:8000/api/demo/prove",
        json={"balances": [10], "limits": [1], "private_input": {"x": 1}},
        timeout=20.0,
    )
    assert response.status_code == 422


@pytest.mark.nightly
def test_private_input_mode_flow(compose_stack: None) -> None:
    proof_id = _submit_proof(
        {
            "private_input": {
                "balances": [120, 220, 330] + [0] * 247,
                "limits": [100, 200, 300] + [0] * 247,
                "active_count": 3,
            }
        }
    )
    job = _wait_proof_status(proof_id)
    assert job["status"] == "completed"


@pytest.mark.nightly
def test_missing_artifact_recovery(compose_stack: None) -> None:
    _compose("exec", "-T", "prover", "sh", "-lc", "rm -f /shared_assets/batch_credit_check/final.zkey")

    proof_id = _submit_proof({"balances": [150, 260], "limits": [100, 200]})
    job = _wait_proof_status(proof_id)
    assert job["status"] == "failed"

    _compose("exec", "-T", "prover", "sh", "-lc", "/app/setup_framework.sh")
    proof_id = _submit_proof({"balances": [180, 290], "limits": [100, 200]})
    recovered = _wait_proof_status(proof_id, timeout=300)
    assert recovered["status"] == "completed"


@pytest.mark.nightly
def test_provider_failure_path(compose_stack: None) -> None:
    _compose("exec", "-T", "prover", "sh", "-lc", "printf 'broken' > /shared_assets/batch_credit_check/final.zkey")
    proof_id = _submit_proof({"balances": [190], "limits": [100]})
    failed = _wait_proof_status(proof_id)
    assert failed["status"] == "failed"
    _compose("exec", "-T", "prover", "sh", "-lc", "/app/setup_framework.sh")


@pytest.mark.nightly
def test_dependency_outage_and_recovery(compose_stack: None) -> None:
    _compose("stop", "redis")
    response = httpx.post(
        "http://localhost:8000/api/demo/prove",
        json={"balances": [120], "limits": [100]},
        timeout=20.0,
    )
    assert response.status_code >= 500

    _compose("start", "redis")
    _wait_http("http://localhost:8000/healthz", timeout=120)


@pytest.mark.nightly
def test_trust_speed_and_metrics(compose_stack: None) -> None:
    trust = httpx.get("http://localhost:8000/api/trust-speed", timeout=20.0)
    assert trust.status_code == 200
    assert "native_verify_ms" in trust.json()

    prover_metrics = httpx.get("http://localhost:8001/metrics", timeout=20.0)
    verifier_metrics = httpx.get("http://localhost:8002/metrics", timeout=20.0)
    assert prover_metrics.status_code == 200
    assert verifier_metrics.status_code == 200
