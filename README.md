# Vellum Core

Production-oriented ZK proving/verification framework with:
- framework/package namespace `vellum_core` (formerly SentinelZK / `sentinel_zk`)
- batch-first proving (`batch_credit_check`, default N=250; study script varies N)
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
- `balances`: `list[int]` (1..250)
- `limits`: `list[int]` (1..250, same length)
- optional `request_id`

2. Adapter mode
- `source_ref`: `str`
- optional `request_id`

Rules:
- Providing both direct arrays and `source_ref` is rejected.
- Server enforces anti-ghost invariants:
  - deterministic zero padding to 250
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

- Batch benchmark (250 decisions in one proof):

```bash
docker compose exec prover python /app/benchmark_batch.py --seed 42
```

This reports native check time, single ZK verify time, proving overhead, and auditor speedup.

## Systematic Study

Use the automation script to run sequential compile/setup/test/export cycles for multiple fixed circuit batch sizes:

```bash
./run_systematic_study.sh
```

Current configured study set in `run_systematic_study.sh`:
- `N in {100,250,500,750}`
- `ops=10000`

Workflow per `N`:
- patch `circuits/batch_credit_check/batch_credit_check.circom` to `BatchCreditCheck(N)`
- patch batch-size config in:
  - `vellum_core/logic/batcher.py`
  - `circuits/batch_credit_check/manifest.json`
- run `./setup_framework.sh`
- run `./up_infra.sh` (with retry/cache-cleanup on transient BuildKit issues)
- wait for Vault + prover health
- execute:
  - `docker compose exec -T prover python /app/systematic_vellum_analysis.py --volumes N --ops 10000 --reset-audit-log`
- copy `/app/vellum_performance_matrix.json` to:
  - `study_results/results_batch_N.json`
- run `./down_infra.sh` before next iteration

Resume behavior:
- if `study_results/results_batch_N.json` already exists, that `N` is skipped on rerun.

### Latest Results (ops=10000)

Results exported from:
- `study_results/results_batch_100.json`
- `study_results/results_batch_250.json`
- `study_results/results_batch_500.json`
- `study_results/results_batch_750.json`
- `study_results/results_batch_1000.json` (older run when `1000` was still included)

| N    | Native Audit Time | Vellum Verify Time | Auditor Speedup | Status            |
|------|-------------------|--------------------|-----------------|-------------------|
| 100  | 166.240 ms        | 215.013 ms         | 0.7732x         | native_faster     |
| 250  | 405.910 ms        | 216.550 ms         | 1.8744x         | vellum_advantage  |
| 500  | 822.539 ms        | 207.675 ms         | 3.9607x         | vellum_advantage  |
| 750  | 1,199.072 ms      | 214.134 ms         | 5.5996x         | vellum_advantage  |
| 1000 | 1,621.910 ms      | 201.295 ms         | 8.0574x         | vellum_advantage  |
