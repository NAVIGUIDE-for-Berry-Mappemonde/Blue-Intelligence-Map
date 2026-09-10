#!/usr/bin/env bash
# (Re)déploiement de NAVIGUIDE sur le VPS OVH (www.naviguide.fr).
# Suppose : monorepo présent dans ~/blue-intelligence-map, Node + nginx +
# certbot déjà installés (déploiement Blue Intelligence). Idempotent.
#
# Premier déploiement — après ce script :
#   1. renseigner ~/.config/naviguide/naviguide.env (NVIDIA_API_KEY /
#      OPENROUTER_API_KEY / ANTHROPIC_API_KEY — cascade LLM —, COPERNICUS_*)
#   2. sudo systemctl restart naviguide-api naviguide-orchestrator naviguide-polar
#   3. TLS : le certificat Let's Encrypt live/naviguide.fr (SAN apex + www) existe
#      déjà et est référencé par nginx-naviguide.conf ; sur un VPS vierge :
#      sudo certbot --nginx -d www.naviguide.fr -d naviguide.fr
set -euo pipefail

APP="$HOME/blue-intelligence-map"
NAV="$APP/naviguide"
CONF_DIR="$HOME/.config/naviguide"
UV="$HOME/.local/bin/uv"

command -v "$UV" >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh

# ── Venv Python partagé des 3 services NAVIGUIDE ──────────────────────────────
cd "$NAV"
[ -d .venv ] || "$UV" venv --python 3.12 .venv
# scipy : requis par polar_engine (interpolation des polaires), absent des requirements
"$UV" pip install --python .venv/bin/python \
  -r naviguide-api/requirements.txt \
  -r naviguide_workspace/requirements.txt \
  scipy

# ── Secrets (EnvironmentFile des unités systemd) ──────────────────────────────
mkdir -p "$CONF_DIR"
if [ ! -f "$CONF_DIR/naviguide.env" ]; then
  umask 077
  cp "$APP/infra/vps/naviguide/naviguide.env.example" "$CONF_DIR/naviguide.env"
  echo "⚠  $CONF_DIR/naviguide.env créé — renseigner les clés LLM (NVIDIA/OpenRouter/Anthropic) et COPERNICUS_*"
fi

# ── Frontend : build production (VITE_* → https://www.naviguide.fr) ───────────
cd "$NAV/naviguide-app"
npm install --no-audit --no-fund
npm run build

# ── Services systemd ──────────────────────────────────────────────────────────
sudo cp "$APP"/infra/vps/naviguide/naviguide-api.service \
        "$APP"/infra/vps/naviguide/naviguide-orchestrator.service \
        "$APP"/infra/vps/naviguide/naviguide-polar.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
for svc in naviguide-api naviguide-orchestrator naviguide-polar; do
  sudo systemctl enable "$svc" >/dev/null 2>&1 || true
  sudo systemctl restart "$svc"
done

# ── nginx : installé au premier passage seulement (certbot modifie le fichier) ─
if [ ! -f /etc/nginx/sites-available/naviguide ]; then
  sudo cp "$APP/infra/vps/naviguide/nginx-naviguide.conf" /etc/nginx/sites-available/naviguide
  sudo ln -sf /etc/nginx/sites-available/naviguide /etc/nginx/sites-enabled/naviguide
fi
# nginx (www-data) doit pouvoir traverser ~ pour lire dist/ (bit x seulement)
chmod o+x "$HOME"
sudo nginx -t && sudo systemctl reload nginx

# ── Santé (naviguide-api charge xarray/copernicusmarine : ~10 s au démarrage) ──
for svc in "9000:naviguide-api" "9008:orchestrator" "9004:polar-api"; do
  port="${svc%%:*}"; name="${svc##*:}"; code=000
  for _ in $(seq 1 15); do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$port/" || true)
    [ "$code" = "200" ] && break
    sleep 2
  done
  echo "  $name (:$port) → HTTP $code"
done
