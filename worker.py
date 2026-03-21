"""Reference Celery worker for asynchronous proof-job execution."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from celery.signals import worker_ready
from prometheus_client import start_http_server

from vellum_core.api.types import ProofGenerationRequest
from vellum_core.celery_app import celery_app
from vellum_core.config import Settings
from vellum_core.database import Database
from vellum_core.logic.batcher import batch_prepare_from_private_input
from vellum_core.metrics import observe_proof_duration
from vellum_core.observability import configure_logging, init_telemetry
from vellum_core.proof_store import VellumAuditStore
from vellum_core.runtime import build_framework_client
from vellum_core.security import SecurityEventLogger, unseal_job_payload
from vellum_core.vault import VaultTransitClient

from vellum_core.schemas import DEFAULT_BATCH_CIRCUIT_ID

settings = Settings.from_env()
configure_logging(settings.app_name)
logger = logging.getLogger(__name__)
init_telemetry(
    service_name=settings.app_name,
    instrument_celery=True,
)
framework = build_framework_client(settings)

_METRICS_STARTED = False


@worker_ready.connect
def _start_metrics_server(**_: object) -> None:
    """Start worker metrics endpoint once per worker process."""
    global _METRICS_STARTED
    if not _METRICS_STARTED:
        start_http_server(settings.worker_metrics_port, addr=settings.worker_metrics_host)
        _METRICS_STARTED = True
        logger.info(
            "worker_metrics_started",
            extra={
                "host": settings.worker_metrics_host,
                "port": settings.worker_metrics_port,
            },
        )


@celery_app.task(name="worker.process_proof_job")
def process_proof_job(proof_id: str) -> str:
    """Celery task entrypoint delegating to async job processor."""
    asyncio.run(_process_proof_job_async(proof_id))
    return proof_id


async def _process_proof_job_async(proof_id: str) -> None:
    """Execute full proof-job lifecycle and persist state/audit transitions."""
    logger.info("proof_job_processing_started", extra={"proof_id": proof_id})
    db = Database(settings.database_url)
    vault_client = VaultTransitClient(
        addr=settings.vault_addr,
        token=settings.vault_token,
        tls_ca_bundle=settings.tls_ca_bundle,
    )
    security_logger = SecurityEventLogger(db)
    audit_store = VellumAuditStore(
        db=db,
        vault=vault_client,
        audit_key_name=settings.vault_audit_key,
    )

    await db.init_models()
    job = await db.get_proof_job(proof_id)
    if job is None:
        logger.warning("proof_job_missing", extra={"proof_id": proof_id})
        return
    if job.status not in {"queued", "running"}:
        logger.info(
            "proof_job_skipped_status",
            extra={"proof_id": proof_id, "status": job.status},
        )
        return

    await db.update_proof_job(proof_id=proof_id, status="running")
    await audit_store.append_event(
        proof_id=proof_id,
        circuit_id=job.circuit_id,
        status="running",
        public_signals=[],
        metadata=job.meta,
    )

    started = time.perf_counter()
    try:
        if job.sealed_job_payload is None:
            raise ValueError("Missing sealed_job_payload for proof job")

        try:
            decrypted = await unseal_job_payload(
                vault_client=vault_client,
                key_name=settings.vellum_data_key,
                sealed_payload=job.sealed_job_payload,
            )
        except Exception as exc:
            await security_logger.record(
                event_type="payload_decrypt_failed",
                outcome="error",
                proof_id=proof_id,
                details={"reason": str(exc)},
            )
            raise ValueError("Unable to decrypt sealed job payload") from exc

        private_input = decrypted.get("private_input")
        if not isinstance(private_input, dict):
            raise ValueError("Missing private_input for proof job")
        if job.circuit_id == DEFAULT_BATCH_CIRCUIT_ID:
            prepared = batch_prepare_from_private_input(private_input)
            private_input = prepared.to_circuit_input()
        result = await framework.proof_engine.generate(
            ProofGenerationRequest(circuit_id=job.circuit_id, private_input=private_input)
        )

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
        await db.purge_sealed_job_payload(proof_id=proof_id)

        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=job.circuit_id,
            status="completed",
            public_signals=result.public_signals,
            proof_payload=result.proof,
            metadata=job.meta,
        )
        logger.info(
            "proof_job_completed",
            extra={
                "proof_id": proof_id,
                "circuit_id": job.circuit_id,
                "proof_path": str(proof_path),
            },
        )
    except Exception as exc:
        await db.update_proof_job(
            proof_id=proof_id,
            status="failed",
            error=str(exc),
        )
        await db.purge_sealed_job_payload(proof_id=proof_id)
        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=job.circuit_id,
            status="failed",
            public_signals=[],
            metadata=job.meta,
            error=str(exc),
        )
        logger.exception(
            "proof_job_failed",
            extra={"proof_id": proof_id, "circuit_id": job.circuit_id},
        )
        raise
    finally:
        observe_proof_duration(time.perf_counter() - started)
