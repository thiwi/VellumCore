"""Tests for Auth security."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.security import HTTPAuthorizationCredentials
from types import SimpleNamespace

from vellum_core.auth import (
    AuthManager,
    RedisNonceReplayGuard,
    RedisSubmitRateLimiter,
    build_canonical_request_string,
)
from vellum_core.errors import APIError

pytestmark = pytest.mark.security


class _FakeKeyCache:
    def __init__(self, public_key_pem: str) -> None:
        self.public_key_pem = public_key_pem

    async def get_public_key(self, *, key_name: str, key_version: str | None = None) -> str:
        _ = (key_name, key_version)
        return self.public_key_pem


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        current = self.values.get(key, 0) + 1
        self.values[key] = current
        return current

    async def expire(self, key: str, ttl: int) -> bool:
        _ = (key, ttl)
        return True


class _FakeNonceRedis:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    async def set(self, key: str, value: str, ex: int, nx: bool) -> bool:
        _ = (value, ex, nx)
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _ReplayGuard:
    def __init__(self, exc: APIError | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple[str, str, float]] = []

    async def check_and_store(self, *, key_id: str, nonce: str, timestamp: float) -> None:
        self.calls.append((key_id, nonce, timestamp))
        if self.exc is not None:
            raise self.exc


class _RateLimiter:
    def __init__(self, exc: APIError | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple[str, str | None]] = []

    async def check_and_store(self, *, key_id: str, source_ip: str | None) -> None:
        self.calls.append((key_id, source_ip))
        if self.exc is not None:
            raise self.exc


class _Request:
    def __init__(
        self,
        headers: dict[str, str],
        *,
        method: str = "POST",
        path: str = "/v1/proofs/batch",
        client_host: str | None = "127.0.0.1",
    ) -> None:
        self.headers = headers
        self.method = method
        self.url = SimpleNamespace(path=path)
        self.client = (
            None if client_host is None else SimpleNamespace(host=client_host)
        )


def _build_auth_manager(
    private_key: Ed25519PrivateKey,
    *,
    max_ttl: int = 900,
    recorder: _Recorder | None = None,
    replay_guard: _ReplayGuard | None = None,
    rate_limiter: _RateLimiter | None = None,
) -> AuthManager:
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return AuthManager(
        vault_client=object(),  # type: ignore[arg-type]
        key_cache=_FakeKeyCache(public_key),  # type: ignore[arg-type]
        jwt_key_name="vellum-jwt",
        jwt_issuer="bank.local",
        jwt_audience="sentinel-zk",
        bank_key_mapping={"bank-key-1": "vellum-bank"},
        redis_url="redis://localhost:6379/1",
        nonce_window_seconds=300,
        jwt_max_ttl_seconds=max_ttl,
        jwt_leeway_seconds=0,
        submit_rate_limit_per_minute=30,
        security_event_recorder=recorder,
        replay_guard=replay_guard,  # type: ignore[arg-type]
        submit_rate_limiter=rate_limiter,  # type: ignore[arg-type]
    )


def _token(
    *,
    private_key: Ed25519PrivateKey,
    ttl_seconds: int = 600,
    include_nbf: bool = True,
    include_jti: bool = True,
    scope: str | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "bank.local",
        "aud": "sentinel-zk",
        "sub": "tester",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if include_nbf:
        claims["nbf"] = now
    if include_jti:
        claims["jti"] = str(uuid4())
    if scope is not None:
        claims["scope"] = scope
    return jwt.encode(claims, private_key, algorithm="EdDSA")


def test_jwt_requires_nbf_and_jti() -> None:
    private_key = Ed25519PrivateKey.generate()
    auth = _build_auth_manager(private_key)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=_token(private_key=private_key, include_nbf=False, include_jti=False),
    )

    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_jwt_credentials(credentials))
    assert exc.value.code == "invalid_token"


def test_jwt_rejects_excessive_ttl() -> None:
    private_key = Ed25519PrivateKey.generate()
    auth = _build_auth_manager(private_key, max_ttl=900)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=_token(private_key=private_key, ttl_seconds=3600),
    )

    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_jwt_credentials(credentials))
    assert exc.value.code == "invalid_token_ttl"


def test_jwt_scope_enforcement() -> None:
    private_key = Ed25519PrivateKey.generate()
    auth = _build_auth_manager(private_key)
    denied = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=_token(private_key=private_key, scope="proofs:read"),
    )

    with pytest.raises(APIError) as exc:
        asyncio.run(
            auth.verify_jwt_credentials(
                denied,
                required_scopes={"proofs:write"},
            )
        )
    assert exc.value.code == "insufficient_scope"

    granted = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=_token(private_key=private_key, scope="proofs:write proofs:read"),
    )
    claims = asyncio.run(
        auth.verify_jwt_credentials(
            granted,
            required_scopes={"proofs:write"},
        )
    )
    assert claims["sub"] == "tester"


def test_submit_rate_limiter_enforces_limit() -> None:
    limiter = RedisSubmitRateLimiter(redis_url="redis://localhost:6379/1", max_per_minute=2)
    limiter.redis = _FakeRedis()  # type: ignore[assignment]

    asyncio.run(limiter.check_and_store(key_id="bank-key-1", source_ip="127.0.0.1"))
    asyncio.run(limiter.check_and_store(key_id="bank-key-1", source_ip="127.0.0.1"))
    with pytest.raises(APIError) as exc:
        asyncio.run(limiter.check_and_store(key_id="bank-key-1", source_ip="127.0.0.1"))
    assert exc.value.code == "rate_limited"


def test_build_canonical_request_string_is_deterministic() -> None:
    body = b'{"amount":120}'
    expected_hash = hashlib.sha256(body).hexdigest()
    canonical = build_canonical_request_string(
        method="POST",
        path="/v1/proofs/batch",
        timestamp="1700000000",
        nonce="nonce-1",
        raw_body=body,
    )
    assert canonical == f"POST\n/v1/proofs/batch\n1700000000\nnonce-1\n{expected_hash}"


def test_nonce_replay_guard_rejects_second_use() -> None:
    guard = RedisNonceReplayGuard(
        redis_url="redis://localhost:6379/1",
        window_seconds=300,
        redis_client=_FakeNonceRedis(),
    )
    now = time.time()
    asyncio.run(guard.check_and_store(key_id="bank-key-1", nonce="n-1", timestamp=now))
    with pytest.raises(APIError) as exc:
        asyncio.run(guard.check_and_store(key_id="bank-key-1", nonce="n-1", timestamp=now))
    assert exc.value.code == "nonce_replay"


def test_nonce_replay_guard_rejects_stale_request() -> None:
    guard = RedisNonceReplayGuard(
        redis_url="redis://localhost:6379/1",
        window_seconds=10,
        redis_client=_FakeNonceRedis(),
    )
    with pytest.raises(APIError) as exc:
        asyncio.run(
            guard.check_and_store(
                key_id="bank-key-1",
                nonce="n-2",
                timestamp=time.time() - 60,
            )
        )
    assert exc.value.code == "stale_request"


def test_submit_rate_limiter_missing_redis_dependency_raises_runtime_error() -> None:
    limiter = RedisSubmitRateLimiter(redis_url="redis://localhost:6379/1", max_per_minute=1)
    with pytest.raises(RuntimeError, match="redis package not installed"):
        asyncio.run(limiter.check_and_store(key_id="bank-key-1", source_ip=None))


def test_nonce_guard_missing_redis_dependency_raises_runtime_error() -> None:
    guard = RedisNonceReplayGuard(redis_url="redis://localhost:6379/1", window_seconds=30)
    with pytest.raises(RuntimeError, match="redis package not installed"):
        asyncio.run(
            guard.check_and_store(
                key_id="bank-key-1",
                nonce="n-1",
                timestamp=time.time(),
            )
        )


def test_verify_jwt_missing_token_emits_event() -> None:
    recorder = _Recorder()
    auth = _build_auth_manager(Ed25519PrivateKey.generate(), recorder=recorder)
    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_jwt_credentials(None))
    assert exc.value.code == "missing_token"
    assert recorder.events[-1]["event_type"] == "jwt_missing"


def test_verify_jwt_invalid_token_emits_event() -> None:
    recorder = _Recorder()
    auth = _build_auth_manager(Ed25519PrivateKey.generate(), recorder=recorder)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")
    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_jwt_credentials(creds))
    assert exc.value.code == "invalid_token"
    assert recorder.events[-1]["event_type"] == "jwt_invalid"


def test_verify_jwt_accepts_scopes_claim_list() -> None:
    private_key = Ed25519PrivateKey.generate()
    auth = _build_auth_manager(private_key)
    now = int(time.time())
    claims = {
        "iss": "bank.local",
        "aud": "sentinel-zk",
        "sub": "tester",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "jti": str(uuid4()),
        "scopes": ["proofs:write", "proofs:read"],
    }
    token = jwt.encode(claims, private_key, algorithm="EdDSA")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    resolved = asyncio.run(
        auth.verify_jwt_credentials(creds, required_scopes={"proofs:write"})
    )
    assert resolved["sub"] == "tester"


def test_verify_handshake_rejects_missing_headers_and_records_event() -> None:
    recorder = _Recorder()
    auth = _build_auth_manager(Ed25519PrivateKey.generate(), recorder=recorder)
    request = _Request(headers={"X-Bank-Key-Id": "bank-key-1"})
    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_handshake(request, b"{}"))  # type: ignore[arg-type]
    assert exc.value.code == "missing_handshake_headers"
    assert recorder.events[-1]["event_type"] == "handshake_headers_missing"


def test_verify_handshake_rejects_unknown_key() -> None:
    recorder = _Recorder()
    auth = _build_auth_manager(Ed25519PrivateKey.generate(), recorder=recorder)
    sig = "vault:v1:" + base64.b64encode(b"sig").decode("utf-8")
    request = _Request(
        headers={
            "X-Bank-Key-Id": "unknown",
            "X-Bank-Timestamp": str(int(time.time())),
            "X-Bank-Nonce": "n1",
            "X-Bank-Signature": sig,
        }
    )
    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_handshake(request, b"{}"))  # type: ignore[arg-type]
    assert exc.value.code == "unknown_bank_key"
    assert recorder.events[-1]["event_type"] == "handshake_unknown_key"


def test_verify_handshake_rejects_invalid_timestamp() -> None:
    auth = _build_auth_manager(Ed25519PrivateKey.generate())
    sig = "vault:v1:" + base64.b64encode(b"sig").decode("utf-8")
    request = _Request(
        headers={
            "X-Bank-Key-Id": "bank-key-1",
            "X-Bank-Timestamp": "not-a-timestamp",
            "X-Bank-Nonce": "n1",
            "X-Bank-Signature": sig,
        }
    )
    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_handshake(request, b"{}"))  # type: ignore[arg-type]
    assert exc.value.code == "invalid_timestamp"


def test_verify_handshake_rejects_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    auth = _build_auth_manager(Ed25519PrivateKey.generate(), recorder=recorder)
    monkeypatch.setattr("vellum_core.auth._verify_ed25519_signature", lambda *args: False)
    sig = "vault:v1:" + base64.b64encode(b"sig").decode("utf-8")
    request = _Request(
        headers={
            "X-Bank-Key-Id": "bank-key-1",
            "X-Bank-Timestamp": str(int(time.time())),
            "X-Bank-Nonce": "n1",
            "X-Bank-Signature": sig,
            "X-Forwarded-For": "10.0.0.1, 10.0.0.2",
        }
    )
    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_handshake(request, b"{}"))  # type: ignore[arg-type]
    assert exc.value.code == "invalid_handshake_signature"
    assert recorder.events[-1]["event_type"] == "handshake_signature_invalid"
    assert recorder.events[-1]["source_ip"] == "10.0.0.1"


def test_verify_handshake_replay_and_rate_limit_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    replay_exc = APIError(status_code=409, code="nonce_replay", message="Replay", details={})
    rate_exc = APIError(status_code=429, code="rate_limited", message="Rate", details={})
    recorder = _Recorder()
    replay = _ReplayGuard(exc=replay_exc)
    rate = _RateLimiter(exc=None)
    auth = _build_auth_manager(
        Ed25519PrivateKey.generate(),
        recorder=recorder,
        replay_guard=replay,
        rate_limiter=rate,
    )
    monkeypatch.setattr("vellum_core.auth._verify_ed25519_signature", lambda *args: True)
    sig = "vault:v1:" + base64.b64encode(b"sig").decode("utf-8")
    request = _Request(
        headers={
            "X-Bank-Key-Id": "bank-key-1",
            "X-Bank-Timestamp": str(int(time.time())),
            "X-Bank-Nonce": "n1",
            "X-Bank-Signature": sig,
        }
    )
    with pytest.raises(APIError) as exc:
        asyncio.run(auth.verify_handshake(request, b"{}"))  # type: ignore[arg-type]
    assert exc.value.code == "nonce_replay"
    assert recorder.events[-1]["event_type"] == "handshake_nonce_replay"

    recorder_2 = _Recorder()
    replay_ok = _ReplayGuard(exc=None)
    rate_bad = _RateLimiter(exc=rate_exc)
    auth_2 = _build_auth_manager(
        Ed25519PrivateKey.generate(),
        recorder=recorder_2,
        replay_guard=replay_ok,
        rate_limiter=rate_bad,
    )
    with pytest.raises(APIError) as exc2:
        asyncio.run(auth_2.verify_handshake(request, b"{}"))  # type: ignore[arg-type]
    assert exc2.value.code == "rate_limited"
    assert recorder_2.events[-1]["event_type"] == "submit_rate_limited"


def test_verify_handshake_success_returns_key_id(monkeypatch: pytest.MonkeyPatch) -> None:
    replay = _ReplayGuard(exc=None)
    rate = _RateLimiter(exc=None)
    auth = _build_auth_manager(
        Ed25519PrivateKey.generate(),
        replay_guard=replay,
        rate_limiter=rate,
    )
    monkeypatch.setattr("vellum_core.auth._verify_ed25519_signature", lambda *args: True)
    sig = "vault:v12:" + base64.b64encode(b"sig").decode("utf-8")
    request = _Request(
        headers={
            "X-Bank-Key-Id": "bank-key-1",
            "X-Bank-Timestamp": str(int(time.time())),
            "X-Bank-Nonce": "nonce-ok",
            "X-Bank-Signature": sig,
        },
        client_host="192.168.1.9",
    )
    key_id = asyncio.run(auth.verify_handshake(request, b'{"ok":true}'))  # type: ignore[arg-type]
    assert key_id == "bank-key-1"
    assert replay.calls and replay.calls[0][0] == "bank-key-1"
    assert rate.calls and rate.calls[0] == ("bank-key-1", "192.168.1.9")


def test_verify_handshake_success_without_client_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    replay = _ReplayGuard(exc=None)
    rate = _RateLimiter(exc=None)
    auth = _build_auth_manager(
        Ed25519PrivateKey.generate(),
        replay_guard=replay,
        rate_limiter=rate,
    )
    monkeypatch.setattr("vellum_core.auth._verify_ed25519_signature", lambda *args: True)
    sig = "vault:v1:" + base64.b64encode(b"sig").decode("utf-8")
    request = _Request(
        headers={
            "X-Bank-Key-Id": "bank-key-1",
            "X-Bank-Timestamp": str(int(time.time())),
            "X-Bank-Nonce": "nonce-ok",
            "X-Bank-Signature": sig,
        },
        client_host=None,
    )
    key_id = asyncio.run(auth.verify_handshake(request, b'{"ok":true}'))  # type: ignore[arg-type]
    assert key_id == "bank-key-1"
    assert rate.calls and rate.calls[0] == ("bank-key-1", None)
