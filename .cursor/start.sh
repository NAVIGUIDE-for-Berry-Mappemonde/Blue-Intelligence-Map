#!/usr/bin/env bash
# Per-boot reconciliation: MongoDB + SearXNG (JSON on 127.0.0.1:8888).
# Backend/frontend servers run as visible `terminals` (not here).
# SearXNG is started HERE only — do not also add it to terminals.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../infra/searxng/install-local.sh
. "$REPO/infra/searxng/install-local.sh"

ensure_searxng_url "$REPO/backend/.env"

sudo mkdir -p /var/lib/mongodb /var/log/mongodb 2>/dev/null || true
sudo chown -R "$(id -u):$(id -g)" /var/lib/mongodb /var/log/mongodb 2>/dev/null || true

if pgrep -x mongod >/dev/null 2>&1; then
  echo "mongod already running"
else
  echo "starting mongod..."
  mongod --dbpath /var/lib/mongodb --bind_ip 127.0.0.1 --port 27017 \
    --logpath /var/log/mongodb/mongod.log --logappend --fork
fi

STARTED_SEARXNG=0
start_searxng_venv() {
  if [ ! -x /opt/searxng/.venv/bin/python ]; then
    echo "SearXNG venv missing — installing idempotently (fallback if install.sh did not run)..."
    install_searxng_venv
  fi
  echo "starting SearXNG (venv) on 127.0.0.1:8888..."
  nohup bash "$REPO/infra/searxng/run-local.sh" >/tmp/searxng.log 2>&1 &
  echo $! > /tmp/searxng.pid
  STARTED_SEARXNG=1
}

# SearXNG local (JSON) — requis par les runs PoE v1/v2/tinyfish
if searxng_json_ok; then
  echo "SearXNG already up on 127.0.0.1:8888"
elif command -v docker >/dev/null 2>&1 && { docker info >/dev/null 2>&1 || sudo docker info >/dev/null 2>&1; }; then
  echo "starting SearXNG container on 127.0.0.1:8888..."
  DK=docker
  docker info >/dev/null 2>&1 || DK="sudo docker"
  $DK rm -f blue-intelligence-searxng >/dev/null 2>&1 || true
  if $DK run -d --name blue-intelligence-searxng \
    -p 127.0.0.1:8888:8080 \
    -v "$REPO/infra/searxng/settings.yml:/etc/searxng/settings.yml:ro" \
    -e SEARXNG_BASE_URL=http://127.0.0.1:8888/ \
    searxng/searxng:latest >/dev/null; then
    for _ in $(seq 1 15); do
      if searxng_json_ok; then
        echo "SearXNG container is up"
        break
      fi
      sleep 2
    done
  else
    echo "docker run SearXNG failed — falling back to venv" >&2
  fi
  if ! searxng_json_ok; then
    $DK rm -f blue-intelligence-searxng >/dev/null 2>&1 || true
    start_searxng_venv
  fi
else
  start_searxng_venv
fi

# Wait for MongoDB to accept connections before returning.
mongo_ready=0
for _ in $(seq 1 30); do
  if mongosh --quiet --eval 'db.runCommand({ping:1})' >/dev/null 2>&1; then
    mongo_ready=1
    break
  fi
  sleep 1
done
if [ "$mongo_ready" != 1 ]; then
  echo "ERROR: mongod did not become ready within 30s; see /var/log/mongodb/mongod.log" >&2
  exit 1
fi
echo "mongod is ready on 127.0.0.1:27017"

# Wait for SearXNG JSON — same bar as mongod. Public instances do not count.
searx_ready=0
for _ in $(seq 1 90); do
  if searxng_json_ok; then
    searx_ready=1
    break
  fi
  if [ "$STARTED_SEARXNG" = 1 ] && [ -f /tmp/searxng.pid ]; then
    pid="$(cat /tmp/searxng.pid 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && ! kill -0 "$pid" 2>/dev/null; then
      echo "ERROR: SearXNG process died before becoming ready; see /tmp/searxng.log" >&2
      tail -n 80 /tmp/searxng.log >&2 || true
      exit 1
    fi
  fi
  sleep 1
done
if [ "$searx_ready" != 1 ]; then
  echo "ERROR: SearXNG did not become ready on http://127.0.0.1:8888 (JSON) within 90s" >&2
  tail -n 80 /tmp/searxng.log >&2 || true
  exit 1
fi
echo "SearXNG is ready on 127.0.0.1:8888"
