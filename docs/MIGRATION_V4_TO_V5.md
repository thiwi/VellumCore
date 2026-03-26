# Migration: v4 to v5

v5 introduces policy-centric primary APIs while keeping v1 endpoints in legacy mode.

## What changed

- New primary endpoints:
  - `POST /v5/policy-runs`
  - `GET /v5/policy-runs/{run_id}`
  - `GET /v5/attestations/{attestation_id}`
- New framework API objects:
  - `PolicyRunRequest`
  - `PolicyRunResult`
  - `AttestationBundle`
- New SPI protocols:
  - `EvidenceStore`
  - `AttestationSigner`

## Legacy status of v1

v1 endpoints continue to work, but now return deprecation metadata headers:

- `Deprecation: true`
- `Sunset: Tue, 30 Sep 2026 00:00:00 GMT`

## Integration migration path

1. Switch submit flow from circuit payloads to policy runs.
2. Persist `run_id` + `attestation_id` as primary business references.
3. Consume verifier attestation export for external audit evidence packages.
4. Keep direct circuit integration only for transitional workloads.

## Code migration example

Before:

```python
from vellum_core.api import FrameworkClient, ProofGenerationRequest

framework = FrameworkClient.from_env()
proof = await framework.proof_engine.generate(
    ProofGenerationRequest(circuit_id="batch_credit_check", private_input=payload)
)
```

After:

```python
from vellum_core.api import FrameworkClient, PolicyRunRequest

framework = FrameworkClient.from_env()
result = await framework.policy_engine.run(
    PolicyRunRequest(policy_id="lending_risk_v1", evidence_payload=payload)
)
bundle = await framework.attestation_service.export(result.attestation_id)
```
