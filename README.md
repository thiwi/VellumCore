# Vellum Protocol Core

Production-oriented ZK proving/verification framework with:
- package namespace `vellum_core` (hard rename from `sentinel_zk`)
- batch-first proving (`batch_credit_check`, N=100)
- distributed proving (FastAPI orchestrator + Redis/Celery worker)
- Vault Transit signing for JWT, bank-handshake, and audit-chain links
- PostgreSQL system-of-record for proof jobs and append-only audit chain
- Prometheus metrics + dashboard trust-speed view
- Docker Compose runtime for `linux/amd64` and `linux/arm64`

## Services

- `prover_service.py`: thin API orchestrator
  - `POST /v1/proofs/batch`
  - `GET /v1/proofs/{proof_id}`
  - `GET /metrics`
- `worker.py`: Celery worker doing SnarkJS proving
- `verifier_service.py`: proof verifier + integrity service
  - `POST /v1/verify`
  - `GET /v1/audit/verify-chain`
  - `GET /v1/trust-speed`
  - `GET /metrics`
- `dashboard_service.py`: demo UI for batch prove/verify + trust-speed

Infrastructure in `docker-compose.yml`:
- `postgres`
- `redis`
- `vault`
- `vault-init` (creates transit keys)
- `prover`
- `worker`
- `verifier`
- `dashboard`

## Architecture Notes

- Prover API no longer executes heavy proofs locally.
- Proof jobs are written to Postgres (`queued`) and sent to Celery queue `vellum-queue`.
- Worker pulls jobs, proves, persists result (`running -> completed/failed`) in Postgres.
- Audit events are appended into `audit_log` with `previous_entry_hash`, `entry_hash`, and Vault signature.
- Chain integrity is verified from Postgres rows via `VellumIntegrityService`.
- Nonce replay protection is Redis-based (`SETNX` + TTL), so it is multi-instance safe.

## Batch API Contract

`POST /v1/proofs/batch` accepts exactly one mode:

1. Direct mode
- `balances`: `list[int]` (1..100)
- `limits`: `list[int]` (1..100, same length)
- optional `request_id`

2. Adapter mode
- `source_ref`: `str`
- optional `request_id`

Rules:
- Providing both direct arrays and `source_ref` is rejected.
- Server enforces anti-ghost invariants:
  - deterministic zero padding to 100
  - explicit `active_count`
  - strict uint bounds

## Quickstart

1. Start full stack:

```bash
./up_infra.sh
```

2. Compile circuits and generate Groth16 artifacts:

```bash
docker compose exec prover /app/setup_framework.sh
```

3. Health checks:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8001/healthz
curl -fsS http://localhost:8002/healthz
```

4. Open UI:
- Dashboard: `http://localhost:8000`
- Prover docs: `http://localhost:8001/docs`
- Verifier docs: `http://localhost:8002/docs`

Stop and remove containers:

```bash
./down_infra.sh
```

## Vault / Keys

Private keys are not used from local PEM files for runtime operations.
Runtime signing is done through Vault Transit keys:
- `VELLUM_JWT_KEY`
- `VELLUM_AUDIT_KEY`
- `VELLUM_BANK_KEY`

`vault-init` auto-creates these keys on startup.

## Metrics and Trust-Speed

- Prover/worker/verifier expose Prometheus metrics.
- Core metrics:
  - `vellum_proof_duration_seconds`
  - `vellum_verify_duration_seconds`
  - `vellum_native_verify_duration_seconds`
- Trust-speed endpoint: `GET /v1/trust-speed`
  - `native_verify_ms`
  - `zk_batch_verify_ms`
  - `trust_speedup`

## Benchmarks

- Legacy comparison:

```bash
docker compose exec prover python /app/benchmark_comparison.py --sample-size 1000
```

- Batch benchmark (100 decisions in one proof):

```bash
docker compose exec prover python /app/benchmark_batch.py --seed 42
```

This reports native check time, single ZK verify time, proving overhead, and auditor speedup.
