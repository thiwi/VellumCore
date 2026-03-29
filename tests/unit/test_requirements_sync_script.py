"""Tests for deterministic requirements sync script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync_requirements.py"


def _write_pyproject(path: Path, deps: list[str]) -> None:
    lines = [
        "[project]",
        'name = "test"',
        'version = "0.0.1"',
        "dependencies = [",
        *[f'  "{dep}",' for dep in deps],
        "]",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.unit
def test_export_writes_deterministic_requirements(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "requirements.txt"
    _write_pyproject(pyproject, ["a==1.0.0", "b==2.0.0"])

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "export",
            "--pyproject",
            str(pyproject),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert output.read_text(encoding="utf-8") == "a==1.0.0\nb==2.0.0\n"


@pytest.mark.unit
def test_check_fails_when_output_is_out_of_sync(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "requirements.txt"
    _write_pyproject(pyproject, ["a==1.0.0"])
    output.write_text("a==2.0.0\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "check",
            "--pyproject",
            str(pyproject),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "drift:detected" in result.stdout
