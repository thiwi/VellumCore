# Vellum Core

Vellum Core is a batch-first ZK framework and reference deployment stack (formerly SentinelZK / `sentinel_zk`).

## What Is Framework vs. Reference Deployment?

Framework (stable contract):
- `vellum_core.api`
- `vellum_core.spi`
- `vellum_core.runtime`

Reference deployment (operational example built on SDK):
- `prover_service.py`
- `worker.py`
- `verifier_service.py`
- `dashboard_service.py`

## Architecture (Current)

- FastAPI prover/verifier services with JWT + bank handshake auth.
- Celery worker for asynchronous proving.
- PostgreSQL as system-of-record (`proof_jobs`, `audit_log`).
- Redis for queue broker and nonce replay protection.
- Vault Transit for JWT, bank signatures, and audit chain signing.
- SnarkJS-based proof generation and verification with manifest-discovered circuits.

## SDK Quick Start

```python
from vellum_core.api import FrameworkClient, ProofGenerationRequest

framework = FrameworkClient.from_env()
result = await framework.proof_engine.generate(
    ProofGenerationRequest(
        circuit_id="batch_credit_check",
        private_input={"balances": ["120"], "limits": ["100"], "active_count": "1"},
    )
)
```

## CLI

After installing package mode (`pip install -e .`):

```bash
vellum circuits list
vellum circuits validate --json
```

## Reference Services

Start full stack:

```bash
./up_infra.sh
```

Compile/setup circuit artifacts:

```bash
docker compose exec prover /app/setup_framework.sh
```

Health checks:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8001/healthz
curl -fsS http://localhost:8002/healthz
```

Stop stack:

```bash
./down_infra.sh
```

## API Surface (Reference Deployment)

Prover:
- `POST /v1/proofs/batch`
- `GET /v1/proofs/{proof_id}`
- `GET /metrics`

Verifier:
- `POST /v1/verify`
- `GET /v1/audit/verify-chain`
- `GET /v1/trust-speed`
- `GET /v1/circuits`
- `GET /metrics`

Dashboard/Console:
- Environment health view
- Circuit/artifact status
- Proof submit/status
- Verification + audit-chain checks
- Trust-speed and diagnostics

## Testing Strategy

- Unit tests: isolated SDK behavior and model validation.
- Integration tests: framework runtime wiring, dashboard backend routes, artifact discovery/validation.
- E2E tests: docker-compose flow with critical-path and nightly matrix.

Commands:

```bash
pytest -m unit
pytest -m integration
RUN_E2E=1 pytest -m "e2e and critical"
RUN_E2E=1 pytest -m "e2e and nightly"
```

## Systematic Performance Study

`systematic_study/run_systematic_study.sh` and `systematic_study/study_results/*.json`
are kept for benchmarking evidence only.
They are not required for framework feature validation/release gating.

## Documentation

- Documentation index: [docs/README.md](docs/README.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- API reference: [docs/API_REFERENCE.md](docs/API_REFERENCE.md)
- Configuration: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
- Operations runbook: [docs/OPERATIONS.md](docs/OPERATIONS.md)
- Development guide: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Security model: [docs/SECURITY.md](docs/SECURITY.md)
- Troubleshooting: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- SDK: [docs/SDK.md](docs/SDK.md)
- Reference services: [docs/REFERENCE_SERVICES.md](docs/REFERENCE_SERVICES.md)
- Compatibility policy: [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)
- Release checklist: [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
