"""Tests for maintenance filesystem archival helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from vellum_core.maintenance import _archive_path


@pytest.mark.unit
def test_archive_path_moves_file_and_creates_symlink(tmp_path: Path) -> None:
    root = tmp_path / "proofs"
    source_dir = root / "evidence"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / "run-1.json"
    source.write_text('{"a":1}', encoding="utf-8")

    archived = _archive_path(source=source, root=root, bucket="evidence")
    assert archived is True
    assert source.is_symlink()

    target = source.resolve()
    assert "archive/evidence" in str(target)
    assert target.read_text(encoding="utf-8") == '{"a":1}'
