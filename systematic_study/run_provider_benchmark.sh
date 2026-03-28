#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

RUNS="${RUNS:-40}"
PAYLOAD_JSON="${PAYLOAD_JSON:-$ROOT_DIR/examples/real_policy_runs/portfolio_mortgage_q1_pass.json}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/systematic_study/reports/provider_cutover}"
DAYS_OBSERVED="${DAYS_OBSERVED:-0}"
COMPARED_RUNS="${COMPARED_RUNS:-0}"
FUNCTIONAL_MISMATCHES="${FUNCTIONAL_MISMATCHES:-0}"
SHADOW_RUNS="${SHADOW_RUNS:-0}"
SHADOW_METRICS_URL="${SHADOW_METRICS_URL:-http://localhost:9108/metrics}"
ENABLE_RAPIDSNARK="${ENABLE_RAPIDSNARK:-0}"
RAPIDSNARK_BIN="${RAPIDSNARK_BIN:-rapidsnark}"
RAPIDSNARK_DOWNLOAD_URL="${RAPIDSNARK_DOWNLOAD_URL:-}"
GATE_GRPC_MODE="${GATE_GRPC_MODE:-snarkjs}"
SHADOW_NATIVE_GENERATE_BACKEND="${SHADOW_NATIVE_GENERATE_BACKEND:-}"
NATIVE_WITNESS_BACKEND="${NATIVE_WITNESS_BACKEND:-snarkjs}"
WITNESS_GEN_BIN="${WITNESS_GEN_BIN:-witnesscalc}"
WITNESSCALC_DOWNLOAD_URL="${WITNESSCALC_DOWNLOAD_URL:-}"

SNARKJS_OUT="$OUT_DIR/snarkjs_benchmark.json"
GRPC_OUT="$OUT_DIR/grpc_snarkjs_benchmark.json"
GRPC_RAPIDSNARK_OUT="$OUT_DIR/grpc_rapidsnark_benchmark.json"
SHADOW_OUT="$OUT_DIR/shadow_benchmark.json"
SHADOW_SUMMARY_OUT="$OUT_DIR/shadow_summary.json"
GATE_OUT="$OUT_DIR/cutover_gate.json"

mkdir -p "$OUT_DIR"

if [[ -z "$SHADOW_NATIVE_GENERATE_BACKEND" ]]; then
  if [[ "$ENABLE_RAPIDSNARK" == "1" && "$GATE_GRPC_MODE" != "snarkjs" ]]; then
    SHADOW_NATIVE_GENERATE_BACKEND="rapidsnark"
  else
    SHADOW_NATIVE_GENERATE_BACKEND="snarkjs"
  fi
fi

case "$SHADOW_NATIVE_GENERATE_BACKEND" in
  snarkjs|rapidsnark)
    ;;
  *)
    echo "[error] unsupported SHADOW_NATIVE_GENERATE_BACKEND=$SHADOW_NATIVE_GENERATE_BACKEND (expected: snarkjs|rapidsnark)" >&2
    exit 1
    ;;
esac

compose_down() {
  docker compose -f "$ROOT_DIR/docker-compose.yml" down --remove-orphans
}

cleanup() {
  compose_down || true
}

trap cleanup EXIT

wait_dashboard() {
  local timeout_seconds=240
  local started
  started="$(date +%s)"
  while true; do
    if curl -fsS "http://localhost:8000/healthz" >/dev/null 2>&1; then
      return 0
    fi
    if (( $(date +%s) - started > timeout_seconds )); then
      echo "[error] timeout waiting for dashboard health" >&2
      return 1
    fi
    sleep 2
  done
}

run_benchmark_mode() {
  local mode="$1"
  local out_json="$2"
  shift 2

  echo "[bench] starting mode=$mode"
  compose_down || true
  "$@"
  wait_dashboard

  python systematic_study/benchmark_policy_runs.py \
    --base-url "http://localhost:8000" \
    --payload-json "$PAYLOAD_JSON" \
    --runs "$RUNS" \
    --mode-label "$mode" \
    --output-json "$out_json"

  compose_down
  echo "[bench] completed mode=$mode output=$out_json"
}

run_shadow_collection() {
  echo "[shadow] starting shadow-mode run collection backend=$SHADOW_NATIVE_GENERATE_BACKEND"
  compose_down || true
  env PROOF_PROVIDER_MODE=snarkjs \
      GRPC_PROVER_ENDPOINT=native-prover:50051 \
      PROOF_SHADOW_MODE=true \
      PROOF_SHADOW_PROVIDER_MODE=grpc \
      PROOF_SHADOW_COMPARE_PUBLIC_SIGNALS=true \
      NATIVE_GENERATE_BACKEND="$SHADOW_NATIVE_GENERATE_BACKEND" \
      RAPIDSNARK_BIN="$RAPIDSNARK_BIN" \
      RAPIDSNARK_DOWNLOAD_URL="$RAPIDSNARK_DOWNLOAD_URL" \
      NATIVE_WITNESS_BACKEND="$NATIVE_WITNESS_BACKEND" \
      WITNESS_GEN_BIN="$WITNESS_GEN_BIN" \
      WITNESSCALC_DOWNLOAD_URL="$WITNESSCALC_DOWNLOAD_URL" \
      docker compose -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/docker-compose.grpc.yml" up --build -d
  wait_dashboard

  python systematic_study/benchmark_policy_runs.py \
    --base-url "http://localhost:8000" \
    --payload-json "$PAYLOAD_JSON" \
    --runs "$SHADOW_RUNS" \
    --mode-label "shadow-snarkjs-primary-$SHADOW_NATIVE_GENERATE_BACKEND" \
    --output-json "$SHADOW_OUT"

  python systematic_study/collect_shadow_metrics.py \
    --metrics-url "$SHADOW_METRICS_URL" \
    --fallback-benchmark-json "$SHADOW_OUT" \
    --output-json "$SHADOW_SUMMARY_OUT"

  compose_down
  echo "[shadow] completed shadow collection backend=$SHADOW_NATIVE_GENERATE_BACKEND output=$SHADOW_SUMMARY_OUT"
}

