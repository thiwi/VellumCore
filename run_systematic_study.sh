#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

CIRCOM_FILE="circuits/batch_credit_check/batch_credit_check.circom"
MANIFEST_FILE="circuits/batch_credit_check/manifest.json"
BATCHER_FILE="vellum_core/logic/batcher.py"
RESULTS_DIR="$SCRIPT_DIR/study_results"
VOLUMES=(100 250 500 750 1000)
OPS=10000
PROVER_HEALTH_URL="http://localhost:8001/healthz"
WAIT_TIMEOUT_SECONDS=300
WAIT_INTERVAL_SECONDS=2

mkdir -p "$RESULTS_DIR"

if [[ ! -f "$CIRCOM_FILE" ]]; then
  echo "[error] Missing circuit file: $CIRCOM_FILE" >&2
  exit 1
fi

BACKUP_DIR="$(mktemp -d)"
cp "$CIRCOM_FILE" "$BACKUP_DIR/$(basename "$CIRCOM_FILE")"
cp "$MANIFEST_FILE" "$BACKUP_DIR/$(basename "$MANIFEST_FILE")"
cp "$BATCHER_FILE" "$BACKUP_DIR/$(basename "$BATCHER_FILE")"
INFRA_UP=0

cleanup() {
  if [[ "$INFRA_UP" -eq 1 ]]; then
    echo "[cleanup] Stopping infrastructure..."
    ./down_infra.sh || true
    INFRA_UP=0
  fi

  if [[ -d "${BACKUP_DIR:-}" ]]; then
    cp "$BACKUP_DIR/$(basename "$CIRCOM_FILE")" "$CIRCOM_FILE"
    cp "$BACKUP_DIR/$(basename "$MANIFEST_FILE")" "$MANIFEST_FILE"
    cp "$BACKUP_DIR/$(basename "$BATCHER_FILE")" "$BATCHER_FILE"
    rm -rf "$BACKUP_DIR"
  fi
}

trap cleanup EXIT

wait_for_condition() {
  local description="$1"
  local check_cmd="$2"
  local waited=0

  echo "[wait] $description"
  while true; do
    if eval "$check_cmd" >/dev/null 2>&1; then
      echo "[wait] OK: $description"
      return 0
    fi

    if (( waited >= WAIT_TIMEOUT_SECONDS )); then
      echo "[error] Timeout while waiting for: $description" >&2
      return 1
    fi

    sleep "$WAIT_INTERVAL_SECONDS"
    waited=$((waited + WAIT_INTERVAL_SECONDS))
  done
}

start_infra_with_retry() {
  local attempt=1
  local max_attempts=2

  while (( attempt <= max_attempts )); do
    if ./up_infra.sh; then
      return 0
    fi

    if (( attempt == max_attempts )); then
      echo "[error] Infrastructure startup failed after ${max_attempts} attempts" >&2
      return 1
    fi

    echo "[warn] up_infra failed (attempt ${attempt}); cleaning Docker BuildKit cache and retrying"
    docker compose down --remove-orphans || true
    docker buildx prune -af || true
    attempt=$((attempt + 1))
  done
}

