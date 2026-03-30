"""Periodic lifecycle maintenance runner for DLQ/data-retention operations."""

from __future__ import annotations

import asyncio
import logging

from vellum_core.config import Settings
from vellum_core.maintenance import run_maintenance_cycle
from vellum_core.observability import configure_logging, init_telemetry


settings = Settings.from_env()
configure_logging(settings.app_name)
logger = logging.getLogger(__name__)
init_telemetry(service_name=settings.app_name)


async def _run_forever() -> None:
    while True:
        try:
            report = await run_maintenance_cycle(settings=settings)
            logger.info(
                "maintenance_cycle_completed",
                extra={
                    "runtime_rows_pruned": report.runtime_rows_pruned,
                    "proof_files_archived": report.proof_files_archived,
                    "evidence_files_archived": report.evidence_files_archived,
                },
            )
        except Exception:
            logger.exception("maintenance_cycle_failed")
        await asyncio.sleep(settings.maintenance_interval_seconds)


if __name__ == "__main__":
    asyncio.run(_run_forever())
