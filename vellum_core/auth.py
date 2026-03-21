"""JWT and bank-handshake authentication primitives for reference services."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from vellum_core.errors import APIError
from vellum_core.vault import VaultPublicKeyCache, VaultTransitClient


BEARER_SCHEME = HTTPBearer(auto_error=False)


class _MissingRedisClient:
    """Placeholder client used when redis dependency is not installed."""

    async def set(self, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise RuntimeError("redis package not installed")

    async def incr(self, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise RuntimeError("redis package not installed")

    async def expire(self, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise RuntimeError("redis package not installed")


def _create_redis_client(redis_url: str) -> Any:
    try:
        from redis.asyncio import Redis
    except ModuleNotFoundError:
        return _MissingRedisClient()
    return Redis.from_url(redis_url, decode_responses=True)


class RedisNonceReplayGuard:
    """Reject replayed or stale bank handshakes using Redis NX+TTL keys."""

    def __init__(
        self,
        *,
        redis_url: str,
        window_seconds: int,
        redis_client: Any | None = None,
    ) -> None:
        self.window_seconds = window_seconds
        self.redis = redis_client if redis_client is not None else _create_redis_client(redis_url)

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


class RedisSubmitRateLimiter:
    """Rate-limit submit requests per bank key (and source IP when present)."""

    def __init__(
        self,
        *,
        redis_url: str,
        max_per_minute: int,
        redis_client: Any | None = None,
    ) -> None:
        self.max_per_minute = max_per_minute
        self.redis = redis_client if redis_client is not None else _create_redis_client(redis_url)

    async def check_and_store(self, *, key_id: str, source_ip: str | None) -> None:
        if self.max_per_minute < 1:
            return
        window = int(time.time() // 60)
        client_marker = source_ip or "unknown"
        redis_key = f"vellum:ratelimit:submit:{key_id}:{client_marker}:{window}"
        count = await self.redis.incr(redis_key)
        if count == 1:
            await self.redis.expire(redis_key, 61)
        if count > self.max_per_minute:
            raise APIError(
                status_code=429,
                code="rate_limited",
                message="Submit rate limit exceeded",
                details={"limit_per_minute": self.max_per_minute},
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

    async def sign(
        self,
        *,
        subject: str,
        ttl_seconds: int = 3600,
        scopes: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> str:
        now = int(time.time())
        normalized_scopes = sorted({scope.strip() for scope in (scopes or set()) if scope.strip()})
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": subject,
            "iat": now,
            "nbf": now,
            "exp": now + ttl_seconds,
            "jti": str(uuid4()),
        }
        if normalized_scopes:
            payload["scope"] = " ".join(normalized_scopes)
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
        jwt_max_ttl_seconds: int,
        jwt_leeway_seconds: int,
        submit_rate_limit_per_minute: int,
        security_event_recorder: Callable[..., Awaitable[None]] | None = None,
        replay_guard: RedisNonceReplayGuard | None = None,
        submit_rate_limiter: RedisSubmitRateLimiter | None = None,
    ) -> None:
        self.vault_client = vault_client
        self.key_cache = key_cache
        self.jwt_key_name = jwt_key_name
        self.jwt_issuer = jwt_issuer
        self.jwt_audience = jwt_audience
        self.jwt_max_ttl_seconds = jwt_max_ttl_seconds
        self.jwt_leeway_seconds = jwt_leeway_seconds
        self.bank_key_mapping = bank_key_mapping
        self.security_event_recorder = security_event_recorder
        self.replay_guard = replay_guard or RedisNonceReplayGuard(
            redis_url=redis_url,
            window_seconds=nonce_window_seconds,
        )
        self.submit_rate_limiter = submit_rate_limiter or RedisSubmitRateLimiter(
            redis_url=redis_url,
            max_per_minute=submit_rate_limit_per_minute,
        )

    async def verify_jwt_credentials(
        self,
        credentials: HTTPAuthorizationCredentials | None,
        *,
        required_scopes: set[str] | None = None,
    ) -> dict[str, Any]:
        """Validate bearer token and return claims payload."""
        if credentials is None:
            await self._emit_security_event(
                event_type="jwt_missing",
                outcome="denied",
                details={"reason": "missing bearer token"},
            )
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
                options={"require": ["iss", "aud", "sub", "iat", "exp", "nbf", "jti"]},
                leeway=self.jwt_leeway_seconds,
            )
        except InvalidTokenError as exc:
            await self._emit_security_event(
                event_type="jwt_invalid",
                outcome="denied",
                details={"reason": str(exc)},
            )
            raise APIError(
                status_code=401,
                code="invalid_token",
                message="JWT validation failed",
                details={"reason": str(exc)},
            ) from exc

        token_lifetime = int(claims["exp"]) - int(claims["iat"])
        if token_lifetime > self.jwt_max_ttl_seconds:
            await self._emit_security_event(
                event_type="jwt_ttl_exceeded",
                outcome="denied",
                actor=str(claims.get("sub")),
                details={"max_ttl_seconds": self.jwt_max_ttl_seconds},
            )
            raise APIError(
                status_code=401,
                code="invalid_token_ttl",
                message="JWT lifetime exceeds configured maximum",
                details={"max_ttl_seconds": self.jwt_max_ttl_seconds},
            )

        if required_scopes:
            claim_scopes = _extract_scope_set(claims)
            if not required_scopes.issubset(claim_scopes):
                await self._emit_security_event(
                    event_type="jwt_scope_denied",
                    outcome="denied",
                    actor=str(claims.get("sub")),
                    details={
                        "required_scopes": sorted(required_scopes),
                        "granted_scopes": sorted(claim_scopes),
                    },
                )
                raise APIError(
                    status_code=403,
                    code="insufficient_scope",
                    message="JWT does not contain required scopes",
                    details={"required_scopes": sorted(required_scopes)},
                )

        return claims

    async def verify_handshake(self, request: Request, raw_body: bytes) -> str:
        """Validate bank headers, signature, and replay protection for request body."""
        source_ip = _client_ip(request)
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
            await self._emit_security_event(
                event_type="handshake_headers_missing",
                outcome="denied",
                source_ip=source_ip,
                details={"missing_headers": missing},
            )
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
        canonical = build_canonical_request_string(
            method=request.method,
            path=request.url.path,
            timestamp=timestamp_raw,
            nonce=nonce,
            raw_body=raw_body,
        )

        bank_vault_key = self.bank_key_mapping.get(key_id)
        if bank_vault_key is None:
            await self._emit_security_event(
                event_type="handshake_unknown_key",
                outcome="denied",
                source_ip=source_ip,
                details={"key_id": key_id},
            )
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
            await self._emit_security_event(
                event_type="handshake_signature_invalid",
                outcome="denied",
                source_ip=source_ip,
                details={"key_id": key_id},
            )
            raise APIError(
                status_code=401,
                code="invalid_handshake_signature",
                message="Bank request signature invalid",
            )

        try:
            await self.replay_guard.check_and_store(
                key_id=key_id,
                nonce=nonce,
                timestamp=timestamp_epoch,
            )
        except APIError as exc:
            await self._emit_security_event(
                event_type=f"handshake_{exc.code}",
                outcome="denied",
                source_ip=source_ip,
                details={"key_id": key_id},
            )
            raise
        try:
            await self.submit_rate_limiter.check_and_store(
                key_id=key_id,
                source_ip=source_ip,
            )
        except APIError:
            await self._emit_security_event(
                event_type="submit_rate_limited",
                outcome="denied",
                source_ip=source_ip,
                details={"key_id": key_id},
            )
            raise
        return key_id

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

    async def _emit_security_event(
        self,
        *,
        event_type: str,
        outcome: str,
        actor: str | None = None,
        source_ip: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        recorder = self.security_event_recorder
        if recorder is None:
            return
        try:
            await recorder(
                event_type=event_type,
                outcome=outcome,
                actor=actor,
                source_ip=source_ip,
                details=details or {},
            )
        except Exception:
            return


def _verify_ed25519_signature(public_key_pem: str, payload: bytes, signature: bytes) -> bool:
    """Return True when signature verifies for payload under provided key."""
    try:
        key = _load_ed25519_public_key(public_key_pem)
        key.verify(signature, payload)
        return True
    except Exception:
        return False


def build_canonical_request_string(
    *,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    raw_body: bytes,
) -> str:
    """Build canonical request string used for bank request signatures."""
    body_hash = hashlib.sha256(raw_body).hexdigest()
    return f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"


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


def _extract_scope_set(claims: dict[str, Any]) -> set[str]:
    scopes: set[str] = set()
    scope_value = claims.get("scope")
    if isinstance(scope_value, str):
        scopes.update({part.strip() for part in scope_value.split(" ") if part.strip()})
    scopes_value = claims.get("scopes")
    if isinstance(scopes_value, list):
        scopes.update({str(part).strip() for part in scopes_value if str(part).strip()})
    return scopes


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return None
