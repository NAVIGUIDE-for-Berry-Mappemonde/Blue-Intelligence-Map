# Testing Protocol

## Communication with the testing agents

- Whenever we finish a code change we invoke either `deep_testing_backend_v2` (backend/curl) or `deep_testing_frontend_v2` (Playwright UI).
- The testing agent may only be triggered by the main agent, not by the user.
- The testing agent MUST NOT be invoked twice back-to-back without the main agent making progress in between (either applying a fix or explicitly re-scoping the task).

## Incorporate User Feedback

- User feedback trumps testing-agent verdict for scope disagreements.
- If the user reports a specific bug, the fix MUST be verified by the testing agent (never by main-agent inspection alone).
- Never claim a fix as verified based on curl / inline reasoning — only the sub-agent report counts.

## Current Task Under Test

**4 bugs after formalities generation** (2026-08-24, phase 4)

### Bug 1 — Formalities export was META-ONLY (round-trip broken)
`GET /api/export/formalities.geojson` shipped only 8 meta fields (status,
is_port_of_entry, generated_at, verified_at, stale, escale_name, leg,
territory_code) — the AI-generated fiche content (entree/sortie/
cas_particuliers/immigration/contacts/liens_officiels/sources) was silently
dropped. Round-trip export → import → identical restore was impossible.
**Fix**: added the 7 content fields + a per-escale `escale_overlay` object
to every feature. Import endpoint upgraded to merge those fields when
present, backwards-compatible with the old meta-only export.

### Bug 2 — "Items Mapped" KPI stuck at 4463 in every mode
`GET /api/stats` always returned `projects_mapped = db.projects.count()`,
regardless of mode. **Fix**: added `?mode=projects|marinas|formalities`
query param. Returns `items_mapped = 17 / 212 / 4463`. `AuditView` now
passes the active mode and reads the new `items_mapped` key.

### Bug 3a — Popups cut off (overflow above the map viewport)
`bindPopup` was called with `autoPan: false` on ALL three modes. Long
Martinique / Nouméa fiches (400+ px tall) escaped through the top of the
map container. **Fix**: `autoPan: true, keepInView: true, maxHeight: 400,
autoPanPadding: [40, 40]` on all four bindPopup call-sites (projects,
marinas, formalities, route escales).

### Bug 3b — SPM (and other antipodal escales) invisible after click
`leaflet.markercluster`'s post-init bounds cache is stubbornly wrong for
markers whose longitude falls outside the initial map viewport
(Saint-Pierre-et-Miquelon at -56°, Papeete at -149°, Nouméa at +166°,
Wallis at -176°). Even with `removeOutsideVisibleBounds: false` and
`disableClusteringAtZoom: 4`, those markers' `__parent` stayed pointing
at the ROOT cluster at zoom 1 (`_icon: false`), so no DOM element was
ever attached even at zoom 6. **Fix**: dropped clustering for this layer
— 17 markers world-wide, clustering is aesthetic-only. `L.featureGroup()`
guarantees every marker gets a DOM element the moment the layer is on
the map, regardless of viewport bounds.

### Bug 3c — Blue triangles between stopovers (defensive fix)
Could not reproduce the actual artifact with a headless probe (0 filled
polygons anywhere, before or after hover). Added `fill: false` explicitly
on both polylines (casing + main) as a defensive guard against any
theoretical SVG-fill leak.

### Non-regression contract (from previous phases)
- Zero rebuild of formalities markers on selection or language change
  (`clearLayers`/`addLayers` = 0 calls during click + FR ↔ EN toggle)
- Popups use lazy `bindPopup(fn)` reading `tRef.current` at open time
- All 3 GeoJSON import endpoints keep working; the 3 datasets stay in
  the DB (projects=4463, marinas=212, formalities=13 territories)

### `test_credentials.md`
See `/app/memory/test_credentials.md` — the app has NO auth.

## Structured status (2026-08-24 phase 4)

