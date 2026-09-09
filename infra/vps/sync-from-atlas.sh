#!/usr/bin/env bash
# Resynchronise la base LOCALE depuis Atlas — ÉCRASE les données locales.
# À utiliser tant qu'Atlas est la base « vivante » (une dernière fois juste
# avant la bascule DNS Cloudflare), puis plus jamais.
set -euo pipefail

CONF_DIR="$HOME/.config/blue-intelligence"
. "$CONF_DIR/atlas.env"   # MONGO_URL (Atlas) + DB_NAME
. "$CONF_DIR/mongo.env"   # MONGO_URL_LOCAL

ARCHIVE="$HOME/backups/mongodb/atlas-sync-$(date +%F-%H%M).archive.gz"
echo "Dump Atlas → $ARCHIVE (M0 throttlé : plusieurs minutes)"
mongodump --uri "$MONGO_URL" --db "$DB_NAME" --gzip --archive="$ARCHIVE" --quiet

echo "Restauration locale (--drop)"
mongorestore --uri "$MONGO_URL_LOCAL" --gzip --archive="$ARCHIVE" --drop --quiet

mongosh --quiet "$MONGO_URL_LOCAL" --eval "
const s = db.getSiblingDB('$DB_NAME').stats();
print('OK : ' + s.objects + ' documents / ' + s.collections + ' collections (' + (s.dataSize/1e6).toFixed(1) + ' Mo)');
"
