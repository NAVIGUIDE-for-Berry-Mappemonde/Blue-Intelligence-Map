#!/usr/bin/env bash
# (Re)déploiement de l'application sur le VPS : dépendances backend (Python 3.12
# via uv), Playwright Chromium, build frontend, service systemd, cron de
# sauvegarde. Suppose le code présent dans ~/blue-intelligence-map et
# install-mongodb.sh déjà exécuté.
set -euo pipefail

APP="$HOME/blue-intelligence-map"
CONF_DIR="$HOME/.config/blue-intelligence"
UV="$HOME/.local/bin/uv"

command -v "$UV" >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh

cd "$APP/backend"
[ -d .venv ] || "$UV" venv --python 3.12 .venv
"$UV" pip install --python .venv/bin/python -r requirements.txt \
  --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match
sudo .venv/bin/python -m playwright install-deps chromium >/dev/null 2>&1 || true
.venv/bin/python -m playwright install chromium

if [ ! -f .env ]; then
  . "$CONF_DIR/mongo.env"
  umask 077
  cat > .env <<ENV
MONGO_URL=$MONGO_URL_LOCAL
DB_NAME=$DB_NAME
CORS_ORIGINS=https://blueintelligence.online,https://www.blueintelligence.online
ENV
  echo "backend/.env créé — compléter les clés API (NVIDIA_API_KEY, OPENROUTER_API_KEY…)"
fi

cd "$APP/frontend"
printf 'REACT_APP_BACKEND_URL=\n' > .env
npm install --no-audit --no-fund
CI=true npm run build

sudo cp "$APP/infra/vps/blue-intelligence.service" /etc/systemd/system/blue-intelligence.service
sudo cp "$APP/infra/vps/blue-intelligence-backup.cron" /etc/cron.d/blue-intelligence-backup
sudo systemctl daemon-reload
sudo systemctl enable blue-intelligence >/dev/null 2>&1 || true
sudo systemctl restart blue-intelligence

code=000
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/api/ || true)
  [ "$code" = "200" ] && break
  sleep 3
done
echo "Santé : HTTP $code — $(curl -s http://127.0.0.1:8001/api/)"
