#!/usr/bin/env bash
# Idempotent repository bootstrap for the Blue Intelligence dev environment.
# Prepares: MongoDB (system), the FastAPI backend (Python venv + deps) and the
# React frontend (npm). Safe to run repeatedly and against a warm snapshot.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTORCH_INDEX="https://download.pytorch.org/whl/cpu"
EMERGENT_INDEX="https://d33sy5i8bnduwe.cloudfront.net/simple/"

echo "==> [1/4] MongoDB (system package)"
if ! command -v mongod >/dev/null 2>&1; then
  sudo apt-get install -y gnupg curl
  curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc \
    | sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor --yes
  echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" \
    | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
  sudo apt-get update
  sudo apt-get install -y mongodb-org
else
  echo "    mongod already installed ($(mongod --version | head -1))"
fi
sudo mkdir -p /var/lib/mongodb /var/log/mongodb
sudo chown -R "$(id -u):$(id -g)" /var/lib/mongodb /var/log/mongodb

echo "==> [2/4] Backend (Python venv + dependencies)"
sudo apt-get install -y python3.12-venv build-essential >/dev/null 2>&1 || true
cd "$REPO/backend"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
# `emergentintegrations` and the top-level `litellm` line both reference the same
# direct-URL wheel, which the resolver rejects as a conflict. Install the core
# requirements first, then add emergentintegrations with --no-deps (litellm is
# already satisfied by the pinned URL wheel from requirements.txt).
grep -v -iE '^emergentintegrations' requirements.txt > /tmp/req.core.txt
pip install -r /tmp/req.core.txt --extra-index-url "$PYTORCH_INDEX"
pip install --no-deps "emergentintegrations==0.2.0" --extra-index-url "$EMERGENT_INDEX"
deactivate

echo "==> [3/4] backend/.env"
if [ ! -f "$REPO/backend/.env" ]; then
  cat > "$REPO/backend/.env" <<EOF
MONGO_URL=mongodb://localhost:27017
DB_NAME=blueintel_db
CORS_ORIGINS=*
GEONAMES_USERNAME=BerryMappemonde
# Optional LLM / scraping keys (cascade falls back gracefully when empty).
EMERGENT_LLM_KEY=${EMERGENT_LLM_KEY:-}
OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
TINYFISH_API_KEY=${TINYFISH_API_KEY:-}
GEMINI_API_KEY=${GEMINI_API_KEY:-}
EOF
  echo "    wrote backend/.env"
else
  echo "    backend/.env already present — leaving it untouched"
fi

echo "==> [4/4] Frontend (npm)"
if [ ! -f "$REPO/frontend/.env" ]; then
  cat > "$REPO/frontend/.env" <<'EOF'
# Laisser vide pour le mode même-origine (preview Cloud Agent + prod derrière reverse proxy).
REACT_APP_BACKEND_URL=
PORT=3000
DANGEROUSLY_DISABLE_HOST_CHECK=true
WDS_SOCKET_PORT=0
EOF
  echo "    wrote frontend/.env"
fi
cd "$REPO/frontend"
npm install

echo "==> [5/5] Frontend production build (preview unifié port 8001)"
cd "$REPO/frontend"
CI=true REACT_APP_BACKEND_URL= npm run build

echo "==> install.sh complete"
