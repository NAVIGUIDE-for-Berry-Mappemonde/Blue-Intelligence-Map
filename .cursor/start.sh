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

# SearXNG local (JSON) — requis par les runs PoE v1/v2/tinyfish
if curl -sf -m 2 "http://127.0.0.1:8888/search?q=ping&format=json" >/dev/null 2>&1; then
  echo "SearXNG already up on 127.0.0.1:8888"
elif command -v docker >/dev/null 2>&1 && { docker info >/dev/null 2>&1 || sudo docker info >/dev/null 2>&1; }; then
  echo "starting SearXNG container on 127.0.0.1:8888..."
  DK=docker
  docker info >/dev/null 2>&1 || DK="sudo docker"
  $DK rm -f blue-intelligence-searxng >/dev/null 2>&1 || true
  $DK run -d --name blue-intelligence-searxng \
    -p 127.0.0.1:8888:8080 \
    -v /workspace/infra/searxng/settings.yml:/etc/searxng/settings.yml:ro \
    -e SEARXNG_BASE_URL=http://127.0.0.1:8888/ \
    searxng/searxng:latest >/dev/null
elif [ -x /opt/searxng/.venv/bin/python ]; then
  echo "starting SearXNG (venv) on 127.0.0.1:8888..."
  nohup bash /workspace/infra/searxng/run-local.sh >/tmp/searxng.log 2>&1 &
  echo $! > /tmp/searxng.pid
else
  echo "WARNING: SearXNG not installed — PoE search will fall back to public instances" >&2
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
