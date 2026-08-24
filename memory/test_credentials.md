# Test Credentials

## Authentication
**This app has NO authentication.** It is a fully public app — no login page, no user accounts, no sessions, no protected routes. All endpoints under `/api/*` (except `/api/webhook/stripe`) are open. The testing agent does NOT need any credentials to reach any UI or API surface.

## Backend API keys (server-side only, never exposed to the frontend)
Configured in `/app/backend/.env` and re-provisioned live on 2026-08-25 during Phase 4.0 reanimation:
- `TINYFISH_API_KEY` — real key (`sk-tinyfish-tz-…`), used by the Phase 3 marina/project enrichment chain.
- `OPENROUTER_API_KEY` — real key (`sk-or-v1-…`), 2nd LLM tier in the enrichment chain (`openai/gpt-4o-mini`).
- `EMERGENT_LLM_KEY` — universal LLM key (`sk-emergent-2BaBcC37a89984a811`), fallback for Gemini through `emergentintegrations.LlmChat.with_model("gemini", ...)`. Powers the Gatekeeper Protocol + project extraction + smart geocoding.
- `STRIPE_API_KEY=sk_test_emergent` (sandbox). Test card `4242 4242 4242 4242`, any future date, any CVC.
- `RESEND_API_KEY=` intentionally empty — community-report emails fall back to `email_status: "skipped"` (expected, not a failure).
- `CLOUDFLARE_ACCOUNT_ID=` and `CLOUDFLARE_API_TOKEN=` intentionally empty — the Cloudflare Workers AI tier is dormant and the chain falls through to OpenRouter → OSM tags (matches Phase 3.1 verdict).

## Frontend
- `REACT_APP_BACKEND_URL=https://codebase-scan-45.preview.emergentagent.com` — set in `/app/frontend/.env`, used by axios in `src/api.js`.

## MongoDB
- Local Mongo at `mongodb://localhost:27017`, DB name `blueintel_db`.
- Collections (as of Phase 4A, 2026-08-25):
  - `projects`: **0 documents** — DB was empty at Phase 4.0 reanimation; the 4 463 historical projects need to be re-imported by the user via `POST /api/import/geojson` with their GeoJSON backup. Mode Projects UI is code-functional but has no features to display until re-import.
  - `marinas`: **212 documents** — rebuilt live during Phase 4.0 (124 OSM + 69 SHOM + 19 curated, P1=192 · P2=17 · P3=3, 0 overpass_error, 0 shom_error). None enriched yet on this fresh instance.
  - `settings`: `_id="global"` — created on first `GET /api/settings` call, defaults from `DEFAULT_SETTINGS` in `server.py`.
  - **`formalities` (Phase 4A, new)**: **13 documents** seeded automatically at backend startup (one per territory: `france_metropolitaine, martinique, guadeloupe, saint_barthelemy, saint_martin, guyane, saint_pierre_et_miquelon, polynesie_francaise, wallis_et_futuna, nouvelle_caledonie, mayotte, taaf, la_reunion`). All `status: "non_generee"`. Unique index on `territory_code`.
- **Feature flags for the testing agent** (Phase 4A additions):
  - Global mode switch header now has **3 buttons**: `[data-testid="mode-toggle-projects"]`, `[data-testid="mode-toggle-marinas"]`, `[data-testid="mode-toggle-formalities"]`. Persisted in `localStorage.bi.mode` (accepts `"projects" | "marinas" | "formalities"`).
  - `<html data-mode="projects|marinas|formalities">` drives CSS var `--accent-rgb` (`0 240 255` cyan · `255 74 74` red · `251 191 36` amberx).
  - Formalities sidebar (`mode=formalities`): `formalities-panel`, `formalities-disclaimer`, `nationality-selector` (values `fr|ca|us|gb`, persisted in `localStorage.bi.nationality`), `formalities-list`, `formalities-row-{territory_code}` (with `-departure` / `-return` suffix on La Rochelle's two rows), `formalities-card`, `formalities-escale-overlay`, `formalities-tab-{entree|sortie|cas_particuliers|immigration|contacts|sources}`, `formalities-tab-content-{tab_id}`, `formalities-card-wrap`.
  - Map layer in Formalities mode: **no project cluster, no marina cluster**. Escale markers coloured by status (`non_generee=slate-500 · ia=amberx · ia_sans_source=amberx dashed · verifiee=bio-green`). Ports of entry get a white ring badge (13 rings on the current data). Class hooks: `.bi-poe-ring`, `.bi-escale-marker--dashed`.
- **API endpoints added in Phase 4A**:
  - `GET /api/territories` → curated territory reference (13 items, `content_language: "fr"`, blacklist at top level).
  - `GET /api/formalities` → `{count, items[]}` — 13 formalities docs, ordered along the route.
  - `GET /api/formalities/{territory_code}` → doc + embedded `territory` reference. Returns 404 for unknown code.
- **Overpass status**: `overpass.openstreetmap.fr` remains the working primary endpoint from this container. `overpass-api.de` and `kumi.systems` still refuse this container's IP.
- **SHOM WFS**: `https://services.data.shom.fr/INSPIRE/wfs` public, LON-first bbox, EPSG:3857 coords. Typenames `INFORMATIONS_PORTUAIRES_BDD_WFS:smcfac_point` + `hrbfac_point`.
