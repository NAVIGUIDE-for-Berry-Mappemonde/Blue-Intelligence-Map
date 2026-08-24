# Test Credentials

## Authentication
**This app has NO authentication.** It is a fully public app — no login page, no user accounts, no sessions, no protected routes. All endpoints under `/api/*` (except `/api/webhook/stripe`) are open. The testing agent does NOT need any credentials to reach any UI or API surface.

## Backend API keys (server-side only, never exposed to the frontend)
Configured in `/app/backend/.env` and validated live on 2026-08-24:
- `TINYFISH_API_KEY` — real key, POC-verified (POST /automation/run-async returned run_id 8f4c6e72…, GET /runs/{id} → PENDING).
- `OPENROUTER_API_KEY` — real key, POC-verified (422 models listed; live gpt-4o-mini completion returned "OK", $2.7e-6 cost). Not wired into features yet (Phase 1 POC only).
- `EMERGENT_LLM_KEY` — universal LLM key used as fallback for Gemini through `emergentintegrations.LlmChat.with_model("gemini", ...)`. Verified live ({"pong": true}). This is the key that powers the Gatekeeper Protocol + extraction + smart geocoding when no user-supplied Gemini key is present in the Settings panel.
- `STRIPE_API_KEY` — sandbox `sk_test_emergent`. Sandbox test card `4242 4242 4242 4242`, any future date, any CVC.
- `RESEND_API_KEY` — currently empty; community-report emails will fall back to `email_status: "skipped"` (this is expected, not a failure).

## Frontend
- `REACT_APP_BACKEND_URL` — set in `/app/frontend/.env`, used by axios in `src/api.js`.

## MongoDB
- Local Mongo at `mongodb://localhost:27017`, DB name `blueintel_db`.
- Collections (as of Phase 3, 2026-08-24):
  - `projects`: 4463 documents with correct `category_group`.
  - `marinas`: **212 documents** — 124 OSM + 69 SHOM + 19 curated. Priority split: 192 P1, 17 P2, 3 P3. Enriched: 3 (Port des Minimes, Rodney Bay Marina, Marina Bas-du-Fort — all via TinyFish, 5-7 fields filled each). Indexes: unique `dedup_key`, compound `(priority, name)`.
  - `settings`: `_id="global"` with 23 tunables (Phase 3 added `marina_batch_concurrency`, `openrouter_min_credits_usd`, `enrich_stale_days`).
- **Feature flags for the testing agent**:
  - Global mode switch header: `[data-testid="mode-toggle-projects"]`, `[data-testid="mode-toggle-marinas"]`. Persisted in `localStorage["bi.mode"]`.
  - `<html data-mode="projects|marinas">` drives CSS var `--accent-rgb` (`0 240 255` vs `255 74 74`).
  - Marinas sidebar (mode=marinas): `marinas-panel`, `marinas-search-input`, `marinas-filter-priority`, `marinas-filter-source`, `marinas-scan-btn`, `marinas-batch-btn`, `marinas-batch-count`, `marinas-list`, `marina-row-<uuid>`.
  - Marina popup: `popup-enrich-btn` (red, calls `window.__biEnrichMarina('<id>')` → `POST /api/marinas/{id}/enrich`).
  - Project popup: `popup-donate-btn`, `popup-project-enrich-btn` (calls `window.__biEnrichProject('<id>')` → `POST /api/projects/{id}/enrich`).
  - Map layers: `map-container`, `mpa-toggle-btn`, `route-toggle-btn`.
- **API endpoints added in Phase 3**:
  - `POST /api/marinas/{id}/enrich` — on-demand, per-id lock, 409 if in progress.
  - `POST /api/marinas/enrich-batch` — background task with `limit`, `priority`, `include_enriched`, `stale_only`.
  - `GET /api/marinas/enrich-batch/status` — running/progress/results/logs.
  - `POST /api/projects/{id}/enrich` — re-run extraction (Readability + Gemini) on the project URL.
- **Overpass status**: `overpass-api.de` and `kumi.systems` are unreachable from this container (TCP refused / 502). **`overpass.openstreetmap.fr` is the working endpoint** — the marinas.py client uses it as primary. Do NOT expect `overpass-api.de` to answer.
- **SHOM WFS**: `https://services.data.shom.fr/INSPIRE/wfs` is public, no auth, but requires **LON-first bbox** and returns coords in **EPSG:3857**. Typenames: `INFORMATIONS_PORTUAIRES_BDD_WFS:smcfac_point` + `hrbfac_point`.
