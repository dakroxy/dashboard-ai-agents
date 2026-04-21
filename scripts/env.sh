#!/usr/bin/env bash
# Baut .env aus .env.op, indem 1Password-Refs aufgeloest werden.
# Erwartet den Service-Account-Token in der macOS-Keychain unter "op-service-account-ki".
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v op >/dev/null 2>&1; then
    echo "Fehler: 1Password-CLI ('op') nicht installiert." >&2
    exit 1
fi

TOKEN=$(security find-generic-password -a "$USER" -s "op-service-account-ki" -w 2>/dev/null || true)
if [ -z "${TOKEN:-}" ]; then
    echo "Fehler: Kein Service-Account-Token im Keychain (op-service-account-ki)." >&2
    echo "       Entweder Keychain-Entry anlegen oder OP_SERVICE_ACCOUNT_TOKEN exportieren." >&2
    exit 1
fi

export OP_SERVICE_ACCOUNT_TOKEN="$TOKEN"
op inject -i .env.op -o .env
echo ".env aktualisiert."
