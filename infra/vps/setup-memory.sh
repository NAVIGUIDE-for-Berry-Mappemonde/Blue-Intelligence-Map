#!/usr/bin/env bash
# Swap 4 Go + swappiness basse + plafond cache MongoDB.
# Idempotent. Ne redémarre PAS mongod (à faire hors run Complet).
set -euo pipefail

SWAPFILE=/swapfile
SWAP_MB=4096

if ! swapon --show | grep -q .; then
  if [ ! -f "$SWAPFILE" ]; then
    echo "Création de ${SWAP_MB} Mo de swap ($SWAPFILE)…"
    if ! sudo fallocate -l "${SWAP_MB}M" "$SWAPFILE" 2>/dev/null; then
      sudo dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SWAP_MB" status=none
    fi
    sudo chmod 600 "$SWAPFILE"
    sudo mkswap "$SWAPFILE" >/dev/null
  fi
  sudo swapon "$SWAPFILE"
  echo "Swap activé."
else
  echo "Swap déjà actif :"
  swapon --show
fi

if ! grep -q "$SWAPFILE" /etc/fstab; then
  echo "$SWAPFILE none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

echo "vm.swappiness=10" | sudo tee /etc/sysctl.d/99-blue-intelligence-memory.conf >/dev/null
sudo sysctl -p /etc/sysctl.d/99-blue-intelligence-memory.conf >/dev/null

CONF=/etc/mongod.conf
if [ -f "$CONF" ] && ! grep -q "cacheSizeGB" "$CONF"; then
  sudo python3 - <<'PY'
from pathlib import Path
p = Path("/etc/mongod.conf")
text = p.read_text()
needle = "storage:\n  dbPath:"
insert = (
    "storage:\n"
    "  wiredTiger:\n"
    "    engineConfig:\n"
    "      cacheSizeGB: 1.5\n"
    "  dbPath:"
)
if "cacheSizeGB" in text:
    raise SystemExit(0)
if needle not in text:
    raise SystemExit("mongod.conf : bloc storage/dbPath introuvable")
p.write_text(text.replace(needle, insert, 1))
print("mongod.conf : cacheSizeGB=1.5 ajouté (prend effet au prochain restart mongod)")
PY
else
  echo "MongoDB : cacheSizeGB déjà présent ou pas de mongod.conf"
fi

free -h
echo "OK — swap + swappiness. Pour appliquer le cache Mongo : sudo systemctl restart mongod (hors run)."
