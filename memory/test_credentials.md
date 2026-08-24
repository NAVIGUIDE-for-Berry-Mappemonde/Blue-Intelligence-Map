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
- `REACT_APP_BACKEND_URL=https://anchorages-50nm.preview.emergentagent.com` — set in `/app/frontend/.env`, used by axios in `src/api.js`.

## MongoDB
- Local Mongo at `mongodb://localhost:27017`, DB name `blueintel_db`.
- Collections (as of Phase 4B, 2026-08-24):
  - `projects`: **4 463 documents** — restored via `POST /api/import/geojson` from the user's backup GeoJSON (Aug 24). Category distribution: MPA 402, Conservation 765, Research 895, Fisheries 361, Policy & Advocacy 490, Pollution 391, Coastal & Habitat 389, Education 301, Other 469. API `/api/projects` renvoie bien les 4 463 features (curl 200 en 619 ms) ; un bug de rendering React empêche l'affichage sidebar/clusters — à investiguer dans un vrai navigateur (voir PRD.md Update 2026-08-24 — Phase 5 Closure).
  - `marinas`: **212 documents** — rebuilt Phase 4.0 (124 OSM + 69 SHOM + 19 curated, P1=192 · P2=17 · P3=3). None enriched yet.
  - `settings`: `_id="global"`.
  - `formalities`: **13 documents** (13 territoires seedés au Phase 4A). Après batch Phase 4B : **12/13 status=`ia`, 1/13 status=`ia_sans_source` (la_reunion)**. Distribution des sources : 18 URLs whitelistées au total, 0 hors whitelist, 0 blacklist. Unique index sur `territory_code`.
- **Feature flags for the testing agent** (Phase 4A additions):
  - Global mode switch header now has **3 buttons**: `[data-testid="mode-toggle-projects"]`, `[data-testid="mode-toggle-marinas"]`, `[data-testid="mode-toggle-formalities"]`. Persisted in `localStorage.bi.mode` (accepts `"projects" | "marinas" | "formalities"`).
  - `<html data-mode="projects|marinas|formalities">` drives CSS var `--accent-rgb` (`0 240 255` cyan · `255 74 74` red · `251 191 36` amberx).
  - Formalities sidebar (`mode=formalities`): `formalities-panel`, `formalities-disclaimer`, `nationality-selector` (values `fr|ca|us|gb`, persisted in `localStorage.bi.nationality`), `formalities-list`, `formalities-row-{territory_code}` (with `-departure` / `-return` suffix on La Rochelle's two rows), `formalities-card`, `formalities-escale-overlay`, `formalities-tab-{entree|sortie|cas_particuliers|immigration|contacts|sources}`, `formalities-tab-content-{tab_id}`, `formalities-card-wrap`.
  - Map layer in Formalities mode: **no project cluster, no marina cluster**. Escale markers coloured by status (`non_generee=slate-500 · ia=amberx · ia_sans_source=amberx dashed · verifiee=bio-green`). Ports of entry get a white ring badge (13 rings on the current data). Class hooks: `.bi-poe-ring`, `.bi-escale-marker--dashed`.
- **API endpoints added in Phase 4A**:
  - `GET /api/territories` → curated territory reference (13 items, `content_language: "fr"`, blacklist at top level).
  - `GET /api/formalities` → `{count, items[]}` — 13 formalities docs, ordered along the route.
  - `GET /api/formalities/{territory_code}` → doc + embedded `territory` reference. Returns 404 for unknown code.
- **API endpoints added in Phase 4B (generation, verification, exports)**:
  - `POST /api/formalities/{code}/generate` → 202 `{status:"started"}` — kicks a real TinyFish+LLM pipeline. 409 if already running for that code.
  - `GET /api/formalities/{code}/generate/status` → `{state, logs_tail, result, started_at, finished_at}`. Poll every 2-3 s.
  - `POST /api/formalities/generate-batch` → runs the 13 with `Semaphore(2)`. Optional `{"stale_only": true}` body. 409 if any batch is already running.
  - `GET /api/formalities/generate-batch/status` → `{running, progress, total, results[], logs_tail[-80:]}`.
  - `PUT /api/formalities/{code}/verify` → flip status to `verifiee` + stamp `verified_at`. 400 if `non_generee`.
  - `POST /api/formalities/{code}/immigration/{nat}` → nat ∈ ca|us|gb (400 for fr or any other value). 202 + verrou `{code:nat}`.
  - `GET /api/formalities/{code}/immigration/{nat}/status` → idem generate/status.
  - `GET /api/export/formalities.json` → `FormalitiesCollection` attachment (14 KB current).
  - `GET /api/export/formalities.geojson` → 17-feature `FeatureCollection`, 1 Point per escale of route.geojson, with properties `{escale_name, leg, territory_code, status, is_port_of_entry, stale, generated_at, verified_at}`.
- **Phase 4B UI additions**:
  - `formalities-batch-btn` + `formalities-batch-logs` (live tail during batch).
  - `formalities-refresh-btn` (per-territory refresh, in the open card).
  - `formalities-verify-btn` (visible only when status=ia|ia_sans_source).
  - `immigration-generate-btn` (visible in Immigration tab when nationality != fr AND slot empty).
  - `formalities-export-json` + `formalities-export-geojson` (anchor links to the export endpoints).
  - `formalities-no-source-warning` (red banner shown on Sources tab when status=ia_sans_source).
  - `formalities-stale-badge` (amberx clock badge, appears when generated_at > 180 days).
- **Testing tips for Phase 4B**:
  - The generation endpoints take **6–10 min per territory** in practice (2 × 210 s TinyFish TIMEOUT budget on gov.fr sites + fallback httpx fetch + LLM ~5 s). A single-territory refresh from the UI is a real operation, not instantaneous.
  - The **fallback httpx+BeautifulSoup fetch** kicks in when all TinyFish missions on a territory time out — the source URL is still whitelisted, no mocked content. Log line `[fallback-fetch] {url}: N chars extracted` proves it ran.
  - la_reunion always ends in `ia_sans_source` on this environment because the entry PDF (arrêté 401-2017) is not extractible by the current fallback (would need a PDF parser).
  - Immigration on-demand for ca/us/gb typically returns null-filled slots on French official portals — this is expected behaviour (the LLM refuses to invent facts absent from the whitelisted sources).
- **Overpass status**: `overpass.openstreetmap.fr` remains the working primary endpoint from this container. `overpass-api.de` and `kumi.systems` still refuse this container's IP.
- **SHOM WFS**: `https://services.data.shom.fr/INSPIRE/wfs` public, LON-first bbox, EPSG:3857 coords. Typenames `INFORMATIONS_PORTUAIRES_BDD_WFS:smcfac_point` + `hrbfac_point`.
