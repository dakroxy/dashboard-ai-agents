#!/usr/bin/env bash
# Redeploy auf Elestio-Prod (dashboard.dbshome.de): pullt das aktuelle
# :latest-Image von ghcr.io und recreatet den App-Container.
#
# Voraussetzungen: SSH-Zugang zu root@91.99.31.95 (Daniel hat den Key).
# Image-Build laeuft via GitHub-Action `docker-build.yml` automatisch bei
# Push auf main — diesem Skript erst nach gruenem Action-Run aufrufen.
#
# Usage: ./scripts/redeploy-prod.sh
set -euo pipefail

PROD_HOST="${PROD_HOST:-root@91.99.31.95}"
PROD_PATH="${PROD_PATH:-/opt/app/hv-dashboard}"

echo "Redeploy auf ${PROD_HOST}:${PROD_PATH} ..."
ssh "${PROD_HOST}" "cd '${PROD_PATH}' && docker compose pull && docker compose up -d && docker compose ps"
echo
echo "Smoke-Test:"
curl -sS -m 8 https://dashboard.dbshome.de/health
echo