run_benchmark_mode "snarkjs" "$SNARKJS_OUT" \
  docker compose -f "$ROOT_DIR/docker-compose.yml" up --build -d

run_benchmark_mode "grpc" "$GRPC_OUT" \
  env PROOF_PROVIDER_MODE=grpc \
      GRPC_PROVER_ENDPOINT=native-prover:50051 \
      PROOF_SHADOW_MODE=false \
      NATIVE_GENERATE_BACKEND=snarkjs \
      RAPIDSNARK_BIN="$RAPIDSNARK_BIN" \
      RAPIDSNARK_DOWNLOAD_URL="$RAPIDSNARK_DOWNLOAD_URL" \
      NATIVE_WITNESS_BACKEND="$NATIVE_WITNESS_BACKEND" \
      WITNESS_GEN_BIN="$WITNESS_GEN_BIN" \
      WITNESSCALC_DOWNLOAD_URL="$WITNESSCALC_DOWNLOAD_URL" \
      docker compose -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/docker-compose.grpc.yml" up --build -d

if [[ "$ENABLE_RAPIDSNARK" == "1" ]]; then
  run_benchmark_mode "grpc-rapidsnark" "$GRPC_RAPIDSNARK_OUT" \
    env PROOF_PROVIDER_MODE=grpc \
        GRPC_PROVER_ENDPOINT=native-prover:50051 \
        PROOF_SHADOW_MODE=false \
        NATIVE_GENERATE_BACKEND=rapidsnark \
        RAPIDSNARK_BIN="$RAPIDSNARK_BIN" \
        RAPIDSNARK_DOWNLOAD_URL="$RAPIDSNARK_DOWNLOAD_URL" \
        NATIVE_WITNESS_BACKEND="$NATIVE_WITNESS_BACKEND" \
        WITNESS_GEN_BIN="$WITNESS_GEN_BIN" \
        WITNESSCALC_DOWNLOAD_URL="$WITNESSCALC_DOWNLOAD_URL" \
        docker compose -f "$ROOT_DIR/docker-compose.yml" -f "$ROOT_DIR/docker-compose.grpc.yml" up --build -d
fi

if [[ "$SHADOW_RUNS" != "0" ]]; then
  run_shadow_collection
  gate_shadow_args=(--shadow-summary "$SHADOW_SUMMARY_OUT")
else
  gate_shadow_args=(
    --compared-runs "$COMPARED_RUNS"
    --functional-mismatches "$FUNCTIONAL_MISMATCHES"
  )
fi

GATE_GRPC_BENCHMARK="$GRPC_OUT"
case "$GATE_GRPC_MODE" in
  snarkjs)
    GATE_GRPC_BENCHMARK="$GRPC_OUT"
    ;;
  rapidsnark)
    if [[ ! -f "$GRPC_RAPIDSNARK_OUT" ]]; then
      echo "[error] GATE_GRPC_MODE=rapidsnark requires ENABLE_RAPIDSNARK=1 and a successful grpc-rapidsnark benchmark run" >&2
      exit 1
    fi
    GATE_GRPC_BENCHMARK="$GRPC_RAPIDSNARK_OUT"
    ;;
  auto)
    if [[ -f "$GRPC_RAPIDSNARK_OUT" ]]; then
      GATE_GRPC_BENCHMARK="$(python - "$GRPC_OUT" "$GRPC_RAPIDSNARK_OUT" <<'PY'
import json
import sys

snark_path = sys.argv[1]
rapid_path = sys.argv[2]
with open(snark_path, "r", encoding="utf-8") as f:
    snark = json.load(f)
with open(rapid_path, "r", encoding="utf-8") as f:
    rapid = json.load(f)
snark_p95 = float(snark.get("p95_ms", float("inf")))
rapid_p95 = float(rapid.get("p95_ms", float("inf")))
print(rapid_path if rapid_p95 < snark_p95 else snark_path)
PY
)"
    else
      GATE_GRPC_BENCHMARK="$GRPC_OUT"
    fi
    ;;
  *)
    echo "[error] unsupported GATE_GRPC_MODE=$GATE_GRPC_MODE (expected: snarkjs|rapidsnark|auto)" >&2
    exit 1
    ;;
esac

python systematic_study/evaluate_cutover_gate.py \
  --snarkjs-benchmark "$SNARKJS_OUT" \
  --grpc-benchmark "$GATE_GRPC_BENCHMARK" \
  --days-observed "$DAYS_OBSERVED" \
  "${gate_shadow_args[@]}" \
  --output-json "$GATE_OUT"

echo "[done] benchmark outputs:"
echo "  snarkjs: $SNARKJS_OUT"
echo "  grpc (snarkjs generate): $GRPC_OUT"
if [[ "$ENABLE_RAPIDSNARK" == "1" ]]; then
  echo "  grpc (rapidsnark generate): $GRPC_RAPIDSNARK_OUT"
fi
if [[ "$SHADOW_RUNS" != "0" ]]; then
  echo "  shadow benchmark: $SHADOW_OUT"
  echo "  shadow summary:   $SHADOW_SUMMARY_OUT"
  echo "  shadow backend:   $SHADOW_NATIVE_GENERATE_BACKEND"
fi
echo "  gate grpc source: $GATE_GRPC_BENCHMARK (mode=$GATE_GRPC_MODE)"
echo "  gate:    $GATE_OUT"
