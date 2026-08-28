#!/usr/bin/env bash
# Per-boot reconciliation: ensure the MongoDB daemon is running and ready.
# The backend/frontend servers themselves run as visible `terminals`.
set -euo pipefail

sudo mkdir -p /var/lib/mongodb /var/log/mongodb 2>/dev/null || true
sudo chown -R "$(id -u):$(id -g)" /var/lib/mongodb /var/log/mongodb 2>/dev/null || true

if pgrep -x mongod >/dev/null 2>&1; then
  echo "mongod already running"
else
  echo "starting mongod..."
  mongod --dbpath /var/lib/mongodb --bind_ip 127.0.0.1 --port 27017 \
    --logpath /var/log/mongodb/mongod.log --logappend --fork
fi

# Wait for MongoDB to accept connections before returning.
for _ in $(seq 1 30); do
  if mongosh --quiet --eval 'db.runCommand({ping:1})' >/dev/null 2>&1; then
    echo "mongod is ready on 127.0.0.1:27017"
    exit 0
  fi
  sleep 1
done

echo "WARNING: mongod did not become ready within 30s; see /var/log/mongodb/mongod.log" >&2
exit 1
