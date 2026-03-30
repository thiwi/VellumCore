"""Shared HTTP auth dependency helpers for FastAPI services."""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials

from vellum_core.auth import BEARER_SCHEME


class JWTScopeVerifier(Protocol):
    """Protocol expected by scoped JWT dependency factories."""

    async def verify_jwt_credentials(
        self,
        credentials: HTTPAuthorizationCredentials | None,
        *,
        required_scopes: set[str],
    ) -> dict[str, Any]: ...


def build_scoped_jwt_dependency(
    verifier: JWTScopeVerifier,
    *scopes: str,
):
    """Create a FastAPI dependency that enforces one required scope set."""

    async def _dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
    ) -> dict[str, Any]:
        return await verifier.verify_jwt_credentials(
            credentials,
            required_scopes=set(scopes),
        )

    return _dependency
