#!/usr/bin/env python3
"""Synchronize requirements.txt from pyproject.toml project dependencies."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def _load_pyproject_dependencies(pyproject_path: Path) -> list[str]:
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml is missing [project] table")
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("pyproject.toml is missing project.dependencies list")

    normalized: list[str] = []
    for index, item in enumerate(dependencies):
        if not isinstance(item, str):
            raise ValueError(
                f"project.dependencies[{index}] must be a string, got {type(item).__name__}"
            )
        value = item.strip()
        if not value:
            raise ValueError(f"project.dependencies[{index}] is empty")
        normalized.append(value)
    return normalized


def _render_requirements(dependencies: list[str]) -> str:
    return "\n".join(dependencies) + "\n"


def export_requirements(*, pyproject_path: Path, output_path: Path) -> None:
    dependencies = _load_pyproject_dependencies(pyproject_path)
    output_path.write_text(_render_requirements(dependencies), encoding="utf-8")


def check_requirements(*, pyproject_path: Path, output_path: Path) -> bool:
    expected = _render_requirements(_load_pyproject_dependencies(pyproject_path))
    if not output_path.exists():
        print(f"requirements drift detected: missing file {output_path}")
        return False

    actual = output_path.read_text(encoding="utf-8")
    if actual == expected:
        return True

    print("requirements drift detected between pyproject.toml and requirements.txt")
    diff = difflib.unified_diff(
        actual.splitlines(),
        expected.splitlines(),
        fromfile=str(output_path),
        tofile=f"expected:{output_path}",
        lineterm="",
    )
    for line in diff:
        print(line)
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync_requirements",
        description="Export/check requirements.txt from pyproject.toml canonical dependencies.",
    )
    parser.add_argument(
        "command",
        choices={"export", "check"},
        help="Action to run.",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("requirements.txt"),
        help="Path to requirements.txt.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        export_requirements(pyproject_path=args.pyproject, output_path=args.output)
        print(f"exported:{args.output}")
        return 0

    in_sync = check_requirements(pyproject_path=args.pyproject, output_path=args.output)
    print("drift:none" if in_sync else "drift:detected")
    return 0 if in_sync else 1


if __name__ == "__main__":
    sys.exit(main())
