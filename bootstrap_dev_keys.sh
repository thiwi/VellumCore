#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CONFIG_DIR="${1:-$SCRIPT_DIR/config}"
mkdir -p "$CONFIG_DIR"

JWT_PRIV="$CONFIG_DIR/dev_jwt_private.pem"
JWT_PUB="$CONFIG_DIR/jwt_public.pem"
BANK_PRIV="$CONFIG_DIR/dev_bank_private.pem"
BANK_PUB="$CONFIG_DIR/dev_bank_public.pem"
BANK_KEYS_JSON="$CONFIG_DIR/bank_public_keys.json"
AUDIT_PRIV="$CONFIG_DIR/audit_private.pem"
AUDIT_PUB="$CONFIG_DIR/audit_public.pem"

echo "[keygen] Regenerating development key material in: $CONFIG_DIR"

if ! command -v openssl >/dev/null 2>&1; then
  echo "[keygen] ERROR: openssl not found in PATH" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "[keygen] ERROR: python3 not found in PATH" >&2
  exit 1
fi

# JWT signing keypair (RS256)
echo "[keygen] Generating JWT RSA keypair..."
openssl genrsa -out "$JWT_PRIV" 2048
openssl rsa -in "$JWT_PRIV" -pubout -out "$JWT_PUB"

# Bank request-signature keypair (RSA + PKCS1v15/SHA256)
echo "[keygen] Generating Bank RSA keypair..."
openssl genrsa -out "$BANK_PRIV" 2048
openssl rsa -in "$BANK_PRIV" -pubout -out "$BANK_PUB"

# Audit chain keypair (Ed25519)
echo "[keygen] Generating Audit Ed25519 keypair..."
openssl genpkey -algorithm ED25519 -out "$AUDIT_PRIV"
openssl pkey -in "$AUDIT_PRIV" -pubout -out "$AUDIT_PUB"

# Bank key registry (JSON map consumed by AuthManager).
bank_pub_json=$(python3 -c 'import json,sys;print(json.dumps(open(sys.argv[1],"r",encoding="utf-8").read()))' "$BANK_PUB")
cat > "$BANK_KEYS_JSON" <<EOF
{
  "keys": {
    "bank-key-1": ${bank_pub_json}
  }
}
EOF

chmod 600 "$JWT_PRIV" "$BANK_PRIV" "$AUDIT_PRIV"
chmod 644 "$JWT_PUB" "$BANK_PUB" "$AUDIT_PUB" "$BANK_KEYS_JSON"

echo "[keygen] Done."
