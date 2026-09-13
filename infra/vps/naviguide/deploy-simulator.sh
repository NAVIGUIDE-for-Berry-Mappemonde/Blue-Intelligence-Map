#!/usr/bin/env bash
# Déploie NAVIGUIDE simulator sur simulator.naviguide.fr (même VPS).
# Ne redémarre PAS blue-intelligence, naviguide-api, polar, orchestrateur.
# Ne touche PAS /etc/nginx/sites-available/naviguide.
#
# Prérequis : code dans ~/blue-intelligence-map/naviguide-simulator
# (rsync depuis le Mac — voir publish-simulator-from-mac.sh).
# DNS A simulator → 135.125.226.16 déjà en place.
# À lancer sur le VPS, hors run Complet Blue Intelligence si dist/ manque
# (npm serait alors lancé ici).
set -euo pipefail

APP="$HOME/blue-intelligence-map"
SIM="$APP/naviguide-simulator"
CONF_DIR="$HOME/.config/naviguide"
UV="$HOME/.local/bin/uv"
WWW_ROOT=/var/www/naviguide-simulator
NGINX_SRC="$APP/infra/vps/naviguide/nginx-simulator.conf"
UNIT_SRC="$APP/infra/vps/naviguide/naviguide-simulator.service"

if [ ! -d "$SIM/server" ]; then
  echo "Dossier $SIM/server introuvable. Rsync d'abord depuis le Mac." >&2
  exit 1
fi
if [ ! -f "$NGINX_SRC" ] || [ ! -f "$UNIT_SRC" ]; then
  echo "Fichiers infra manquants (nginx-simulator.conf / .service)." >&2
  exit 1
fi

command -v "$UV" >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh

# ── Venv dédié (pas celui de naviguide/) ─────────────────────────────────────
cd "$SIM"
[ -d .venv ] || "$UV" venv --python 3.12 .venv
"$UV" pip install --python .venv/bin/python -r server/requirements.txt

mkdir -p "$CONF_DIR"
if [ ! -f "$CONF_DIR/simulator.env" ]; then
  umask 077
  cp "$APP/infra/vps/naviguide/simulator.env.example" "$CONF_DIR/simulator.env"
  # Copernicus seulement — jamais le fichier naviguide.env (clés LLM).
  if [ -f "$CONF_DIR/naviguide.env" ]; then
    grep -E '^COPERNICUS_(USERNAME|PASSWORD)=' "$CONF_DIR/naviguide.env" \
      >> "$CONF_DIR/simulator.env" || true
  fi
  echo "⚠  $CONF_DIR/simulator.env créé (Copernicus optionnel, sans clés LLM)"
fi
chmod 600 "$CONF_DIR/simulator.env"

# ── Frontend : dist/ déjà buildé sur le Mac de préférence ────────────────────
if [ ! -f "$SIM/dist/index.html" ]; then
  echo "dist/ absent — npm run build sur le VPS (RAM : pas pendant un Complet)"
  cd "$SIM"
  npm install --no-audit --no-fund
  npm run build
fi

sudo mkdir -p "$WWW_ROOT"
sudo rsync -a --delete "$SIM/dist/" "$WWW_ROOT/"
sudo chown -R ubuntu:ubuntu "$WWW_ROOT"
sudo chmod -R a+rX "$WWW_ROOT"

# ── systemd : uniquement naviguide-simulator ─────────────────────────────────
sudo cp "$UNIT_SRC" /etc/systemd/system/naviguide-simulator.service
sudo systemctl daemon-reload
sudo systemctl enable naviguide-simulator >/dev/null 2>&1 || true
sudo systemctl restart naviguide-simulator

# ── nginx : fichier à part, sites-available/naviguide intouché ───────────────
if [ -f /etc/nginx/sites-available/naviguide ]; then
  sudo cp -a /etc/nginx/sites-available/naviguide \
    "/etc/nginx/sites-available/naviguide.bak-before-simulator-$(date +%Y%m%d)"
fi
sudo cp "$NGINX_SRC" /etc/nginx/sites-available/naviguide-simulator
sudo ln -sf /etc/nginx/sites-available/naviguide-simulator /etc/nginx/sites-enabled/naviguide-simulator
sudo nginx -t
sudo systemctl reload nginx

# ── TLS : ajouter le SAN si absent (Let's Encrypt, gratuit) ──────────────────
# Plugin nginx (pas webroot) : le vhost www redirige encore /.well-known
# vers HTTPS. certonly n'écrit pas de nouveau vhost skipper.
CERT=/etc/letsencrypt/live/naviguide.fr/fullchain.pem
if ! sudo test -f "$CERT"; then
  echo "Certificat $CERT introuvable — abort." >&2
  exit 1
fi
if ! sudo openssl x509 -in "$CERT" -noout -text | grep -q 'DNS:simulator.naviguide.fr'; then
  echo "Extension du certificat Let's Encrypt (naviguide.fr + www + simulator)…"
  sudo certbot certonly --nginx --cert-name naviguide.fr \
    -d naviguide.fr -d www.naviguide.fr -d simulator.naviguide.fr \
    --expand --non-interactive --agree-tos --no-eff-email
  sudo nginx -t
  sudo systemctl reload nginx
fi

# ── Santé ────────────────────────────────────────────────────────────────────
code=000
for _ in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8010/" || true)
  [ "$code" = "200" ] && break
  sleep 1
done
echo "  naviguide-simulator (:8010) → HTTP $code"

www_code=$(curl -s -o /dev/null -w "%{http_code}" "https://www.naviguide.fr/" || true)
sim_code=$(curl -s -o /dev/null -w "%{http_code}" "https://simulator.naviguide.fr/" || true)
echo "  https://www.naviguide.fr/ → HTTP $www_code (doit rester 200)"
echo "  https://simulator.naviguide.fr/ → HTTP $sim_code"

if [ "$www_code" != "200" ] && [ "$www_code" != "301" ] && [ "$www_code" != "302" ]; then
  echo "⚠  www.naviguide.fr ne répond plus comme prévu. Retour arrière nginx :" >&2
  echo "    sudo rm -f /etc/nginx/sites-enabled/naviguide-simulator" >&2
  echo "    sudo nginx -t && sudo systemctl reload nginx" >&2
  exit 1
fi
