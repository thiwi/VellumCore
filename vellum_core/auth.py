"""JWT and bank-handshake authentication primitives for reference services."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from redis.asyncio import Redis

from vellum_core.errors import APIError
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


BEARER_SCHEME = HTTPBearer(auto_error=False)


class RedisNonceReplayGuard:
    """Reject replayed or stale bank handshakes using Redis NX+TTL keys."""

    def __init__(self, *, redis_url: str, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def check_and_store(self, *, key_id: str, nonce: str, timestamp: float) -> None:
        now = time.time()
        if abs(now - timestamp) > self.window_seconds:
            raise APIError(
                status_code=401,
                code="stale_request",
                message="Request timestamp outside allowed window",
                details={"window_seconds": self.window_seconds},
            )

        redis_key = f"vellum:nonce:{key_id}:{nonce}"
        stored = await self.redis.set(redis_key, str(timestamp), ex=self.window_seconds, nx=True)
        if not stored:
            raise APIError(
                status_code=409,
                code="nonce_replay",
                message="Replay detected for nonce",
                details={"nonce": nonce},
            )


class VaultJWTSigner:
    """Create EdDSA JWTs using Vault Transit signing keys."""

    def __init__(
        self,
        *,
        vault_client: VaultTransitClient,
        key_name: str,
        issuer: str,
        audience: str,
    ) -> None:
        self.vault_client = vault_client
        self.key_name = key_name
        self.issuer = issuer
        self.audience = audience

    async def sign(self, *, subject: str, ttl_seconds: int = 3600) -> str:
        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": subject,
            "iat": now,
            "exp": now + ttl_seconds,
        }
        header = {"alg": "EdDSA", "typ": "JWT"}

        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

        signature = await self.vault_client.sign(self.key_name, signing_input)
        sig_b64 = _b64url_encode(signature.raw)
        return f"{header_b64}.{payload_b64}.{sig_b64}"


class AuthManager:
    """Central auth facade for JWT validation and bank request handshake checks."""

    def __init__(
        self,
        *,
        vault_client: VaultTransitClient,
        key_cache: VaultPublicKeyCache,
        jwt_key_name: str,
        jwt_issuer: str,
        jwt_audience: str,
        bank_key_mapping: dict[str, str],
        redis_url: str,
        nonce_window_seconds: int,
    ) -> None:
        self.vault_client = vault_client
        self.key_cache = key_cache
        self.jwt_key_name = jwt_key_name
        self.jwt_issuer = jwt_issuer
        self.jwt_audience = jwt_audience
        self.bank_key_mapping = bank_key_mapping
        self.replay_guard = RedisNonceReplayGuard(
            redis_url=redis_url,
            window_seconds=nonce_window_seconds,
        )

    async def verify_jwt_credentials(
        self, credentials: HTTPAuthorizationCredentials | None
    ) -> dict[str, Any]:
        """Validate bearer token and return claims payload."""
        if credentials is None:
            raise APIError(
                status_code=401,
                code="missing_token",
                message="Missing bearer token",
            )

        public_key_value = await self.key_cache.get_public_key(key_name=self.jwt_key_name)
        token = credentials.credentials
        try:
            claims = jwt.decode(
                token,
                _load_ed25519_public_key(public_key_value),
                algorithms=["EdDSA"],
                issuer=self.jwt_issuer,
                audience=self.jwt_audience,
                options={"require": ["iss", "aud", "sub", "iat", "exp"]},
            )
        except InvalidTokenError as exc:
            raise APIError(
                status_code=401,
                code="invalid_token",
                message="JWT validation failed",
                details={"reason": str(exc)},
            ) from exc
        return claims

    async def verify_handshake(self, request: Request, raw_body: bytes) -> None:
        """Validate bank headers, signature, and replay protection for request body."""
        key_id = request.headers.get("X-Bank-Key-Id")
        timestamp_raw = request.headers.get("X-Bank-Timestamp")
        nonce = request.headers.get("X-Bank-Nonce")
        signature_value = request.headers.get("X-Bank-Signature")

        missing = [
            name
            for name, value in {
                "X-Bank-Key-Id": key_id,
                "X-Bank-Timestamp": timestamp_raw,
                "X-Bank-Nonce": nonce,
                "X-Bank-Signature": signature_value,
            }.items()
            if not value
        ]
        if missing:
            raise APIError(
                status_code=401,
                code="missing_handshake_headers",
                message="Missing bank handshake headers",
                details={"missing_headers": missing},
            )

        assert key_id is not None
        assert timestamp_raw is not None
        assert nonce is not None
        assert signature_value is not None

        timestamp_epoch = self._parse_timestamp(timestamp_raw)
        canonical = self._canonical_request_string(
            method=request.method,
            path=request.url.path,
            timestamp=timestamp_raw,
            nonce=nonce,
            raw_body=raw_body,
        )

        bank_vault_key = self.bank_key_mapping.get(key_id)
        if bank_vault_key is None:
            raise APIError(
                status_code=401,
                code="unknown_bank_key",
                message="Unknown bank key id",
                details={"key_id": key_id},
            )

        signature_raw, signature_key_version = VaultTransitClient.decode_signature(signature_value)
        public_key_pem = await self.key_cache.get_public_key(
            key_name=bank_vault_key,
            key_version=signature_key_version,
        )
        if not _verify_ed25519_signature(public_key_pem, canonical.encode("utf-8"), signature_raw):
            raise APIError(
                status_code=401,
                code="invalid_handshake_signature",
                message="Bank request signature invalid",
            )

        await self.replay_guard.check_and_store(
            key_id=key_id,
            nonce=nonce,
            timestamp=timestamp_epoch,
        )

    @staticmethod
    def _canonical_request_string(
        *,
        method: str,
        path: str,
        timestamp: str,
        nonce: str,
        raw_body: bytes,
    ) -> str:
        """Build deterministic signed string used by both producer and verifier."""
        body_hash = hashlib.sha256(raw_body).hexdigest()
        return f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"

    @staticmethod
    def _parse_timestamp(timestamp_raw: str) -> float:
        if timestamp_raw.isdigit():
            return float(timestamp_raw)
        try:
            parsed = datetime.fromisoformat(timestamp_raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError as exc:
            raise APIError(
                status_code=401,
                code="invalid_timestamp",
                message="X-Bank-Timestamp must be unix seconds or ISO8601",
                details={"value": timestamp_raw},
            ) from exc


def _verify_ed25519_signature(public_key_pem: str, payload: bytes, signature: bytes) -> bool:
    """Return True when signature verifies for payload under provided key."""
    try:
        key = _load_ed25519_public_key(public_key_pem)
        key.verify(signature, payload)
        return True
    except Exception:
        return False


def _load_ed25519_public_key(public_key_value: str) -> Ed25519PublicKey:
    """Load Ed25519 key from PEM or raw base64 key material."""
    try:
        key = load_pem_public_key(public_key_value.encode("utf-8"))
        if isinstance(key, Ed25519PublicKey):
            return key
    except Exception:
        pass

    # Vault transit ed25519 exposes raw 32-byte public key as base64.
    raw = base64.b64decode(public_key_value)
    return Ed25519PublicKey.from_public_bytes(raw)


def _b64url_encode(raw: bytes) -> str:
    """Encode bytes to unpadded base64url string."""
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
