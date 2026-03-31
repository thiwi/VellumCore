"""Reference Celery worker for asynchronous proof-job execution."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_ready
from prometheus_client import start_http_server

from vellum_core.api.types import ProofGenerationRequest, VerificationRequest
from vellum_core.celery_app import celery_app
from vellum_core.config import Settings
from vellum_core.database import Database
from vellum_core.logic.batcher import batch_prepare_from_private_input
from vellum_core.logic.explainability import build_explainability
from vellum_core.logic.failure_triage import classify_failure
from vellum_core.logic.job_attempts import next_attempt_metadata
from vellum_core.logic.private_input_schema import validate_private_input_schema
from vellum_core.maintenance import run_maintenance_cycle as run_data_lifecycle_cycle
from vellum_core.metrics import observe_proof_duration
from vellum_core.observability import configure_logging, init_telemetry
from vellum_core.policies.dual_track import (
    DualTrackReferenceResult,
    assert_dual_track_consistency,
    evaluate_circuit_track,
)
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


@celery_app.task(name="worker.run_maintenance_cycle")
def run_maintenance_cycle_task() -> dict[str, int]:
    """Celery task entrypoint for periodic lifecycle maintenance."""
    return asyncio.run(_run_maintenance_cycle_async())


async def _run_maintenance_cycle_async() -> dict[str, int]:
    report = await run_data_lifecycle_cycle(settings=settings)
    payload = {
        "runtime_rows_pruned": report.runtime_rows_pruned,
        "proof_files_archived": report.proof_files_archived,
        "evidence_files_archived": report.evidence_files_archived,
    }
    logger.info("maintenance_cycle_completed", extra=payload)
    return payload


async def _record_dead_letter_job(
    *,
    db: Database,
    job: object,
    failure_reason: str,
    error_message: str,
    attempt_metadata: dict[str, int],
    sealed_rerun_payload: str | None,
    explainability: dict[str, Any] | None = None,
) -> None:
    triage = classify_failure(
        failure_reason=failure_reason,
        error_message=error_message,
    )
    await db.upsert_dead_letter_job(
        proof_id=str(job.proof_id),
        circuit_id=str(job.circuit_id),
        error_class=triage.error_class,
        retryable=triage.retryable,
        failure_reason=failure_reason,
        error_message=error_message,
        attempt_count=int(attempt_metadata.get("attempt_count", 0)),
        max_attempts=int(attempt_metadata.get("max_attempts", 0)),
        triage_details={
            "detail": triage.detail,
            "explainability": explainability or {},
        },
        job_metadata=dict((job.meta or {})),
        sealed_rerun_payload=sealed_rerun_payload,
    )


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

    max_attempts = settings.proof_job_max_attempts
    attempt_metadata, attempts_exceeded = next_attempt_metadata(
        metadata=job.meta,
        max_attempts=max_attempts,
    )
    attempt_count = attempt_metadata["attempt_count"]
    if attempts_exceeded:
        failure_reason = f"proof job exceeded max attempts ({max_attempts})"
        sealed_rerun_payload = job.sealed_job_payload
        failed_job = await db.update_proof_job(
            proof_id=proof_id,
            status="failed",
            error=failure_reason,
            metadata_patch={
                **attempt_metadata,
                "failure_reason": "max_attempts_exceeded",
                "error_details": {
                    "explainability": {
                        "version": "v1",
                        "reason": "max_attempts_exceeded",
                    }
                },
            },
        )
        failed_metadata = dict((failed_job.meta if failed_job is not None else job.meta) or {})
        failed_metadata.update(
            {
                **attempt_metadata,
                "failure_reason": "max_attempts_exceeded",
            }
        )
        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=job.circuit_id,
            status="failed",
            public_signals=[],
            metadata=failed_metadata,
            error=failure_reason,
        )
        await _record_dead_letter_job(
            db=db,
            job=job,
            failure_reason="max_attempts_exceeded",
            error_message=failure_reason,
            attempt_metadata=attempt_metadata,
            sealed_rerun_payload=sealed_rerun_payload,
            explainability={"version": "v1", "reason": "max_attempts_exceeded"},
        )
        await db.purge_sealed_job_payload(proof_id=proof_id)
        logger.error(
            "proof_job_max_attempts_exceeded",
            extra={
                "proof_id": proof_id,
                "attempt_count": attempt_count,
                "max_attempts": max_attempts,
            },
        )
        return

    updated_job = await db.update_proof_job(
        proof_id=proof_id,
        status="running",
        metadata_patch=attempt_metadata,
    )
    if updated_job is not None:
        job = updated_job
    await audit_store.append_event(
        proof_id=proof_id,
        circuit_id=job.circuit_id,
        status="running",
        public_signals=[],
        metadata=job.meta,
    )

    started = time.perf_counter()
    decrypted: dict[str, Any] | None = None
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

        manifest = framework.circuit_manager.registry.get_manifest(job.circuit_id)
        validate_private_input_schema(
            input_schema=manifest.input_schema,
            private_input=private_input,
        )

        result = await framework.proof_engine.generate(
            ProofGenerationRequest(circuit_id=job.circuit_id, private_input=private_input)
        )
        verify_result = await framework.proof_engine.verify(
            VerificationRequest(
                circuit_id=job.circuit_id,
                proof=result.proof,
                public_signals=result.public_signals,
            )
        )

        metadata_patch: dict[str, str] | None = None
        policy_id = (job.meta or {}).get("policy_id")
        if isinstance(policy_id, str) and policy_id:
            policy_version = ""
            try:
                policy_manifest = framework.policy_registry.get_manifest(policy_id)
                policy_version = policy_manifest.policy_version
                dual_track_reference_raw = decrypted.get("dual_track_reference")
                if not isinstance(dual_track_reference_raw, dict):
                    raise ValueError("Missing dual_track_reference for policy run")
                reference_decision = dual_track_reference_raw.get("decision")
                reference_outputs = dual_track_reference_raw.get("outputs")
                if reference_decision not in {"pass", "fail"}:
                    raise ValueError("dual_track_reference.decision must be pass|fail")
                if not isinstance(reference_outputs, dict):
                    raise ValueError("dual_track_reference.outputs must be an object")
                reference_result = DualTrackReferenceResult(
                    private_input={},
                    decision=reference_decision,
                    outputs=reference_outputs,
                )
                circuit_result = evaluate_circuit_track(
                    policy_id=policy_id,
                    expected_attestation=policy_manifest.expected_attestation,
                    differential_outputs=policy_manifest.differential_outputs,
                    public_signals=result.public_signals,
                    verified=verify_result.valid,
                )
                assert_dual_track_consistency(
                    policy_id=policy_id,
                    reference=reference_result,
                    circuit=circuit_result,
                )
                decision = circuit_result.decision
            except Exception as exc:
                logger.warning(
                    "policy_dual_track_failed",
                    extra={"proof_id": proof_id, "policy_id": policy_id, "reason": str(exc)},
                )
                raise
            metadata_patch = {
                "policy_version": policy_version,
                "decision": decision,
            }

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
            metadata_patch=metadata_patch,
        )
        await db.purge_sealed_job_payload(proof_id=proof_id)

        completion_metadata = dict(job.meta or {})
        if metadata_patch:
            completion_metadata.update(metadata_patch)

        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=job.circuit_id,
            status="completed",
            public_signals=result.public_signals,
            proof_payload=result.proof,
            metadata=completion_metadata,
        )
        logger.info(
            "proof_job_completed",
            extra={
                "proof_id": proof_id,
                "circuit_id": job.circuit_id,
                "proof_path": str(proof_path),
                "attempt_count": attempt_count,
            },
        )
    except SoftTimeLimitExceeded:
        sealed_rerun_payload = job.sealed_job_payload
        timeout_error = (
            "proof job exceeded celery soft time limit "
            f"({settings.celery_task_soft_time_limit_seconds}s)"
        )
        explainability = _build_failure_explainability(
            job=job,
            decrypted_payload=decrypted,
            error_message=timeout_error,
        )
        failed_job = await db.update_proof_job(
            proof_id=proof_id,
            status="failed",
            error=timeout_error,
            metadata_patch={
                "failure_reason": "soft_time_limit_exceeded",
                "error_details": {"explainability": explainability},
                **attempt_metadata,
            },
        )
        failed_metadata = dict((failed_job.meta if failed_job is not None else job.meta) or {})
        failed_metadata.update(
            {
                "failure_reason": "soft_time_limit_exceeded",
                **attempt_metadata,
            }
        )
        await db.purge_sealed_job_payload(proof_id=proof_id)
        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=job.circuit_id,
            status="failed",
            public_signals=[],
            metadata=failed_metadata,
            error=timeout_error,
        )
        await _record_dead_letter_job(
            db=db,
            job=job,
            failure_reason="soft_time_limit_exceeded",
            error_message=timeout_error,
            attempt_metadata=attempt_metadata,
            sealed_rerun_payload=sealed_rerun_payload,
            explainability=explainability,
        )
        logger.exception(
            "proof_job_soft_time_limit_exceeded",
            extra={
                "proof_id": proof_id,
                "circuit_id": job.circuit_id,
                "attempt_count": attempt_count,
            },
        )
        raise
    except Exception as exc:
        sealed_rerun_payload = job.sealed_job_payload
        explainability = _build_failure_explainability(
            job=job,
            decrypted_payload=decrypted,
            error_message=str(exc),
        )
        failed_job = await db.update_proof_job(
            proof_id=proof_id,
            status="failed",
            error=str(exc),
            metadata_patch={
                "failure_reason": "runtime_exception",
                "error_details": {"explainability": explainability},
                **attempt_metadata,
            },
        )
        await db.purge_sealed_job_payload(proof_id=proof_id)
        failed_metadata = dict((failed_job.meta if failed_job is not None else job.meta) or {})
        failed_metadata.update(
            {
                "failure_reason": "runtime_exception",
                **attempt_metadata,
            }
        )
        await audit_store.append_event(
            proof_id=proof_id,
            circuit_id=job.circuit_id,
            status="failed",
            public_signals=[],
            metadata=failed_metadata,
            error=str(exc),
        )
        await _record_dead_letter_job(
            db=db,
            job=job,
            failure_reason="runtime_exception",
            error_message=str(exc),
            attempt_metadata=attempt_metadata,
            sealed_rerun_payload=sealed_rerun_payload,
            explainability=explainability,
        )
        logger.exception(
            "proof_job_failed",
            extra={
                "proof_id": proof_id,
                "circuit_id": job.circuit_id,
                "attempt_count": attempt_count,
            },
        )
        raise
    finally:
        observe_proof_duration(time.perf_counter() - started)


def _build_failure_explainability(
    *,
    job: object,
    decrypted_payload: dict[str, Any] | None,
    error_message: str,
) -> dict[str, Any]:
    metadata = dict(getattr(job, "meta", {}) or {})
    policy_id = metadata.get("policy_id")
    private_input: dict[str, Any] | None = None
    policy_parameters: dict[str, int] = {}
    if isinstance(decrypted_payload, dict):
        private_input_raw = decrypted_payload.get("private_input")
        if isinstance(private_input_raw, dict):
            private_input = private_input_raw
        policy_params_raw = decrypted_payload.get("policy_parameters")
        if isinstance(policy_params_raw, dict):
            policy_parameters = {
                str(key): int(value)
                for key, value in policy_params_raw.items()
                if isinstance(value, int) and not isinstance(value, bool)
            }

    if not isinstance(policy_id, str) or policy_id == "":
        return {"version": "v1", "reason": "policy_trace_unavailable"}

    try:
        return build_explainability(
            policy_id=policy_id,
            policy_packs_dir=settings.policy_packs_dir,
            private_input=private_input,
            policy_parameters=policy_parameters,
            error_message=error_message,
        )
    except Exception:
        return {"version": "v1", "reason": "policy_trace_unavailable"}
