"""Helpers for discovering runnable circuits from manifest directories."""

from __future__ import annotations

import json
from pathlib import Path


def discover_runnable_circuits(circuits_dir: Path) -> list[tuple[Path, str]]:
    """Return `(circuit_dir, circuit_id)` entries that pass manifest/file checks."""
    results: list[tuple[Path, str]] = []
    if not circuits_dir.exists():
        return results

    for child in sorted(circuits_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        circuit_id = payload.get("circuit_id")
        if not isinstance(circuit_id, str) or not circuit_id:
            raise ValueError(f"Invalid manifest circuit_id in {manifest_path}")

        circuit_file = child / f"{circuit_id}.circom"
        if not circuit_file.exists():
            raise ValueError(f"Missing circuit file referenced by manifest: {circuit_file}")

        results.append((child, circuit_id))

    return results
