#!/usr/bin/env bash
# Resynchronise la base LOCALE depuis Atlas — ÉCRASE les données locales.
# ⚠️ OBSOLÈTE depuis la bascule DNS du 2026-09-10 : le VPS est la base
# VIVANTE, Atlas est figé à l'état d'avant-bascule. Lancer ce script
# écraserait les données récentes. Verrou ci-dessous.
set -euo pipefail

if [ "${FORCE_RESYNC:-}" != "oui-ecraser-la-base" ]; then
  echo "REFUS — Depuis la bascule DNS du 2026-09-10, le VPS est la base vivante."
  echo "Resynchroniser depuis Atlas ÉCRASERAIT les données actuelles avec un état périmé."
  echo "Les sauvegardes quotidiennes locales sont dans ~/backups/mongodb/."
  echo "Pour forcer en toute connaissance de cause :"
  echo "  FORCE_RESYNC=oui-ecraser-la-base bash $0"
  exit 1
fi

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
