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
- Collections (as of Phase 2, 2026-08-24):
  - `projects`: 4463 documents (all with correct `category_group` after import bugfix). Distribution: Research 890, Conservation 765, Policy 490, Other 474, MPA 402, Pollution 391, Coastal 389, Fisheries 361, Education 301.
  - `marinas`: 19 documents, all `source: "curated"` (Overpass + SHOM unreachable at build time — see PRD Update 2026-08 Phase 2 for full verdict). Split: 16 priority-1 (near escale), 0 priority-2, 3 priority-3 (TAAF remote mooring, Ilet la Mère). Indexes: unique on `dedup_key`, compound on `(priority, name)`.
  - `settings`: `_id: "global"` with 21 tunables (including new `marina_search_radius_nm: 10.0`).
- **Feature flags for the testing agent to know**:
  - Global mode switch in header: `[data-testid="mode-toggle-projects"]` and `[data-testid="mode-toggle-marinas"]`. Persisted in `localStorage["bi.mode"]`.
  - The `<html>` element carries `data-mode="projects|marinas"` — CSS var `--accent-rgb` reads `0 240 255` in Projects, `255 74 74` in Marinas.
  - Marinas mode sidebar test-ids: `marinas-panel`, `marinas-search-input`, `marinas-filter-priority`, `marinas-filter-source`, `marinas-scan-btn`, `marinas-list`, `marina-row-<uuid>`.
  - Map layer test-ids preserved: `map-container`, `mpa-toggle-btn`, `route-toggle-btn`.
