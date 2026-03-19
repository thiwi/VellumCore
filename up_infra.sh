#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

"$SCRIPT_DIR/bootstrap_dev_keys.sh" "$SCRIPT_DIR/config"

# Recreate running containers so all services reload regenerated key material.
echo "[infra] Starting Docker Compose services..."
docker compose up --build -d --force-recreate --remove-orphans "$@"

# Regenerated audit keys invalidate signatures from previous runs.
# Reset the dev audit log so the new chain starts from a clean genesis entry.
if docker compose ps --services --filter status=running | grep -qx "prover"; then
  echo "[infra] Resetting dev audit log..."
  docker compose exec -T prover sh -lc 'mkdir -p /shared_store && : > /shared_store/proof_audit.jsonl'
fi

echo "[infra] Done."
