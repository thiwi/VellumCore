"""Data lifecycle maintenance: DB retention and local file archival."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vellum_core.config import Settings
from vellum_core.database import Database


@dataclass(frozen=True)
class MaintenanceReport:
    """Summary of one lifecycle maintenance cycle."""

    runtime_rows_pruned: int
    proof_files_archived: int
    evidence_files_archived: int


async def run_maintenance_cycle(*, settings: Settings, db: Database | None = None) -> MaintenanceReport:
    """Execute one lifecycle cycle using configured retention thresholds."""
    database = db or Database(settings.database_url)
    await database.init_models()

    now = datetime.now(timezone.utc)
    prune_cutoff = now - timedelta(days=settings.job_runtime_retention_days)
    archive_cutoff = now - timedelta(days=settings.file_archive_after_days)

    runtime_rows_pruned = await database.prune_terminal_job_runtime_data(
        older_than=prune_cutoff,
    )

    proof_files_archived = 0
    candidates = await database.list_jobs_for_file_archival(
        older_than=archive_cutoff,
        limit=settings.maintenance_cycle_file_scan_limit,
    )
    for job in candidates:
        if not isinstance(job.proof_path, str) or not job.proof_path.strip():
            continue
        source = Path(job.proof_path).expanduser()
        if _archive_path(source=source, root=settings.proof_output_dir, bucket="proofs"):
            proof_files_archived += 1

    evidence_files_archived = _archive_evidence_files(
        proof_output_dir=settings.proof_output_dir,
        older_than=archive_cutoff,
        max_files=settings.maintenance_cycle_file_scan_limit,
    )

    return MaintenanceReport(
        runtime_rows_pruned=runtime_rows_pruned,
        proof_files_archived=proof_files_archived,
        evidence_files_archived=evidence_files_archived,
    )


def _archive_evidence_files(
    *,
    proof_output_dir: Path,
    older_than: datetime,
    max_files: int,
) -> int:
    evidence_dir = proof_output_dir / "evidence"
    if not evidence_dir.exists():
        return 0
    archived = 0
    for source in sorted(evidence_dir.glob("*.json")):
        if archived >= max_files:
            break
        if _path_older_than(source, older_than):
            if _archive_path(source=source, root=proof_output_dir, bucket="evidence"):
                archived += 1
    return archived


def _path_older_than(path: Path, cutoff: datetime) -> bool:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    return modified < cutoff


def _archive_path(*, source: Path, root: Path, bucket: str) -> bool:
    if source.is_symlink() or not source.exists() or not source.is_file():
        return False
    try:
        source.relative_to(root)
    except ValueError:
        return False

    archive_root = root / "archive" / bucket
    if source.is_relative_to(archive_root):
        return False

    ts = datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc)
    target_dir = archive_root / str(ts.year) / f"{ts.month:02d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists():
        return False

    shutil.move(str(source), str(target))
    relative_target = os.path.relpath(target, start=source.parent)
    source.symlink_to(relative_target)
    return True
