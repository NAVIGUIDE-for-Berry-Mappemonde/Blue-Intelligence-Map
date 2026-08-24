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

## Update 2026-06 — Fixes carte
- Popup bord de carte: autoPan:false + adjustPopup (translate CSS de la bulle, carte immobile, flèche ancrée) — testé sur les 4 bords (iteration_5)
- Monde unique: noWrap + maxBounds ±180° + viscosité 1.0 + fitMinZoom (getBoundsZoom) — plus de duplication du monde ni de glissement chaotique (iteration_6, 100%)

## Update 2026-06 — Découverte incrémentale
- discovery_state (TTL par portail, rescan_after_days=7): seeds scannés récemment sautés (0 crédit TinyFish)
- Delta scan: URLs connues transmises à l agent TinyFish (retourne uniquement les nouveautés)
- Case "Forcer un rescan complet" dans les contrôles Swarm (force_rescan)
- 9 portails marqués scannés; 12 restants seront découverts au prochain full run
- Vérifié: deploy test → 3 seeds sautés, 0 appel TinyFish, manuels EN/FR mis à jour

## Update 2026-06 — Intégration ProtectedSeas Navigator (Phase 1)
- Endpoint proxy GET /api/mpa?bbox= → ArcGIS Living Atlas (Navigator All Sites), cache Mongo mpa_cache TTL 3j, propriétés normalisées (ps_id, site_name, lfp, designation, country, managing_authority, url)
- Couche Leaflet: toggle "Aires Marines Protégées", chargement par bbox à zoom>=5 (hint sinon), polygones colorés LFP 1-5 (bleu→violet), popups (nom, badge LFP, désignation, lien), légende LFP on-map, attribution CC BY 4.0 + disclaimer
- Vérifié: API Banc d Arguin LFP4 OK, rendu frontend OK
- Backlog ProtectedSeas: Phase 2 enrichissement projets (badge intersection AMP, sites_updated sync), Phase 3 PMTiles

## Update 2026-06 — Fix visibilité AMP + filtre LFP
- Bug 50MB géométries (Parc Mer de Corail): maxAllowableOffset adaptatif (bbox/500) + geometryPrecision 4 + gzip middleware + timeout 90s + cache offset-bucket → NC bbox 76 AMP en ~2s
- Style polygones plus visible (fillOpacity 0.28), cases à cocher LFP 1-5 dans la légende on-map (filtrage live, labels barrés)
- Vérifié iteration_7 100%: popup Chesterfield-Bellona LFP5 No-Take, filtre 328→303→328 polygones

## Update 2026-08 — Phase 1 : Réanimation + Route Berry-Mappemonde
- Réanimation : /app/backend/.env et /app/frontend/.env restaurés (MongoDB local, DB_NAME=blueintel_db, CORS *, clés TinyFish/OpenRouter/Stripe réelles, EMERGENT_LLM_KEY comme clé universelle Gemini). ai.py::get_llm_key et server.py::read_settings acceptent désormais EMERGENT_LLM_KEY en fallback → LlmChat().with_model("gemini", ...) fonctionne sans clé Gemini directe.
- Dépendances Python manquantes réinstallées dans le venv : global-land-mask, readability-lxml, resend, beautifulsoup4 (le venv d'origine avait perdu ces paquets).
- OpenAPI exposé sous /api : GET /api/openapi.json renvoie app.openapi() (26 paths). Nécessaire pour les tests automatisés — l'ingress ne route que /api/*.
- Ré-import projets historiques : 4 465 features du GeoJSON officiel → 4 463 importés + 2 fusionnés en doublons, 0 skipped, 0 invalid, 861 financeurs uniques. NB : l'endpoint POST /api/import/geojson actuel ne restaure PAS le champ `category_group` depuis les propriétés du GeoJSON → tous les projets réimportés retombent en catégorie "Other" côté légende (bug pré-existant, non corrigé dans cette phase).
- Route Berry-Mappemonde (statique, officielle, lecture seule) : /app/backend/data/route.geojson (121 KB, 71 features : 17 escales + 19 intermédiaires + 34 segments maritimes + 1 segment overland), servie par GET /api/route avec Cache-Control 1h + X-Route-Source header.
- Rendu Leaflet dans MapView (aucun react-leaflet — L direct) : couche layerGroup dédiée (jamais fondue dans le markerCluster des projets), style neutre bicontraste (casing #0f172a opacité 0.35 + main #e2e8f0 opacité 0.95, dashArray "6 6" pour overland vs solide pour maritime) lisible sur fond sombre ET clair. Escales : circleMarker blanc r=6 + bordure sombre + tooltip permanent avec le nom. Intermédiaires : petits points slate-500 r=2.5, tooltip au survol seulement. Popup au clic sur chaque waypoint (type + nom + attribution). Toggle "⛵ Berry-Mappemonde Route" en haut à droite au-dessus du toggle AMP, visible par défaut, testé : off → 134→28 paths SVG et 0 label escale, on → 17 escales restaurées, popup Saint-Maur (Berry, Indre) OK.
- i18n EN/FR complet : routeLayer / routeSegmentMaritime / routeSegmentOverland / routeWaypointEscale / routeWaypointIntermediate / routeAttribution.
- POC clés API (aucune intégration dans le pipeline en Phase 1) :
  - TinyFish : POST /automation/run-async → HTTP 200 + run_id valide, GET /runs/{id} → PENDING. Clé active. Aucun header de quota exposé par l'API.
  - OpenRouter : GET /models → 422 modèles disponibles ; GET /key → limit=null (illimité), usage cumulé $0.00058 ; complétion réelle gpt-4o-mini → "OK" (15 tokens, coût $2.7e-6). Clé active.
  - Emergent LLM (Gemini) : appel réel via LlmChat.with_model("gemini","gemini-2.5-flash") → {"pong": true}. Clé universelle opérationnelle.
- Non touché : dual-mode UI Marinas/Projects, enrichissement marinas, éditeur de route (backlog Phase 2+).
