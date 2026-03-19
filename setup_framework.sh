#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CIRCUITS_DIR="${CIRCUITS_DIR:-$ROOT_DIR/circuits}"
SHARED_ASSETS_DIR="${SHARED_ASSETS_DIR:-$ROOT_DIR/shared_assets}"
BUILD_ROOT="${BUILD_ROOT:-$ROOT_DIR/.build}"
PTAU_POWER="${PTAU_POWER:-14}"
CONTRIBUTION_ENTROPY="${CONTRIBUTION_ENTROPY:-sentinel-zk-local-dev}"
SNARKJS_BIN="${SNARKJS_BIN:-snarkjs}"
CIRCOM_LIB_PATH="${CIRCOM_LIB_PATH:-/usr/local/lib/node_modules}"

detect_arch() {
  local machine
  machine="$(uname -m)"
  case "$machine" in
    x86_64|amd64) echo "amd64" ;;
    arm64|aarch64) echo "arm64" ;;
    *)
      echo "unsupported architecture: $machine" >&2
      exit 1
      ;;
  esac
}

ensure_tooling() {
  if ! command -v "$SNARKJS_BIN" >/dev/null 2>&1; then
    echo "missing dependency: $SNARKJS_BIN" >&2
    exit 1
  fi

  if command -v circom >/dev/null 2>&1; then
    return
  fi

  if command -v cargo >/dev/null 2>&1; then
    echo "circom not found, installing via cargo (native build for $(detect_arch))"
    cargo install --locked --git https://github.com/iden3/circom.git --tag v2.1.8 circom
    return
  fi

  echo "missing dependency: circom (and cargo not available to auto-install)" >&2
  exit 1
}

compile_circuit() {
  local circuit_dir="$1"
  local circuit_id="$2"
  local circuit_file="$circuit_dir/$circuit_id.circom"
  local circuit_build_dir="$BUILD_ROOT/$circuit_id"
  local assets_dir="$SHARED_ASSETS_DIR/$circuit_id"

  if [[ ! -f "$circuit_file" ]]; then
    echo "skipping $circuit_id (missing $circuit_file)"
    return
  fi

  mkdir -p "$circuit_build_dir" "$assets_dir"

  echo "==> [$circuit_id] compiling circuit"
  circom "$circuit_file" \
    --r1cs --wasm --sym \
    -l "$CIRCOM_LIB_PATH" \
    -l "$CIRCUITS_DIR" \
    -o "$circuit_build_dir"

  local r1cs_file="$circuit_build_dir/$circuit_id.r1cs"
  local ptau_power
  ptau_power="$(select_ptau_power "$r1cs_file")"

  local ptau_0="$circuit_build_dir/pot_${ptau_power}_0000.ptau"
  local ptau_1="$circuit_build_dir/pot_${ptau_power}_0001.ptau"
  local ptau_final="$circuit_build_dir/pot_${ptau_power}_final.ptau"
  local zkey_0="$circuit_build_dir/${circuit_id}_0000.zkey"
  local zkey_final="$assets_dir/final.zkey"
  local wasm_file="$circuit_build_dir/${circuit_id}_js/${circuit_id}.wasm"

  echo "==> [$circuit_id] powers of tau (power=${ptau_power})"
  "$SNARKJS_BIN" powersoftau new bn128 "$ptau_power" "$ptau_0"
  "$SNARKJS_BIN" powersoftau contribute \
    "$ptau_0" "$ptau_1" \
    --name="sentinel-initial" \
    -e="$CONTRIBUTION_ENTROPY"
  "$SNARKJS_BIN" powersoftau prepare phase2 "$ptau_1" "$ptau_final"

  echo "==> [$circuit_id] groth16 setup"
  "$SNARKJS_BIN" groth16 setup "$r1cs_file" "$ptau_final" "$zkey_0"
  "$SNARKJS_BIN" zkey contribute \
    "$zkey_0" "$zkey_final" \
    --name="sentinel-zkey" \
    -e="$CONTRIBUTION_ENTROPY"
  "$SNARKJS_BIN" zkey export verificationkey "$zkey_final" "$assets_dir/verification_key.json"

  cp "$wasm_file" "$assets_dir/$circuit_id.wasm"
  echo "==> [$circuit_id] artifacts written to $assets_dir"
}

select_ptau_power() {
  local r1cs_file="$1"
  local constraints_raw
  constraints_raw="$("$SNARKJS_BIN" r1cs info "$r1cs_file" 2>&1 \
    | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' \
    | sed -nE 's/.*# of Constraints:[[:space:]]*([0-9]+).*/\1/p' \
    | head -n1)"
  if [[ -z "${constraints_raw}" ]]; then
    echo "failed to detect constraint count for $r1cs_file" >&2
    exit 1
  fi

  local constraints="$constraints_raw"
  local required_power=0
  local capacity=1
  while (( capacity < constraints )); do
    capacity=$((capacity * 2))
    required_power=$((required_power + 1))
  done

  if (( required_power < PTAU_POWER )); then
    required_power="$PTAU_POWER"
  fi
  echo "$required_power"
}

discover_runnable_circuits() {
  python3 - "$CIRCUITS_DIR" <<'PY'
import pathlib
import sys

from sentinel_zk.circuit_discovery import discover_runnable_circuits

circuits = discover_runnable_circuits(pathlib.Path(sys.argv[1]))
for path, circuit_id in circuits:
    print(f"{path}|{circuit_id}")
PY
}

main() {
  ensure_tooling
  mkdir -p "$SHARED_ASSETS_DIR" "$BUILD_ROOT"

  local arch
  arch="$(detect_arch)"
  echo "Sentinel-ZK setup started for architecture: $arch"

  local runnable
  runnable="$(discover_runnable_circuits)"
  if [[ -z "${runnable}" ]]; then
    echo "no runnable manifest-backed circuits found in $CIRCUITS_DIR" >&2
    exit 1
  fi

  while IFS='|' read -r dir circuit_id; do
    [[ -n "$dir" ]] || continue
    compile_circuit "$dir" "$circuit_id"
  done <<< "$runnable"

  echo "Sentinel-ZK setup completed"
}

main "$@"
