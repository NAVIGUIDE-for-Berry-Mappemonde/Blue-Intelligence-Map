#!/usr/bin/env bash
# =============================================================================
# NAVIGUIDE — Local Development Startup Script
# Starts all 4 services: API + Orchestrator + Weather Routing + Frontend
#
# Usage:
#   chmod +x start_local.sh
#   ./start_local.sh
#
# Services launched:
#   http://localhost:8000   — naviguide-api      (FastAPI routes + Copernicus)
#   http://localhost:3008   — naviguide-orchestrator  (Multi-Agent LangGraph)
#   http://localhost:3010   — naviguide-weather-routing  (Isochrone engine)
#   http://localhost:5173   — naviguide-app (Vite React frontend)
#
# Prerequisites:
#   Python 3.9+    brew install python (Mac)
#   Node.js 18+    brew install node   (Mac)
#   pip install -r naviguide_workspace/requirements.txt
#   pip install -r naviguide-api/requirements.txt
#   cd naviguide-app && npm install
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[NAVIGUIDE]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; }

# ── Kill any leftover processes on our ports ──────────────────────────────────
info "Freeing ports 8000, 3008, 3010..."
for PORT in 8000 3008 3010; do
    lsof -ti tcp:"$PORT" | xargs kill -9 2>/dev/null || true
done

# ── Check Python ──────────────────────────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    error "Python 3 not found. Install with: brew install python"
    exit 1
fi
PY_VER=$($PYTHON --version 2>&1)
info "Python: $PY_VER"

# ── Check Node.js ─────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    error "Node.js not found. Install with: brew install node"
    exit 1
fi
info "Node: $(node --version)"

# ── Service 1: naviguide-api (port 8000) ──────────────────────────────────────
info "Starting naviguide-api on port 8000..."
cd "$SCRIPT_DIR/naviguide-api"
# Create .env if missing
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || cat > .env <<'ENVEOF'
COPERNICUS_USERNAME=berrymappemonde@gmail.com
COPERNICUS_PASSWORD=Hackmyroute2027
PORT=8000
ENVEOF
fi
NAVIGUIDE_API_LOG="$LOG_DIR/naviguide-api.log"
nohup $PYTHON main.py > "$NAVIGUIDE_API_LOG" 2>&1 &
API_PID=$!
echo "$API_PID" > "$LOG_DIR/naviguide-api.pid"
success "naviguide-api started (PID $API_PID) → log: $NAVIGUIDE_API_LOG"

# ── Service 2: Orchestrator (port 3008) ───────────────────────────────────────
info "Starting orchestrator on port 3008..."
cd "$SCRIPT_DIR/naviguide_workspace"
ORCH_LOG="$LOG_DIR/orchestrator.log"
PORT=3008 nohup $PYTHON -m naviguide_orchestrator.main > "$ORCH_LOG" 2>&1 &
ORCH_PID=$!
echo "$ORCH_PID" > "$LOG_DIR/orchestrator.pid"
success "orchestrator started (PID $ORCH_PID) → log: $ORCH_LOG"

# ── Service 3: Weather Routing (port 3010) ────────────────────────────────────
info "Starting weather-routing on port 3010..."
WEATHER_LOG="$LOG_DIR/weather-routing.log"
PORT=3010 nohup $PYTHON -m naviguide_weather_routing.main > "$WEATHER_LOG" 2>&1 &
WEATHER_PID=$!
echo "$WEATHER_PID" > "$LOG_DIR/weather-routing.pid"
success "weather-routing started (PID $WEATHER_PID) → log: $WEATHER_LOG"

# ── Wait for backends to start ────────────────────────────────────────────────
info "Waiting for backends to initialise (15 s)..."
sleep 15

# ── Health checks ─────────────────────────────────────────────────────────────
check_service() {
    local name=$1 url=$2
    if curl -sf "$url" -o /dev/null 2>/dev/null; then
        success "$name is UP → $url"
    else
        warn "$name not responding yet — check $LOG_DIR"
    fi
}

check_service "naviguide-api"     "http://localhost:8000/"
check_service "orchestrator"      "http://localhost:3008/"
check_service "weather-routing"   "http://localhost:3010/"

# ── Service 4: Frontend (Vite dev server) ────────────────────────────────────
info "Starting Vite frontend..."
cd "$SCRIPT_DIR/naviguide-app"

# Ensure .env points to localhost services
cat > .env.local <<'ENVEOF'
VITE_API_URL=http://localhost:8000
VITE_ORCHESTRATOR_URL=http://localhost:3008
VITE_WEATHER_ROUTING_URL=http://localhost:3010
ENVEOF

FRONTEND_LOG="$LOG_DIR/frontend.log"
nohup npm run dev -- --host > "$FRONTEND_LOG" 2>&1 &
FRONT_PID=$!
echo "$FRONT_PID" > "$LOG_DIR/frontend.pid"
success "frontend started (PID $FRONT_PID) → log: $FRONTEND_LOG"

sleep 5

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${BOLD}  NAVIGUIDE is running locally!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "  ${CYAN}Frontend :${NC}        http://localhost:5173"
echo -e "  ${CYAN}API      :${NC}        http://localhost:8000"
echo -e "  ${CYAN}Orchestrator :${NC}    http://localhost:3008"
echo -e "  ${CYAN}Weather Routing :${NC} http://localhost:3010"
echo ""
echo -e "  Logs → ${LOG_DIR}/"
echo -e "  Stop all → ${BOLD}./stop_local.sh${NC}  (or kill the PIDs above)"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
