# Sentinel-ZK Core

Modular local-first framework for proving and verifying Circom/SnarkJS proofs with:
- dynamic circuit registry
- pluggable ZK provider abstraction
- JWT + signed-request handshake
- append-only audit log with signed hash-chain links
- interactive dashboard GUI for live demo flows
- 100-decision batch proving endpoint for credit decisions
- stress testing harness for proving latency and resource pressure
- Docker Compose deployment for `linux/amd64` and `linux/arm64`

## Project Layout

- `prover_service.py`: async proof job API (`POST /v1/proofs`, `POST /v1/proofs/batch`, `GET /v1/proofs/{proof_id}`)
- `verifier_service.py`: verification API (`POST /v1/verify`) + audit chain verifier (`GET /v1/audit/verify-chain`)
- `sentinel_zk/registry.py`: dynamic circuit discovery from `/circuits/<circuit_id>/manifest.json`
- `sentinel_zk/providers/`: provider interface + `SnarkJSProvider`
- `sentinel_zk/proof_store.py`: JSONL proof/audit store with signed chain links
- `circuits/library/banking_library.circom`: reusable `RangeProof32`, `MerkleInclusionPoseidonDepth10`, `FixedPoint*`
- `circuits/batch_credit_check/`: canonical batch circuit (`BatchCreditCheck(100)`)
- `benchmark_comparison.py`: native vs ZK verification benchmark utility
- `benchmark_batch.py`: 100-decision native-vs-single-batch-verify showdown
- `stress_tester.py`: prover saturation harness with latency/CPU/RSS metrics
- `setup_framework.sh`: compiles all runnable manifest-backed circuits and generates Groth16 artifacts

## Circuit Structure

Each circuit must be placed in:

```text
circuits/<circuit_id>/
  <circuit_id>.circom
  manifest.json
```

`manifest.json` requires:
- `circuit_id`
- `input_schema` (JSON schema for proving input)
- `public_signals`
- `version`

`circuits/library/` is reserved for reusable templates and is not compiled as a standalone circuit.

## Quickstart

1. Build and start services:

```bash
./up_infra.sh
```

This regenerates dev PEM keys in `config/` and recreates containers so all services use the fresh keys.
Because audit keys are rotated, `up_infra.sh` also resets the dev audit log (`/shared_store/proof_audit.jsonl`).

Stop and remove all compose containers:

```bash
./down_infra.sh
```

2. Generate proving/verification artifacts in the prover container:

```bash
docker compose exec prover /app/setup_framework.sh
```

3. Health checks:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8001/healthz
curl -fsS http://localhost:8002/healthz
```

4. Open the GUI:

- Dashboard: `http://localhost:8000`
- Prover Swagger: `http://localhost:8001/docs`
- Verifier Swagger: `http://localhost:8002/docs`

The dashboard can:
- list available circuits
- submit proof jobs
- poll proof status
- verify completed proofs end-to-end

## Batch API (Hard Replacement)

- `POST /v1/proofs/batch`: submit `balances` + `limits` with 1..100 records.
  - Request shape:
    - `balances: number[]` (len 1..100)
    - `limits: number[]` (len 1..100)
    - `request_id?: string`
  - Server pads to 100 rows, sets `active_count`, and proves against `batch_credit_check`.
- Old `credit_batch_v1` item-based payload is removed from the runtime batch path (hard replacement).
- `GET /v1/audit/verify-chain`: verify signed integrity of the complete audit chain.

## Auth Config (Dev)

- JWT public key: `config/jwt_public.pem`
- Bank request verification keys: `config/bank_public_keys.json`
- Dev private keys (for local tests only):
  - `config/dev_jwt_private.pem`
  - `config/dev_bank_private.pem`
- Audit chain keys:
  - `config/audit_private.pem`
  - `config/audit_public.pem`

Manual key regeneration (optional):

```bash
./bootstrap_dev_keys.sh
```

## Benchmark Utility

Run deterministic benchmark for 1,000 credit decisions:

```bash
docker compose exec prover python /app/benchmark_comparison.py --sample-size 1000
```

It compares:
- native auditor re-calculation time
- ZK proof verification time (proof generation excluded from timed verify section)

Run the 100-decision batch showdown:

```bash
docker compose exec prover python /app/benchmark_batch.py
```

Output includes:
- native total time for 100 `balance > limit` checks
- single batch proof verification time
- proving overhead (separate)
- auditor speedup ratio (`Native / single ZK verify`)

Batching is the compliance bottleneck killer because the auditor verifies one proof for many decisions instead of verifying each decision independently.

## Stress Tester

Run stress service (profile-based):

```bash
docker compose --profile stress up --build stress_tester
```

Output report:
- `stress_results/stress_report.json`
- includes latency percentiles, throughput, Prover CPU/RSS peaks, and thermal-throttling indicator by degradation trend.

## Multi-Arch Build (optional)

```bash
docker buildx build --platform linux/amd64,linux/arm64 -f Dockerfile.prover -t sentinel-zk/prover:dev --load .
docker buildx build --platform linux/amd64,linux/arm64 -f Dockerfile.verifier -t sentinel-zk/verifier:dev --load .
```
