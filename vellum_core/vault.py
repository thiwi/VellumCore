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
    raw: bytes
    encoded: str
    key_version: str


class VaultTransitClient:
    def __init__(self, *, addr: str, token: str, timeout: float = 5.0) -> None:
        self.addr = addr.rstrip("/")
        self.token = token
        self.timeout = timeout

    async def sign(self, key_name: str, payload: bytes) -> VaultSignature:
        data = {"input": base64.b64encode(payload).decode("utf-8")}
        body = await self._request("POST", f"/v1/transit/sign/{key_name}", json=data)
        signature = body["data"]["signature"]
        raw, key_version = self.decode_signature(signature)
        return VaultSignature(raw=raw, encoded=signature, key_version=key_version)

    async def read_public_keys(self, key_name: str) -> dict[str, str]:
        body = await self._request("GET", f"/v1/transit/keys/{key_name}")
        keys = body.get("data", {}).get("keys", {})
        result: dict[str, str] = {}
        for version, payload in keys.items():
            public_key = payload.get("public_key") if isinstance(payload, dict) else None
            if isinstance(version, str) and isinstance(public_key, str):
                result[version] = public_key
        return result

    async def read_latest_public_key(self, key_name: str) -> tuple[str, str]:
        keys = await self.read_public_keys(key_name)
        if not keys:
            raise ValueError(f"Vault key '{key_name}' has no public keys")
        latest_version = str(max(int(v) for v in keys.keys()))
        return latest_version, keys[latest_version]

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"X-Vault-Token": self.token}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, f"{self.addr}{path}", headers=headers, json=json)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def decode_signature(signature: str) -> tuple[bytes, str]:
        matched = _VAULT_SIG_PATTERN.match(signature)
        if matched is not None:
            key_version = matched.group("version")
            sig_blob = matched.group("sig")
            return base64.b64decode(sig_blob), key_version

        # Backward fallback: plain base64 signature treated as version 0.
        return base64.b64decode(signature), "0"


class VaultPublicKeyCache:
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
