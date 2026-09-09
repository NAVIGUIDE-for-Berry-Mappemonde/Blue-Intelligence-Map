#!/usr/bin/env bash
# Installation + sécurisation de MongoDB 8.0 Community sur le VPS (Ubuntu).
# Idempotent : réexécutable sans danger. Détails : infra/vps/README.md.
set -euo pipefail

CONF_DIR="$HOME/.config/blue-intelligence"
MONGO_ENV="$CONF_DIR/mongo.env"

# DB_NAME : soit exporté, soit lu depuis atlas.env (MONGO_URL Atlas + DB_NAME).
[ -f "$CONF_DIR/atlas.env" ] && . "$CONF_DIR/atlas.env"
: "${DB_NAME:?DB_NAME requis (export DB_NAME=… ou renseigner $CONF_DIR/atlas.env)}"

grep -q avx /proc/cpuinfo || { echo "ERREUR : CPU sans AVX — MongoDB ≥ 5.0 ne démarre pas"; exit 1; }

if ! command -v mongod >/dev/null 2>&1; then
  sudo apt-get install -y gnupg curl
  curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc \
    | sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor --yes
  # Canal "noble" (24.04) : fonctionne aussi sur les Ubuntu intermédiaires (25.x).
  echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" \
    | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list >/dev/null
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y mongodb-org
fi
sudo systemctl enable --now mongod

grep -q "bindIp: 127.0.0.1" /etc/mongod.conf \
  || { echo "ERREUR : bindIp inattendu dans /etc/mongod.conf (127.0.0.1 requis)"; exit 1; }

umask 077
mkdir -p "$CONF_DIR" "$HOME/backups/mongodb"

if [ ! -f "$MONGO_ENV" ]; then
  ADMIN_PWD=$(openssl rand -hex 24)
  APP_PWD=$(openssl rand -hex 24)
  mongosh --quiet --eval "db.getSiblingDB('admin').createUser({user:'admin', pwd:'$ADMIN_PWD', roles:[{role:'root', db:'admin'}]})" >/dev/null
  mongosh --quiet --eval "db.getSiblingDB('admin').createUser({user:'blue', pwd:'$APP_PWD', roles:[{role:'readWrite', db:'$DB_NAME'}]})" >/dev/null
  cat > "$MONGO_ENV" <<ENV
MONGO_URL_LOCAL=mongodb://blue:$APP_PWD@127.0.0.1:27017/?authSource=admin
DB_NAME=$DB_NAME
MONGO_ADMIN_USER=admin
MONGO_ADMIN_PWD=$ADMIN_PWD
ENV
  echo "Comptes MongoDB créés — identifiants dans $MONGO_ENV"
fi

if ! grep -q "^security:" /etc/mongod.conf; then
  printf "security:\n  authorization: enabled\n" | sudo tee -a /etc/mongod.conf >/dev/null
  sudo systemctl restart mongod
  echo "Authentification MongoDB activée"
fi

. "$MONGO_ENV"
mongosh --quiet "$MONGO_URL_LOCAL" --eval "db.runCommand({ping:1}).ok" >/dev/null \
  && echo "MongoDB opérationnel — 127.0.0.1 uniquement, auth obligatoire"
