"""Tests for Http legacy."""

from __future__ import annotations

from fastapi.responses import Response

from vellum_core.http_legacy import mark_legacy_api


def test_mark_legacy_api_sets_expected_headers() -> None:
    response = Response()
    mark_legacy_api(response)

    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == "Tue, 30 Sep 2026 00:00:00 GMT"
    assert "MIGRATION_V4_TO_V5" in response.headers["Link"]
