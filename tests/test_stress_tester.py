from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

import stress_tester
from vellum_core.auth import build_canonical_request_string


def test_parse_args_accepts_vault_jwt_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stress_tester.py",
            "--vault-jwt-key",
            "custom-jwt-key",
            "--vault-bank-key",
            "custom-bank-key",
        ],
    )
    args = stress_tester.parse_args()
    assert args.vault_jwt_key == "custom-jwt-key"
    assert args.vault_bank_key == "custom-bank-key"


def test_build_jwt_token_uses_vault_signer(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}

    class _FakeSigner:
        def __init__(self, *, vault_client: object, key_name: str, issuer: str, audience: str) -> None:
            observed["init"] = (vault_client, key_name, issuer, audience)

        async def sign(
            self,
            *,
            subject: str,
            ttl_seconds: int = 3600,
            scopes: set[str] | list[str] | tuple[str, ...] | None = None,
        ) -> str:
            observed["sign"] = (subject, ttl_seconds, sorted(scopes or []))
            return "jwt-token"

    monkeypatch.setattr(stress_tester, "VaultJWTSigner", _FakeSigner)
    token = asyncio.run(
        stress_tester.build_jwt_token(
            vault_client=object(),  # type: ignore[arg-type]
            vault_jwt_key="vellum-jwt",
            jwt_issuer="bank.local",
            jwt_audience="sentinel-zk",
        )
    )
    assert token == "jwt-token"
    assert observed["init"][1:] == ("vellum-jwt", "bank.local", "sentinel-zk")
    assert observed["sign"] == ("stress-tester", 600, ["proofs:read", "proofs:write"])


def test_build_handshake_headers_uses_canonical_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _fake_sign(
        *,
        vault_client: object,
        vault_bank_key: str,
        payload: bytes,
    ) -> str:
        captured["vault_client"] = vault_client
        captured["vault_bank_key"] = vault_bank_key
        captured["payload"] = payload
        return "vault:v1:abc"

    monkeypatch.setattr(stress_tester, "_vault_sign", _fake_sign)
    monkeypatch.setattr(stress_tester.time, "time", lambda: 1700000000)
    monkeypatch.setattr(stress_tester, "uuid4", lambda: "nonce-42")

    body = b'{"x":1}'
    headers = asyncio.run(
        stress_tester.build_handshake_headers(
            method="POST",
            path="/v1/proofs/batch",
            body=body,
            bank_key_id="bank-key-1",
            vault_client="client",  # type: ignore[arg-type]
            vault_bank_key="vellum-bank",
        )
    )

    assert headers["X-Bank-Key-Id"] == "bank-key-1"
    assert headers["X-Bank-Timestamp"] == "1700000000"
    assert headers["X-Bank-Nonce"] == "nonce-42"
    assert headers["X-Bank-Signature"] == "vault:v1:abc"

    expected = build_canonical_request_string(
        method="POST",
        path="/v1/proofs/batch",
        timestamp="1700000000",
        nonce="nonce-42",
        raw_body=body,
    ).encode("utf-8")
    assert captured["payload"] == expected
    assert captured["vault_bank_key"] == "vellum-bank"


def test_detect_prover_container_without_docker_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "docker":
            raise ModuleNotFoundError("No module named 'docker'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(RuntimeError, match="docker"):
        stress_tester.detect_prover_container()


def test_monitor_resources_without_docker_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "docker":
            raise ModuleNotFoundError("No module named 'docker'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    stop = asyncio.Event()
    with pytest.raises(RuntimeError, match="docker"):
        asyncio.run(stress_tester.monitor_resources(container_id="x", stop=stop))


def test_extract_cpu_percent_handles_zero_system_delta() -> None:
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 10, "percpu_usage": [1]}, "system_cpu_usage": 100, "online_cpus": 1},
        "precpu_stats": {"cpu_usage": {"total_usage": 5}, "system_cpu_usage": 100},
    }
    assert stress_tester.extract_cpu_percent(stats) == 0.0


def test_percentile_empty_returns_zero() -> None:
    assert stress_tester.percentile([], 0.95) == 0.0


def test_compute_thermal_indicator_small_sample() -> None:
    result = stress_tester.compute_thermal_indicator([1.0, 1.1, 1.2], 90.0)
    assert result["throttling_suspected"] is False
    assert result["degradation_percent"] == 0.0
