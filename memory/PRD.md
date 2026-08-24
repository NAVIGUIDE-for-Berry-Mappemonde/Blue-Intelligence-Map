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

## Update 2026-08 — Phase 2 : Marinas layer + Dual-mode UI (R-002) + fix import
- **Bug fix C (import GeoJSON)** : `POST /api/import/geojson` respecte désormais `properties.category` ET `properties.category_group` en création ET en backfill sur les projets déjà présents (branches URL-match ET title-similarity). Résultat après ré-import du GeoJSON historique : **Research 890 · Conservation 765 · Policy 490 · Other 474 · MPA 402 · Pollution 391 · Coastal & Habitat 389 · Fisheries 361 · Education 301** (total 4 463). Légende sidebar en mode Projects désormais correcte.
- **Backend marinas** :
  - Nouvelle collection Mongo `marinas` (index unique sur `dedup_key`, index composé `(priority, name)`). Champs : `_id` uuid, `name`, `lat`, `lon`, `source` (`openstreetmap|shom|curated`), `osm_id`, `tags` (VHF/tel/site/capacité/profondeur/redevance…), `priority` (1 escale ≤15 NM, 2 waypoint intermédiaire ≤15 NM, 3 corridor), `nearest_waypoint {id,name,kind,distance_nm}`, `dedup_key = normalize(name[:25]) + geohash6(lat,lon)`, `fetched_at`, `enriched: false`, `stale: false`. Newest-wins upsert par dedup_key.
  - Nouveau module `/app/backend/marinas.py` (~500 lignes) : geohash + haversine locaux, client Overpass poli (retry backoff, User-Agent, 3 mirrors), client SHOM WFS best-effort (INSPIRE, 4 typenames candidats), échantillonnage corridor tous les 100 NM, priorité par distance au waypoint le plus proche.
  - Fichier seed curated `/app/backend/data/curated_marinas.json` (19 marinas connues aux 17 escales : Port des Minimes, Port Charles Ornano, Marina Rubicon, Mindelo, Rodney Bay, Marina Bas-du-Fort, Fort Louis, Marina Taina, Port Moselle, etc.) chargé en premier à chaque build → l'UI a toujours des données concrètes même si Overpass est en panne. Une fois OSM opérationnel, ses résultats plus riches gagnent la préférence via l'ordre `openstreetmap > shom > curated`.
  - Nouveaux endpoints : `POST /api/marinas/build` (background task, guarde 409 si déjà en cours, params `radius_nm`, `clear_before`, `include_corridor`, `corridor_step_nm`), `GET /api/marinas/build/status` (progress, logs, summary, error), `GET /api/marinas` (GeoJSON, filtres `?priority=` et `?source=`), `GET /api/marinas/count`, `GET /api/export/marinas.geojson`, `GET /api/export/route.geojson`.
  - Nouveau setting `marina_search_radius_nm` (défaut 10 NM).
