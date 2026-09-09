#!/usr/bin/env bash
# Installation idempotente de SearXNG (venv /opt/searxng) SANS lancer le serveur.
# Doc : https://docs.searxng.org/admin/installation-searxng.html
# Appelé par .cursor/install.sh (snapshot) et par .cursor/start.sh si le venv manque.
set -euo pipefail

SEARXNG_HOME="${SEARXNG_HOME:-/opt/searxng}"
SEARXNG_GIT="${SEARXNG_GIT:-https://github.com/searxng/searxng.git}"
OWNER="$(id -u):$(id -g)"

install_searxng_venv() {
  echo "==> SearXNG apt packages"
  if ! sudo apt-get install -y \
    python3-dev python3-venv python3-babel git build-essential \
    libxslt-dev zlib1g-dev libffi-dev libssl-dev; then
    sudo apt-get update
    sudo apt-get install -y \
      python3-dev python3-venv python3-babel git build-essential \
      libxslt-dev zlib1g-dev libffi-dev libssl-dev
  fi

  if [ ! -d "$SEARXNG_HOME/.git" ]; then
    echo "    cloning $SEARXNG_GIT → $SEARXNG_HOME"
    sudo rm -rf "$SEARXNG_HOME"
    sudo mkdir -p "$SEARXNG_HOME"
    sudo chown "$OWNER" "$SEARXNG_HOME"
    git clone "$SEARXNG_GIT" "$SEARXNG_HOME"
  else
    echo "    $SEARXNG_HOME already a git clone"
  fi
  # Jamais un tree root-only : le process Cloud Agent (ubuntu) doit pouvoir pip/run.
  sudo chown -R "$OWNER" "$SEARXNG_HOME"

  if [ ! -x "$SEARXNG_HOME/.venv/bin/python" ]; then
    echo "    creating venv $SEARXNG_HOME/.venv"
    python3 -m venv "$SEARXNG_HOME/.venv"
  else
    echo "    venv already present"
  fi

  echo "    pip bootstrap (pip/setuptools/wheel/pyyaml/msgspec/typing-extensions/pybind11)"
  "$SEARXNG_HOME/.venv/bin/python" -m pip install -U \
    pip setuptools wheel pyyaml msgspec typing-extensions pybind11

  echo "    pip install --use-pep517 --no-build-isolation -e $SEARXNG_HOME"
  (
    cd "$SEARXNG_HOME"
    "$SEARXNG_HOME/.venv/bin/python" -m pip install --use-pep517 --no-build-isolation -e .
  )
  echo "    SearXNG venv ready ($SEARXNG_HOME/.venv/bin/python)"
}

ensure_searxng_url() {
  # SEARXNG_URL n'est pas un secret : URL de NOTRE process local.
  local envf="${1:?backend .env path}"
  local url="http://127.0.0.1:8888"
  mkdir -p "$(dirname "$envf")"
  python3 - "$envf" "$url" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
url = sys.argv[2]
text = path.read_text(encoding="utf-8") if path.exists() else ""
out: list[str] = []
found = False
for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith("SEARXNG_URL=") and not stripped.startswith("#"):
        found = True
        val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
        out.append(f"SEARXNG_URL={url}" if not val else line)
    else:
        out.append(line)
if not found:
    if out and out[-1] != "":
        out.append("")
    out.append(f"SEARXNG_URL={url}")
path.write_text(("\n".join(out) + "\n") if out else f"SEARXNG_URL={url}\n", encoding="utf-8")
print(f"    SEARXNG_URL ensured in {path}")
PY
}

searxng_json_ok() {
  python3 - <<'PY'
import json, sys, urllib.request

url = "http://127.0.0.1:8888/search?q=ping&format=json"
req = urllib.request.Request(
    url,
    headers={"User-Agent": "BlueIntelligence-start/1.0", "Accept": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status != 200:
            sys.exit(1)
        json.load(resp)
except Exception:
    sys.exit(1)
PY
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  install_searxng_venv
fi
