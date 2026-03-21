from __future__ import annotations

import asyncio
import base64
from typing import Any

import pytest

from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


class _FakeVaultClient(VaultTransitClient):
    def __init__(self) -> None:
        super().__init__(addr="https://vault.local", token="token")
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, path, json))
        if path.startswith("/v1/transit/encrypt/"):
            return {"data": {"ciphertext": "vault:v1:Zm9v"}}
        if path.startswith("/v1/transit/decrypt/"):
            return {"data": {"plaintext": base64.b64encode(b'{"ok":true}').decode("utf-8")}}
        if path.startswith("/v1/transit/keys/"):
            return {"data": {"keys": {"1": {"public_key": "PUB1"}, "2": {"public_key": "PUB2"}}}}
        if path.startswith("/v1/transit/sign/"):
            return {"data": {"signature": "vault:v2:Zm9v"}}
        raise AssertionError(f"Unexpected path {path}")


def test_decode_signature_requires_transit_format() -> None:
    raw, version = VaultTransitClient.decode_signature("vault:v12:Zm9v")
    assert raw == b"foo"
    assert version == "12"

    with pytest.raises(ValueError):
        VaultTransitClient.decode_signature("Zm9v")


def test_encrypt_and_decrypt_roundtrip_calls_vault() -> None:
    client = _FakeVaultClient()
    ciphertext = asyncio.run(client.encrypt("vellum-data", b"abc"))
    plaintext = asyncio.run(client.decrypt("vellum-data", ciphertext))
    assert ciphertext.startswith("vault:v1:")
    assert plaintext == b'{"ok":true}'


def test_read_latest_public_key_picks_highest_version() -> None:
    client = _FakeVaultClient()
    version, key = asyncio.run(client.read_latest_public_key("vellum-jwt"))
    assert version == "2"
    assert key == "PUB2"


def test_public_key_cache_refreshes_missing_requested_version() -> None:
    class _ChangingClient:
        def __init__(self) -> None:
            self.counter = 0

        async def read_public_keys(self, key_name: str) -> dict[str, str]:
            _ = key_name
            self.counter += 1
            if self.counter == 1:
                return {"1": "PUB1"}
            return {"1": "PUB1", "2": "PUB2"}

    client = _ChangingClient()
    cache = VaultPublicKeyCache(client=client, ttl_seconds=60)  # type: ignore[arg-type]

    first = asyncio.run(cache.get_public_key(key_name="vellum-jwt"))
    second = asyncio.run(cache.get_public_key(key_name="vellum-jwt", key_version="2"))
    assert first == "PUB1"
    assert second == "PUB2"
