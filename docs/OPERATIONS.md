# Operations Runbook

## Local Stack Lifecycle

Start:

```bash
./up_infra.sh
docker compose exec prover /app/setup_framework.sh
```

Stop:

```bash
./down_infra.sh
```

Health checks:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8001/healthz
curl -fsS http://localhost:8002/healthz
```

## Standard Operational Checks

- `GET /api/framework/overview` (dashboard aggregate)
- `GET /api/framework/diagnostics` (degraded dependency details)
- `GET /v1/circuits` (artifact readiness)
- `GET /v1/audit/verify-chain` (audit integrity)

## Incident Priorities

1. **Data integrity risk**: audit chain invalid, signature errors, proof verification failures.
2. **Availability risk**: prover/verifier down, queue backlog increasing.
3. **Performance risk**: proving latency spikes, trust-speed regressions.

## Failure Handling

### Job stuck in `queued`

- Check Redis health and worker container status.
- Confirm `CELERY_QUEUE` matches worker startup queue.
- Check worker logs for runtime exceptions.

### Job in `failed`

- Inspect `error` on job payload.
- Verify artifacts exist and match manifest (`vellum circuits validate --json`).
- Re-submit as a new job after fix.

### Verify endpoint returns invalid or fails

- Confirm `circuit_id` matches proof/public signals.
- Ensure verification key artifacts exist for target circuit.
- Verify no proof payload mutation happened between generation and verify.

## Observability Baseline

- Use `/metrics` on prover/verifier/worker for Prometheus scraping.
- Track queue depth, job status counts, proving duration, and verification duration.
- Keep dashboard auto-refresh enabled during active investigations.

## Backup / Recovery Notes

- PostgreSQL is source of truth for job and audit state.
- `shared_assets/` must remain consistent with circuit manifests.
- If rebuilding artifacts, re-run `setup_framework.sh` before resuming operations.
