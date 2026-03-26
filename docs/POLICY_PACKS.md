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
- `expected_attestation`: decision extraction hints for attestation export.

## Built-in policy

`lending_risk_v1`:

- circuit: `batch_credit_check`
- evidence modes:
  - `evidence_payload.private_input`
  - `evidence_payload.balances` + `evidence_payload.limits`
- decision mapping:
  - `public_signals[0] == "1"` => `pass`
  - otherwise => `fail`
