from __future__ import annotations

import json
from pathlib import Path

from sentinel_zk.circuit_discovery import discover_runnable_circuits


def test_discovery_ignores_library_and_finds_manifest_circuits() -> None:
    root = Path(__file__).resolve().parents[1]
    discovered = discover_runnable_circuits(root / "circuits")
    ids = [circuit_id for _, circuit_id in discovered]

    assert "credit_check" in ids
    assert "batch_credit_check" in ids
    assert "complexity_1k" in ids
    assert "library" not in ids


def test_discovery_requires_manifest_matching_circuit_file(tmp_path: Path) -> None:
    circuits_dir = tmp_path / "circuits"
    broken = circuits_dir / "broken"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text(
        json.dumps({"circuit_id": "does_not_exist", "input_schema": {}, "public_signals": [], "version": "1.0.0"}),
        encoding="utf-8",
    )

    try:
        discover_runnable_circuits(circuits_dir)
        assert False, "Expected ValueError for missing circuit file"
    except ValueError as exc:
        assert "Missing circuit file" in str(exc)
