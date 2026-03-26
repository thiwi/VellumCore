"""Pytest configuration hooks for test collection and markers."""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-assign base test layer markers for consistent CI slicing."""
    _ = config
    for item in items:
        existing = {mark.name for mark in item.iter_markers()}
        if {"unit", "integration", "e2e"}.intersection(existing):
            continue

        path = Path(str(item.fspath))
        parts = set(path.parts)
        if "e2e" in parts:
            item.add_marker(pytest.mark.e2e)
        elif "integration" in parts:
            item.add_marker(pytest.mark.integration)
        elif "unit" in parts:
            item.add_marker(pytest.mark.unit)
        else:
            item.add_marker(pytest.mark.unit)

        existing = {mark.name for mark in item.iter_markers()}
        if "critical" in existing or "nightly" in existing:
            item.add_marker(pytest.mark.e2e)