set_batch_size() {
  local n="$1"
  local tmp manifest_tmp batcher_tmp
  tmp="$(mktemp)"

  sed -E \
    "s@^(component main \\{public \\[limits, active_count\\]\\} = BatchCreditCheck\\()[0-9]+(\\);)@\\1${n}\\2@" \
    "$CIRCOM_FILE" > "$tmp"

  if cmp -s "$CIRCOM_FILE" "$tmp"; then
    rm -f "$tmp"
    echo "[error] Batch size pattern not found in $CIRCOM_FILE" >&2
    return 1
  fi

  mv "$tmp" "$CIRCOM_FILE"

  local current
  current="$(sed -nE 's@^component main \{public \[limits, active_count\]\} = BatchCreditCheck\(([0-9]+)\);@\1@p' "$CIRCOM_FILE")"
  if [[ "$current" != "$n" ]]; then
    echo "[error] Failed to set batch size to $n (current: ${current:-unknown})" >&2
    return 1
  fi

  batcher_tmp="$(mktemp)"
  sed -E "s@^(MAX_BATCH_SIZE = )[0-9]+@\1${n}@" "$BATCHER_FILE" > "$batcher_tmp"
  if cmp -s "$BATCHER_FILE" "$batcher_tmp"; then
    rm -f "$batcher_tmp"
    echo "[error] Failed to patch MAX_BATCH_SIZE in $BATCHER_FILE" >&2
    return 1
  fi
  mv "$batcher_tmp" "$BATCHER_FILE"

  manifest_tmp="$(mktemp)"
  sed -E \
    "s@(\"minItems\": )[0-9]+@\\1${n}@g; s@(\"maxItems\": )[0-9]+@\\1${n}@g; s@(\"active_count\": \\{ \"type\": \"integer\", \"minimum\": 1, \"maximum\": )[0-9]+@\\1${n}@" \
    "$MANIFEST_FILE" > "$manifest_tmp"
  if cmp -s "$MANIFEST_FILE" "$manifest_tmp"; then
    rm -f "$manifest_tmp"
    echo "[error] Failed to patch limits in $MANIFEST_FILE" >&2
    return 1
  fi
  mv "$manifest_tmp" "$MANIFEST_FILE"
}

validate_result_json() {
  local path="$1"
  python3 - "$path" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
rows = data.get("matrix", [])
failed = [row for row in rows if row.get("status") == "failed" or row.get("error")]
if failed:
    print(f"[error] Result contains failed rows: {failed}", file=sys.stderr)
    raise SystemExit(1)
print("[check] Result JSON validated (no failed rows)")
PY
}

sync_artifacts_to_prover() {
  echo "[sync] Refreshing /shared_assets in prover container"
  docker compose exec -T prover sh -lc 'rm -rf /shared_assets/*'
  docker compose cp "$SCRIPT_DIR/shared_assets/." prover:/shared_assets
}

run_for_n() {
  local n="$1"

  echo ""
  echo "========== Running study for N=$n =========="

  echo "[step] Patch circuit to BatchCreditCheck($n)"
  set_batch_size "$n"

  echo "[step] Framework setup (compile + trusted setup artifacts)"
  ./setup_framework.sh

  echo "[step] Start infrastructure"
  start_infra_with_retry
  INFRA_UP=1

  wait_for_condition \
    "Vault unsealed" \
    "docker compose exec -T vault sh -lc 'vault status -address=http://127.0.0.1:8200 | grep -Eq \"Sealed[[:space:]]+false\"'"

  wait_for_condition \
    "Prover healthy" \
    "curl -fsS '$PROVER_HEALTH_URL'"

  echo "[step] Sync host artifacts into prover shared volume"
  sync_artifacts_to_prover

  echo "[step] Run systematic analysis in prover container"
  docker compose exec -T prover \
    python /app/systematic_vellum_analysis.py \
      --volumes "$n" \
      --ops "$OPS" \
      --reset-audit-log

  local out_file="$RESULTS_DIR/results_batch_${n}.json"
  echo "[step] Copy result JSON to host: $out_file"
  docker compose cp prover:/app/vellum_performance_matrix.json "$out_file"
  validate_result_json "$out_file"

  echo "[step] Stop infrastructure to free resources"
  ./down_infra.sh
  INFRA_UP=0

  echo "[done] N=$n completed"
}

echo "[init] Ensure clean starting point"
./down_infra.sh || true

for n in "${VOLUMES[@]}"; do
  if [[ -f "$RESULTS_DIR/results_batch_${n}.json" ]]; then
    echo "[skip] Existing result found for N=$n -> $RESULTS_DIR/results_batch_${n}.json"
    continue
  fi
  run_for_n "$n"
done

echo ""
echo "All runs completed. Results are in: $RESULTS_DIR"
