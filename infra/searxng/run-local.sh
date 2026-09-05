#!/usr/bin/env bash
# Lance SearXNG sans Docker (JSON activé) sur 127.0.0.1:8888.
set -euo pipefail
ROOT="${SEARXNG_HOME:-/opt/searxng}"
SETTINGS="${SEARXNG_SETTINGS_PATH:-/tmp/searxng-settings.yml}"
SRC_SETTINGS="$(dirname "$0")/settings.yml"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "SearXNG venv absent ($ROOT/.venv) — cloner et pip install -e d'abord" >&2
  exit 1
fi

python3 - << PY
from pathlib import Path
src = Path("$SRC_SETTINGS").read_text()
if "port:" not in src:
    src = src.replace(
        "  limiter: false",
        "  limiter: false\n  bind_address: \"127.0.0.1\"\n  port: 8888",
    )
Path("$SETTINGS").write_text(src)
print("settings → $SETTINGS")
PY

export SEARXNG_SETTINGS_PATH="$SETTINGS"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m searx.webapp
