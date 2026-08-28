#!/usr/bin/env bash
# Build le frontend et démarre l'application unifiée (UI + API) sur le port 8001.
# Usage : bash .cursor/preview.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Build frontend (même-origine)"
cd "$REPO/frontend"
CI=true REACT_APP_BACKEND_URL= npm run build

echo "==> Démarrage backend + UI sur http://0.0.0.0:8001"
cd "$REPO/backend"
# shellcheck disable=SC1091
. .venv/bin/activate
exec SERVE_FRONTEND=1 uvicorn server:app --host 0.0.0.0 --port 8001
