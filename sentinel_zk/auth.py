from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from sentinel_zk.errors import APIError


BEARER_SCHEME = HTTPBearer(auto_error=False)


class NonceReplayGuard:
    def __init__(self, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self._seen: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def check_and_store(self, *, key_id: str, nonce: str, timestamp: float) -> None:
        now = time.time()
        if abs(now - timestamp) > self.window_seconds:
            raise APIError(
                status_code=401,
                code="stale_request",
                message="Request timestamp outside allowed window",
                details={"window_seconds": self.window_seconds},
            )

        token = f"{key_id}:{nonce}"
        async with self._lock:
            self._cleanup(now)
            if token in self._seen:
                raise APIError(
                    status_code=409,
                    code="nonce_replay",
                    message="Replay detected for nonce",
                    details={"nonce": nonce},
                )
            self._seen[token] = timestamp

    def _cleanup(self, now: float) -> None:
        threshold = now - self.window_seconds
        stale_keys = [key for key, ts in self._seen.items() if ts < threshold]
        for key in stale_keys:
            self._seen.pop(key, None)


class AuthManager:
    def __init__(
        self,
        *,
        jwt_public_key_path: Path,
        jwt_issuer: str,
        jwt_audience: str,
        bank_public_keys_path: Path,
        nonce_window_seconds: int,
    ) -> None:
        self.jwt_issuer = jwt_issuer
        self.jwt_audience = jwt_audience
        self.jwt_public_key = jwt_public_key_path.read_text(encoding="utf-8")
        self.bank_public_keys = self._load_bank_keys(bank_public_keys_path)
        self.replay_guard = NonceReplayGuard(window_seconds=nonce_window_seconds)

    def verify_jwt_credentials(
        self, credentials: HTTPAuthorizationCredentials | None
    ) -> dict[str, Any]:
        if credentials is None:
            raise APIError(
                status_code=401,
                code="missing_token",
                message="Missing bearer token",
            )

        token = credentials.credentials
        try:
            claims = jwt.decode(
                token,
                self.jwt_public_key,
                algorithms=["RS256"],
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
        key_id = request.headers.get("X-Bank-Key-Id")
        timestamp_raw = request.headers.get("X-Bank-Timestamp")
        nonce = request.headers.get("X-Bank-Nonce")
        signature_b64 = request.headers.get("X-Bank-Signature")

        missing = [
            name
            for name, value in {
                "X-Bank-Key-Id": key_id,
                "X-Bank-Timestamp": timestamp_raw,
                "X-Bank-Nonce": nonce,
                "X-Bank-Signature": signature_b64,
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

        timestamp_epoch = self._parse_timestamp(timestamp_raw)
        canonical = self._canonical_request_string(
            method=request.method,
            path=request.url.path,
            timestamp=timestamp_raw,
            nonce=nonce or "",
            raw_body=raw_body,
        )

        pubkey = self.bank_public_keys.get(key_id or "")
        if pubkey is None:
            raise APIError(
                status_code=401,
                code="unknown_bank_key",
                message="Unknown bank key id",
                details={"key_id": key_id},
            )

        try:
            signature = base64.b64decode(signature_b64 or "", validate=True)
            pubkey.verify(
                signature,
                canonical.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except Exception as exc:
            raise APIError(
                status_code=401,
                code="invalid_handshake_signature",
                message="Bank request signature invalid",
                details={"reason": str(exc)},
            ) from exc

        await self.replay_guard.check_and_store(
            key_id=key_id or "",
            nonce=nonce or "",
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
        body_hash = hashlib.sha256(raw_body).hexdigest()
        return f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"

    @staticmethod
    def _parse_timestamp(timestamp_raw: str | None) -> float:
        if timestamp_raw is None:
            raise APIError(
                status_code=401,
                code="invalid_timestamp",
                message="Missing request timestamp",
            )
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

    @staticmethod
    def _load_bank_keys(path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        keys_blob = raw.get("keys") if isinstance(raw, dict) else None
        keys_map = keys_blob if isinstance(keys_blob, dict) else raw
        if not isinstance(keys_map, dict):
            raise ValueError("bank public key file must contain a JSON object")

        parsed: dict[str, Any] = {}
        for key_id, pem in keys_map.items():
            if not isinstance(key_id, str) or not isinstance(pem, str):
                raise ValueError("invalid bank public key map")
            parsed[key_id] = load_pem_public_key(pem.encode("utf-8"))
        return parsed
