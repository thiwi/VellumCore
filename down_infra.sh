#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Stop and remove all containers created by this compose project.
docker compose down --remove-orphans "$@"
