# Provider Cutover Gate

This document defines how to evaluate readiness for switching primary proof provider from `snarkjs` to `grpc`.

## Hard Gates

All of the following must pass:

- Shadow window at least 7 days.
- At least 1000 compared runs with valid comparison data.
- Zero functional mismatches.
- At least 2x p95 proof latency improvement (`snarkjs_p95_ms / grpc_p95_ms >= 2.0`).

## Local/Manual Benchmark

Run reproducible benchmark against the same policy payload for both modes:

```bash
RUNS=40 DAYS_OBSERVED=0 COMPARED_RUNS=0 FUNCTIONAL_MISMATCHES=0 \
  ./systematic_study/run_provider_benchmark.sh
```

Automatic shadow-derived gate inputs (recommended):

```bash
RUNS=40 SHADOW_RUNS=1200 DAYS_OBSERVED=7 \
  ./systematic_study/run_provider_benchmark.sh
```

When `SHADOW_RUNS>0`, the script runs an additional shadow-mode phase
(`snarkjs` primary + `grpc` shadow), scrapes worker metrics, and feeds
`compared_runs` + `functional_mismatches` into cutover evaluation automatically.
Use `SHADOW_NATIVE_GENERATE_BACKEND=rapidsnark` to ensure shadow comparisons
run against the same native generate backend used for grpc cutover benchmarking.

Outputs:

- `systematic_study/reports/provider_cutover/snarkjs_benchmark.json`
- `systematic_study/reports/provider_cutover/grpc_snarkjs_benchmark.json`
- `systematic_study/reports/provider_cutover/shadow_benchmark.json` (when `SHADOW_RUNS>0`)
- `systematic_study/reports/provider_cutover/shadow_summary.json` (when `SHADOW_RUNS>0`)
- `systematic_study/reports/provider_cutover/cutover_gate.json`

Optional extra mode (`rapidsnark` generate backend inside native-prover):

```bash
ENABLE_RAPIDSNARK=1 RAPIDSNARK_DOWNLOAD_URL=<binary-url> \
RUNS=40 DAYS_OBSERVED=0 COMPARED_RUNS=0 FUNCTIONAL_MISMATCHES=0 \
  ./systematic_study/run_provider_benchmark.sh
```

Optional gate source selection for grpc benchmark:

- `GATE_GRPC_MODE=snarkjs` (default): use `grpc_snarkjs_benchmark.json`
- `GATE_GRPC_MODE=rapidsnark`: use `grpc_rapidsnark_benchmark.json` (requires `ENABLE_RAPIDSNARK=1`)
- `GATE_GRPC_MODE=auto`: use whichever grpc benchmark has lower p95

Optional witness backend override for `rapidsnark` mode:

```bash
ENABLE_RAPIDSNARK=1 RAPIDSNARK_DOWNLOAD_URL=<binary-url> \
NATIVE_WITNESS_BACKEND=binary WITNESS_GEN_BIN=/usr/local/bin/witnesscalc \
WITNESSCALC_DOWNLOAD_URL=<witnesscalc-url> \
RUNS=40 DAYS_OBSERVED=0 COMPARED_RUNS=0 FUNCTIONAL_MISMATCHES=0 \
  ./systematic_study/run_provider_benchmark.sh
```

Shadow mode against `rapidsnark` (recommended when evaluating grpc cutover):

```bash
ENABLE_RAPIDSNARK=1 GATE_GRPC_MODE=rapidsnark \
SHADOW_NATIVE_GENERATE_BACKEND=rapidsnark \
RAPIDSNARK_DOWNLOAD_URL=<binary-url> \
RUNS=40 SHADOW_RUNS=1200 DAYS_OBSERVED=7 \
  ./systematic_study/run_provider_benchmark.sh
```

## GitHub Workflow

Manual workflow is available at:

- `.github/workflows/provider-benchmark.yml`

It runs the same benchmark script and uploads JSON artifacts.

## Gate-Only Evaluation

If you already have benchmark/shadow summary values:

```bash
vellum-cutover-gate --summary-json path/to/cutover_summary.json
```

Required JSON keys:

- `days_observed`
- `compared_runs`
- `functional_mismatches`
- `snarkjs_p95_ms`
- `grpc_p95_ms`

## Runtime Enforcement

To block accidental grpc cutover before gates pass, set:

- `GRPC_CUTOVER_GATE_ENFORCED=true`
- `GRPC_CUTOVER_GATE_REPORT_PATH=/path/to/cutover_gate.json`

When enforced and `PROOF_PROVIDER_MODE=grpc`, startup fails unless the report marks `pass_gate=true`.
