# Circuit YAML Guide (`policy_spec.yaml`)

This guide explains how to write the YAML spec used by the Vellum policy compiler to generate:

- a reference Python policy
- a generated Circom circuit file
- compiler metadata for the policy pack

The file is usually located at:

- `policy_packs/<policy_id>/policy_spec.yaml`

## 1) Full Example (Recommended Starting Point)

```yaml
policy_id: lending_risk_v1
policy_version: "1.0.0"
reference_policy: lending_risk_reference_v1
spec_version: "1.0.0"
compiler_version: "0.1.0"
description: Batch lending risk control proving all active balances exceed limits.

batch:
  batch_size: 250

inputs:
  balances:
    kind: uint32_array
  limits:
    kind: uint32_array

decision:
  kind: all
  inner:
    kind: comparison
    comparison:
      op: ">"
      left:
        ref: balances
      right:
        ref: limits

outputs:
  all_valid:
    expr: decision
    value_type: bool
    signal_index: 0
  active_count_out:
    expr: active_count
    value_type: int
    signal_index: 1

primitives:
  - SafeSub
  - InterestRateValidator
  - MerkleProof
  - BalanceGreaterThanLimit
  - ActiveCountBounds
  - ZeroPaddingInvariant

expected_attestation:
  decision_signal_index: 0
  pass_signal_value: "1"

generated_python_path: vellum_core/policies/generated/lending_risk_reference_v1.py
generated_circom_path: policy_packs/lending_risk_v1/generated/lending_risk_v1.generated.circom
generated_debug_trace_path: policy_packs/lending_risk_v1/generated/lending_risk_v1.generated.debug.json
circuit_id: batch_credit_check
```

## 2) Required Top-Level Fields

- `policy_id`: unique policy identifier.
- `policy_version`: semantic version for policy behavior.
- `reference_policy`: ID of the reference policy implementation.
- `spec_version`: DSL spec version.
- `compiler_version`: expected compiler version.
- `batch.batch_size`: fixed batch size (`>= 1`).
- `inputs`: input declarations (currently only `uint32_array`).
- `decision`: recursive boolean decision expression.
- `outputs`: public outputs projected from decision/runtime values.
- `primitives`: primitive IDs declared by the policy.
- `expected_attestation`: hints for pass/fail extraction from public signals.
- `generated_python_path`: output path for generated Python reference code.
- `generated_circom_path`: output path for generated Circom.
- `generated_debug_trace_path`: output path for generated explainability/debug metadata JSON.
- `circuit_id`: target circuit ID used by the policy.

Optional:

- `description`

## 3) Decision DSL (What You Can Express)

Supported decision kinds:

- `comparison`
- `and`
- `or`
- `not`
- `all`
- `any`

Supported comparison operators:

- `<`, `>`, `<=`, `>=`, `==`

Supported value sources:

- `ref: balances`
- `ref: limits`
- `ref: active_count`
- `param: <policy_parameter_name>`
- `const_int: <integer>`

## 3.4 Policy Parameters

You can declare policy parameters with typed bounds/defaults and reference them via `param`:

```yaml
policy_parameters:
  min_balance:
    value_type: int
    minimum: 0
    maximum: 1000000
    default: 100
```

### 3.1 `comparison`

```yaml
decision:
  kind: comparison
  comparison:
    op: ">="
    left:
      ref: active_count
    right:
      const_int: 10
```

Rules:

- must include `comparison`
- must not include `args` or `inner`

### 3.2 `and` / `or`

```yaml
decision:
  kind: and
  args:
    - kind: comparison
      comparison:
        op: ">"
        left: { ref: active_count }
        right: { const_int: 0 }
    - kind: comparison
      comparison:
        op: "<="
        left: { ref: active_count }
        right: { const_int: 250 }
```

Rules:

- must include at least 2 `args`
- must not include `comparison` or `inner`

### 3.3 `not`, `all`, `any`

```yaml
decision:
  kind: not
  inner:
    kind: comparison
    comparison:
      op: "=="
      left: { ref: active_count }
      right: { const_int: 0 }
```

Rules:

- must include `inner`
- must not include `comparison` or `args`

`all` and `any` are typically used for batch element checks.

## 4) Outputs Section

Each output must define:

- `expr`
- `value_type` (`int`, `bool`, `string`)
- `signal_index` (`>= 0`)

Current supported `expr` values are:

- `decision`
- `active_count`
- `policy_params_hash`

Example:

```yaml
outputs:
  all_valid:
    expr: decision
    value_type: bool
    signal_index: 0
  active_count_out:
    expr: active_count
    value_type: int
    signal_index: 1
```

## 5) Primitives

Use only primitives supported by runtime validation:

- `SafeSub`
- `InterestRateValidator`
- `MerkleProof`
- `BalanceGreaterThanLimit`
- `ActiveCountBounds`
- `ZeroPaddingInvariant`

## 6) Validate and Generate

From repository root:

```bash
vellum-compiler validate policy_packs/<policy_id>/policy_spec.yaml
vellum-compiler generate policy_packs/<policy_id>/policy_spec.yaml --repo-root .
vellum-compiler check-drift policy_packs/<policy_id>/policy_spec.yaml --repo-root .
```

## 7) Common Errors

- Defining both `ref` and `const_int` in one value node.
- Missing `inner` for `not`/`all`/`any`.
- Using fewer than 2 `args` for `and`/`or`.
- Using unsupported output expression (anything other than `decision` / `active_count`).
- Unknown primitive IDs.
- Paths in `generated_python_path` / `generated_circom_path` not matching repository layout.
