from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from celery.signals import worker_ready
from prometheus_client import start_http_server

from vellum_core.adapters import MainframeAdapter
from vellum_core.celery_app import celery_app
from vellum_core.config import Settings
from vellum_core.database import Database
from vellum_core.logic.batcher import batch_prepare_from_private_input, batch_prepare_input
from vellum_core.metrics import observe_proof_duration
from vellum_core.proof_store import VellumAuditStore
from vellum_core.providers import SnarkJSProvider
from vellum_core.registry import CircuitRegistry
from vellum_core.vault import VaultTransitClient


BATCH_CIRCUIT_ID = "batch_credit_check"

settings = Settings.from_env()
db = Database(settings.database_url)
registry = CircuitRegistry(settings.circuits_dir, settings.shared_assets_dir)
provider = SnarkJSProvider(registry=registry, snarkjs_bin=settings.snarkjs_bin)
vault_client = VaultTransitClient(addr=settings.vault_addr, token=settings.vault_token)
audit_store = VellumAuditStore(
    db=db,
    vault=vault_client,
    audit_key_name=settings.vault_audit_key,
)
adapter = MainframeAdapter()

_METRICS_STARTED = False


@worker_ready.connect
def _start_metrics_server(**_: object) -> None:
    global _METRICS_STARTED
    if not _METRICS_STARTED:
        start_http_server(settings.worker_metrics_port)
        _METRICS_STARTED = True


@celery_app.task(name="worker.process_proof_job")
def process_proof_job(proof_id: str) -> str:
    asyncio.run(_process_proof_job_async(proof_id))
    return proof_id


async def _process_proof_job_async(proof_id: str) -> None:
    await db.init_models()
    job = await db.get_proof_job(proof_id)
    if job is None:
        return
    if job.status not in {"queued", "running"}:
        return

    await db.update_proof_job(proof_id=proof_id, status="running")
    await audit_store.append_event(
        proof_id=proof_id,
        circuit_id=BATCH_CIRCUIT_ID,
        status="running",
        public_signals=[],
        metadata=job.meta,
    )

    started = time.perf_counter()
    try:
        if job.source_ref is not None:
            mapped = await adapter.fetch_credit_batch(job.source_ref)
            prepared = batch_prepare_input(balances=mapped.balances, limits=mapped.limits)
        else:
            if job.private_input is None:
                raise ValueError("Missing private_input for direct mode proof job")
            prepared = batch_prepare_from_private_input(job.private_input)

        private_input = prepared.to_circuit_input()
        await provider.ensure_artifacts(BATCH_CIRCUIT_ID)
        result = await provider.generate_proof(BATCH_CIRCUIT_ID, private_input)

        proof_output_dir = Path(settings.proof_output_dir)
        proof_output_dir.mkdir(parents=True, exist_ok=True)
        proof_path = proof_output_dir / f"{proof_id}.json"
        proof_path.write_text(
            json.dumps(
                {
                    "proof": result.proof,
                    "public_signals": result.public_signals,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

        await db.update_proof_job(
            proof_id=proof_id,
            status="completed",
            public_signals=result.public_signals,
            proof=result.proof,
            proof_path=str(proof_path),
        )

        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=BATCH_CIRCUIT_ID,
            status="completed",
            public_signals=result.public_signals,
            proof_payload=result.proof,
            metadata=job.meta,
        )
    except Exception as exc:
        await db.update_proof_job(
            proof_id=proof_id,
            status="failed",
            error=str(exc),
        )
        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=BATCH_CIRCUIT_ID,
            status="failed",
            public_signals=[],
            metadata=job.meta,
            error=str(exc),
        )
        raise
    finally:
        observe_proof_duration(time.perf_counter() - started)
