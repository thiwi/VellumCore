# Vellum Core

Vellum Core v5 is an open-source, compliance-ready ZK pipeline for lending risk controls.

## Positioning

Vellum Core focuses on regulated fintech workflows:

- policy-centric API surface (`PolicyEngine`, `AttestationService`)
- signed audit chain and evidence traceability
- reference services for prover, worker, verifier, and operations dashboard

## v5 Surface (Primary)

Framework contract:

- `vellum_core.api`
- `vellum_core.spi`
- `vellum_core.runtime`

Primary domain objects:

- `PolicyRunRequest { policy_id, evidence_payload|evidence_ref, context }`
- `PolicyRunResult { run_id, policy_id, decision, attestation_id, timings }`
- `AttestationBundle { policy_version, circuit_id, proof_hash, public_signals_hash, artifact_digests, signature_chain }`

## SDK Quick Start (v5)

```python
from vellum_core.api import FrameworkClient, PolicyRunRequest

framework = FrameworkClient.from_env()
result = await framework.policy_engine.run(
    PolicyRunRequest(
        policy_id="lending_risk_v1",
        evidence_payload={"balances": [120], "limits": [100]},
        context={"tenant": "acme-bank"},
    )
)
attestation = await framework.attestation_service.export(result.attestation_id)
```

## Reference Services

Start full stack:

```bash
./up_infra.sh
```

`framework-init` now prepares required circuit artifacts during compose startup.

v5 endpoints:

- Prover: `POST /v5/policy-runs`, `GET /v5/policy-runs/{run_id}`
- Verifier: `GET /v5/attestations/{attestation_id}`
- Dashboard proxies:
  - `POST /api/v5/policy-runs`
  - `GET /api/v5/policy-runs/{run_id}`
  - `GET /api/v5/attestations/{attestation_id}`

Legacy v1 endpoints remain available with deprecation headers and sunset metadata.

## Development

Install runtime + dev extras:

```bash
pip install -e .[dev]
```

Run checks:

```bash
ruff check .
mypy --follow-imports=skip --ignore-missing-imports vellum_core/api/attestation_service.py vellum_core/api/policy_engine.py vellum_core/policy_registry.py vellum_core/policy_runtime.py
python -m pytest -m unit
python -m pytest -m integration
python -m pytest -m contract
python -m pytest -m security
RUN_E2E=1 python -m pytest -m "e2e and critical"
```

## OSS Governance

- License: Apache-2.0 (`LICENSE`)
- Contribution guide: `CONTRIBUTING.md`
- Code of conduct: `CODE_OF_CONDUCT.md`
- Security process: `SECURITY.md`

## Documentation

- Documentation index: [docs/README.md](docs/README.md)
- Migration notes: [docs/MIGRATION_V4_TO_V5.md](docs/MIGRATION_V4_TO_V5.md)
- API reference: [docs/API_REFERENCE.md](docs/API_REFERENCE.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
