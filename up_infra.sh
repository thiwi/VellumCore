#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "[infra] Building and starting Vellum services..."
docker compose up --build -d --force-recreate --remove-orphans "$@"

echo "[infra] Waiting for Vault bootstrap..."
docker compose ps

echo "[infra] Done."
