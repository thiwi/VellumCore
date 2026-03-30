# DLQ and Lifecycle Operations

This guide documents operational best practices for dead-letter triage, controlled reruns, and lifecycle retention/archival.

## Objectives

- Prevent silent data loss on terminal worker failures.
- Enable deterministic triage (`error_class`, `retryable`) and audited reruns.
- Keep long-running storage healthy with bounded runtime payload retention and file archival.

## Runtime Defaults

- Runtime provider mode: `grpc` only.
- Terminal runtime payload retention: `JOB_RUNTIME_RETENTION_DAYS=7`.
- Proof/evidence archival threshold: `FILE_ARCHIVE_AFTER_DAYS=30`.
- Maintenance cycle interval: `MAINTENANCE_INTERVAL_SECONDS=3600`.
- Maintenance scan cap per cycle: `MAINTENANCE_CYCLE_FILE_SCAN_LIMIT=1000`.

## Dead-Letter Flow

1. Worker marks a job `failed`.
2. Worker classifies failure deterministically:
   - `timeout`
   - `dependency`
   - `artifact`
   - `schema`
   - `crypto`
   - `retry_exhausted`
   - `unknown`
3. Worker writes/updates one DLQ row keyed by source `proof_id`.
4. Source lifecycle states remain unchanged:
   - `queued`, `running`, `completed`, `failed`

## Admin Endpoints

- `GET /v6/ops/dlq` (scope `ops:read`)
- `POST /v6/ops/dlq/{dlq_id}/requeue` (scope `ops:write`)

Requeue behavior:

- Idempotent by DLQ entry.
- If already requeued, returns existing `rerun_proof_id`.
- Creates a new queued job with source linkage metadata:
  - `rerun_of`
  - `dlq_entry_id`
  - `rerun_requested_by`
  - `rerun_reason`
- Emits audit events for queue + rerun trigger.

## Lifecycle and Archival

Maintenance worker (`maintenance_worker.py`) performs:

- DB runtime payload pruning for terminal jobs older than retention cutoff.
  - Prunes heavy runtime columns (`proof`, `public_signals`, `error`).
  - Keeps audit/security records untouched.
- File archival:
  - Moves aged proof/evidence files into `PROOF_OUTPUT_DIR/archive/<bucket>/<YYYY>/<MM>/`.
  - Replaces original file path with symlink for compatibility.

## Operational Best Practices

- Use reruns only for clearly retryable classes (`timeout`, `dependency`, selected `artifact` cases).
- Require a rerun reason in operator playbooks for traceability.
- Monitor DLQ growth rate and class distribution (timeouts vs crypto/schema).
- Track maintenance cycle outputs:
  - rows pruned
  - proof files archived
  - evidence files archived
- Treat repeated `crypto`/`schema` DLQ classes as release-quality regressions, not ops noise.

## Failure Investigation Checklist

1. Inspect DLQ entry (`error_class`, `failure_reason`, attempts).
2. Correlate with worker logs and dependency health.
3. Verify artifact state (`vellum circuits validate --json`).
4. For retryable failures, trigger controlled rerun via admin endpoint.
5. Confirm rerun audit trail and final status.