```yaml
backend:
  - task: "GET /api/export/formalities.geojson ships full fiche content"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Export now includes entree/sortie/cas_particuliers/immigration/contacts/liens_officiels/sources + a per-feature escale_overlay. Verified via curl on Martinique — 62KB vs old ~5KB, all fields populated with AI-generated content."
        - working: true
          agent: "testing"
          comment: "T1 PASS. GET /api/export/formalities.geojson → HTTP 200, size=62670 bytes (61.2 KB, comfortably >20 KB). type=='FeatureCollection', features.length==17. Martinique feature has ALL 16 required properties: escale_name, leg, territory_code, status, is_port_of_entry, stale, generated_at, verified_at, entree, sortie, cas_particuliers, immigration, contacts, liens_officiels, sources, escale_overlay. entree is a dict with demarches_arrivee (355 chars) + 10 other keys (admission_temporaire, biosecurite, douanes_clearance, frais, franchises, horaires, ou_s_amarrer, pavillon_q, preavis, vhf) all populated. sortie is a dict. contacts is a list (len=1). sources is a list (len=1). Full AI content shipped, not null."

  - task: "POST /api/import/formalities.geojson round-trip preserves content"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Import merges content fields when present in the file, backwards-compat with old meta-only files (content fields simply stay untouched instead of overwritten with null). Verified: export → re-import → GET /api/formalities returns identical entree/sortie/contacts/sources for Martinique."
        - working: true
          agent: "testing"
          comment: "T2 PASS. Saved T1 export → POST /api/import/formalities.geojson → HTTP 200, resp={imported:0, merged:13, skipped_existing:0, invalid:0, total_formalities:13, territories_touched:13}. Round-trip byte-identical: GET /api/formalities martinique.entree.demarches_arrivee == exported (both 355 chars). sortie.clearance == exported ('Les formalités de clearance obligatoires sont également requises pour la sortie…'). escale_overlays for martinique has exactly 1 entry: [{escale_name:'Fort-de-France (Martinique)', is_port_of_entry:true, note:null}]."

  - task: "GET /api/stats?mode=... returns mode-scoped counter"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "New `mode` query param. Returns `items_mapped`: 17 (formalities, from route escales), 212 (marinas), 4463 (projects). Telemetry counts scoped by `dataset` field (legacy rows without `dataset` count as projects). Legacy `projects_mapped` key still returned for backwards-compat."
        - working: true
          agent: "testing"
          comment: "T3 PASS. /api/stats?mode=projects → items_mapped==4463, projects_mapped==4463 (bw-compat), mode=='projects'. /api/stats?mode=marinas → items_mapped==212, mode=='marinas'. /api/stats?mode=formalities → items_mapped==17, mode=='formalities'. /api/stats (no query) → items_mapped==4463 (defaults to projects). T4 PASS: /api/stats?mode=xxx_unknown → HTTP 200, no crash, items_mapped==4463 (falls back to projects). T5 non-regression sanity ALL PASS: /api/ (200), /api/route (FeatureCollection, 71 features), /api/projects (4463 features), /api/marinas (212 features), /api/formalities (count==13), /api/territories (200), /api/openapi.json exposes all 5 required paths (/api/import/geojson, /api/import/marinas.geojson, /api/import/formalities.geojson, /api/export/formalities.geojson, /api/stats). Zero 500s observed. 48/48 assertions PASS."

frontend:
  - task: "AuditView passes active mode to /api/stats and reads items_mapped"
    implemented: true
    working: true
    file: "frontend/src/components/AuditView.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "`api.get('/stats', { params: { mode } })`. `stats.items_mapped ?? stats.projects_mapped` keeps backwards-compat. `load` callback now depends on `mode`, so the 5s polling interval auto-refreshes when the user switches mode."
        - working: true
          agent: "testing"
          comment: "T1 PASS on desktop AND mobile. Opened Swarm Intelligence Audit view, toggled through all 3 modes. kpi-projects-mapped reads: projects mode→'4463', marinas mode→'212', formalities mode→'17'. KPI updates immediately upon mode change (within the 2s wait). Same values observed on both viewports (1920x900 and 390x844)."

  - task: "MapView popups fit inside the map viewport (autoPan + keepInView + maxHeight)"
    implemented: true
    working: true
    file: "frontend/src/components/MapView.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "All four bindPopup call-sites (projects, marinas, formalities, route escales) upgraded from `autoPan: false` to `autoPan: true, keepInView: true, autoPanPadding: [40, 40]`. Formalities + marinas + projects also get `maxHeight: 400` so long fiches scroll internally instead of pushing the popup outside the map. Verified: Martinique popup boundingClientRect fits inside the leaflet-container (overflow_top: false, overflow_bottom: false)."
        - working: true
          agent: "testing"
          comment: "T2 PASS on desktop AND mobile. FR language, clicked formalities-row-martinique. Popup rect (t=122, b=548, l=954, r=1325), height=426px. Map rect (t=56, b=1080, l=360, r=1920). All four bounds checks PASS (top≥map.top-5, bottom≤map.bottom+5, left≥map.left-5, right≤map.right+5). Popup fits entirely within the leaflet-container viewport."

  - task: "MapView formalities layer switched to L.featureGroup (no clustering)"
    implemented: true
    working: true
    file: "frontend/src/components/MapView.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Dropped `L.markerClusterGroup` for the formalities layer — 17 world-wide markers make clustering aesthetic-only. `L.featureGroup()` attaches all 17 markers to the DOM the instant the layer is added to the map. Verified: initial state = 17/17 attached, clicking SPM/Papeete/Wallis/Nouméa all open popups and show target._icon = true. Non-regression: zero rebuild on selection or language change (`onSelectEscaleRef` + data-only deps unchanged), popup i18n lazy binding + language-change refresh preserved."
        - working: true
          agent: "testing"
          comment: "T3 PASS on desktop AND mobile. Initial state: window.__biDebug.formalities.getLayers().length===17 AND all 17 have _icon attached (17/17). Clicked antipodal escales in sequence (SPM, Papeete, Wallis, Nouméa) — each opened popup with correct escale name (Saint-Pierre / Papeete / Mata-Utu / Nouméa) and all 17 markers stayed attached (_icon!==null). window.__rebuilds === 0 across the entire sequence (no cluster rebuild on selection)."

  - task: "Route polylines defensively set fill: false"
    implemented: true
    working: true
    file: "frontend/src/components/MapView.js"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Could not reproduce the 'triangles bleus' artifact — 0 filled polygons in the map SVG before or after hover on multiple positions. Added `fill: false` explicitly to both polylines (casing + main) as a defensive guard. If the artifact ever comes back, it won't be a fill leak on the route layer."
        - working: true
          agent: "testing"
          comment: "T4 PASS on desktop AND mobile. Set map view to [15,-30] zoom=3. Filled paths before hover: 39. Moved mouse to 4 positions on the route ([500,400], [900,500], [700,300], [1000,400]) with 350ms wait. Filled paths after hover: 39 (unchanged). Zero blue-fill paths inside .leaflet-route-pane."

  - task: "Non-regression — imports, popup at sidebar click, i18n live refresh"
    implemented: true
    working: true
    file: "backend + frontend (no functional change this phase)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "The 3 import endpoints, the popup open-on-click flow, and the FR ↔ EN live popup refresh mechanism were NOT touched this phase. Manual browser sanity: clicking Martinique still opens its popup with restored 'Verified · Port of entry' content; switching FR ↔ EN with a popup open still updates the section titles immediately."
        - working: true
          agent: "testing"
          comment: "T5 PASS on desktop AND mobile. Opened Martinique popup in EN → content contains 'IA-generated / Port of entry' (EN markers present). Installed rebuild counter, clicked lang-toggle-fr WITHOUT closing popup. Polled every 100ms during 1500ms window: .leaflet-popup element was NEVER null. After 1.5s, popup content became 'IA-générée / Port d'entrée' (FR labels). window.__rebuilds === 0. Popup i18n live refresh preserved, zero marker rebuild."

metadata:
  created_by: "main_agent"
  version: "1.4"
  test_sequence: 4
  run_ui: true

test_plan:
  current_focus:
    - "GET /api/export/formalities.geojson ships full fiche content"
    - "POST /api/import/formalities.geojson round-trip preserves content"
    - "GET /api/stats?mode=... returns mode-scoped counter"
    - "AuditView passes active mode to /api/stats and reads items_mapped"
    - "MapView popups fit inside the map viewport (autoPan + keepInView + maxHeight)"
    - "MapView formalities layer switched to L.featureGroup (no clustering)"
    - "Route polylines defensively set fill: false"
    - "Non-regression — imports, popup at sidebar click, i18n live refresh"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    - agent: "main"
      message: "4 bugs fixed in this phase. Please verify (1) round-trip formalities export → import restores identical fiche content, (2) /api/stats?mode=... returns 17/212/4463 for formalities/marinas/projects and the Audit view KPI reflects that, (3) popup boundingClientRect fits inside the leaflet-container after opening a long fiche, (4) clicking Saint-Pierre-et-Miquelon (and Papeete/Wallis/Nouméa) attaches the marker in the DOM AND opens the popup. Non-regression: no marker rebuild on click or lang toggle, imports still work, popup i18n still updates live."
    - agent: "testing"
      message: "FRONTEND UI VERIFIED (phase 4, 4-bug fixes) — All 5 tests (T1..T5) PASS on BOTH desktop (1920x900) and mobile (390x844) viewports via headless Playwright, DOM-only assertions. T1 (KPI mode-scoped): kpi-projects-mapped reads 4463/212/17 in projects/marinas/formalities modes. T2 (popup fits): Martinique FR popup rect (h=426px) fits inside leaflet-container, all 4 bounds within 5px tolerance. T3 (antipodal escales attached): 17/17 markers attached from init; SPM/Papeete/Mata-Utu/Nouméa all open popups with correct content and stay attached; zero rebuild across 4 clicks. T4 (route fill defensive): 39 filled paths before vs 39 after hover on 4 positions; 0 blue-fill paths in .leaflet-route-pane. T5 (lang live refresh non-regression): EN→FR toggle on open Martinique popup swapped 'IA-generated / Port of entry' → 'IA-générée / Port d'entrée' within 1.5s; popup element never null during poll; window.__rebuilds===0. All 5 frontend tasks flipped to working=true. Recommend main agent summarise and finish."
    - agent: "testing"
      message: "BACKEND VERIFIED (phase 4, 4-bug fixes) — /app/backend_test.py, 48/48 assertions PASS. T1 (export ships full content): HTTP 200, 62670 bytes = 61.2 KB (>20 KB), 17 features, martinique feature has all 16 required properties including entree (dict, demarches_arrivee=355 chars + 10 subfields populated), sortie (dict), contacts (list len=1), sources (list len=1), escale_overlay (dict). T2 (round-trip): POST /api/import/formalities.geojson with the saved export → HTTP 200, total_formalities=13, territories_touched=13, invalid=0. martinique.entree.demarches_arrivee round-trip byte-identical (355==355). sortie.clearance preserved. escale_overlays.length==1. T3 (mode-scoped): projects→items_mapped=4463 (+ projects_mapped=4463 bw-compat), marinas→212, formalities→17, default→4463. T4 (unknown mode): HTTP 200, items_mapped=4463 (falls back to projects), no crash. T5 (non-regression): /api/, /api/route (71 features ≥60), /api/projects (4463), /api/marinas (212), /api/formalities (count=13), /api/territories all 200; /api/openapi.json paths contains all 5 required endpoints. Zero 500s. All 3 backend tasks flipped to working=true. Recommend main agent summarise and finish."


### Bug reported by user
The "Import GeoJSON" button in the settings panel silently did nothing when
the current mode was Marinas or Formalities: the frontend always POSTed to
`/api/import/geojson`, which is projects-only. Marinas/formalities exports
therefore ended up as 4 000+ "invalid" projects rejected without any user
feedback. There was NO backend endpoint for marinas or formalities imports.

### Root cause
1. Backend: only `/api/import/geojson` existed (projects). No import route
   for marinas or formalities.
2. Frontend `SettingsPanel.importFile`: hard-coded `api.post("/import/geojson", …)`,
   ignoring the `mode` prop.
3. Frontend `App.js`: `onImported={() => fetchProjects(true)}` — the refresh
   callback only refreshed projects; even if we hit the right endpoint,
   the map wouldn't show the newly-imported marinas/formalities without a
   manual page reload.

### Data files provided by user (downloaded to /tmp/geojson_import/)
- `projects.geojson`     — 4 463 Point features (funder + description + s_ocean)
- `formalities.geojson`  —    17 Point features (1 per route escale)
- `marinas.geojson`      —   212 Point features (source ∈ openstreetmap/shom/curated)

### What the frontend testing agent must verify (headless Playwright, real DOM)

**Endpoints (curl-verifiable):**
- `POST /api/import/geojson`             — projects,     returns `{imported, merged, skipped_existing, invalid, total_projects}`
- `POST /api/import/marinas.geojson`     — marinas,      returns same shape with `total_marinas`
- `POST /api/import/formalities.geojson` — formalities,  returns same shape with `total_formalities` + `territories_touched`
- Malformed body → HTTP 400 `{"detail":"invalid GeoJSON FeatureCollection"}`
- All three are idempotent (re-run = merged only, imported=0).

**UI (Playwright, `mode-toggle-*` + `settings-toggle-btn` + `import-geojson-input`):**

1. **Marinas import via UI**
   a. Switch to Marinas mode. Open settings.
   b. `[data-testid="settings-import-context-hint"]` MUST end with `· MARINAS`.
   c. `page.set_input_files('[data-testid="import-geojson-input"]', '/tmp/geojson_import/marinas.geojson')`.
   d. Auto-accept the alert; message must include `• Total marinas: 212`.
   e. `window.__biDebug.marinas.getLayers().length` MUST equal `212` after import.
   f. `.leaflet-marker-icon` count MUST stay ≥ 11 all along (poll every 100 ms) — no rebuild-induced drop to 0.

2. **Formalities import via UI**
   a. Switch to Formalities mode. Open settings.
   b. Hint MUST end with `· FORMALITIES`.
   c. Import `/tmp/geojson_import/formalities.geojson`.
   d. Alert message includes `• Total formalities: 13`.
   e. `window.__biDebug.formalities.getLayers().length` MUST equal `17` after import.

3. **Projects import via UI**
   a. Switch to Projects mode. Open settings.
   b. Hint MUST end with `· PROJECTS`.
   c. Import `/tmp/geojson_import/projects.geojson`.
   d. Alert message includes `• Total projects: 4463`.
   e. `window.__biDebug.projects.getLayers().length` MUST equal `1000` (`max_markers`
      cap) or the exact `min(4463, max_markers)` value.

4. **Cross-mode mismatch protection**
   - In Projects mode, import `/tmp/geojson_import/marinas.geojson` — the
     frontend detects the file shape and shows an alert:
     `Import failed: Fichier détecté comme "marinas" mais le mode actif est "projects"…`
   - `window.__biDebug.projects.getLayers().length` MUST NOT change (still 1000).

5. **Non-regression: sidebar click still opens popup**
   - After all three imports, switch to Formalities, click
     `[data-testid="formalities-row-martinique"]`. Popup MUST open with title
     starting `🇲🇶 Fort-de-France (Martinique)` and content including the
     restored status `Verified` and `Port of entry`.

### `test_credentials.md`
See `/app/memory/test_credentials.md` — the app has NO auth, endpoints open under `/api/*`.

## Structured status (GeoJSON import repair — 2026-08-24)

```yaml
backend:
  - task: "POST /api/import/marinas.geojson — new endpoint, upserts by _id"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "New endpoint validates FeatureCollection, requires Point geometry with valid lat/lon and non-empty properties.name. Idempotent upsert by _id (falls back to a fresh uuid if missing). Returns {imported, merged, skipped_existing, invalid, total_marinas}. Malformed body → 400. Verified via curl: 212 imported on fresh DB, 212 merged on idempotent re-run, no dupes."
        - working: true
          agent: "testing"
          comment: "T3 PASS. Fresh POST /tmp/geojson_import/marinas.geojson → HTTP 200 in 0.14s, resp={imported:0, merged:212, skipped_existing:0, invalid:0, total_marinas:212} (already loaded from previous run). Idempotent re-POST → identical response (imported:0, merged:212). GET /api/marinas → FeatureCollection with exactly 212 features. GET /api/marinas/count → {total:212, by_source:{openstreetmap:124, shom:69, curated:19}} — all 3 required source families present. T5 PASS: POST /api/import/marinas.geojson with {\"type\":\"NotFC\"} returns HTTP 400 + detail=='invalid GeoJSON FeatureCollection'. T6 PASS: 4-feature payload (2 valid + LineString + empty-props) returns HTTP 200 with invalid:2, imported:2 — invalid features counted, non-fatal. Testing agent cleaned up its 2 test 'SDET' marinas via pymongo after T6 so DB stays at 212."

  - task: "POST /api/import/formalities.geojson — new endpoint, groups by territory_code"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "New endpoint groups 17 escale features → 13 territory docs. Only META fields (status, escale_overlays[], generated_at, verified_at) are set; existing entree/sortie/… fiche content is NEVER overwritten. Returns {imported, merged, skipped_existing, invalid, total_formalities, territories_touched}. Verified: 13 territories touched, statuses correctly restored (france_metropolitaine=ia, martinique=verifiee, etc.), escale_overlays contain 17 escales incl. both La Rochelle entries."
        - working: true
          agent: "testing"
          comment: "T4 PASS. POST /tmp/geojson_import/formalities.geojson → HTTP 200 in 0.01s, resp={imported:0, merged:13, skipped_existing:0, invalid:0, total_formalities:13, territories_touched:13}. 17 escales correctly collapsed to 13 territories. GET /api/formalities → count==13. Item where territory_code=='france_metropolitaine' has exactly 4 escale_overlays (Saint-Maur + La Rochelle x2 + Ajaccio). Item where territory_code=='martinique' has status=='verifiee' (valid per spec). T5 PASS: POST with {\"type\":\"NotFC\"} → HTTP 400 + detail=='invalid GeoJSON FeatureCollection'."

  - task: "POST /api/import/geojson — no-regression"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Existing projects import endpoint left untouched. Verified via curl on user-provided projects.geojson (4463 features) — no rebuild of the endpoint code, same response shape."
        - working: true
          agent: "testing"
          comment: "T2 PASS (functional) with a minor perf note. POST /tmp/geojson_import/projects.geojson (4463 features) → HTTP 200, resp={imported:0, merged:0, skipped_existing:4463, invalid:0, total_projects:4463}. Response shape correct, invalid==0, total==4463 as required. Minor: latency was ~13.2s across 3 consecutive runs (spec asked <10s). This is the pre-existing endpoint (untouched by this phase), so not a regression — but if <10s is required, main agent may want to add bulk_write / index review. T1 PASS: /api/openapi.json advertises all 3 import paths (/api/import/geojson, /api/import/marinas.geojson, /api/import/formalities.geojson). T5 PASS: malformed body → HTTP 400 + detail=='invalid GeoJSON FeatureCollection'. T7 non-regression PASS: GET /api/ (200), GET /api/route (FeatureCollection, 71 features ≥60), GET /api/projects (4463 features), GET /api/marinas (exactly 212), GET /api/formalities (count=13), GET /api/territories (200). No 500 anywhere."

frontend:
  - task: "SettingsPanel — Import button routes to the endpoint matching the current mode"
    implemented: true
    working: true
    file: "frontend/src/components/SettingsPanel.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Replaced hard-coded api.post('/import/geojson', ...) with IMPORT_URLS[mode] router. Added a heuristic that inspects the FIRST feature.properties to detect the actual dataset (title+url → projects; source+priority → marinas; escale_name/territory_code → formalities) and refuses cross-mode uploads with a clear FR error. Added a contextual hint (data-testid=settings-import-context-hint) that displays the target dataset."
        - working: true
          agent: "testing"
          comment: "T1/T2/T3 PASS on desktop (1920x900). Contextual hint text confirmed for each mode: marinas → 'IMPORTS INTO · MARINAS', formalities → 'IMPORTS INTO · FORMALITIES', projects → 'IMPORTS INTO · PROJECTS'. T4 cross-mode mismatch PASS — importing marinas.geojson in projects mode alerts: 'Import failed: Fichier détecté comme \"marinas\" mais le mode actif est \"projects\". Bascule dans le bon mode avant d''importer.' AND window.__biDebug.projects.getLayers().length remained at 1000 (no partial import). T6 PASS on mobile (390x844) — settings panel opens, marinas import completes with alert 'Total marinas: 212' and cluster == 212."

  - task: "App.js — onImported callback refreshes the right dataset per mode"
    implemented: true
    working: true
    file: "frontend/src/App.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "onImported now receives the mode arg from SettingsPanel and dispatches to fetchMarinas / fetchFormalities / fetchProjects(true). Only the affected dataset is re-fetched; no double refresh."
        - working: true
          agent: "testing"
          comment: "PASS. After each UI import, the correct debug cluster refreshed to the expected size: marinas → getLayers()=212, formalities → getLayers()=17, projects → getLayers()=1000 (max_markers cap, in 500–1500 range). No cross-mode reload observed. Marker DOM min-count during import: T1=11, T2=7, T3=73 (never dropped to 0, no full rebuild). T6 mobile marinas cluster also refreshed to 212 correctly."

  - task: "3 GeoJSON files reinjected — projects/marinas/formalities visible on map"
    implemented: true
    working: true
    file: "backend + curl seeding"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Files downloaded from customer-assets to /tmp/geojson_import/. Curl POSTs applied to the 3 endpoints. Final counts: /api/projects → 4463 features, /api/marinas → 212 features, /api/formalities → 13 territory docs (17 escale overlays). Every mode's cluster now shows markers on load."
        - working: true
          agent: "testing"
          comment: "PASS. Verified via UI imports (T1/T2/T3): alerts show 'Total marinas: 212', 'Total formalities: 13', 'Total projects: 4463'. All three datasets remain queryable and clustered (marinas 212 / formalities 17 / projects 1000 capped). Idempotent behavior observed on re-imports (already-known counts populated, invalid=0)."

  - task: "Non-regression — popup opens on sidebar click after imports, i18n lazy binding preserved"
    implemented: true
    working: true
    file: "frontend/src/components/MapView.js (unchanged this phase)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "MapView.js untouched by this phase. The previous i18n lazy-binding + zero-rebuild-on-selection guarantees still hold. Manually spot-checked in-browser: sidebar row click → popup opens (Fort-de-France Martinique with restored 'Verified · Port of entry')."
        - working: true
          agent: "testing"
          comment: "T5 PASS. Sidebar click on formalities-row-martinique opens the popup: '🇲🇶 Fort-de-France (Martinique) / Martinique / Verified / ⚓ Port of entry / Generated: 2026-08-24 · Verified: 2026-08-24 / ↻ Refresh / SOURCES USED / No source recorded yet.'. Contains Fort-de-France + Martinique + Verified + Port of entry — restored status confirmed post-import. No regression."

metadata:
  created_by: "main_agent"
  version: "1.3"
  test_sequence: 3
  run_ui: true

test_plan:
  current_focus:
    - "POST /api/import/marinas.geojson — new endpoint, upserts by _id"
    - "POST /api/import/formalities.geojson — new endpoint, groups by territory_code"
    - "SettingsPanel — Import button routes to the endpoint matching the current mode"
    - "App.js — onImported callback refreshes the right dataset per mode"
    - "3 GeoJSON files reinjected — projects/marinas/formalities visible on map"
    - "Non-regression — popup opens on sidebar click after imports, i18n lazy binding preserved"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    - agent: "main"
      message: "GeoJSON import fully repaired + 3 user-provided files reinjected. Please verify all backend endpoints via curl AND the UI import flow via headless Playwright as described in the test plan. Focus on the 5 UI scenarios (marinas UI import → 212 markers, formalities UI import → 17 markers, projects UI import → up to max_markers cap, cross-mode mismatch protection, non-regression popup click). Files at /tmp/geojson_import/{projects,marinas,formalities}.geojson."
    - agent: "testing"
      message: "Backend testing done via /app/backend_test.py (19 assertions, 18 PASS, 1 minor-perf soft FAIL). T1 openapi PASS · T2 projects import PASS functionally (200/4463/invalid=0) with a minor timing note: ~13.2s across 3 runs vs the spec's <10s (pre-existing endpoint, not modified this phase). T3 marinas PASS (fresh 200 in 0.14s, idempotent, GET /api/marinas=212, GET /api/marinas/count total=212 with by_source {openstreetmap:124,shom:69,curated:19}). T4 formalities PASS (200 in 0.01s, 17 escales collapsed to 13 territories, france_metropolitaine has 4 escale_overlays, martinique.status=='verifiee'). T5 malformed→400 with correct detail on all 3 endpoints. T6 invalid features counted, non-fatal (invalid=2, imported=2). T7 non-regression sanity PASS: /api/ /api/route (71 features) /api/projects (4463) /api/marinas (212) /api/formalities (13) /api/territories all 200. Testing agent cleaned up its 2 test 'SDET' marinas from mongo post-T6 so DB is back to 212. No 500 observed anywhere. All 3 backend tasks flipped to working=true. Recommend main agent summarise and finish; the projects-import 13s latency is optional to optimise (skipped_existing path could switch to bulk_write for speed)."
    - agent: "testing"
      message: "FRONTEND UI VERIFIED — T1..T6 all PASS on real DOM via headless Playwright. T1 (desktop marinas): hint='IMPORTS INTO · MARINAS', alert 'Total marinas: 212', cluster=212, min sampled markers=11 (never 0). T2 (formalities): hint='IMPORTS INTO · FORMALITIES', alert 'Total formalities: 13', cluster=17, min markers=7. T3 (projects): hint='IMPORTS INTO · PROJECTS', alert 'Total projects: 4463', cluster=1000 (within 500–1500 cap), min markers=73. T4 (cross-mode mismatch): alert 'Import failed: Fichier détecté comme \"marinas\" mais le mode actif est \"projects\". Bascule dans le bon mode avant d''importer.'; projects layers unchanged 1000→1000. T5 (non-regression popup): sidebar click on formalities-row-martinique opens popup '🇲🇶 Fort-de-France (Martinique) / Verified / ⚓ Port of entry / Generated: 2026-08-24 · Verified: 2026-08-24 / ↻ Refresh'. T6 (mobile 390x844 marinas UI import): PASS, alert 'Total marinas: 212', cluster=212, settings panel opens correctly on mobile. All 4 frontend tasks flipped to working=true. Fix is production-ready — recommend main agent summarise and finish."
```


### Bug reported by user
Popup content (Projects, Marinas, Formalities) stayed in the language captured
at marker creation time. Toggling FR ↔ EN after page load left the open popup
in the old language, and any newly-opened popup used the language present when
the markers were built.

### What must be verified by the frontend testing agent (UI)
Test on `mode=formalities` primarily (also spot-check projects & marinas
popups if easy). All measurements MUST come from the real DOM (Playwright
`querySelectorAll`), never a screenshot.

1. **(a) UI language = FR on click** — With the UI switched to FR *before*
   clicking, click a sidebar row like `[data-testid="formalities-row-martinique"]`.
   The popup must open in French. Assertion: `document.querySelector('.leaflet-popup-content').innerText`
   must contain at least one of `["Non générée", "Port d'entrée", "Rafraîchir"]`
   and must NOT contain any of `["Not generated", "Port of entry", "Refresh"]`.

2. **(b) Live language toggle updates the OPEN popup** — Open the Martinique
   popup while UI is in EN. Verify EN content. Without closing the popup,
   click `[data-testid="lang-toggle-fr"]`. Within ≤1500 ms the popup content
   must switch to FR (`popup.setContent`/`popup.update()` internal refresh).
   The popup element (`.leaflet-popup`) must remain present in the DOM
   throughout (no flash of empty popup, no reopen).

3. **(c) Zero marker rebuild across (a) and (b)** — Monkey-patch
   `window.__biDebug.formalities.clearLayers` and `.addLayers` before the
   test and expect a total of 0 calls to either function during the whole
   `(a) → (b)` sequence. Marker DOM count (`.leaflet-marker-icon`) must
   never drop below the pre-click count.

4. **(d) Non-regression — click Papeete (far escale) after lang toggle** —
   Directly click `[data-testid="formalities-row-polynesie_francaise"]`
   while the previous popup is still open. The map must fly to Papeete AND
   the Martinique popup must be replaced by a Papeete popup (title contains
   "Papeete" or "Polynésie") in French, with 0 marker rebuilds.

### Notes / hooks for the testing agent
- Debug handle: `window.__biDebug = { map, projects, marinas, formalities }` — use
  `formalities.getLayers().length` to confirm 17 markers stay in the cluster
  throughout, and `.filter(m => !!m._icon).length` to count DOM-attached ones.
- Route markers (escale dots in the route line) are drawn ONCE and never
  rebuilt; only spot-check formalities cluster markers.
- 17 escale rows exist (`formalities-row-*`); the second La Rochelle row has
  the suffix `-return` (`formalities-row-france_metropolitaine-return`) and
  the first has `-departure`.
- Zero authentication, all endpoints under `/api/*` are open.

### `test_credentials.md`
See `/app/memory/test_credentials.md` — the app has NO auth. No creds needed.

## Structured status (Popup i18n lazy-binding fix — 2026-08-24)

```yaml
frontend:
  - task: "Popup content re-evaluates translation at OPEN time (lazy bindPopup fn)"
    implemented: true
    working: true
    file: "frontend/src/components/MapView.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Projects popup converted from `bindPopup(templateString)` to `bindPopup(FN)` where FN reads `tRef.current` at each open. Formalities helpers now read `tRef.current` at call time."
        - working: true
          agent: "testing"
          comment: "Test (a) PASS on desktop (1920x900) AND mobile (390x844). Switched UI to FR before clicking [formalities-row-martinique]. Popup innerText: '🇲🇶 Fort-de-France (Martinique) — Non générée — ⚓ Port d entrée — ↻ Rafraîchir — Cette fiche n a pas encore été générée...'. Contains FR markers, ZERO EN markers. window.__totalRebuilds === 0. Marker samples min=7 (== pre-click 7), max=11 (cluster expanded on flyTo, which is normal)."

  - task: "Language change refreshes the OPEN popup via popup.update()"
    implemented: true
    working: true
    file: "frontend/src/components/MapView.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "New useEffect with dep [t] calls map._popup.update() on language change."
        - working: true
          agent: "testing"
          comment: "Test (b) PASS on desktop AND mobile. Opened Martinique popup in EN → 'Not generated / Port of entry / Refresh'. Toggled to FR without closing → within 1500 ms popup text became 'Non générée / Port d entrée / Rafraîchir', ZERO EN markers remaining. Polled every 50 ms: .leaflet-popup element was NEVER null during the toggle (popup_never_null=true). window.__totalRebuilds === 0."

  - task: "Zero marker rebuild on language change or selection change"
    implemented: true
    working: true
    file: "frontend/src/components/MapView.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Effect deps kept data-only; onSelectEscale/t/mode read via refs."
        - working: true
          agent: "testing"
          comment: "Test (c) PASS. Across the full (a)→(b)→(d) sequence on both viewports, window.__totalRebuilds === 0. Marker DOM count never dropped below the pre-click baseline (desktop a:7→min 7, b:11→min 11; mobile a:7→min 7, b:7→min 15 — samples never dipped). No cluster clearLayers/addLayers call was observed."

  - task: "Non-regression — sidebar click still opens popup for far-away escales (Papeete)"
    implemented: true
    working: true
    file: "frontend/src/components/MapView.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "openWithFallback now checks map._popup._source === target."
        - working: true
          agent: "testing"
          comment: "Test (d) PASS on desktop AND mobile. With Martinique popup still open in FR, clicked [formalities-row-polynesie_francaise]. After 4.5 s: .leaflet-popup present=true, popup text: '🇵🇫 Papeete (Polynésie française) — Non générée — ⚓ Port d entrée — ↻ Rafraîchir'. Contains 'Papeete' AND 'Polynésie', FR markers present, ZERO EN markers, window.__totalRebuilds === 0. Antipodal flyTo worked and popup was correctly swapped from Martinique to Papeete."

  - task: "Cross-mode spot check (Projects / Marinas popup i18n)"
    implemented: true
    working: "NA"
    file: "frontend/src/components/MapView.js"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "testing"
          comment: "NOT VERIFIED via automation — attempted to open a project/marina popup via layer.openPopup() on the first cluster layer, but the returned handle was a MarkerCluster group whose child layers are not directly programmatically-openable without spiderfying. This is a test-methodology limitation, not an app defect. The same lazy-binding mechanism (bindPopup(fn) reading tRef.current + map._popup.update() effect on [t]) is used for ALL 3 modes' popups in MapView.js, and the formalities verification (tests a/b/c/d) proves the mechanism works. Recommend manual QA spot-check by human if desired."

metadata:
  created_by: "main_agent"
  version: "1.2"
  test_sequence: 2
  run_ui: true

test_plan:
  current_focus:
    - "Popup content re-evaluates translation at OPEN time (lazy bindPopup fn)"
    - "Language change refreshes the OPEN popup via popup.update()"
    - "Zero marker rebuild on language change or selection change"
    - "Non-regression — sidebar click still opens popup for far-away escales (Papeete)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    - agent: "main"
      message: "Applied surgical fix to /app/frontend/src/components/MapView.js only (scope-strict, App.js untouched). Frontend hard-restarted (killed react-scripts + supervisord restart) so the served bundle is guaranteed fresh. Please verify the 4 assertions above via headless Playwright on the preview URL https://anchorages-50nm.preview.emergentagent.com. Do NOT rely on screenshots — measure DOM directly."
    - agent: "testing"
      message: "VERIFIED — all 4 primary tests (a), (b), (c), (d) PASS on BOTH desktop (1920x900) and mobile (390x844) viewports. Popup i18n lazy-binding bug is fixed. Measured directly from DOM via Playwright evaluate(). Highlights: (a) FR-first click yields FR popup with 0 EN markers, 0 rebuilds. (b) EN→FR toggle while popup is open swaps content within 1500 ms; polled every 50 ms and .leaflet-popup was NEVER null during the swap. (c) window.__totalRebuilds === 0 across the entire (a→b→d) sequence on both viewports; marker DOM min-count never dropped below pre-click baseline. (d) Antipodal Papeete click while Martinique FR popup was open correctly swapped to a Papeete popup in FR, 0 rebuilds. Cross-mode Projects/Marinas spot-check could not be automated (cluster child layers not directly openable without a real mouse click on a specific canvas pixel), but the same tRef.current lazy-binding + map._popup.update() mechanism is shared for all 3 modes in MapView.js, so the formalities verification transitively proves the fix. Recommend manual QA if a full cross-mode UI validation is required. No red-screen errors, no console errors observed. Fix is production-ready — please summarise and finish."
```

