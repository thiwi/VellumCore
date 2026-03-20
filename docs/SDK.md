# Vellum Core SDK (v1)

## Scope

`vellum_core` is the framework contract for direct integration.

Use the SDK when you want to:

- embed proving/verification in your own service
- keep transport/auth concerns outside your business logic
- swap providers/adapters via SPI without changing call sites

## Stable Public Surface

- `vellum_core.api`
  - `FrameworkClient`
  - `CircuitManager`
  - `ProofEngine`
  - strongly typed models in `vellum_core.api.types`
- `vellum_core.spi`
  - extension protocols for providers, artifact stores, input adapters, signers, and job backends

## Minimal Usage

```python
from vellum_core.api import FrameworkClient, ProofGenerationRequest

framework = FrameworkClient.from_env()
result = await framework.proof_engine.generate(
    ProofGenerationRequest(
        circuit_id="batch_credit_check",
        private_input={
            "balances": ["120"],
            "limits": ["100"],
            "active_count": "1",
        },
    )
)
```

## Best Practices

- Always validate circuit artifact readiness before production rollout.
- Keep circuit-specific request payload shaping outside core business layers.
- Treat `ProofGenerationRequest` / `VerificationRequest` as immutable boundary objects.
- Prefer SPI-based substitution over editing runtime internals directly.

## Stability and Compatibility

- `vellum_core.api` and `vellum_core.spi` follow documented compatibility policy.
- Reference service schemas in `vellum_core.schemas` are deployment-specific and evolve faster.
- See `docs/COMPATIBILITY.md` for deprecation windows and versioning guarantees.
