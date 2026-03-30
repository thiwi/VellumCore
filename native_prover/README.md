# Native Prover (Rust gRPC)

`native_prover` is the optional Rust gRPC proving backend for VellumCore.
Current backend split:

- `GenerateProof`: configurable backend:
  - `snarkjs` (default): `snarkjs groth16 fullprove`
  - `rapidsnark`: witness generation + `rapidsnark` prove
    - witness backend `snarkjs` (default): `snarkjs wtns calculate`
    - witness backend `binary`: `<WITNESS_GEN_BIN> <wasm> <input.json> <witness.wtns>`
- `VerifyProof`: native-first verification with compatibility fallback:
  - first attempts Rust `arkworks` BN254/Groth16 verification
  - if native check is inconclusive/false, falls back to `snarkjs groth16 verify`

## API

The service implements `proto/vellum_prover.proto`:

- `GenerateProof`: runs selected backend (`snarkjs` fullprove or `rapidsnark` path)
- `VerifyProof`: native-first (`arkworks`) with `snarkjs` compatibility fallback

The protobuf package is `vellum.nativeprover`.

## Run locally

Requirements:

- Rust toolchain
- `snarkjs` in `PATH` (always required for `snarkjs` generate backend and default witness backend)

Start service:

```bash
cd native_prover
cargo run --release -- --addr 0.0.0.0:50051 --snarkjs-bin snarkjs
```

Equivalent env-based startup:

```bash
NATIVE_PROVER_ADDR=0.0.0.0:50051 SNARKJS_BIN=snarkjs cargo run --release
```

Enable `rapidsnark` generate backend:

```bash
NATIVE_PROVER_ADDR=0.0.0.0:50051 \
SNARKJS_BIN=snarkjs \
NATIVE_GENERATE_BACKEND=rapidsnark \
RAPIDSNARK_BIN=rapidsnark \
cargo run --release
```

Use external witness generator binary (for `rapidsnark` backend):

```bash
NATIVE_PROVER_ADDR=0.0.0.0:50051 \
SNARKJS_BIN=snarkjs \
NATIVE_GENERATE_BACKEND=rapidsnark \
RAPIDSNARK_BIN=rapidsnark \
NATIVE_WITNESS_BACKEND=binary \
WITNESS_GEN_BIN=/usr/local/bin/witnesscalc \
cargo run --release
```

Docker image can install `rapidsnark` during build via:

- `RAPIDSNARK_DOWNLOAD_URL` build arg in `Dockerfile.native-prover`.
- `WITNESSCALC_DOWNLOAD_URL` build arg for optional witness generator binary.

## Runtime integration

Configure Vellum runtime:

- `PROOF_PROVIDER_MODE=grpc`
- `GRPC_PROVER_ENDPOINT=<host>:50051`

Runtime is grpc-only; shadow mode is no longer part of the reference runtime path.