- **Build réel exécuté — verdict honnête** :
  - **OpenStreetMap Overpass** : 34/36 requêtes en erreur. `overpass-api.de` **complètement injoignable** (HTTP 000, DNS/firewall block), `overpass.kumi.systems` **retourne HTTP 500 systématique** (jusque `node(1)` échoue) — l'IP du container est visiblement blacklistée par les mirrors publics à l'instant du build. Pipeline vérifié correct (un test antérieur avec Ajaccio a rendu 13 candidats OSM avant que kumi.systems ne tombe). Un simple `POST /api/marinas/build` re-idempotent enrichira la collection dès que Overpass acceptera nos requêtes.
  - **SHOM WFS** : les 4 typenames candidats (`SMCFAC_TS_PORT_HARBOUR_BDD_WFS`, `smcfac:smcfac_point`, `MOUILLAGE_FR_WFS`, `MOUILLAGE_ORGANISE_FR_WFS`) renvoient tous **HTTP 401** — l'endpoint public INSPIRE de SHOM exige désormais un compte / clé API. Fallback silencieux comme prévu par la spec.
  - **Curated seed** : **19 marinas insérées** — 16 priorité 1 (à ≤15 NM d'une escale) + 3 priorité 3 (mouillages TAAF / Ilet la Mère qui sortent du rayon 15 NM). 0 priorité 2 (curation limitée aux escales).
- **Frontend R-002 dual-mode UI** :
  - `Header` — pill switch **Projets (cyan #00f0ff) ↔ Marinas (rouge #ff4a4a)**, persistence localStorage `bi.mode`. Attribut `data-mode="projects|marinas"` posé sur `<html>` pilotant deux variables CSS (`--accent-rgb`, `--accent-glow`). Nouvelle couleur Tailwind sémantique `accent: rgb(var(--accent-rgb) / <alpha-value>)` utilisée dans `Header` (waves icon, subtitle, view/lang/settings toggles) → tout l'accent bascule automatiquement. Le reste de l'app (`.text-sonar`, `.text-alert`…) reste inchangé, seuls les accents changent, comme demandé.
  - Nouvelle sidebar `MarinasPanel.js` (~230 lignes) — titre "Marinas", compteur, recherche (nom + escale), 2 filtres select (priorité 1/2/3 + source), bouton **"Scan marinas along the route"** qui déclenche `POST /api/marinas/build` avec spinner + progress + summary post-build, liste triée par priorité puis nom avec badges P1/P2/P3 + source (OSM/SHOM/Curated) + waypoint le plus proche + distance NM. Clic sur une ligne → fly-to + popup.
  - `MapView` — nouveau prop `mode` + `marinas` + `flyToMarina`. **Deux `L.markerClusterGroup` distincts** : projets (icônes `.bi-cluster` cyan, r=34) et marinas (icônes `.bi-cluster-marina` rouge, r=32). Un seul cluster est attaché à la carte à la fois — mode-swap useEffect ferme le popup, retire l'autre cluster et ajoute le bon. Popup marina : nom + badge priorité + badge source + waypoint le plus proche + tags OSM (VHF, capacité, profondeur, redevance, tél, site web) + osm_id + date de fetch. **Route Berry-Mappemonde reste visible dans les deux modes** ; toggle AMP disponible dans les deux modes.
  - i18n EN/FR complet pour tous les nouveaux libellés (`modeProjects`, `modeMarinas`, `marinasSearch`, `marinasPriority1/2/3`, `marinasSourceOSM/SHOM/Curated`, `marinasFlyTo`, `marinasScan[ning|Done|Error]`, `marinasVHF/Capacity/Website/Phone/Fee/Depth`, `marinasNearest`, `marinasFetchedAt`, `marinasAll`, `marinasEmpty`).
- **Vérifié end-to-end** : mode par défaut Projects (bleu, 4463 markers clusterisés + 17 escale labels + route visibles), switch Marinas (rouge, 19 marinas listées, cluster rouge sur la carte, route encore visible), reload conserve le mode (localStorage), clic sur "Cayenne — Port du Larivot" fly + popup ("P1 · Escale · Curated · NEAREST WAYPOINT Cayenne (Guyane) · 2.1 NM · Fetched: 2026-08-24"), switch retour Projects préserve tout (4463 markers + route + escales), lang FR bascule tous les libellés.
- **Non fait cette phase** (backlog Phase 3) : enrichissement TinyFish/OpenRouter des marinas ; refresh planifié de la collection ; UI d'édition/CRUD des marinas ; drawing on map ; scan sur zone géographique arbitraire (hors route).
- **Polish parasite corrigé** : le bouton "Report missing project" existait mais son `<ReportModal>` n'était jamais rendu — corrigé.


## Update 2026-08 — Phase 3 : Enrichment (TinyFish + OpenRouter + fallback) + fixes SHOM/Overpass
### Fix parasite #1 — SHOM WFS était le mauvais endpoint, PAS un problème d'auth
- Le 401 précédent venait de typenames inventés (`SMCFAC_TS_PORT_HARBOUR_BDD_WFS`, `smcfac:smcfac_point`, `MOUILLAGE_FR_WFS`…). Le service `https://services.data.shom.fr/INSPIRE/wfs` est bien **public, Licence Ouverte Etalab, sans auth**.
- GetCapabilities réel → 181 FeatureTypes. Bons typenames identifiés : `INFORMATIONS_PORTUAIRES_BDD_WFS:smcfac_point` (S-57 Small Craft Facilities — 291 features Métropole) + `hrbfac_point` (Harbour Facilities — 636 Métropole).
- 2 gotchas techniques : (a) bbox exige **LON-FIRST** (`west,south,east,north`) malgré la convention WFS 2.0, et (b) données renvoyées en **EPSG:3857 Web Mercator** malgré `srsName=EPSG:4326` → conversion Merc→WGS84 côté client (formule inverse standard, sans dépendance).
- Table de correspondance S-57 `catscf` → labels français ajoutée (Marina, Ponton, Yacht club, Atelier, Bureau des douanes, Grue, etc.), exposée en tag `shom:category`.
- Requêtes multi-régions : Métropole+Corsica, Antilles+Saint-Pierre, Guyane, Polynésie, Réunion+Mayotte+TAAF.

### Fix parasite #2 — Overpass : UA compliant + /api/status pre-flight
- User-Agent conforme à l'OSM API Usage Policy : `BerryMappemonde-BlueIntelligence/1.0 (+https://berrymappemonde.org; contact: clementfilisetti@berrymappemonde.org)`.
- Nouveau pre-flight `GET /api/status` (parsage slots disponibles + waits), `overpass_await_slot()` respecte les cool-downs annoncés, back-off Retry-After sur 429.
- Concurrency=1 (strictement séquentiel), throttle 3s entre requêtes, timeout `[out:json][timeout:60]` dans chaque QL.
- Endpoints testés depuis l'IP de ce container avec l'UA compliant :
  - `overpass-api.de` → **TCP CONN REFUSED** sur les 2 IPs Hetzner (blocage réseau — DNS OK, TCP KO)
  - `overpass.kumi.systems` → connect OK mais `/api/interpreter` → 502 permanent (upstream daemon inaccessible depuis notre AS)
  - **`overpass.openstreetmap.fr` → HTTP 200, marche impeccablement**. Adopté comme endpoint primaire.

### Build marinas ré-exécuté (résultats réels) — build fondamental utilisé par Phase 3
- 36 waypoints × per-point `around:` r=10 NM, 133 s au total, 0 error, 232 raw features, 20 duplicates fusionnés → **212 marinas insérées**.
- **Répartition finale** : OSM **124**, SHOM **69**, Curated **19**. Par priorité : P1 **192**, P2 **17**, P3 **3**.
- Exemples OSM par escale : La Rochelle 15 (Port des Minimes, Port du Plomb, Bassins des Chalutiers/Marillac/Lazaret, Havre d'échouage…), Ajaccio 13, Fort-de-France 8, Pointe-à-Pitre 18, Marigot **26**, Papeete 6, Nouméa 9, Mata-Utu 1, détroit de Torres 1, Seychelles 2, Dzaoudzi 1, Saint-Gilles 6, Halifax (intermédiaire) 16, Saint-Pierre 1. Guyane (Cayenne) 3.
- SHOM totaux (post-filtre 10 NM) : Métropole 25, Antilles+SPM 27, Guyane 2, Polynésie 6, Réunion+Mayotte+TAAF 11 = 71.

### Phase 3 backend — enrichment chain per R-001
- Nouveau module `/app/backend/enrichment.py` (~330 lignes) implémentant la chaîne **TinyFish → OpenRouter → OSM-tags fallback** avec `MARINA_ENRICH_SCHEMA` (7 champs : `canal_vhf`, `places_visiteurs`, `tirant_eau_max_metres`, `score_protection_meteo` (1-5), `services_disponibles` (list), `telephone_capitainerie`, `resume_avis`) + normaliser strict qui traite les `""` / `0` / `0.0` comme null (schéma TinyFish n'accepte pas les union types ni les descriptions sur les propriétés — les vides deviennent nulls dans notre code).
- **TinyFish** : approche `run-async + poll every 4s (budget 210s)`. URL hint = tag `website` OSM prioritairement, sinon recherche DuckDuckGo HTML (`https://html.duckduckgo.com/html/`, sans clé). Détection COMPLETED/FAILED via polling.
- **OpenRouter** : credit-guard avant tout appel (`GET /v1/key`, respecte `openrouter_min_credits_usd` setting, défaut 0.5 USD ; si `limit=null` → key illimitée, on passe). Modèle `openai/gpt-4o-mini`, `response_format=json_object`, temperature=0. Contexte : URL DDG-picked → readability → titre + texte (max 6000 chars) + tags OSM + prompt strict "return null if not present, never fabricate". Coût ~$0.00013 par marina.
- **Fallback OSM tags** : traduit `shower`→`douches`, `drinking_water`→`eau`, `electricity`→`électricité`, `fuel`→`carburant`, etc. Extrait `vhf_channel`, `capacity`, `max_depth`, `phone`. `score_protection_meteo` et `resume_avis` toujours null (jamais inféré du néant). `enriched: false` si aucun champ tiré des tags.
- **Nouveaux endpoints** : `POST /api/marinas/{id}/enrich` (on-demand, verrou per-id, retourne le doc mis à jour + logs), `POST /api/marinas/enrich-batch` (params `limit`, `priority`, `include_enriched`, `stale_only`, background task, concurrency depuis setting), `GET /api/marinas/enrich-batch/status` (progress, results per-marina, logs_tail), `POST /api/projects/{id}/enrich` (rejoue le pipeline extraction complet — httpx + readability + Gatekeeper + Gemini/emergentintegrations — met à jour title/description/location/category/category_group/image/s_ocean).
- Nouveaux settings : `marina_batch_concurrency` (défaut 2), `openrouter_min_credits_usd` (défaut 0.5), `enrich_stale_days` (défaut 365). Champ `stale` calculable via `is_stale()`.
- `marinas_to_geojson()` étendu — les 7 champs d'enrichissement + `enrichment_source` + `enriched_at` + `stale` exposés dans les properties.

### Preuves d'enrichissement réel — verbatim (2026-08-24) 
- **Port des Minimes (La Rochelle)** → **source: tinyfish**, 5/7 champs remplis : canal_vhf='9' · places_visiteurs=400 · score_protection_meteo=1 · services=['eau','électricité','carburant','douches','wifi','capitainerie','grue'] · telephone_capitainerie='00 33 (0)5 46 44 41 20 (Choix 3)' · tirant_eau_max_metres=null · resume_avis=null. Temps ~70 s.
- **Rodney Bay Marina (Sainte-Lucie)** → **source: tinyfish**, **7/7 champs remplis** : canal_vhf='16' · places_visiteurs=253 · tirant_eau_max_metres=3.9 · score_protection_meteo=4 (★★★★☆) · services=['carburant','douches','wifi','provisionnement','grue (chantier naval)','restaurant','capitainerie'] · telephone_capitainerie='+1 758-458-7200' · resume_avis="Tout le personnel de la réception est formidable, tout comme celui du quai. Nous avons tout apprécié lors de nos différents séjours à la marina." Temps ~110 s.
- **Marina Bas-du-Fort (Guadeloupe)** → **source: tinyfish**, **7/7 champs remplis** : canal_vhf='9' · places_visiteurs=1260 · tirant_eau_max_metres=4.5 · score_protection_meteo=5 (★★★★★) · services=['eau','électricité','carburant','douches','wifi','capitainerie','grue','carénage','restaurant'] · telephone_capitainerie='0590 936 620' · resume_avis="La Marina de Bas-du-Fort est la plus ancienne et la plus importante marina de Guadeloupe, construite en 1977 pour la Route du Rhum. Située dans le Petit Cul-de-Sac Marin, elle offre un emplacement idéal…"
- **Marina Rubicon (Lanzarote)** → tentative TinyFish timeout après 210s → **fallback OpenRouter** (credit-guard PASS, limit=null, usage cumulé $0.0011), 2/7 champs : canal_vhf='9' · places_visiteurs=500 · reste null. Coût $0.00013. Honnête : Readability n'a récupéré que ~500 chars sur cette page JS lourde, le modèle n'a rempli que ce qu'il pouvait justifier.
- **Batch de 5** (concurrency=2, 217s au total) : 5 entrées OSM anonymes (Anse à Rodrigue, Any Way Marine, Aquamania, Aspretto, Atelier SHOM @ ...) sans tag `website` → TinyFish DDG-picked URLs mais pages non exploitables → tous **source: fallback**, 0 champ rempli, **`enriched: false`**. **Pas d'invention** — la chaîne a correctement échoué et signalé le fallback.
- **Projet réel enrichi** — Oceana Marine Conservation (Packard grantee) → titre corrigé de "Oceana Marine Conservation - Mexico and Chile" à "Oceana Grants" (vrai titre de la page), description remplacée par un vrai résumé, `engine=Gemini Extractor` (via EMERGENT_LLM_KEY), 15s.

### Phase 3 frontend
- **Popup marina** enrichi : bloc "◆ ENRICHED via tinyfish/openrouter/fallback" affichant les 7 champs quand non-null (étoiles pour la météo, chips pour les services), tag "stale" si applicable, **bouton "◆ Enrich"** qui appelle `POST /api/marinas/{id}/enrich` avec spinner + re-fetch + réouverture popup automatique.
- **Popup projet** : **bouton "↻ Rafraîchir / Ré-extraire"** appelant `POST /api/projects/{id}/enrich`, à côté du bouton Donate existant. Feedback in-place (✓ Rafraîchi / échec).
- **MarinasPanel** section "Enrich Next Batch" : sélecteur count (5/10/25) + bouton "Enrich all (by priority)". Pendant l'exécution : progress `n/total` + spinner + liste live des 8 derniers résultats avec ✓/✗/· + source + `fields_filled/7`.
- Badge ◆ rouge sur les lignes de marinas déjà enrichies.
- Hooks globaux `window.__biEnrichMarina(id)` et `window.__biEnrichProject(id)` (mêmes patterns que `__biDonate` existant).
- i18n EN/FR complet (~25 nouveaux libellés : `enrichAction`, `enrichSourceTinyfish/OpenRouter/Fallback`, `enrichVHF`, `enrichBerths`, `enrichDraft`, `enrichWeather`, `enrichServices`, `enrichPhone`, `enrichReview`, `enrichBatchTitle`, `enrichBatchStart`, `enrichBatchRunning`, `enrichStale`, `enrichNever`, `projectEnrich`, `projectEnriching`, `projectEnrichDone`, `projectEnrichFailed`, etc.).

### Vérifié end-to-end (2026-08-24)
- Frontend en mode Marinas → 212 marinas listées, 3 avec badge ◆ (les 3 tests TinyFish réussis), Popup Rodney Bay affiche tous les 7 champs enrichis + étoiles + services chips + review verbatim + bouton Enrich rouge.
- Section batch visible avec sélecteur 5/10/25 + bouton "Enrich all (by priority)".
- Aucune régression Phase 1 ni Phase 2 : switch mode, route + escale labels, MPA toggle, EN/FR, clusters projets, categories, donations, import/export intacts.

### Non fait cette phase (backlog Phase 4+)
- Cron scheduler pour rafraîchissement automatique (report produit).
- UI de Settings pour ajuster `marina_batch_concurrency`, `openrouter_min_credits_usd`, `enrich_stale_days` (les paramètres existent en base mais l'écran Settings ne les expose pas encore).
- CRUD manuel des marinas + drawing on map.
- Backup Overpass via extraits Geofabrik PBF (documenté comme alternative future — hors scope tant que openstreetmap.fr suffit).


## Update 2026-08 — Phase 3.1 : Async enrichment + Kimi K2 tier (cost-order chain upgrade)
### Bug fix (user-reported blocker)
- Previous behaviour : `POST /api/marinas/{id}/enrich` et `POST /api/projects/{id}/enrich` étaient **synchrones** — le TinyFish poll budget de 210 s bloquait la requête HTTP jusqu'à ~4 min → 502/504 via l'ingress, incompatible avec les testeurs automatisés (cap 300 s).
- Nouveau contrat : les 2 endpoints renvoient désormais **HTTP 202 `{"status":"started","marina_id":"..."}` en <15 ms**. La chaîne s'exécute en background task (`asyncio.create_task`). Verrou per-id conservé → 409 si un enrichissement est déjà en cours pour ce même id.
- Nouveaux endpoints polling : **`GET /api/marinas/{id}/enrich/status`** et **`GET /api/projects/{id}/enrich/status`** → renvoient `{state: idle|running|done|error, started_at, finished_at, result, error, logs_tail}`. Le `result` contient le doc mis à jour (marina complète ou feature projet) quand `state=done`.
- Registres in-memory `MARINA_ENRICH_TASKS` / `PROJECT_ENRICH_TASKS` (par id) avec purge auto des tâches finies > 1h.
- Frontend `App.js` — nouveaux handlers `__biEnrichMarina` / `__biEnrichProject` : POST 202 puis **poll `/status` toutes les 2,5 s** (max ~180 s), update UI en place (spinner → success/error) sans jamais bloquer une requête HTTP. Sur 409 (déjà en cours), le poller s'attache directement au status endpoint existant.
- Vérifié end-to-end : `time curl POST` = **14 ms**, first status poll montre déjà `state=running` + les 2 premières lignes de logs.

### Chain upgrade (per user decision)
- Ordre coût de la chaîne d'enrichissement devient : **TinyFish → Kimi K2 (Cloudflare Workers AI) → OpenRouter → OSM-tags fallback**.
- Nouveau client Kimi dans `enrichment.py::enrich_via_kimi()` (~150 lignes) — tente `@cf/moonshotai/kimi-k2.6` puis `kimi-k2`, `kimi-instruct-72b`, `kimi-vl-a3b-thinking` (sticky-cache du 1er modèle qui répond). Gestion propre : messages format + `response_format: json_object`, parsage tolérant de `result.response` OU `result.choices[]`, stripping de fences markdown si présents, normalisation via `_normalise_enrichment`.
- **Guards conformes à la spec** :
  - Pas de creds (`CLOUDFLARE_ACCOUNT_ID` ou `CLOUDFLARE_API_TOKEN` absent/vide) → log `"[kimi] skipped (no credentials)"` et retourne None (fall-through immédiat).
  - HTTP 401/403 → log `[kimi] AUTH ERROR HTTP xxx` et fall-through — pas de retry.
  - Code 5035 (restriction free plan) → log `[kimi] unavailable on free plan` et fall-through.
  - HTTP 429 → **un** backoff (Retry-After ou 5s) puis un retry, jamais deux. Sinon fall-through.
  - HTTP 404 → tente le modèle candidat suivant.
- Nouveaux env vars `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` dans `.env`.
- `_run_marina_enrich_one()` accepte désormais un `skip_tinyfish` optionnel (utile pour tester le tier suivant).

### POC Kimi — verdict honnête (2026-08-24)
- Endpoint discovery : `GET /accounts/{id}/ai/models/search?search=kimi` → **HTTP 403** (auth).
- Tous les modèles candidats (`kimi-k2.6`, `kimi-k2`, `kimi-instruct-72b`, `kimi-vl-a3b-thinking`) → **HTTP 401 `code:10000 "Authentication error"`**.
- Vérif indépendante `/user/tokens/verify` → **HTTP 401 `code:1000 "Invalid API Token"`**. `/accounts/{id}` → 403 `code:9109 "Invalid account identifier"`. Les deux credentials fournis sont rejetés par Cloudflare lui-même.
- Le préfixe `cfat_` de la valeur `CLOUDFLARE_API_TOKEN` correspond typiquement à un **Cloudflare Access For Teams / Zero Trust** token — pas à un Cloudflare API Token avec scope Workers AI. Une fois un token régénéré avec la permission `Account: Workers AI: Read`, le client fonctionnera sans changement de code.
- **POC en conditions "TinyFish désactivé"** sur Rodney Bay Marina → chaîne fonctionne exactement comme prévu : `TinyFish: skipped` → `Kimi AUTH ERROR HTTP 401` → **OpenRouter réussit** (credit-guard PASS, gpt-4o-mini, 6000 chars readability, coût $0.000312, retourne canal_vhf='16/74', places_visiteurs=253, 11 services, resume_avis). L'auth-error Kimi ne bloque jamais la chaîne, exactement comme demandé.

### Non-regression
- Phase 1/2 features intactes (mode switch, route + escale labels, MPA toggle, EN/FR, clusters projets, categories, donations, import/export).
- `POST /api/marinas/enrich-batch` continue de marcher (nouvelle chaîne TinyFish → Kimi → OpenRouter appelée par `_run_marina_enrich_one` — Kimi ajoute juste un tier de fallback avant OpenRouter).
- Overpass confirm : `overpass.openstreetmap.fr` reste primary ; `overpass-api.de` et `kumi.systems` restent dans la liste mais déprioritisés (rappel : IP block persistent depuis ce container).

### Backlog
- Régénérer un Cloudflare API Token avec scope Workers AI et re-tester le tier Kimi.
- Settings UI pour ajuster `openrouter_min_credits_usd` / `enrich_stale_days` / `marina_batch_concurrency`.



## 2026-08-24 — P0 Blank/no-data fix on public preview

### Symptom
- App shell rendait bien (header, sidebar) mais **map vide** (0 projet, 0 marina, pas de route, tuiles Carto avortées) depuis le browser externe. Fonctionnait à l'intérieur du pod (localhost).

### Root cause
- `/app/frontend/.env` avait `REACT_APP_BACKEND_URL=http://0.0.0.0:8001` (restauré incorrectement à la relance du job).
- Depuis un browser HTTPS externe :
  1. Mixed Content warning (HTTPS → HTTP).
  2. Chrome **Private Network Access** blocking : *"Permission was denied for this request to access the loopback address space"* → **toutes** les XHR échouent en `net::ERR_FAILED`.
  3. Résultat : `/api/route`, `/api/projects`, `/api/marinas`, `/api/settings`, `/api/funders`, `/api/categories`, `/api/donations/total` = tous KO côté client, tuiles Carto avortées par ricochet.

### Fix (1 ligne)
- `REACT_APP_BACKEND_URL=https://marina-intel.preview.emergentagent.com` puis `sudo supervisorctl restart frontend` → CRA rebuild → bundle contient l'URL publique, plus aucune occurrence de `0.0.0.0:8001`.

### Verification externe (public URL)
- `curl https://marina-intel.preview.emergentagent.com/api/projects` → HTTP 200, FeatureCollection **4 463 features**.
- `curl .../api/marinas` → HTTP 200, FeatureCollection **212 features**.
- `curl .../api/route` → HTTP 200, FeatureCollection **71 features** (Berry-Mappemonde).
- MongoDB `blueintel_db` : projects=4463, marinas=212 — **DB intacte**, pas de wipe, pas de re-import nécessaire.
- Screenshot public URL Projects mode : sidebar "PROJECTS (4463)", légende 9 catégories (MPA 402, Conservation 765, Research 895, Fisheries 361, Policy & Advocacy 490, Pollution 392, Coastal & Habitat 389, Education 301, Other 473), 73 markers/clusters cyan visibles + route Berry.
- Screenshot public URL Marinas mode : "212 MARINAS", markers rouges, filters Priority/Source, liste (Anse à Rodrigue, Any Way Marine, Aquamania, Aspretto, Ateliers SHOM) avec badges P1/ESCALE + source OPENSTREETMAP/SHOM.

### P1 async enrichment — re-vérifié en externe
- `POST /api/marinas/{id}/enrich` → HTTP **202** `{"status":"started","marina_id":"…"}`.
- `GET  /api/marinas/{id}/enrich/status` → HTTP 200 `{state:"running", started_at, logs_tail:["[hh:mm:ss] === attempt 1: TinyFish ==="]}`.
- `POST /api/projects/{id}/enrich` → HTTP **202** `{"status":"started","project_id":"…"}`.
- `GET  /api/projects/{id}/enrich/status` → HTTP 200 `{state:"running", started_at, logs_tail:["Refreshing …"]}`.
- `GET  /api/settings` → `cloudflare_model = @cf/openai/gpt-oss-120b` (configurable, tier Kimi dormant tant qu'un token Workers AI valide n'est pas fourni).

### Lesson learnt (à documenter dans les runbooks fork)
- Après relance d'un job, **toujours** vérifier que `REACT_APP_BACKEND_URL` pointe sur le slug public (`https://<slug>.preview.emergentagent.com`), pas sur `http://0.0.0.0:8001`. Symptôme : shell OK, mais toutes les XHR bloquées par Private Network Access en HTTPS externe (pas de blank screen, juste zéro data).
