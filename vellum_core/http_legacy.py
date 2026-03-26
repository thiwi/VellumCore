"""Helpers for marking legacy HTTP surfaces with deprecation metadata."""

from __future__ import annotations

from fastapi.responses import Response

LEGACY_SUNSET_AT = "Tue, 30 Sep 2026 00:00:00 GMT"
LEGACY_MIGRATION_LINK = '</docs/MIGRATION_V4_TO_V5.md>; rel="deprecation"; type="text/markdown"'


def mark_legacy_api(
    response: Response,
    *,
    sunset: str = LEGACY_SUNSET_AT,
    migration_link: str = LEGACY_MIGRATION_LINK,
) -> None:
    """Attach RFC-style deprecation metadata headers for legacy endpoints."""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = sunset
    response.headers["Link"] = migration_link
