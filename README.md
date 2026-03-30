# Vellum Core

Vellum Core is an open-source, compliance-ready ZK pipeline for lending risk controls.

![Vellum Core Logo](docs/vellumcore_logo.png)

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
python scripts/sync_requirements.py check
python -m pytest -m unit
python -m pytest -m integration
python -m pytest -m contract
python -m pytest -m security
RUN_E2E=1 python -m pytest -m "e2e and critical"
cargo test --manifest-path native_prover/Cargo.toml
pip install pip-audit
pip-audit -r requirements.txt
python -m build
```

Dependency governance (canonical source = `pyproject.toml`):

```bash
python scripts/sync_requirements.py export
python scripts/sync_requirements.py check
```

`requirements.txt` stays committed for Dockerfiles and `pip-audit`, but must match `pyproject.toml`.

GitHub CI runs the same quality gates:

- `pip-audit -r requirements.txt` (dependency CVE gate)
- `cargo test --manifest-path native_prover/Cargo.toml` (native prover gate)
- `python scripts/sync_requirements.py check` (requirements drift gate)

See [`docs/CI.md`](docs/CI.md) for the full CI matrix and local reproduction commands.

## Policy Compiler (Single Source)

`lending_risk_v1` now ships with a canonical DSL source:

- [`policy_packs/lending_risk_v1/policy_spec.yaml`](policy_packs/lending_risk_v1/policy_spec.yaml)
- [`policy_packs/lending_risk_portfolio_v1/policy_spec.yaml`](policy_packs/lending_risk_portfolio_v1/policy_spec.yaml)

Generate artifacts from DSL:

```bash
vellum-compiler validate policy_packs/lending_risk_v1/policy_spec.yaml
vellum-compiler generate policy_packs/lending_risk_v1/policy_spec.yaml --repo-root .
vellum-compiler check-drift policy_packs/lending_risk_v1/policy_spec.yaml --repo-root .
```

`generate` also updates `policy_packs/<policy_id>/manifest.json` compiler metadata (`generated_from_hash`, paths, versions) when a manifest exists next to the spec.

Generated files are committed for auditability:

- `vellum_core/policies/generated/lending_risk_reference_v1.py`
- `policy_packs/lending_risk_v1/generated/lending_risk_v1.generated.circom`

## Native gRPC Prover (Optional)

Vellum runtime supports two proof backends:

- `snarkjs` (default)
- `grpc` (Rust native prover service)

Runtime knobs:

- `PROOF_PROVIDER_MODE=snarkjs|grpc`
- `GRPC_PROVER_ENDPOINT=host:port`
- `PROOF_SHADOW_MODE=true|false`
- `PROOF_SHADOW_PROVIDER_MODE=snarkjs|grpc`
- `PROOF_SHADOW_COMPARE_PUBLIC_SIGNALS=true|false`

Rust service sources live in [`native_prover/`](native_prover/README.md).
Current phase keeps Circom compatibility with split backend:
- generate via `snarkjs` (or optional `rapidsnark` path inside native-prover)
- verify via native Rust `arkworks` (BN254/Groth16)

Local prerequisite for Rust build/tests: `protoc` (Protocol Buffers compiler).
- Ubuntu/Debian: `sudo apt-get install -y protobuf-compiler`
- macOS: `brew install protobuf`

Cutover gate evaluation:

```bash
vellum-cutover-gate --summary-json path/to/cutover_summary.json
```

Provider benchmark runner (snarkjs vs grpc, same payload):

```bash
RUNS=40 DAYS_OBSERVED=0 COMPARED_RUNS=0 FUNCTIONAL_MISMATCHES=0 \
  ./systematic_study/run_provider_benchmark.sh
```

Shadow-assisted gate evaluation (auto derives compared runs + mismatches):

```bash
RUNS=40 SHADOW_RUNS=1200 DAYS_OBSERVED=7 \
  ./systematic_study/run_provider_benchmark.sh
```

To run shadow in the same native generate mode as grpc cutover benchmarking:

```bash
ENABLE_RAPIDSNARK=1 GATE_GRPC_MODE=rapidsnark \
SHADOW_NATIVE_GENERATE_BACKEND=rapidsnark RAPIDSNARK_DOWNLOAD_URL=<binary-url> \
RUNS=40 SHADOW_RUNS=1200 DAYS_OBSERVED=7 \
  ./systematic_study/run_provider_benchmark.sh
```

Optional additional benchmark mode with `rapidsnark` generate backend:

```bash
ENABLE_RAPIDSNARK=1 RAPIDSNARK_DOWNLOAD_URL=<binary-url> \
RUNS=40 DAYS_OBSERVED=0 COMPARED_RUNS=0 FUNCTIONAL_MISMATCHES=0 \
  ./systematic_study/run_provider_benchmark.sh
```

Use `rapidsnark` benchmark as grpc gate source:

```bash
ENABLE_RAPIDSNARK=1 GATE_GRPC_MODE=rapidsnark RAPIDSNARK_DOWNLOAD_URL=<binary-url> \
RUNS=40 SHADOW_RUNS=1200 DAYS_OBSERVED=7 \
  ./systematic_study/run_provider_benchmark.sh
```

Optional witness backend override for the `rapidsnark` path:

```bash
ENABLE_RAPIDSNARK=1 RAPIDSNARK_DOWNLOAD_URL=<binary-url> \
NATIVE_WITNESS_BACKEND=binary WITNESS_GEN_BIN=/usr/local/bin/witnesscalc \
WITNESSCALC_DOWNLOAD_URL=<witnesscalc-url> \
RUNS=40 DAYS_OBSERVED=0 COMPARED_RUNS=0 FUNCTIONAL_MISMATCHES=0 \
  ./systematic_study/run_provider_benchmark.sh
```

## OSS Governance

- License: Apache-2.0 (`LICENSE`)
- Contribution guide: `CONTRIBUTING.md`
- Code of conduct: `CODE_OF_CONDUCT.md`
- Security process: `SECURITY.md`

## Documentation

- Documentation index: [docs/README.md](docs/README.md)
- CI and quality gates: [docs/CI.md](docs/CI.md)
- Migration notes: [docs/MIGRATION_V4_TO_V5.md](docs/MIGRATION_V4_TO_V5.md)
- API reference: [docs/API_REFERENCE.md](docs/API_REFERENCE.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
