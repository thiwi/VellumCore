# Architecture

## Overview

Vellum Core consists of:

- **Framework contract** (`vellum_core.api`, `vellum_core.spi`, `vellum_core.runtime`)
- **Reference deployment** (`prover_service.py`, `worker.py`, `verifier_service.py`, `dashboard_service.py`)
- **Policy packs** (`policy_packs/*/manifest.json`) for domain behavior and attestation semantics

The framework is provider-oriented and circuit-manifest-driven. Circuits are discovered from `circuits/**/manifest.json`, while proving artifacts are read from `shared_assets/`.

## Runtime Topology

- **Framework Init (one-shot compose bootstrap)**
  - compiles required circuit artifacts via `setup_framework.sh`
  - writes outputs into shared artifact volume (`shared_assets`)
  - must complete before prover/worker/verifier start in compose
- **Prover API (FastAPI)**
  - validates auth + request mode
  - creates `proof_jobs` in PostgreSQL
  - enqueues asynchronous work to Celery/Redis
- **Worker (Celery)**
  - fetches queued jobs
  - normalizes/validates inputs
  - generates proofs with configured provider (`SnarkJSProvider` or `GrpcProofProvider`)
  - optional shadow-compare mode (`ShadowProofProvider`) for backend migration
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

Bootstrap flow:

1. `framework-init` compiles and publishes required artifacts.
2. Prover/worker/verifier start only after bootstrap completion.

v5 primary flow:

1. Client sends `POST /v5/policy-runs` with JWT + bank handshake headers.
2. Prover resolves policy pack, normalizes evidence, and stores queued run.
3. Worker transitions run `queued -> running -> completed|failed`.
4. Worker persists proof/public signals and policy decision (`pass|fail`) in job metadata.
5. Verifier exports compliance attestation via `GET /v5/attestations/{attestation_id}`.
6. Audit integrity remains checkable via `GET /v1/audit/verify-chain`.

Quality gates:

- Contract surface: `pytest -m contract`
- Security regressions: `pytest -m security`

## Request Modes

`BatchProveRequest` supports exactly one mode:

- `balances` + `limits` (only for `batch_credit_check`)
- `private_input` (generic mode for any circuit)

`PolicyRunRequest` supports:

- `evidence_payload` (recommended)
- `evidence_ref` (pre-stored evidence)

## Module Map

- `vellum_core.api`: stable client-facing framework API
- `vellum_core.api.policy_engine`: policy-centric execution API
- `vellum_core.api.attestation_service`: attestation export API
- `vellum_core.spi`: extension protocols (provider, artifact store, signer, job backend)
- `vellum_core.spi`: plus `EvidenceStore` and `AttestationSigner`
- `vellum_core.runtime`: default runtime wiring
- `vellum_core.providers`: proof provider implementations (`snarkjs`, `grpc`, shadow wrapper)
- `vellum_core.policy_compiler`: YAML DSL compiler (`policy_spec.yaml -> Python + Circom`)
- `vellum_core.cutover_gate`: deterministic gate logic for grpc cutover readiness
- `vellum_core.registry`: circuit discovery + artifact path resolution
- `vellum_core.logic.batcher`: batch pre-processing invariants
- `vellum_core.auth`: JWT and bank-handshake validation
- `vellum_core.proof_store`: signed audit chain and integrity verification

## Design Constraints

- Circuit IDs are runtime-selectable, but direct batch helpers are intentionally scoped to `batch_credit_check`.
- Policy source-of-truth can be DSL-driven (`policy_spec.yaml`) with committed generated artifacts.
- Public API compatibility guarantees apply to `vellum_core.api` and `vellum_core.spi` only.
- Reference service HTTP endpoints are best-effort stable and may evolve faster.
