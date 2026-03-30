# Migration: Runtime grpc-only + DLQ/Lifecycle Operations

This guide covers migration from dual-provider runtime assumptions to grpc-only runtime with DLQ and lifecycle maintenance.

## What Changed

- Runtime proving path is now `grpc` only.
- Runtime shadow mode is disabled.
- New admin DLQ endpoints were added:
  - `GET /v6/ops/dlq`
  - `POST /v6/ops/dlq/{dlq_id}/requeue`
- Maintenance worker introduced for retention and archival.

## Required Configuration Updates

Set or verify:

- `PROOF_PROVIDER_MODE=grpc`
- `PROOF_SHADOW_MODE=false`
- `PROOF_SHADOW_PROVIDER_MODE=grpc`
- `JOB_RUNTIME_RETENTION_DAYS=7` (or your policy)
- `FILE_ARCHIVE_AFTER_DAYS=30` (or your policy)
- `MAINTENANCE_INTERVAL_SECONDS=3600` (or your policy)
- `MAINTENANCE_CYCLE_FILE_SCAN_LIMIT=1000` (or your policy)

## Scope/Token Updates

For operational tokens, add scopes:

- `ops:read` for DLQ listing
- `ops:write` for DLQ requeue actions

Existing scopes (`proofs:*`, `audit:read`) are unchanged.

## Compose/Deployment Updates

- Ensure `native-prover` is deployed and reachable via `GRPC_PROVER_ENDPOINT`.
- Ensure maintenance worker is deployed as a periodic background service.

## Validation Checklist

1. `GET /healthz` for prover/verifier/dashboard.
2. Submit a known-good run and verify completion.
3. Simulate one failure and confirm DLQ row creation.
4. Requeue via admin endpoint and confirm idempotent behavior.
5. Run at least one maintenance cycle and verify archive directory population.
6. Verify attestation export still works for completed runs after pruning window via audit fallback.
