# Policy Packs

Policy packs define domain behavior for v5 policy runs.

## Layout

Policy packs are discovered from `POLICY_PACKS_DIR` (default: `<cwd>/policy_packs`).

Each policy pack must contain:

- `policy_packs/<policy_id>/manifest.json`

## Manifest fields

- `policy_id`: stable policy identifier.
- `policy_version`: semantic version of policy semantics.
- `circuit_id`: proving circuit used by this policy.
- `input_contract`: input requirements for submitters.
- `evidence_contract`: evidence format and constraints.
- `reference_policy`: Python reference-track policy implementation id.
- `primitives`: declared primitive ids, validated against runtime primitive catalog.
- `differential_outputs`: named public-signal projections (`signal_index`, `value_type`) checked in dual-track mode.
- `expected_attestation`: decision extraction hints for attestation export.
- `compiler_metadata`: generation metadata for DSL-transpiled policies (`spec_version`, `compiler_version`, `generated_from_hash`, generated paths).

## DSL Source (Transpiler Path)

Transpiled policies can define a canonical source file:

- `policy_packs/<policy_id>/policy_spec.yaml`

Use `vellum-compiler` to:

- validate spec schema,
- generate Python reference + Circom artifacts,
- sync `manifest.json.compiler_metadata` from the generated spec hash,
- check drift between committed generated files/compiler metadata and compiler output.

Current compiler support for generated decision logic:

- top-level `all` or `any` aggregation over array elements,
- recursive boolean composition: `comparison`, `and`, `or`, `not`, nested `all`/`any`,
- value references: `balances`, `limits`, `active_count`, and `const_int`,
- operators: `<`, `>`, `<=`, `>=`, `==`.
- Circom generation is primitive-based via `circuits/library/banking_library.circom`
  (`ActiveCountBounds`, `ActiveIndexFlag16`, `Primitive*` comparators, `ZeroPaddingInvariant`).

## Built-in policies

`lending_risk_v1`:

- circuit: `batch_credit_check`
- reference policy: `lending_risk_reference_v1`
- evidence modes:
  - `evidence_payload.private_input`
  - `evidence_payload.balances` + `evidence_payload.limits`
- decision mapping:
  - `public_signals[0] == "1"` => `pass`
  - otherwise => `fail`

`lending_risk_portfolio_v1`:

- circuit: `batch_credit_check`
- reference policy: `lending_risk_portfolio_reference_v1`
- evidence modes:
  - `evidence_payload.private_input`
  - `evidence_payload.balances` + `evidence_payload.limits`
- decision mapping:
  - `public_signals[0] == "1"` => `pass`
  - otherwise => `fail`
