# Architecture

## Overview

Vellum Core consists of:

- **Framework contract** (`vellum_core.api`, `vellum_core.spi`, `vellum_core.runtime`)
- **Reference deployment** (`prover_service.py`, `worker.py`, `verifier_service.py`, `dashboard_service.py`)

The framework is provider-oriented and circuit-manifest-driven. Circuits are discovered from `circuits/**/manifest.json`, while proving artifacts are read from `shared_assets/`.

## Runtime Topology

- **Prover API (FastAPI)**
  - validates auth + request mode
  - creates `proof_jobs` in PostgreSQL
  - enqueues asynchronous work to Celery/Redis
- **Worker (Celery)**
  - fetches queued jobs
  - normalizes/validates inputs
  - generates proofs with provider (`SnarkJSProvider`)
  - persists outputs and audit events
- **Verifier API (FastAPI)**
  - verifies submitted proof/public signals
  - exposes trust-speed, circuits, and audit-chain endpoints
- **Dashboard API/UI (FastAPI + server-rendered HTML)**
  - aggregates data from prover/verifier
  - provides operations cockpit and demo flow

State dependencies:

- **PostgreSQL**: job and audit source of truth
- **Redis**: Celery broker + nonce replay protection
- **Vault Transit**: JWT signing, bank request signature verification, audit signatures
- **OpenTelemetry Collector + Tempo + Grafana**: trace ingestion, storage, and visualization

## Core Data Flow

1. Client sends `POST /v1/proofs/batch` with JWT + bank handshake headers.
2. Prover validates payload and stores queued job.
3. Worker transitions job `queued -> running -> completed|failed`.
4. Generated proof and public signals are persisted (`proof_jobs`) and signed into `audit_log`.
5. Verifier checks proof integrity via `POST /v1/verify`.
6. Audit integrity can be checked via `GET /v1/audit/verify-chain`.

## Request Modes

`BatchProveRequest` supports exactly one mode:

- `balances` + `limits` (only for `batch_credit_check`)
- `private_input` (generic mode for any circuit)

## Module Map

- `vellum_core.api`: stable client-facing framework API
- `vellum_core.spi`: extension protocols (provider, artifact store, signer, job backend)
- `vellum_core.runtime`: default runtime wiring
- `vellum_core.providers`: proof provider implementations (SnarkJS)
- `vellum_core.registry`: circuit discovery + artifact path resolution
- `vellum_core.logic.batcher`: batch pre-processing invariants
- `vellum_core.auth`: JWT and bank-handshake validation
- `vellum_core.proof_store`: signed audit chain and integrity verification

## Design Constraints

- Circuit IDs are runtime-selectable, but direct batch helpers are intentionally scoped to `batch_credit_check`.
- Public API compatibility guarantees apply to `vellum_core.api` and `vellum_core.spi` only.
- Reference service HTTP endpoints are best-effort stable and may evolve faster.
