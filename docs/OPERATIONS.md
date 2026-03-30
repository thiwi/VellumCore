# Operations Runbook

## Local Stack Lifecycle

Start:

```bash
./up_infra.sh
```

`framework-init` is executed automatically during compose startup to prepare artifacts.

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
- `GET /v6/circuits` (artifact readiness)
- `GET /v6/audit/verify-chain` (audit integrity)
- `GET /v6/runs/{run_id}` (policy decision lifecycle)
- `GET /v6/runs/{run_id}/attestation` (exportable compliance evidence bundle)

## Incident Priorities

1. **Data integrity risk**: audit chain invalid, signature errors, proof verification failures.
2. **Availability risk**: prover/verifier down, queue backlog increasing.
3. **Performance risk**: proving latency spikes, trust-speed regressions.

## Incident Timeline Mapping (Regulatory Baseline)

- **NYDFS Part 500**: notify superintendent within 72 hours after determining incident.
- **FTC Safeguards Rule**: notify FTC within 30 days for qualifying events (>=500 consumers).
- **Ransom/extortion (NYDFS)**: additional 24-hour notice for extortion payment events.

## Failure Handling

### Job stuck in `queued`

- Check Redis health and worker container status.
- Confirm `CELERY_QUEUE` matches worker startup queue.
- Check worker logs for runtime exceptions.

### Job in `failed`

- Inspect `error` on job payload.
- Inspect DLQ entries via `GET /v6/ops/dlq` (scope `ops:read`).
- Use `POST /v6/ops/dlq/{dlq_id}/requeue` (scope `ops:write`) for controlled reruns.
- Verify artifacts exist and match manifest (`vellum circuits validate --json`).
- Re-submit as a new job after fix.

### Verify endpoint returns invalid or fails

- Confirm `circuit_id` matches proof/public signals.
- Ensure verification key artifacts exist for target circuit.
- Verify no proof payload mutation happened between generation and verify.

## Observability Baseline

- Use `/metrics` on prover/verifier/worker for Prometheus scraping.
- Track queue depth, job status counts, proving duration, and verification duration.
- Track `vellum_security_events_total{event_type,outcome}` and investigate spikes.
- Use `security_events` table for forensics without exposing sensitive payload data.
- Keep dashboard auto-refresh enabled during active investigations.
- Use Grafana (`http://localhost:3000`) with Tempo datasource for distributed traces.
- Ensure all service logs are JSON and include trace/span correlation fields when available.
- Prefer investigating incidents by trace first (request -> worker -> vault/db calls), then metrics.

## Backup / Recovery Notes

- PostgreSQL is source of truth for job and audit state.
- `shared_assets/` must remain consistent with circuit manifests.
- Maintenance worker archives aged proof/evidence files under `shared_assets/proofs/archive`.
- If rebuilding artifacts, run `docker compose run --rm framework-init` before resuming operations.
