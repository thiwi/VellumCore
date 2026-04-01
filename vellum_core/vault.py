"""Vault Transit client and public-key cache helpers."""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx


_VAULT_SIG_PATTERN = re.compile(r"^vault:v(?P<version>\d+):(?P<sig>.+)$")


@dataclass(frozen=True)
class VaultSignature:
    """Decoded Vault Transit signature and metadata."""

    raw: bytes
    encoded: str
    key_version: str


class VaultTransitClient:
    """Minimal async client for Vault Transit signing and key retrieval."""

    def __init__(
        self,
        *,
        addr: str,
        token: str,
        timeout: float = 5.0,
        tls_ca_bundle: str | None = None,
    ) -> None:
        self.addr = addr.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._tls_verify: bool | str = tls_ca_bundle or True
        self._client: httpx.AsyncClient | None = None

    async def sign(self, key_name: str, payload: bytes) -> VaultSignature:
        """Sign bytes with transit key and return structured signature data."""
        data = {"input": base64.b64encode(payload).decode("utf-8")}
        body = await self._request("POST", f"/v1/transit/sign/{key_name}", json=data)
        signature = body["data"]["signature"]
        raw, key_version = self.decode_signature(signature)
        return VaultSignature(raw=raw, encoded=signature, key_version=key_version)

    async def read_public_keys(self, key_name: str) -> dict[str, str]:
        """Return Vault public keys keyed by key version."""
        body = await self._request("GET", f"/v1/transit/keys/{key_name}")
        keys = body.get("data", {}).get("keys", {})
        result: dict[str, str] = {}
        for version, payload in keys.items():
            public_key = payload.get("public_key") if isinstance(payload, dict) else None
            if isinstance(version, str) and isinstance(public_key, str):
                result[version] = public_key
        return result

    async def read_latest_public_key(self, key_name: str) -> tuple[str, str]:
        """Return latest `(version, public_key)` pair for a key."""
        keys = await self.read_public_keys(key_name)
        if not keys:
            raise ValueError(f"Vault key '{key_name}' has no public keys")
        latest_version = str(max(int(v) for v in keys.keys()))
        return latest_version, keys[latest_version]

    async def encrypt(self, key_name: str, plaintext: bytes) -> str:
        """Encrypt bytes with transit key and return encoded Vault ciphertext."""
        data = {"plaintext": base64.b64encode(plaintext).decode("utf-8")}
        body = await self._request("POST", f"/v1/transit/encrypt/{key_name}", json=data)
        return str(body["data"]["ciphertext"])

    async def decrypt(self, key_name: str, ciphertext: str) -> bytes:
        """Decrypt encoded Vault ciphertext and return plaintext bytes."""
        data = {"ciphertext": ciphertext}
        body = await self._request("POST", f"/v1/transit/decrypt/{key_name}", json=data)
        plaintext_b64 = str(body["data"]["plaintext"])
        return base64.b64decode(plaintext_b64)

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an authenticated Vault HTTP request and decode JSON body."""
        headers = {"X-Vault-Token": self.token}
        client = self._client
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=self.timeout, verify=self._tls_verify)
            self._client = client
        response = await client.request(method, f"{self.addr}{path}", headers=headers, json=json)
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        """Close shared HTTP client used by this Vault client."""
        client = self._client
        if client is None:
            return
        self._client = None
        if not client.is_closed:
            await client.aclose()

    @staticmethod
    def decode_signature(signature: str) -> tuple[bytes, str]:
        """Decode transit signature format `vault:vN:<base64>`."""
        matched = _VAULT_SIG_PATTERN.match(signature)
        if matched is None:
            raise ValueError("Vault signature must use transit format vault:vN:<base64>")
        key_version = matched.group("version")
        sig_blob = matched.group("sig")
        return base64.b64decode(sig_blob), key_version


class VaultPublicKeyCache:
    """TTL cache around Vault public-key lookups by key name/version."""

    def __init__(
        self,
        *,
        client: VaultTransitClient,
        ttl_seconds: int = 300,
    ) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, dict[str, str]]] = {}

    async def get_public_key(self, *, key_name: str, key_version: str | None = None) -> str:
        """Return a public key value for requested version (or latest)."""
        versions = await self._get_versions(key_name)
        if not versions:
            raise ValueError(f"No public keys found in Vault for key '{key_name}'")
        if key_version is None:
            latest = str(max(int(v) for v in versions.keys()))
            return versions[latest]
        if key_version in versions:
            return versions[key_version]
        # Refresh once if requested version is not cached.
        self._cache.pop(key_name, None)
        versions = await self._get_versions(key_name)
        if key_version not in versions:
            raise ValueError(f"Public key version '{key_version}' not found for '{key_name}'")
        return versions[key_version]

    async def _get_versions(self, key_name: str) -> dict[str, str]:
        now = time.time()
        cached = self._cache.get(key_name)
        if cached is not None:
            expires_at, versions = cached
            if expires_at > now:
                return versions

        versions = await self.client.read_public_keys(key_name)
        self._cache[key_name] = (now + self.ttl_seconds, versions)
        return versions
