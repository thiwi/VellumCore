# Vellum Core SDK (v6)

## Scope

`vellum_core` is the framework contract for direct integration.

Use the SDK when you want to:

- embed proving/verification in your own service
- keep transport/auth concerns outside your business logic
- swap providers via SPI without changing call sites

## Stable Public Surface

- `vellum_core.api`
  - `FrameworkClient`
  - `CircuitManager`
  - `ProofEngine`
  - `PolicyEngine`
  - `AttestationService`
  - strongly typed models in `vellum_core.api.types`
- `vellum_core.spi`
  - extension protocols for providers, artifact stores, signers, and job backends

## Minimal Usage

```python
from vellum_core.api import FrameworkClient, PolicyRunRequest

framework = FrameworkClient.from_env()
result = await framework.policy_engine.run(
    PolicyRunRequest(
        policy_id="lending_risk_v1",
        policy_params_ref="bank_profile_q2",
        evidence={"type": "inline", "payload": {"balances": [120], "limits": [100]}},
    )
)
bundle = await framework.attestation_service.export(result.attestation_id)
```

Example script: `examples/policy_run_sdk.py`

## Best Practices

- Always validate circuit artifact readiness before production rollout.
- Keep policy-specific evidence shaping outside core business layers.
- Treat `PolicyRunRequest`, `PolicyRunResult`, and `AttestationBundle` as immutable boundary objects.
- Prefer SPI-based substitution over editing runtime internals directly.

## Stability and Compatibility

- `vellum_core.api` and `vellum_core.spi` follow documented compatibility policy.
- Reference service schemas in `vellum_core.schemas` are deployment-specific and evolve faster.
- See `docs/COMPATIBILITY.md` for deprecation windows and versioning guarantees.
