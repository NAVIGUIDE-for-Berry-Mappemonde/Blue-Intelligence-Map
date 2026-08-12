# Blue Intelligence — PRD

## Original Problem Statement
Blue Intelligence transforms the living web of maritime data into an executable geospatial database. The application deploys AI agents (TinyFish + Claude) to discover, extract, and map marine conservation projects worldwide.

## User Choices
- Real TinyFish API key provided (stored in backend/.env TINYFISH_API_KEY)
- User's own Anthropic key — "later" → heuristic fallback active until key entered in Settings
- Full scope v1: swarm controls + live console, Leaflet map w/ clusters, org filter, GeoJSON export, Audit dashboard, Settings panel, EN/FR toggle
- ~14 major marine foundations as MasterSeeds
- Dark ocean-themed UI, English default with FR toggle

## Architecture
- /app/backend — FastAPI (port 8001): server.py (routes), pipeline.py (Swarm orchestrator), tinyfish_client.py, ai.py (Gemini via emergentintegrations w/ user key + heuristic fallback), geo.py (global-land-mask point-in-ocean, coastal snapping, Nominatim geocode), seeds.py
- /app/frontend — React CRA + Tailwind + Leaflet/markercluster (port 3000)
- MongoDB collections: projects, telemetry, failed, settings, deeplink_pages
- Old AI Studio prototype archived at /app/prototype_ai_studio

## ETL Pipeline
1. Discovery: TinyFish async runs (live view URL captured) on MasterSeeds → project page URLs → DeepLinkCache; fallback: httpx+BS4 crawler
2. Extraction: httpx + readability-lxml → Gatekeeper (Gemini Flash or heuristic keywords) → extract+S_ocean (Gemini 3.1 Pro or heuristic) → geocode → point-in-ocean test → coastal snapping → dedup (<500m + title similarity / URL) → Mongo
3. Test mode = 3 seeds; Full mode = all seeds + DeepLinkCache

## Implemented (2026-06)
- Full swarm deploy/stop, live agent console w/ TinyFish live-view links, global log stream
- Map view (Leaflet dark, clusters, dark popups w/ S_ocean + snapped badge), org filter, project list
- GeoJSON export, clear projects
- Audit: KPIs, telemetry table, failed extractions + force extract (TinyFish sync) single/all
- Settings: thresholds, concurrency, Gemini model selects, map limits, API keys (Gemini/TinyFish stored in Mongo settings)
- EN/FR i18n, manual download EN/FR
- Verified live: TinyFish discovered 6 Ocean Foundation projects → 6 mapped, 100% success rate

## Backlog
- P1: Recursive "Follow the Money" discovery (grantee link expansion)
- P1: WebSocket instead of polling
- P2: NDJSON live feed / MapLibre variant, EEZ layers, proxy mode
- P2: DeepLinkCacheProjectsLists (catalog-level cache), 65-foundation MasterSeeds list from user

## Update 2026-06 — Gemini Integration
- Replaced Claude with Gemini (user choice, own Google AI key in backend/.env GEMINI_API_KEY)
- Gatekeeper: gemini-3-flash-preview | Extraction+Scoring: gemini-3.1-pro-preview (selectable in Settings)
- Verified live: marine accepted 1.0, terrestrial rejected, extraction w/ GPS + S_ocean 0.95

## Update 2026-06 — Donations Stripe + UX Map
- Vue mondiale au chargement (zoom 2, centre [22,5])
- Cagnotte globale: compteur EUR en header (GET /api/donations/total), bouton Donner (liste + popups carte), modale montants 5/10/25/50/100 EUR
- Stripe SANDBOX via emergentintegrations StripeCheckout (STRIPE_API_KEY=sk_test_emergent — sandbox à réclamer impossible: pays NC non supporté par Stripe)
- Endpoints: POST /api/donations/checkout, GET /api/payments/status/{id}, GET /api/donations/total, webhook /api/webhook/stripe
- Import GeoJSON (session précédente): 4420 projets importés, popup fix (sigRef), photos og:image/twitter/first-img
- Tests iteration_3: 100% pass

## Update 2026-06 — UX Reorganisation + Engagement
- Sidebar gauche épurée: légende cliquable (9 catégories colorées), filtres org+catégorie, recherche, liste projets, bouton "Projet manquant ?"
- Contrôles Swarm (statut, deploy/stop, logs, console agents) déplacés dans l onglet Swarm Intelligence Audit (SwarmControls.js)
- Export GeoJSON + Clear projects déplacés dans le panneau Paramètres (section Données)
- Auto-Stop saturation (saturation_limit=50, _bump_saturation), formulaire signalement (Resend email OK → clementfilisetti@berrymappemonde.org, mise en file swarm), marqueurs colorés par catégorie + fix zoom (defer rebuild until zoomend, chunkedLoading, maxBounds)
- Tests iteration_4: 100%
