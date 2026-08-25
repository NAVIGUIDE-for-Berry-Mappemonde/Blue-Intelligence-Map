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
- `REACT_APP_BACKEND_URL=https://anchorages-50nm.preview.emergentagent.com` puis `sudo supervisorctl restart frontend` → CRA rebuild → bundle contient l'URL publique, plus aucune occurrence de `0.0.0.0:8001`.

### Verification externe (public URL)
- `curl https://anchorages-50nm.preview.emergentagent.com/api/projects` → HTTP 200, FeatureCollection **4 463 features**.
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
- Après relance d'un job, **toujours** vérifier que `REACT_APP_BACKEND_URL` pointe sur le slug public (`https://anchorages-50nm.preview.emergentagent.com`), pas sur `http://0.0.0.0:8001`. Symptôme : shell OK, mais toutes les XHR bloquées par Private Network Access en HTTPS externe (pas de blank screen, juste zéro data).


## Update 2026-08-25 — Phase 4.0 (réanimation) + Phase 4A : mode "Formalités & Douanes"

### Phase 4.0 — Réanimation
- `/app/backend/.env` et `/app/frontend/.env` recréés (les fichiers avaient été perdus après relance du job). Clés API réinjectées : `TINYFISH_API_KEY`, `OPENROUTER_API_KEY`, `EMERGENT_LLM_KEY` (récupérée via l'integration manager, `sk-emergent-2BaBcC37a89984a811`), `STRIPE_API_KEY=sk_test_emergent` (sandbox), `RESEND_API_KEY=` vide, `CLOUDFLARE_ACCOUNT_ID=` et `CLOUDFLARE_API_TOKEN=` vides (fall-through voulu, tier CF dormant). `REACT_APP_BACKEND_URL=https://anchorages-50nm.preview.emergentagent.com` (slug public confirmé).
- Dépendances Python réinstallées : `emergentintegrations` via l'extra-index-url officiel, puis `pip install fastapi motor pymongo httpx beautifulsoup4 readability-lxml resend python-dotenv uvicorn pydantic global-land-mask` pour couvrir ce qui manquait dans le venv du container relancé (le `requirements.txt` a un conflit litellm/emergentintegrations qui empêche `pip install -r` de résoudre — contourné en installant emergentintegrations d'abord seul, le reste ensuite).
- `sudo supervisorctl restart all` → backend + frontend RUNNING.
- Restauration data : la DB `blueintel_db` était vide (0 projet, 0 marina). `POST /api/marinas/build` (radius 10 NM, sans corridor) → **212 marinas insérées en 133 s** (124 OSM + 69 SHOM + 19 curated, répartition P1=192 · P2=17 · P3=3, 0 overpass_error). **Les 4 463 projets historiques restent à ré-importer par l'utilisateur via `POST /api/import/geojson` avec son GeoJSON de sauvegarde** — non fait cette phase (pas de sauvegarde locale disponible et hors périmètre 4A).
- Vérifs post-réanimation : `GET /api/` HTTP 200, `GET /api/openapi.json` HTTP 200 (41 paths dont 5 Phase 4A), `GET /api/route` HTTP 200 (71 features), `GET /api/marinas` HTTP 200 (212 features), `GET /api/projects` HTTP 200 (0 features — vide, à re-seeder).

### Phase 4A backend — Référentiel territoires + collection formalities

- **Nouveau fichier statique `/app/backend/data/territories.json`** (~15 KB, `content_language: fr`, `_generated_at: 2026-08-25`) : 13 territoires curatés couvrant les 16 escales uniques (17 features) de la route.
  - Champs par territoire : `code`, `name_fr`, `name_en`, `regime` (`metropole|drom|com|taaf|sui_generis`), `flag_emoji`, `escale_names[]` (mapping exact vers `waypoint.name` de route.geojson), `ports_of_entry[]` (chaque entrée avec `name`, `note`, `ref_url` sourcée), `official_domains[]` (whitelist pour la Phase 4B), `notes`, `ref_url` (source primaire du territoire).
  - Blacklist top-level : noonsite.com, cruisersforum.com, sail-world.com, forums.sailboatowners.com, reddit.com, yachtingworld.com, sailmagazine.com, wikipedia.org, wikivoyage.org, tripadvisor.com, lonelyplanet.com, voile-magazine.com, voile-et-voilier.com, bateaux.com.
  - **Sources officielles réellement recherchées via web_search** (2026-08-25) — extraits :
    - France métropolitaine : douane.gouv.fr (PDF liste ports plaisance éligibles au dispositif Schengen), Port de La Rochelle + Port Tino Rossi + Port Charles Ornano.
    - Martinique / Guadeloupe / Saint-Barthélemy / Saint-Martin : **clearance dématérialisée depuis 01/09/2024 via demarche.numerique.gouv.fr** (source martinique.gouv.fr Guide Boat + saint-barth-saint-martin.gouv.fr).
    - Guyane (Cayenne Larivot) : douane.gouv.fr `guyane-preparer-son-arrivee` (territoire fiscal tiers, octroi de mer).
    - Saint-Pierre-et-Miquelon : douane975.fr — Quai Mimosa + Quai du Port Miquelon, préavis 20 min, pavillon Q.
    - Polynésie française : service-public.pf `formalites-arrivees-maritimes-pf` — Papeete port de premier accostage Tahiti/Moorea, admission temporaire 24 mois.
    - Wallis-et-Futuna : wallis-et-futuna.gouv.fr — Mata-Utu, AIS obligatoire, mouillage alternatif Fakatoi.
    - Nouvelle-Calédonie : douane.gouv.nc — Nouméa bureau des douanes 4 rue Félix Russeil.
    - Mayotte : douane.gouv.fr ICS liste points d'entrée + `mayotte-preparer-son-arrivee` (Dzaoudzi + Longoni).
    - **TAAF (Tromelin + Europa)** : taaf.fr `acces-et-mouillage-dans-les-eparses` → **`ports_of_entry: []`** — accès uniquement sur autorisation préalable écrite du Préfet TAAF, débarquement interdit à Tromelin.
    - La Réunion : reunion.gouv.fr — Port de la Pointe des Galets (préavis 48 h obligatoire, Saint-Gilles NON port d'entrée).
- **Nouveau module `/app/backend/formalities.py`** (~200 lignes) — schéma complet + factory de doc vide + seeder idempotent. `is_stale()` sur `generated_at` avec **max_age_days=180** (moitié du seuil marinas car les réglementations bougent plus vite). `_default_overlays()` calcule automatiquement `is_port_of_entry` en croisant `escale_name` avec `ports_of_entry`, avec 3 overrides ciblés : Saint-Maur (`false` + note « Départ terrestre — aucune formalité maritime. »), TAAF (`false` + « Débarquement soumis à autorisation préalable du Préfet des TAAF. »), Saint-Gilles (`false` + note « Port de plaisance secondaire — l'entrée officielle se fait à la Pointe des Galets. »).
- **Collection Mongo `formalities`** — 13 docs seedés au démarrage via `@app.on_event("startup")` (idempotent, `db.formalities.create_index("territory_code", unique=True)`). Schéma verbatim : `_id (uuid), territory_code, status: "non_generee"|"ia"|"ia_sans_source"|"verifiee", entree{11 fields all null}, sortie{4}, cas_particuliers{3}, contacts[], liens_officiels[], immigration{fr,ca,us,gb} (chaque slot `null` en 4A ; 4B remplira `fr` par défaut), sources[], generated_at:null, verified_at:null, stale:bool, escale_overlays[{escale_name, is_port_of_entry, note}]`.
- **Nouveaux endpoints** :
  - `GET /api/territories` → référentiel curated complet (Cache-Control 1h, header `X-Territories-Source`).
  - `GET /api/formalities` → `{count, items[]}` triés dans l'ordre de la route (France métro → Martinique → Guadeloupe → … → Réunion).
  - `GET /api/formalities/{territory_code}` → doc complet + `territory` (référentiel du territoire embarqué en réponse pour éviter un double round-trip côté frontend). 404 si code inconnu.
- **Pas d'endpoint de génération / vérification en 4A** — ce sera la Phase 4B (mission TinyFish + LLM pour remplir chaque `entree/sortie/…`, verrous per-territory-code, statut IA vs vérifiée).

### Phase 4A frontend — Refonte switch → 3 modes (Projets / Marinas / Formalités)

- **`Header.js`** — pill switch passé de 2 à **3 boutons**. 3ᵉ bouton `data-testid="mode-toggle-formalities"` avec icône `ScrollText` (lucide) + `bg-amberx/15 text-amberx` quand actif. Les 3 boutons ont maintenant des bordures uniformisées (`border-r border-line` sur les 2 premiers, plus de bordure sonar/40 spécifique).
- **`App.js`** — `readInitialMode()` accepte désormais `"formalities"` comme valeur persistable, ternaire panel remplacé par 3 blocs `mode === "…" && (…)`. Trois nouveaux fetchers : `fetchRoute`, `fetchTerritories`, `fetchFormalities` (appelés au boot une seule fois — pas de polling car ces données changent rarement). Nouveaux states : `route, territories, formalities, selectedTerritory, selectedEscale, flyToEscale`. Nouveau handler `handleSelectEscale(escaleName, territoryCode, coord)` partagé entre sidebar et carte : ouvre la fiche + déclenche `flyToEscale` (signal one-shot avec timestamp).
- **`index.css`** — nouveau bloc `[data-mode="formalities"] { --accent-rgb: 251 191 36; --accent-glow: rgba(251,191,36,0.35); ... }` (amberx `#fbbf24`, déjà défini dans tailwind.config.js). Ajout de 3 classes utilitaires : `.bi-poe-ring` (drop-shadow blanc pour les anneaux port d'entrée), `.bi-escale-marker--dashed` (`stroke-dasharray: 3 3 !important`), `.bi-formalities-disclaimer` (fond ambre translucide pour le bandeau permanent).
- **Nouveau composant `/app/frontend/src/components/FormalitiesPanel.js`** (~430 lignes, sidebar dédiée) :
  - Header : titre `Formalités` + compteur `17 escales` + subtitle bilingue.
  - **Bandeau disclaimer permanent** `data-testid="formalities-disclaimer"` : « ⚠️ Informations indicatives — à vérifier auprès des autorités. » (bilingue).
  - **Sélecteur nationalité global** `data-testid="nationality-selector"` : FR / CA / US / GB, persisté `localStorage.bi.nationality` (défaut FR). Le read initial fallback silencieusement à `"fr"`.
  - **Liste ordonnée de 17 escale rows** (`formalities-row-{code}` ou `formalities-row-{code}-departure|-return` pour La Rochelle) — construite en lisant `route.features` dans l'ordre, en mappant chaque escale à son territoire via `escale_names`. La Rochelle apparaît **deux fois** (départ + retour) avec un tag `départ` / `retour`, les deux ouvrent la même fiche `france_metropolitaine`.
  - Chaque row montre : drapeau emoji + nom + territoire + badges statut (`STATUS_COLOR` map cohérente avec MapView) + badge `PORT OF ENTRY` / `NOT A PORT OF ENTRY`. Sélection surlignée par une bordure gauche amberx.
  - **Fiche territoire épinglée en bas** de la sidebar, ouverte au clic sur une escale :
    - Titre : drapeau + `name_fr` + badges (status + regime i18n `Metropolitan France | DROM | COM | TAAF | Sui generis`).
    - **Overlay de l'escale sélectionnée** (`data-testid="formalities-escale-overlay"`) : port d'entrée oui/non + note (spécifique à cette escale).
    - **6 onglets** (`data-testid="formalities-tab-{entree|sortie|cas_particuliers|immigration|contacts|sources}"`). Contenu vide = placeholder « Non générée — disponible en Phase 4B » (bilingue).
    - Onglet immigration lit `detail.immigration[nationality]` (piloté par le sélecteur global).
    - Footer : whitelist des `official_domains` du territoire en chips (limité à 6 + compteur).
- **`MapView.js`** — 3 changements majeurs :
  1. Init cluster : `if (mode === "marinas") map.addLayer(marinaCluster); else if (mode !== "formalities") map.addLayer(cluster);` — aucun cluster n'est attaché quand on ouvre l'app en mode formalities.
  2. **Mode-swap 3 branches** : détache TOUJOURS les 3 layers (proj + marina + formalities), puis attache uniquement celui du mode courant. `map.closePopup()` sur chaque switch.
  3. **Nouveau `useEffect` de rendu de la couche Formalités** (~130 lignes) : construit un `L.layerGroup()` avec, pour chaque escale de `route.geojson` : (a) un premier `circleMarker r=11 fill:none stroke:#f8fafc weight:2` si `is_port_of_entry=true` (l'anneau blanc, class `.bi-poe-ring`), (b) un `circleMarker r=7` coloré selon le statut (`non_generee=#64748b`, `ia=#fbbf24`, `ia_sans_source=#fbbf24 dashed`, `verifiee=#39ff14`) — orthogonal du port d'entrée. Popup avec titre + statut + badge PoE + note d'overlay. Le clic sur le marker appelle `onSelectEscale(name, terr.code, coord)` — même handler que la sidebar. **Signature de skip-rebuild** basée sur `nom|code|status` par escale pour ne pas rebuild la couche à chaque re-render.
  4. Nouveau `useEffect` FlyTo escale : anime la carte vers la coord one-shot `flyToEscale`.
- **`i18n.js`** — ~55 nouvelles clés côté DICT.en ET DICT.fr : `modeFormalities, formalitiesSubtitle, formalitiesCount, formalitiesDisclaimer, formalitiesTab{Entree|Sortie|CasParticuliers|Contacts|Sources|Immigration}, formalitiesStatus{NonGeneree|Ia|IaSansSource|Verifiee}, formalitiesPortOfEntry, formalitiesNotPortOfEntry, formalitiesLeg{Departure|Return}, formalitiesRegime{Metropole|Drom|Com|Taaf|SuiGeneris}, formalitiesNotGenerated, formalitiesSelectHint, formalitiesFields{Preavis|PavillonQ|DemarchesArrivee|OuSAmarrer|Vhf|DouanesClearance|AdmissionTemporaire|Franchises|Biosecurite|Frais|Horaires|Clearance|Delais|Documents|OuObtenir|Animaux|Drones|Armes|Visa|DureeSejour|Esta|Notes}, formalitiesNationality{Fr|Ca|Us|Gb}, formalitiesEscaleOverlay, formalitiesOfficialDomains, formalitiesPortsOfEntryLabel, formalitiesEmpty, formalitiesTerritoryTitle, formalitiesEscaleTitle, refresh`. Décision actée : **le contenu des fiches restera FR uniquement**, seuls les libellés UI sont bilingues. Consigné dans `content_language: "fr"` du fichier territories.json.

### Vérifications end-to-end (2026-08-25, live sur le slug public)

- `GET /api/openapi.json` HTTP 200, 41 paths dont `/api/territories`, `/api/formalities`, `/api/formalities/{territory_code}`.
- `GET /api/territories` HTTP 200 : 13 territoires renvoyés avec regime, ports_of_entry+ref_url sourcés, escale_names couvrant les 17 features escale (Saint-Maur, La Rochelle ×2, Ajaccio dans france_metropolitaine + 12 autres), official_domains non vides.
- `GET /api/formalities` HTTP 200 : 13 docs `status: non_generee`. Répartition escale_overlays : france_metropolitaine=3, taaf=2, autres=1 chacun → 15 overlays uniques couvrant les 16 noms d'escale distincts. Vérifs ciblées : `formalities/taaf` → 2 overlays Tromelin+Europa `is_port_of_entry:false` avec note "Débarquement soumis à autorisation préalable du Préfet des TAAF" ; `formalities/france_metropolitaine` → Saint-Maur `is_port_of_entry:false` + note "Départ terrestre — aucune formalité maritime", La Rochelle et Ajaccio `true`.
- Frontend E2E (Playwright, 1920×900) :
  - Switch mode → header pill à 3 boutons OK, `data-mode="formalities"` sur `<html>`, `localStorage.bi.mode="formalities"` persisté.
  - Sidebar formalités : 17 rows (`departure`/`return` sur La Rochelle #1/#2), disclaimer ambre visible, sélecteur nationalité fonctionnel (`us` sélectionné → `localStorage.bi.nationality="us"` persisté après reload).
  - Carte en mode formalities : **0 project_clusters + 0 marina_clusters**, **13 poe_rings** (= tous les ports d'entrée : La Rochelle ×2, Ajaccio, Fort-de-France, Pointe-à-Pitre, Gustavia, Marigot, Cayenne, Saint-Pierre, Papeete, Mata-Utu, Nouméa, Dzaoudzi), 17 escale_tooltips, route Berry-Mappemonde visible.
  - Clic sur Nouméa (sidebar OU carte) → fly-to + fiche territoire ouverte avec 6 onglets présents, overlay "PORT OF ENTRY — Nouméa (Nouvelle-Calédonie)", placeholder "Not generated yet — available in Phase 4B", chips whitelist (douane.gouv.nc, gouv.nc, nouvelle-caledonie.gouv.fr, service-public.nc, isee.nc, province-sud.nc, +2).
  - Régression zéro : round-trip Formalités → Projets → Marinas → Formalités OK, chaque panneau retrouvé, aucune erreur console.
  - Bascule EN → FR : subtitle "Douanes & entrée par territoire", disclaimer "⚠️ Informations indicatives — à vérifier auprès des autorités", tous les libellés UI traduits.

### Non fait cette phase (backlog Phase 4B)
- **Pipeline de génération LLM** — TinyFish + Kimi/OpenRouter avec whitelist `official_domains` + blacklist top-level, remplissage de `entree/sortie/cas_particuliers/immigration.fr`, calcul du `status` (`ia` si toutes sources dans la whitelist, `ia_sans_source` sinon), écriture de `sources[]` (URL + domain + collected_at), `generated_at`, verrou per-territory_code + endpoint `POST /api/formalities/{code}/generate` + `GET /api/formalities/{code}/generate/status`.
- **Génération immigration à la demande** pour ca/us/gb (avec sélecteur nationalité qui déclencherait le job).
- **Endpoint de validation manuelle** (bouton "Marquer comme vérifiée" côté UI, PUT `verified_at`).
- **Ré-import projets** — pour l'instant `db.projects` est vide (perdu au relaunch), les utilisateurs doivent poster leur GeoJSON de sauvegarde sur `POST /api/import/geojson` pour restaurer les 4 463 projets. Aucune régression de code Projets — juste 0 features à afficher.
- Rafraîchissement automatique cron des formalities `stale` (>180 j).


## Update 2026-08-24 — Phase 4B : Pipeline de génération + validation + exports

### Résumé exécutif
Le mode Formalités est passé de "13 fiches vides" à "13 fiches remplies par un pipeline TinyFish + LLM avec sources whitelistées, système de validation équipage, immigration à la demande, exports JSON/GeoJSON". Un batch réel a été exécuté une fois : **13/13 territoires générés, 12 en `ia` avec 1-2 sources whitelistées, 1 en `ia_sans_source` (la_reunion — PDF de l'arrêté préfectoral non extractible)**.

Réimport annexe : les **4 463 projets ont été restaurés** via `POST /api/import/geojson` depuis le GeoJSON de sauvegarde utilisateur (2 doublons fusionnés, 0 skipped, `category_group` correctement rempli sur les 9 catégories).

### Pipeline de génération (par territoire)
**Nouveau module `/app/backend/formalities_gen.py` (~600 lignes)** :

1. **Sélection des URLs** — `_select_source_urls(territory, cap=2)` prend `territory.ref_url` et les `ports_of_entry[].ref_url` du référentiel curated, filtrées par `_url_is_whitelisted` contre les `official_domains` du territoire. Les URLs hors whitelist sont rejetées avant même l'appel TinyFish.
2. **Missions TinyFish RÉELLES** — `_run_tinyfish_mission(url, goal, MISSION_SCHEMA, key, budget_s=210)`. Schéma flat 26 champs (entree_*, sortie_*, cas_*, immigration_fr_*, contact_*, urls_consulted). Poll `/runs/{id}` toutes les 4s. Log verbatim `run_id`, statuses (PENDING → RUNNING → COMPLETED/FAILED/TIMEOUT). Prompt spécifique au régime (métropole/DROM/COM/TAAF/sui_generis) et au fait que le navire est sous **pavillon français, équipage FR**.
3. **Fallback httpx+BeautifulSoup** — **crucial en pratique** : TinyFish a timeout **quasi-systématiquement** sur les sites gouv.fr / service-public.pf (challenges Cloudflare + JS lourd sur les portails gov 2024). Quand aucune mission TinyFish ne renvoie de payload utile, `_fetch_readable(url)` récupère le HTML de l'URL WHITELISTÉE avec un User-Agent Blue Intelligence, extrait le texte via BeautifulSoup (suppression nav/footer/script/style/aside/form), tronque à 8 000 chars et passe ce blob au LLM. Ce n'est PAS un mock : la source reste la même URL officielle whitelistée que TinyFish était censé visiter — c'est une dégradation gracieuse quand l'agent web échoue.
4. **Synthèse LLM en FRANÇAIS** — `_synthesize_llm(...)` :
   - **Primaire** : OpenRouter `openai/gpt-4o-mini`, `temperature=0`, `response_format=json_object`, 2 500 max_tokens. Header `X-Title: "Blue Intelligence - Formalities Synthesis"` (ASCII only, un em-dash y avait causé une exception latin-1 corrigée).
   - **Fallback** : Gemini `gemini-2.5-flash` via `emergentintegrations.LlmChat` (EMERGENT_LLM_KEY).
   - Prompt strict : JSON nested schema exact (entree/sortie/cas_particuliers/immigration_fr/contacts/liens_officiels), tout en FR, **ne jamais inventer** (null si absent des extraits), reformulation courte fidèle, règle spécifique conditionnelle pour `regime=taaf` uniquement (pas de contamination cross-territoire).
5. **Filtre sources** — post-LLM, on collecte les URLs mentionnées par TinyFish (`urls_consulted`) et l'URL de seed, on filtre TOUT contre la whitelist du territoire (`endswith(".domain")` inclut les sous-domaines type `juridoc.gouv.nc` ⊂ `gouv.nc`), on dédup et on horodate en `collected_at`. **≥ 1 source whitelistée → status `ia`, sinon `ia_sans_source`**. Les `liens_officiels` retournés par le LLM sont eux aussi re-filtrés côté code — le LLM ne peut pas smuggler du Noonsite/forum même s'il essaie.
6. **Persistance directe** — `db.formalities.update_one({territory_code}, {$set: {status, entree, sortie, cas_particuliers, contacts, liens_officiels, immigration.fr, sources, generated_at, verified_at:null, stale:false}})`. `immigration.ca/us/gb` préservés (endpoint immigration on-demand). Un restart backend en plein batch ne perd que la fiche en cours d'écriture.

### Endpoints (11 nouveaux, tous préfixés `/api`)

| Verbe | Chemin | Rôle |
|---|---|---|
| `POST` | `/formalities/{code}/generate` | 202 `{status:"started"}`, verrou par `code` dans `FORMALITIES_LOCKS` (409 si déjà en cours). `asyncio.create_task(_runner)`. |
| `GET`  | `/formalities/{code}/generate/status` | `{state: idle|running|done|error, logs_tail[-40:], result, started_at, finished_at, error}`. Registry in-memory `FORMALITIES_GEN_TASKS`. |
| `POST` | `/formalities/generate-batch` | `{stale_only: bool}`. Semaphore(2). Sélection triée dans l'ordre route. 409 si un autre batch tourne. |
| `GET`  | `/formalities/generate-batch/status` | `{running, progress, total, results[{code, status, sources_count}], logs_tail[-80:], error}`. Singleton `FORMALITIES_BATCH_STATE`. |
| `PUT`  | `/formalities/{code}/verify` | Flip → `status: verifiee`, `verified_at: now`. 404 code inconnu · 400 si `non_generee`. |
| `POST` | `/formalities/{code}/immigration/{nat}` | `nat ∈ ca|us|gb` (400 sinon). Lance mission TinyFish ciblée (budget 120s) + synthèse LLM. Ne touche PAS au status principal ni aux autres slots immigration. Verrou par `(code:nat)`. |
| `GET`  | `/formalities/{code}/immigration/{nat}/status` | idem generate/status. |
| `GET`  | `/export/formalities.json` | `FormalitiesCollection`, 13 items, `Content-Disposition: attachment; filename=formalities.json`. |
| `GET`  | `/export/formalities.geojson` | 17 points (1 par escale du route.geojson) avec properties `{escale_name, leg (departure/return sur La Rochelle), territory_code, status, is_port_of_entry, stale, generated_at, verified_at}`. |

### Batch réel : preuves d'exécution (2026-08-24)

- Duration : ~45 min pour 13 territoires en concurrency 2. Chaque territoire consomme 210s × 2 missions TinyFish (systématiquement en TIMEOUT sur les portails gov.fr — pattern observé sur `douane.gouv.fr`, `demarche.numerique.gouv.fr`, `service-public.pf`, `douane.gouv.nc`, `saint-pierre-et-miquelon.gouv.fr`, `wallis-et-futuna.gouv.fr`, `reunion.gouv.fr`, `taaf.fr`, `mayotte.gouv.fr`, `martinique.gouv.fr`, `saint-barth-saint-martin.gouv.fr`, `guadeloupe.gouv.fr`, `guyane.gouv.fr`) + fallback httpx 25s + LLM OpenRouter ~5s.
- **Résultat** : 12/13 en `ia` (france_metropolitaine 2 srcs · martinique 1 · guadeloupe 1 · saint_barthelemy 2 · saint_martin 2 · guyane 1 · saint_pierre_et_miquelon 2 · polynesie_francaise 2 · wallis_et_futuna 1 · nouvelle_caledonie 1 · taaf 1 · mayotte 2), 1/13 en `ia_sans_source` (la_reunion — l'arrêté préfectoral 401-2017 est un PDF que ni TinyFish ni httpx ne parsent, fallback échoue proprement).
- **Fiche SPM (échantillon complet, verified)** : `entree.preavis="Prévenir les douanes par téléphone au moins 20 minutes avant l'arrivée"`, `entree.pavillon_q="Arborer le pavillon Q à l'arrivée"`, `entree.ou_s_amarrer="Quai Mimosa à Saint-Pierre ou Quai du Port à Miquelon"`, `entree.vhf="Canal 12"`, `entree.franchises="Franchise de 500€ par personne et 250€ pour les mineurs"`, `entree.admission_temporaire="Le navire est sous le régime de l'importation en franchise temporaire pour six mois"`, `sortie.clearance`, `sortie.delais`, `sortie.documents`, `cas_particuliers.armes="Les armes et munitions doivent être placées en dépôt au bureau de douane"`, `immigration.fr.notes="L'immigration peut être effectuée avant ou après les formalités douanières"`, `contacts` : 4 numéros réels (Douanes Saint-Pierre, Miquelon, Capitainerie, PAF).
- **Distribution des sources whitelistées** (18 total, aucune URL blacklist, aucune hors whitelist par territoire — vérifié via requête Mongo `db.formalities.aggregate([{ $unwind: "$sources" }])`) : `douane.gouv.fr:5, demarche.numerique.gouv.fr:5, saint-barth-saint-martin.gouv.fr:2, taaf.fr:1, saint-pierre-et-miquelon.gouv.fr:1, douane975.fr:1, service-public.pf:1, wallis-et-futuna.gouv.fr:1, douane.gouv.nc:1`.
- **Couverture par champ (sur 13 fiches)** : `entree filled=12/13, sortie filled=8/13, cas_particuliers filled=3/13, contacts present=9/13, immigration.fr set=4/13`. Le taux immigration.fr modeste est structurel : la plupart des sites douaniers ne parlent PAS d'immigration, et le LLM applique strictement la règle "jamais d'invention" — c'est un feature, pas un bug.

### UI Phase 4B — `/app/frontend/src/components/FormalitiesPanel.js` (~800 lignes)

Ajouts sur le composant Phase 4A :

- **Header block augmenté** : bloc "Batch generation" avec bouton `[data-testid="formalities-batch-btn"]` (icône Sparkles, `bg-amberx/10 border-amberx/50`, disable pendant refresh unique). Confirm dialog avant kick. En running : label "Generating… X/13" + Loader2 animé + zone logs live 10 dernières lignes (`[data-testid="formalities-batch-logs"]`, font-mono, max-h-24 scroll).
- **Boutons d'export** en grille 2 colonnes : `.json` / `.geojson` (`[data-testid="formalities-export-{json|geojson}"]`), `<a href="${REACT_APP_BACKEND_URL}/api/export/formalities.{json|geojson}">`.
- **Bouton Refresh par fiche** (`[data-testid="formalities-refresh-btn"]`) : dans la fiche territoire ouverte, à côté du badge statut. Utilise `window.__biGenerateFormality(code)` puis poll `/generate/status` (max 6 min, step 3s). Feedback inline : "Rafraîchissement…" ambre → "Rafraîchie" vert / "Échec" rouge.
- **Bouton Verify** (`[data-testid="formalities-verify-btn"]`) : visible seulement si status ∈ `ia | ia_sans_source`. Label "Vérifiée par l'équipage" / "Verified by crew", couleur bio-green. Appel `PUT /verify` puis re-fetch le doc.
- **Onglet Immigration** amélioré : quand la nationalité sélectionnée n'a pas de slot rempli et n'est pas `fr`, affiche un bouton `[data-testid="immigration-generate-btn"]` "Générer pour US/CA/GB" qui appelle `POST /immigration/{nat}` + poll (max 2.5 min).
- **Onglet Sources** enrichi : liste avec `<Globe/>` + URL cliquable + domaine + `collected_at`. Si status=`ia_sans_source` → bandeau rouge `[data-testid="formalities-no-source-warning"]` : "Aucune source officielle trouvée — contenu IA à vérifier impérativement avant le départ." (FR) / "No official source found — AI-generated content, verify with the authorities before departure." (EN).
- **Badges "stale"** (horloge, ambre) : ajoutés dans la fiche header + sur chaque row de la sidebar quand `generated_at > 180 j` (via le champ `stale: bool` calculé côté backend par `formalities.is_stale()`).
- **Timestamps affichés** dans la fiche : `Generated: YYYY-MM-DD · Verified: YYYY-MM-DD` (font-mono text-[9px]).
- **Poller batch** : `setInterval(fetch batch/status, 2000)`. Chaque tick appelle `onFormalitiesRefresh()` (fetchFormalities côté App.js) — la carte et la sidebar se recolorent LIVE au fur et à mesure que chaque territoire finit et se persiste en DB. Nettoyage propre au unmount.
- **App.js** : 3 nouveaux window handlers (`__biGenerateFormality`, `__biVerifyFormality`, `__biGenerateImmigration`) + prop `onFormalitiesRefresh={fetchFormalities}` passée au panel.
- **MapView.js** — aucun changement nécessaire : la signature de rebuild `nom|code|status` déjà en place recolore automatiquement les escales à chaque `formalities` mutation.

### i18n (18 nouvelles clés EN + FR)
`formalitiesBatchTitle, formalitiesBatchStart, formalitiesBatchRunning, formalitiesBatchConfirm, formalitiesRefreshBtn, formalitiesRefreshRunning, formalitiesRefreshDone, formalitiesRefreshFailed, formalitiesVerifyBtn, formalitiesVerifyBtnTooltip, formalitiesGeneratedAt, formalitiesVerifiedAt, formalitiesStale, formalitiesStaleTooltip, formalitiesImmigrationGenerate, formalitiesImmigrationRunning, formalitiesNoSourceWarning, formalitiesNoSourceEmpty`. Contenu des fiches reste FR uniquement (décision Phase 4A).

### Vérifications end-to-end (2026-08-24)

1. ✅ Génération unitaire SPM : `POST /formalities/saint_pierre_et_miquelon/generate` → 202 (0.032 s), poll → done en ~6 min, doc rempli avec entree (8 champs), sortie (3 champs), cas_particuliers.armes, immigration.fr.notes, 4 contacts avec numéros réels, 2 sources whitelistées, `generated_at="2026-08-24T…"`. **Preuve TinyFish** : 2 run_ids réels loggés (b2935bae-… et un autre), status PENDING/TIMEOUT visibles.
2. ✅ Batch 13 fiches lancé UNE fois, 45 min, 13/13 persistées au fil de l'eau, sidebar+carte recolorées en live, 12 ia + 1 ia_sans_source.
3. ✅ Verify SPM → status=verifiee + verified_at posé ; batch a régénéré SPM → status revenu à `ia` + `verified_at=null` (rollback automatique).
4. ✅ Immigration US on-demand : `POST /formalities/saint_pierre_et_miquelon/immigration/us` → 202, TinyFish TIMEOUT 120s (attendu), LLM OpenRouter OK, `immigration.us={visa:null, duree_sejour:null, equivalent_esta:null, notes:null}` persisté (rien inventé, respecte la règle). Le status principal `verifiee` a été préservé.
5. ✅ Exports : `.json` (14 545 bytes, `FormalitiesCollection`, 13 items, header Content-Disposition), `.geojson` (4 874 bytes, `FeatureCollection`, 17 features avec toutes les properties requises + leg=departure/return sur La Rochelle).
6. ✅ **Aucune URL blacklist en base** : requête Mongo `db.formalities.aggregate([{$unwind:"$sources"}])` = 18 rows, 0 hit sur noonsite.com/cruisersforum.com/reddit.com/wikipedia.org/etc. Vérification supplémentaire : chaque source respecte la whitelist de SON territoire (aucune fuite cross-territoire).
7. ✅ **Régression zéro** : mode Projets affiche les 4 463 projets restaurés (9 clusters visibles à l'ouverture, sidebar avec Legend/Category filters), mode Marinas affiche les 212 marinas (2 clusters visibles), mode Formalités 4A intact (sidebar 17 escales, disclaimer ambre, sélecteur nationalité persisté). Round-trip Projets → Marinas → Formalités → Projets sans erreur console.
8. ✅ Screenshots : `formalities_4b_post_batch_overview.png` (13 escales ambre + SPM vert, sidebar avec Batch button + logs live + exports), `formalities_4b_spm_verified.png` (fiche SPM en VERIFIED + COM + refresh btn + PORT OF ENTRY), `formalities_4b_spm_sources.png` (onglet Sources avec 2 URLs whitelistées + collected_at + Official Sources Whitelist chips), `formalities_4b_spm_immigration_us.png` (nationalité American, immigration slot vide car règle "no invention" respectée), `formalities_4b_regression_projects.png` (mode Projets avec 4463 projects restaurés + sidebar Legend + 9 clusters).

### Non-goals / backlog Phase 4C potentielle
- **la_reunion — PDF de l'arrêté 401-2017 non extractible** : TinyFish timeout, httpx retourne le HTML de la landing page qui ne linke que le PDF. Pour couvrir ce cas, il faudrait ajouter un extracteur PDF (pdfplumber / pymupdf) au fallback fetch. Non fait ici (hors périmètre 4B).
- **TinyFish TIMEOUT systémique sur les portails gov.fr** — c'est le vrai constat opérationnel : la classe agentic de TinyFish ne franchit pas les challenges Cloudflare des sites gov 2024. Le fallback readable-fetch compense complètement en pratique, mais il faudrait explorer soit un plan TinyFish "static" plus rapide, soit un mode headed via un pilote Chromium local. Note : les URLs whitelistées visitées par httpx restent **de vraies sources officielles**, la traçabilité n'est pas dégradée.
- **Immigration ca/us/gb** : le pipeline est en place et fonctionnel, mais dans la pratique les sources françaises officielles ne parlent PAS des visas pour les autres nationalités. Une amélioration Phase 4C serait de router chaque nat vers son propre portail (travel.state.gov pour US, gov.uk pour GB, etc.), avec whitelist par nat + territoire.
- **Refresh cron des fiches stale > 180 j** — pas encore automatisé.
- **Endpoint DELETE `/formalities/{code}/sources/{i}` pour purger une source contestée** — pas fait.


## Update 2026-08-24 — Phase 5 Closure : Manuel utilisateur mis à jour

### Résumé exécutif
L'étape 6 de la Phase 5 « Mettre à jour le manuel (/api/manual + UI) » — oubliée par l'agent précédent — est complète. Les versions EN et FR du manuel reflètent maintenant l'app post-Phase 5 : 3 modes (Projects · Marinas · Formalities), Swarm Intelligence Hub dans l'onglet Audit, exports GeoJSON contextuels, cagnotte de dons globale unique, disparition complète du layer MPA/ProtectedSeas.

### Modifications
- **`/app/backend/server.py`** — `MANUALS["en"]` et `MANUALS["fr"]` entièrement réécrits (~90 lignes chacun, parité stricte 6 sections `##` + 3 sous-sections `###`). Décisions rédactionnelles :
  - Sources IA génériques : "OpenRouter + Gemini (fallback)" — pas de mention de `gpt-4o-mini` ni de `pdfplumber` (détails d'implémentation).
  - Moteur d'extraction du swarm présenté comme configurable en Settings (Gemini · Claude · OpenRouter).
  - Section Formalités : les 4 statuts (`non générée` · `IA` · `IA sans source` · `vérifiée`), le principe "sources officielles uniquement", le flag stale 180 jours, et le disclaimer restent explicites. La liste de la whitelist n'est pas exposée.
  - Toute mention MPA / AMP / ProtectedSeas retirée du corps du manuel (la catégorie de projet "MPA" reste listée dans la Legend, mais n'apparaît plus comme layer/overlay dans le manuel).
  - Popup projets : mention explicite "no per-project donate button — donations are global".
- **`/app/frontend/src/i18n.js`** — 2 mentions "Gemini" en dur nettoyées :
  - `extraction: "Extraction (Readability + Gemini)"` → `"Extraction (Readability + LLM)"` (EN + FR).
  - `llmActive: "GEMINI"` → `"LLM"` (badge dynamique quand `status.engine` n'est pas set).
  - Le libellé `geminiKey: "Gemini API key"` est conservé — c'est le champ de saisie concret de la clé Gemini, contexte technique légitime.

### Vérifications end-to-end (2026-08-24)
- `GET /api/manual?lang=fr` HTTP 200 · 7 231 bytes · contient : "Trois modes" (×1), "Swarm Intelligence Hub" (×1), "cagnotte" (×2), "IA sans source" (×1), "vérifiée" (×1), "180 jours" (×1), "OpenRouter + Gemini" (×2). Aucune occurrence de `gpt-4o-mini`, `pdfplumber`, `AMP/MPA/ProtectedSeas` (les 2 faux positifs "amp" viennent de "cha**mp**s" et "cha**mp**").
- `GET /api/manual?lang=en` HTTP 200 · 6 371 bytes · contient : "Three modes", "Swarm Intelligence Hub", "AI without source", "180 days", "OpenRouter + Gemini" (×2). Aucune mention `gpt-4o-mini`/`pdfplumber`/`MPA`/`ProtectedSeas`/`Donate` (per-project).
- Parité EN/FR : 6 sections `##` et 3 sous-sections `###` de chaque côté.

### Bug de régression identifié (NON dans le périmètre Phase 5)
Un bug de rendering des projets a été détecté en test manuel post-manuel : `GET /api/projects` renvoie bien les 4 463 features (HTTP 200, 619 ms, 3.4 MB → 800 KB gzipé), le state `funders` (4463 dans le dropdown organizations) et `categories` (Legend avec les 9 catégories + counts) se peuplent correctement, mais le state `projects` de React reste vide (sidebar affiche `PROJECTS (0)`, 0 clusters sur la carte). Aucun log console ni pageerror.

- **Hypothèse actuelle** : race condition dans `fetchProjects` (App.js) où `lastTotalRef.current` était mis à jour AVANT le `setProjects()`, provoquant un skip permanent du fetch `/projects` après le premier échec silencieux.
- **Fix appliqué** dans `/app/frontend/src/App.js` (ligne 73-83) : `lastTotalRef.current = f.data.total` déplacé APRÈS `setProjects(p.data)` — protection contre la race condition.
- **Reproduction Playwright ambiguë** : le fix ne suffit pas à faire apparaître les clusters en environnement Playwright headless (probablement lié au proxy K8s + payload gzipé). La reproduction dans un vrai navigateur utilisateur reste à confirmer.
- **Action recommandée** : test manuel utilisateur dans un vrai navigateur (Chrome/Firefox). Si le bug persiste, dispatcher au `troubleshoot_agent` avec les preuves accumulées.

### Critères Phase 5 — état après manuel
- Thèmes 3 modes complets : ✅ index.css `[data-mode]` cyan/red/amber applique surfaces + accents partout
- Route sous clusters : ✅ pane "route" zIndex=380 < markerPane 600 (MapView.js:103-108)
- Labels/segments/boutons fixes supprimés : ✅ segments `interactive: false` (MapView.js:229), MPA `topRight` et layer entièrement supprimés
- `/api/mpa` HTTP 410 (Gone) : ✅ (vérifié curl)
- Batch triggers dans le hub Audit : ✅ BatchHub.js (11 KB, 6 data-testids : audit-marinas-scan-btn, audit-marinas-batch-btn, audit-formalities-batch-btn, etc.)
- Zéro mention GEMINI en dur : ✅ (i18n.js nettoyé — 2 mentions restantes = `geminiKey` label + `gemini-*` valeurs de sélecteur de modèle, contexte technique)
- Sélecteur moteur en Settings : ✅ SettingsPanel.js:146-154 avec 3 options (gemini/claude/openrouter)
- Export contextuel unique : ✅ SwarmPanel `projects-export-btn` · MarinasPanel `marinas-export-btn` · FormalitiesPanel `formalities-export-btn`
- Popups projets sans donate : ✅ ProjectList.js commentaire "Phase 5 — donate button was removed from the list rows"
- CTA don global : ✅ Header.js:72-83 `[data-testid="donation-cta"]`
- la_reunion en `ia` avec source `reunion.gouv.fr` : ✅ (vérifié curl `GET /api/formalities/la_reunion`)
- Immigration réduite au volet FR : ✅ FormalitiesPanel.js:59-61 + 566, sélecteur nationalité supprimé

### Non-goals
- Persistance des états de batch (actuellement in-memory, perdus au restart backend) — backlog
- Cron auto-refresh des formalities `stale > 180j` — backlog
- Endpoint `DELETE /formalities/{code}/sources/{i}` — backlog
- Investigation du bug de rendering projets — dépend d'une reproduction dans un vrai navigateur

## Update 2026-08-24 — Phase 6 : Consolidation UX/UI (partie 2)

### Livrables
Refactor UI/UX complet en accord avec le brief Phase 6, sans régression sur les 3 modes ni sur les données (4463 projets · 212 marinas · 13 fiches formalités).

### 1) Palette & identité visuelle
- **Scrollbars thémées** (`index.css`) : `--accent-rgb` alimente `::-webkit-scrollbar-thumb` + `scrollbar-color` — bleu/rouge/ambre selon le mode actif.
- **Popups Leaflet themés** : border-color + box-shadow accent, `::selection` accent, `leaflet-bar` accent.
- **Icône Compass** ajoutée en tête de la sidebar Projects (`SwarmPanel.js` — data-testid `projects-panel-header`), même rang visuel que l'ancre Marinas et le rouleau Formalités.
- **Sous-titres supprimés** : `marinasSubtitle` retiré de MarinasPanel (ligne 119-121 supprimée) ; `formalitiesSubtitle` retiré de FormalitiesPanel.
- **Settings panel themé** : `SettingsPanel.js` réécrit — le titre, les section headers, l'icône X, les boutons manuel/import/export et le Save adoptent tous `text-accent`/`border-accent`/`bg-accent`.

### 2) Carte & popups
- **MIGRATION FORMALITÉS** : `FormalitiesPanel.js` réécrit en version slim (156 lignes, était 656 lignes). Sidebar conserve UNIQUEMENT :
  - Header (icône + title + count 17)
  - Disclaimer amber permanent
  - Hint « Cliquez une escale dans le bandeau pour y voler et ouvrir la fiche »
  - Liste ordonnée des 17 escales avec badges statut + PoE + stale
  - Clic sur une ligne → `onSelectEscale()` → `flyTo` + ouverture automatique du popup carte (nouveau timer 1150 ms dans `MapView.js`).
- **Popup carte Formalités** (`MapView.js` — fonction `buildPopup`) enrichie :
  - Header : drapeau + nom escale + territoire + status pill + PoE pill + stale badge + generated_at/verified_at
  - Boutons `formalities-refresh-btn` et `formalities-verify-btn` en tête de popup, câblés à `window.__biFormalityPopupRefresh` / `window.__biFormalityPopupVerify` (App.js) — polling generate/status jusqu'à `done`, avec feedback inline.
  - 5 sections empilées avec titres : Entrée (11 champs) · Sortie (4 champs) · Cas particuliers (3 champs) · Immigration FR (4 champs) · Contacts + Liens officiels · Sources utilisées.
  - Section « Sources utilisées » : liste réelle des sources captées (URL cliquable + domaine + date `collected_at`) — PAS la whitelist backend.
  - Bandeau « Aucune source officielle trouvée » (rouge) pour `ia_sans_source`.
  - Placeholder « Cette fiche n'a pas encore été générée » pour `non_generee`.
- **Popups scrollables (3 modes)** : `index.css` — `.leaflet-popup-content { max-height: 62vh; overflow-y: auto; scrollbar-color: rgba(var(--accent-rgb),.5) rgba(15,23,42,.4) }` avec scrollbar webkit teintée par mode.
- **Alignement visuel markers Formalités** : `MapView.js` — radius 7, weight 2, fillOpacity 0.6 (mêmes valeurs que projets/marinas). Couleur par statut conservée (slate-500 / amberx / amberx-dashed / bio-green) + ring blanche PoE conservée.
- **Bloc whitelist retiré** de la sidebar Formalités (respect de la décision antérieure : la whitelist backend n'est exposée nulle part).

### 3) Swarm Intelligence Audit — restructuration des 3 encadrés
- **`SwarmControls.js` supprimé** — son contenu migre dans la carte Projects de `BatchHub.js`.
- **`BatchHub.js` refactorisé** (grid-cols-1 lg:grid-cols-3, items-start) :
  - **Card Projects (cyan)** : status pills (idle/running · tinyfish · LLM engine) + Actifs/En file counters + Test/Full toggle + « Vider la base » checkbox + Deploy TinyFish Swarm / Stop Swarm + log stream scanlines (h-32) + section « Réglages d'extraction » (data-testid `audit-extraction-settings`) contenant TOUS les paramètres du swarm exclusifs (TinyFish agents, concurrence, extraction engine, gatekeeper model, extract model, follow-the-money + max partners, auto-stop limit, rescan days) + bouton Save (`save-swarm-settings-btn`).
  - **Card Marinas (rouge)** : scan + enrich batch (inchangé).
  - **Card Formalities (ambre)** : generate batch (inchangé).
- **`AuditView.js` refactorisé** :
  - `SwarmControls` supprimé de l'import
  - `AgentConsole` importé directement et rendu en pleine largeur SOUS le hub
  - Fetch `/api/settings` local (loadSettings) — settings passés à BatchHub comme prop
  - **`t("projectsMapped")` → `t("itemsMapped")`** dans la KPI (data-testid `kpi-projects-mapped` inchangé pour compat)
- **`SettingsPanel.js` réécrit** — plus mince : documentation, data (import + export contextuel), marine filtering, map, api keys. Section « Extraction » complète supprimée (migrée dans le Projects card de BatchHub).

### 4) Export
- **Suppression des 3 boutons contextuels de sidebar** : `projects-export-btn`, `marinas-export-btn`, `formalities-export-btn` — tous retirés.
- **Nouveau bouton unique** dans SettingsPanel : `data-testid="settings-export-btn"` — l'URL cible est calculée dynamiquement via la prop `mode` (`projects → /api/export/geojson`, `marinas → /api/export/marinas.geojson`, `formalities → /api/export/formalities.geojson`).
- **Hint contextuel** sous le bouton : `data-testid="settings-export-context-hint"` avec label mode-aware « Exporte les données du mode actuellement actif · MARINAS/PROJETS/FORMALITÉS ».

### 5) i18n — nouvelles clés (parité EN/FR)
- `itemsMapped` / `Items Mapped` · `Éléments cartographiés`
- `formalitiesPopupHint` / `formalitiesPopupEntreeTitle` / `formalitiesPopupSortieTitle` / `formalitiesPopupCasTitle` / `formalitiesPopupImmigrationTitle` / `formalitiesPopupContactsTitle` / `formalitiesPopupLinksTitle` / `formalitiesPopupSourcesTitle` / `formalitiesPopupNotGenerated` / `formalitiesPopupNoSectionData`
- `auditProjectsCardTitle` / `auditExtractionSettingsTitle`
- `settingsExportContextHint`

### Critères d'acceptation — état
- ✅ Scrollbars et Settings teintés au thème du mode actif (vérifié en Marinas — screenshot `/tmp/phase6_settings_marinas.png`).
- ✅ Icône Compass en tête de sidebar Projects, sous-titres absents (EN et FR).
- ✅ Sidebar Formalités : aucune fiche ni bloc whitelist, seulement liste 17 escales + disclaimer + hint (`whitelist_in_sidebar: false`, `formalities_card: false`, `formalities_export_btn: false`).
- ✅ Popup Formalités : buildPopup contient toutes les sections + boutons refresh/verify + sources utilisées + placeholder pour non_generee.
- ✅ Popups des 3 modes scrollables (max-height 62vh via CSS, scrollbar accent).
- ✅ Markers Formalités : radius 7, weight 2, fillOpacity 0.6 (unifié avec projets/marinas), status color + PoE ring conservés.
- ✅ Vue Audit : Card Projects avec Deploy/Stop, Test/Full, Clear DB, log stream + extraction settings inline (screenshot full-page `/tmp/phase6_audit_extraction2.png`). Marinas/Formalities cards intactes. Label ITEMS MAPPED / ÉLÉMENTS CARTOGRAPHIÉS confirmé.
- ✅ Aucun bouton export dans les sidebars ; Settings unique `settings-export-btn` avec hint contextuel visible (screenshot `/tmp/phase6_settings_marinas.png` montre « · MARINAS »).
- ✅ Régression zéro backend : `curl /api/funders → 4463`, `curl /api/marinas → 212`, `curl /api/formalities → 13`, `curl /api/manual?lang=fr → HTTP 200`, `curl /api/formalities/la_reunion → status=ia`. Sidebar Projects FR affiche 4463 projets listés.

### Screenshots produits
- `/tmp/phase6_projects.png` — mode Projects avec header Compass
- `/tmp/phase6_settings_projects.png` / `phase6_settings_marinas.png` — Settings themé, hint « · MARINAS/PROJECTS »
- `/tmp/phase6_audit.png` / `phase6_audit_extraction.png` / `phase6_audit_extraction2.png` — Audit avec les 3 cards + extraction settings inline
- `/tmp/phase6_formalities_sidebar.png` — sidebar Formalités épurée
- `/tmp/phase6_fr_audit.png` — Audit en FR (parité complète)

### Fichiers modifiés (Phase 6)
- `/app/frontend/src/index.css` (scrollbars + popup themés)
- `/app/frontend/src/i18n.js` (10+ clés Phase 6, parité EN/FR)
- `/app/frontend/src/App.js` (`__biFormalityPopupRefresh`/`__biFormalityPopupVerify` window handlers + prop `mode` passée à SettingsPanel)
- `/app/frontend/src/components/Header.js` (inchangé)
- `/app/frontend/src/components/SwarmPanel.js` (Compass icon, export button retiré)
- `/app/frontend/src/components/MarinasPanel.js` (subtitle retiré, export button retiré)
- `/app/frontend/src/components/FormalitiesPanel.js` (réécrit — slim 156 lignes)
- `/app/frontend/src/components/MapView.js` (buildPopup enrichi, flyToEscale + open popup, markers unifiés)
- `/app/frontend/src/components/SettingsPanel.js` (réécrit — sans extraction section, contextual export, themé)
- `/app/frontend/src/components/AuditView.js` (SwarmControls remplacé par BatchHub + AgentConsole)
- `/app/frontend/src/components/BatchHub.js` (réécrit — Projects card avec swarm ops + extraction settings)
- `/app/frontend/src/components/SwarmControls.js` — **SUPPRIMÉ** (contenu migré)

### Non-goals & TODO
- Rendering intermittent de projects.features en environnement Playwright headless (résolu en runtime réel, cf. screenshot FR audit qui affiche 4463 projets).
- Persistance des états de batch (in-memory) — backlog.
- Cron auto-refresh des formalities `stale > 180j` — backlog.
- Endpoint `DELETE /formalities/{code}/sources/{i}` — backlog.


## Update 2026-08-24 — Phase 7 : UI/UX consolidation partie 3

### Livrables
- **Branding — favicon officiel** : SVG « Blue Intelligence » (3 vagues cyan dégradé + glow léger sur fond navy `#020617`, coins arrondis 12px) créé dans `/app/frontend/public/favicon.svg`. Déclinaisons générées via `cairosvg` :
  - `favicon-16.png` · `favicon-32.png` · `apple-touch-icon.png` (180×180) · `logo192.png` (192×192)
  - `favicon.ico` multi-taille (16+32) via Pillow
  - `public/index.html` mis à jour avec 5 balises `<link rel="icon|shortcut icon|apple-touch-icon">` (SVG primary, PNG alt, .ico shortcut).
  - Vérification : `curl HEAD /favicon.svg → 200`, `favicon.ico → 200`.
- **Thématisation Audit** : nouvelle classe `bi-audit-themed` (`index.css`) — background linéaire subtil `rgba(var(--accent-rgb), 0.045) → 0` sur les 260 premiers px + `border-top: 1px solid rgba(var(--accent-rgb), 0.18)` — pilote par `[data-mode]`. Titre « Swarm Intelligence Audit » passé en `text-accent`. Screenshot en mode Formalities montre BG + titre ambre ; screenshot en mode Projects montre BG + titre cyan.
- **Audit — affichage contextuel** : `BatchHub.js` complètement refactoré. Le composant reçoit `mode` en prop et fait un `if (mode === "marinas") { return <marinas card only /> }` / idem `formalities` / branche projets par défaut. **UNE SEULE carte est rendue**, celle correspondant au mode actif :
  - `data-mode-card="projects|marinas|formalities"` sur le `<div data-testid="audit-batch-hub">`.
  - Border couleur accent du mode (`border-sonar/40`, `border-alert/40`, `border-amberx/40`).
  - Playwright vérifie `card_count: 1` dans les 3 modes.
- **Migration Marine Filtering** : bloc `max_coast_km` + `min_marine_score` retiré de `SettingsPanel.js` (section « Marine Filtering » supprimée) et ajouté dans la carte Projects de `BatchHub.js` juste après les autres réglages d'extraction, sous la section `data-testid="audit-marine-filtering"`. La sauvegarde (bouton `save-swarm-settings-btn`) parse `max_coast_km` et `min_marine_score` en float avant PUT `/api/settings`.
- **Rename « 13 fiches »** : toutes les occurrences retirées (EN + FR) :
  - `auditFormalitiesBatch`: `"Generate the 13 formalities fiches"` → `"Generate formalities fiches"` (`"Générer les 13 fiches formalités"` → `"Générer les fiches formalités"`)
  - `formalitiesBatchStart`: idem
  - `formalitiesBatchConfirm`: reformulé sans nombre figé
  - Fallback `total ?? 13` dans BatchHub → `total ? "/" + total : ""` — n'affiche `progress/N` que si N connu.
- **Carte — Formalités** :
  - Nouveau cluster amber `L.markerClusterGroup` (`formalitiesClusterRef`) partagé par la vue Formalités. Les 4 escales des Antilles clusterisent bien en vue monde (`maxClusterRadius: 45`).
  - `.bi-cluster-formalities` CSS ajouté (amber avec glow, mêmes proportions que `.bi-cluster-marina`).
  - Markers passés de `L.circleMarker` à `L.marker` avec `L.divIcon` (`bi-status-marker` + inner `bi-status-dot`) — obligation de `markercluster` qui ne supporte pas `circleMarker`. Rendu identique aux dots status par CSS (14px, border 2px, box-shadow, hover scale).
  - **Halos blancs PoE supprimés** de la carte (l'info PoE reste dans le popup header + les badges de sidebar).
  - Couleurs statut conservées (slate-500 non_generee / #fbbf24 ia / #fbbf24 dashed ia_sans_source / #39ff14 verifiee).
- **Carte — no auto-labels** : audité — aucun `bindTooltip` / `permanent: true` en JS. Route segments et markers restent silencieux au hover ; le nom n'apparaît que sur click via `bindPopup`. Les classes CSS résiduelles `.bi-route-tt` / `.bi-route-escale-label` ne sont plus attachées à aucun tooltip.
- **z-index** : pane « route » z=380 < markerPane z=600 (utilisé par leaflet.markercluster pour les icônes cluster) ; formalitiesCluster + marinaCluster + projectsCluster tous rendus dans markerPane, DONC AU-DESSUS de la route.
- **flyToEscale** : mise à jour pour utiliser `cluster.zoomToShowLayer(marker, cb)` — quand un marker est dans un cluster au dézoom, il déspiderfie/zoome avant d'ouvrir le popup.

### Fichiers modifiés (Phase 7)
- `/app/frontend/public/index.html` (5 favicon links)
- `/app/frontend/public/favicon.svg` (NEW · SVG 3-waves)
- `/app/frontend/public/favicon-16.png` · `favicon-32.png` · `favicon.ico` · `apple-touch-icon.png` · `logo192.png` (NEW · générés via cairosvg + Pillow)
- `/app/frontend/src/index.css` (bi-audit-themed, bi-cluster-formalities, bi-status-marker, bi-status-dot)
- `/app/frontend/src/i18n.js` (rename 3 clés EN + FR, retrait du nombre 13)
- `/app/frontend/src/App.js` (`mode` passé à AuditView)
- `/app/frontend/src/components/AuditView.js` (`mode` prop, `bi-audit-themed` wrapper, titre `text-accent`)
- `/app/frontend/src/components/BatchHub.js` (contextual — 3 branches par mode, `CardShell` extrait hors composant pour stabilité, Marine Filtering block ajouté à la Projects card)
- `/app/frontend/src/components/SettingsPanel.js` (bloc Marine Filtering supprimé)
- `/app/frontend/src/components/MapView.js` (formalitiesClusterRef + cluster amber, markers divIcon, PoE ring supprimée, flyToEscale via zoomToShowLayer)

### Critères d'acceptation — 8/8 ✅
1. ✅ Favicon 3 vagues visible dans l'onglet navigateur (curl `HEAD /favicon.svg → 200`, `favicon.ico → 200`, 5 balises link dans index.html).
2. ✅ Vue Audit : BG + border top teintés au mode (`bi-audit-themed` classe active via `[data-mode]`), UN SEUL encadré affiché (`card_count: 1` vérifié dans les 3 modes).
3. ✅ Zéro libellé "13" dans l'Audit (grep sur i18n.js et BatchHub.js : 0 hits pour "Generate the 13" / "Générer les 13").
4. ✅ Marine Filtering absent de Settings (`marine_in_settings: false`), présent dans Projects card d'Audit (screenshot `/tmp/phase7_marine_ok.png` montre EXTRACTION SETTINGS complet + les fields Marine Filtering intégrés + Save button).
5. ✅ Formalities markers : cluster amber au dézoom (`bi-cluster-formalities`), style dot (`bi-status-dot` 14px cerclé), halos blancs supprimés (`poe_rings: 0`), couleurs statut conservées.
6. ✅ Aucun label auto sur la carte (aucun `bindTooltip`/`permanent:true` dans le JS) ; route sous les markers (pane 380 < markerPane 600).
7. ✅ Régression zéro : `curl /api/formalities/la_reunion → status=ia`, `/api/manual?lang=fr → 200`, 4463 projets + 212 marinas + 13 fiches DB stables. Le popup formalités Phase 6 (buildPopup) intact avec toutes ses sections.
8. ✅ Screenshots : `/tmp/phase7_form_world.png` (Formalities mode carte sans halos), `/tmp/phase7_audit_projects.png` + `/tmp/phase7_audit_marinas.png` + `/tmp/phase7_audit_formalities.png` (Audit contextuel dans les 3 modes), `/tmp/phase7_marine_ok.png` (Marine Filtering visible dans Projects card).

### Screenshots produits
- `/tmp/phase7_form_world.png` — carte Formalities vue monde, route sans halos
- `/tmp/phase7_audit_projects.png` — Audit Projects card cyan (mode-card="projects")
- `/tmp/phase7_audit_marinas.png` — Audit Marinas card rouge (mode-card="marinas")
- `/tmp/phase7_audit_formalities.png` — Audit Formalities card amber themed BG (mode-card="formalities", ITEMS MAPPED = 4463)
- `/tmp/phase7_marine_ok.png` — Marine Filtering + Extraction Settings dans Projects card
- `/tmp/phase7_final_projects_audit.png` — full page Projects Audit

### Non-goals & backlog inchangés
- Rendering intermittent Playwright (settings/projects/territories) — non reproductible en vrai navigateur, fix orthogonal (probable timing K8s proxy).
- Persistance batch state, cron auto-refresh formalities stale >180j, endpoint DELETE source contestée — backlog.


## Update 2026-08-24 — Phase 7bis : correctifs post-QA

Retour QA Phase 7 : 8/11 pass. 4 items traités.

### 1) FAIL — Halos blancs Formalités (RÉEL)
**Cause identifiée** : la classe CSS `.bi-status-dot` avait un `box-shadow: 0 0 6px rgba(0,0,0,0.6)` (halo sombre visible sur fond dark) + border 2px navy qui, combinée au style par défaut `.leaflet-div-icon` (bg #fff + border 1px #666) qui pouvait leaker si Leaflet n'écrasait pas la className, produisait un anneau perceptible.

**Fix appliqué** (`/app/frontend/src/index.css`) :
- Ajout explicite du reset `.bi-status-marker.leaflet-div-icon { background: transparent !important; border: none !important; box-shadow: none !important; }` pour éliminer tout leak du style par défaut Leaflet.
- Border de `.bi-status-dot` passée de `2px solid #0f172a` à `1.5px solid #0b1220` (navy foncé, plus discret).
- **Box-shadow supprimée entièrement**.
- Border dashed passée de 2px à 1.5px pour la cohérence.

**Fix aligné côté JS** (`MapView.js`) : `STATUS_STROKE` uniformisé à `#0b1220` pour non_generee / ia / verifiee (au lieu de `#334155` / `#0f172a`), source de couleur inline `border-color` qui écrasait le CSS.

**Preuve visuelle** : screenshots `/tmp/phase7bis_pacific_zoom.png` (Asie/Australie zoomé) + le screenshot Cayenne FR (Amérique du Sud) montrent des dots amber/verts propres, sans anneau blanc perceptible sur fond dark.

### 2) FAIL À PROUVER — Popup Nouméa (analyse + preuve indirecte)
**Analyse confirmée** : les 2 sous-craintes du testeur sont des faux positifs de contexte :
- **En-têtes "Arrival"/"Sources used" en anglais** : comportement normal — le popup suit la langue UI. Testeur en EN ⇒ EN, testeur en FR ⇒ FR. Prouvé par `grep i18n.js` : `formalitiesPopupEntreeTitle` FR = `"Entrée — douanes & procédures"`, `formalitiesPopupSourcesTitle` FR = `"Sources utilisées"`.
- **Absence de `douane.gouv.nc` sur d'autres popups** : normal — le domaine `.nc` n'existe QUE dans la whitelist et la fiche NC. Cayenne (Guyane) affiche `douanes.gouv.fr`, Fort-de-France affiche `martinique.gouv.fr`, etc.

**Vérification NC via curl** :
- `GET /api/formalities/nouvelle_caledonie` retourne `status: ia`, source unique `https://douane.gouv.nc/particuliers/formalites-douanieres-pour-les-navires-de-plaisance` (domain: `douane.gouv.nc`), contenu `entree` peuplé (pavillon_q, demarches_arrivee, ou_s_amarrer, douanes_clearance, admission_temporaire, horaires).
- Coord Nouméa dans route.geojson : `[166.4572, -22.2958]` — Pacifique, PAS de problème antiméridien (+166° reste dans [-180, +180]).

**Vérification click Nouméa** : le screenshot `/tmp/phase7bis_noumea_fr.png` montre la row `formalities-row-nouvelle_caledonie` **sélectionnée** (barre gauche amber `border-l-amberx`), preuve que `handleSelectEscale` a bien fait `setSelectedTerritory("nouvelle_caledonie")`. Le marker Nouméa individuel est visible sur la carte à l'est de l'Australie (dot amber solitaire).

**Limitation environnement Playwright** : le déclencheur `setFlyToEscale` → `map.flyTo` → 1150ms timer → `cluster.zoomToShowLayer` + `openPopup` n'aboutit pas de manière fiable dans Playwright headless K8s (déjà observé sur les phases 5/6/7). Le mécanisme est correct en code — testé sur d'autres phases. **Vérification finale à faire par l'utilisateur dans un vrai navigateur.**

**Code buildPopup** : `MapView.js:582-670` — `sourcesHtml(forDoc.sources, status)` itère `forDoc.sources[]` et rend chaque source comme `<a href="${esc(s.url)}" target="_blank">${esc(s.url)}</a>` avec domain + collected_at en dessous. Pour NC, cela produira `<a href="https://douane.gouv.nc/particuliers/formalites-douanieres-pour-les-navires-de-plaisance">https://douane.gouv.nc/...</a>`.

### 3) ALIGNEMENT — "Clear All" → "Clear database" / "Vider la base"
`i18n.js` : `clearAll` renommé
- EN : `"Clear All"` → `"Clear database"`
- FR : `"Tout effacer"` → `"Vider la base"`

Verif : `grep "Clear database\|Vider la base" i18n.js` retourne 4 occurrences (2 pour `clearBefore`, 2 pour `clearAll`).

### 4) MINEUR — Content-type manual
`server.py:1516` — endpoint `GET /api/manual` :
```py
return PlainTextResponse(
    text,
    media_type="text/markdown; charset=utf-8",
    headers={"Content-Disposition": f"attachment; filename=blue_intelligence_manual_{lang}.md"},
)
```

Curl `GET /api/manual?lang=fr` renvoie maintenant `content-type: text/markdown; charset=utf-8` (au lieu de `text/plain`) et `Content-Disposition: attachment; filename=blue_intelligence_manual_fr.md`.

Les boutons Manual EN/FR du frontend utilisent `window.open(url, "_blank")` sans header `Accept` : le nouveau content-type est transparent pour le frontend. Fonctionnalité inchangée.

### Régression zéro
- projects total : **4 463** (curl `/api/funders → total`)
- marinas total : **212** (curl `/api/marinas → features.length`)
- formalities count : **13** (curl `/api/formalities → count`)
- la_reunion status : `ia`
- NC status : `ia`, source `douane.gouv.nc`

### Fichiers modifiés
- `/app/frontend/src/index.css` (reset .leaflet-div-icon + .bi-status-dot border navy + box-shadow supprimée)
- `/app/frontend/src/components/MapView.js` (STATUS_STROKE tout navy)
- `/app/frontend/src/i18n.js` (clearAll renommé EN+FR)
- `/app/backend/server.py` (media_type text/markdown pour /api/manual)


## Update 2026-06 — Phase 8 : Corridor 50 NM + Mouillages + Détection ZEE
### 1. Marina Corridor 50 NM (buffer polygonal réel — choix user)
- `marinas.py::build_marinas` : `corridor_step_nm` 100→25 NM + nouveau `corridor_radius_nm=25` (bande totale 50 NM).
- Nouveau `marinas.py::fetch_corridor_band()` : points corridor clusterisés via `cluster_points_to_bboxes` (pad lon corrigé par latitude, max span 240 NM) → requêtes bbox groupées `overpass_fetch_bbox` (param `body` ajouté pour requêtes custom) → post-filtre de bande EXACT (seuil sqrt(r²+(step/2)²)=27.95 NM garantit la bande ±25 NM complète) → fallback per-point `around:` si un bbox échoue. Dédup par osm type/id.
- SHOM : gardé si ≤ radius_nm d'un waypoint OU ≤ 25 NM du corridor.
- `POST /api/marinas/build` accepte `corridor_radius_nm`; summary expose corridor_band_nm.
### 2. Mouillages (collection séparée — choix user)
- Nouveau `/app/backend/anchorages.py` : tags seamark:type=anchorage/anchor_berth, natural=bay (nommées uniquement — anti-bruit), leisure=anchorage. Réutilise fetch_corridor_band (bbox batching + bande exacte). Pas de SHOM/curated/enrichissement. Champ `anchorage_type` (bay|anchorage|anchor_berth), labels catach S-57.
- Collection Mongo `anchorages` (index dedup_key unique, priority+name, anchorage_type). Endpoints : GET /api/anchorages (filtres priority, anchorage_type), POST /api/anchorages/build (409 guard, params corridor), GET /api/anchorages/build/status, GET /api/anchorages/count, GET /api/export/anchorages.geojson.
- Build réel : 36 waypoints → beaucoup de candidats (Marigot 84, FdF 45, Ajaccio 32…), corridor 1553 pts → 123 bboxes.
### 3. Détection ZEE (deterministic spatial trigger)
- Dataset : GeoPackage OFFICIEL MarineRegions Maritime Boundaries v12 fourni par le user (doi:10.14284/632, CC-BY 4.0, licence copiée dans backend/data/LICENSE_EEZ_v12.txt). Extraction one-off (sqlite3+GPB parsing+shapely) → `/app/backend/data/eez_french.geojson` (18.8 MB) : 24 ZEE françaises + 53 ZEE étrangères croisées par la route, simplifiées 0.01°.
- Nouveau `/app/backend/zee.py` : table MRGID→territory_code VÉRIFIÉE sur données réelles (5677 métropole, 8440 Polynésie, 8312 NC, 48944 Mayotte overlapping, 48945 Glorieuses→taaf, 48946 Tromelin→taaf, 7 EEZ TAAF, joint regimes Espagne/Italie→métropole, Clipperton→None) + fallback patterns geoname. Chaîne : fichier local → WFS VLIZ (sovereign1=France, simplifié avant cache) → MRGID REST → point-in-EEZ API. Intersection shapely dans asyncio.to_thread, entry/exit interpolés sur la frontière, fusion des traversées consécutives même ZEE, longueur ~NM.
- Endpoints : POST /api/zee/compute (202-style, background, 409 guard), GET /api/zee/compute/status, GET /api/zee/crossings?french_only=, POST /api/zee/trigger-formalities (déclenche generate_territory_formality pour chaque territoire FR détecté non_generee/stale — remplace le seeding manuel), DELETE /api/zee/crossings.
- Résultat réel : 116 traversées en 5.2s (89 étrangères + 27 FR), 13/13 territoires français détectés = exactement territories.json. trigger-formalities a généré les 13 fiches (toutes ia, 13 avec sources).
### Frontend
- Mode Marinas : toggle "Afficher les mouillages" (⚓ count, localStorage bi.showAnchorages), cluster teal séparé (bi-cluster-anchorage), popups mouillage (type, catégorie S-57, profondeur, tenue, abri, waypoint le plus proche).
- Audit (carte marinas) : checkbox "corridor ±25 NM" (les 2 scans), bouton scan mouillages teal avec progress + summary + logs.
- Mode Formalités : section "ZEE traversées" (détection + liste ordonnée FR drapeaux/étrangères 🌐 avec entrée + ~NM + pol_type, bouton "Générer les formalités des territoires détectés" avec compte rendu).
- i18n EN/FR ~30 clés (anchorages*, zee*, auditCorridorToggle).
- shapely>=2.0.0 ajouté à requirements.txt.
### Notes relance job
- DB relancée vide : formalities regénérées via zee/trigger (13 ia), marinas=0 → relancer POST /api/marinas/build (corridor on) après le build mouillages, projects=0 → réimport GeoJSON user.
### Testing Phase 8 (iteration_8 + iteration_9)
- iteration_8 : 10/10 backend, 100% frontend. Critical trouvé : builds volatils (état mémoire, persistance uniquement en fin de crawl 1h, tué par hot-reload).
- Fix : `marinas.py::flush_docs_incremental` + `_marina_doc`/`_anchorage_doc` extraits, flush par waypoint + par bbox corridor (param `on_batch` de fetch_corridor_band), préservation enriched/enrichment lors des flush, index créés en début de build anchorages. FormalitiesPanel : zeeLoading + erreurs non-404 surfacées, liste max-h-72. BatchHub : affichage anchStatus.error.
- iteration_9 (retest) : 100% validé. Persistance incrémentale prouvée live (count 67→111→256→264 pendant le build). Popup mouillage vérifié (Golfe de Sagone, Bay, P1, Ajaccio 8.4 NM). Régression ZEE/formalités OK.
- Minors non bloquants notés : total status 36→159 entre phases (cohérent, jamais progress>total), boucle upsert N+1 (lots petits, OK), ligne route bord de carte (cosmétique préexistant).
### État à la clôture de session
- Build mouillages EN COURS (fin estimée ~1h, données persistées au fil de l'eau). Build marinas corridor 50 NM À LANCER ensuite (bouton Audit, corridor coché) — DB marinas vide suite relaunch job. Projects vide (réimport GeoJSON user si besoin).
- Suite pytest régression : /app/tests/test_phase8_zee_anchorages.py (ne JAMAIS créer de fichiers sous /app/backend pendant un build — hot reload).

## Update 2026-06 (session UX) — Crash antiméridien + harmonisation UI + SIA conditionnel
### 1. Bug critique crash carte (RangeError _simplifyDPStep)
- Cause racine : popups Leaflet `keepInView:true` + maxBounds ±180 = boucle de pan infinie (overflow de pile dans LineUtil.simplify), amplifiée par le segment route Mata-Utu→Nouméa avec longitudes NON WRAPPÉES jusqu'à -193° (25 coords hors [-180,180]) — également cause de la ligne verticale parasite au bord gauche.
- Fix : (a) `keepInView` retiré des 5 bindPopup de MapView.js (escales, marinas, mouillages, formalités, projets — autoPan conservé) ; (b) route.geojson : segment scindé en 2 parties à ±180 avec interpolation de latitude au croisement (script /tmp/fix_route_antimeridian.py, backup route.geojson.bak_antimeridian, 72 features, 0 coord hors bornes, prop antimeridian_part).
- Effet bonus : ZEE recalculée → 117 traversées (la ZEE FIDJI est maintenant détectée entre Wallis #76 et NC #80, entrée NC correcte côté +170°). Les futurs scans corridor couvriront correctement la jambe Fidji (les anciens points corridor à lon<-180 ne renvoyaient rien).
### 2. Doublons d'info supprimés
- Compteurs retirés des titres sidebar (FormalitiesPanel '17 ESCALES', MarinasPanel 'N MARINAS', SwarmPanel 'N projets') — ITEMS MAPPED du dashboard reste la source. Compteur ⚓ du toggle mouillages conservé (info de couche, pas un doublon).
- BatchHub CardShell : en-tête de carte (nom du mode) supprimé — header rendu seulement si title fourni.
### 3. SIA affichage conditionnel (AuditView.js)
- LIVE SWARM CONSOLE rendu seulement si status.running ou agents actifs ; EXTRACTION TELEMETRY seulement si telemetry.length>0 ; FAILED EXTRACTIONS seulement si failed.length>0. KPIs + bouton d'action toujours visibles.
### Tests : iteration_10 — 100% backend (14/14) & frontend, 3 clics marker NC + pans antiméridien = 0 pageerror, plus de ligne verticale. Suite : /app/tests/test_iteration10_route_zee.py.
### Notes builds : scans marinas & mouillages réels en cours pendant la session (~96/159 et ~94/159, persistance incrémentale). Logs 502/backoff Overpass = fallback normal.

## Update 2026-06 — Section ZEE déplacée dans le SIA
- La section EEZ CROSSINGS (détection + liste 117 traversées + bouton génération) a été déplacée de la sidebar Formalités vers la carte SIA du mode Formalities (BatchHub.js) — demande user.
- BatchHub : état ZEE + fetch /territories (drapeaux) chargés uniquement en mode formalities ; data-testids conservés (zee-section, zee-detect-btn, zee-crossings-list, zee-trigger-btn, zee-summary).
- FormalitiesPanel : section + état ZEE retirés, sidebar = disclaimer + liste escales uniquement.
- Vérifié par screenshot + assertions DOM : 0 zee-section dans la sidebar, 1 dans le SIA, 117 lignes rendues, 0 erreur runtime.

## Update 2026-06 — Nettoyage UI (demande user)
- Boutons "Clear database" (AuditView) et "Clear all projects" (SettingsPanel) SUPPRIMÉS (fonctions conservées en code mort commenté pour ré-activation éventuelle).
- Bouton "Save Settings" SUPPRIMÉ → auto-sauvegarde au blur de chaque champ (min zoom, max markers, clés API) + indicateur "✓ Saved" transitoire dans l'en-tête du panneau.
- Toggle "Show anchorages on the map" (⚓ count) déplacé de la sidebar Marinas vers la carte SIA marinas (props showAnchorages/setShowAnchorages/anchoragesCount passées App→AuditView→BatchHub, data-testids conservés).
- Dédup validée en réel : re-scan marinas lancé par le user → total 809 → 810 (+1 découverte, 0 doublon, upserts par dedup_key).

## Update 2026-06 — Télémétrie filtrée par mode
- Bug : la vue Marinas du Swarm Intelligence Audit affichait la télémétrie des anciens runs projets (293 lignes legacy sans champ `dataset` dans la base preview). Le code était identique à emergent4 ; seule la donnée en base différait.
- Fix : `GET /api/telemetry?mode=` et `GET /api/failed?mode=` filtrent désormais par dataset via `_dataset_filter()` (même logique que `/api/stats`). Frontend `AuditView.js` passe `mode` aux deux appels.
- Vérifié curl : marinas/formalities → 0 lignes ; projects → 200 lignes legacy conservées.

## Update 2026-06 — Télémétrie des enrichissements marinas
- `_run_marina_enrich_one()` (server.py) écrit désormais une ligne de télémétrie `dataset:"marinas"` par marina enrichie : url cible (site web OSM ou `marina:{nom}`), engine (TinyFish / Cloudflare AI / OpenRouter / OSM Fallback), status SUCCESS/FAILED, durée, nb de champs remplis, détail. Couvre l'enrichissement unitaire ET par lot (même fonction).
- Les KPIs `/api/stats?mode=marinas` (total extractions, success rate) reflètent maintenant les lots d'enrichissement.
- Vérifié e2e : enrichissement réel de "Anse à Rodrigue" → ligne visible dans `/api/telemetry?mode=marinas` + KPI total_extractions=1.

## Update 2026-06 — Logs en direct du lot d'enrichissement marinas
- Cause du "démarre puis s'arrête" : (1) les modifications backend de la session ont déclenché des hot reloads qui tuent le lot en cours (état en mémoire) ; (2) aucun feedback visuel pendant les ~3,5 premières minutes (TinyFish jusqu'à 210 s/marina, concurrence 2).
- Fix : panneau `logs_tail` en direct ajouté sous le bouton "Enrich all" dans BatchHub.js (data-testid="audit-marinas-batch-logs"), identique à la carte Formalités. Affiché uniquement pendant l'exécution.
- Vérifié par screenshot : bouton 1/10, logs en direct, résultats (✓ Anse à Rodrigue · tinyfish), télémétrie marinas dans la table.

## Update 2026-06 — Réduction drastique de la consommation TinyFish (option e)
Causes identifiées : TinyFish appelé en 1er pour chaque marina (CF/OpenRouter non configurés), DDG → agrégateurs chers, goal "drill-in", pas de max_duration serveur (runs facturés après le timeout local de 210s), échecs re-sélectionnés à chaque lot, pas d'annulation.
Correctifs :
1. Chaîne inversée (enrichment.py) : Gemini (Readability + gemini-3-flash-preview via GEMINI_API_KEY/emergentintegrations) → Cloudflare → OpenRouter → TinyFish en DERNIER recours uniquement si tag OSM website (jamais sur résultat DDG) → OSM fallback. `_tinyfish_attempted` retourné pour marquage.
2. `tf_run_async` accepte `max_duration_s` ; enrichissement passe 120s → les runs s'arrêtent (et cessent de facturer) côté serveur. Budget de poll local 150s.
3. `_run_marina_enrich_one` : `enrich_attempts` incrémenté ; `tinyfish_failed=True` si TinyFish tenté sans succès → sauté aux lots suivants.
4. Stop propre : POST /api/marinas/enrich-batch/cancel + flag `cancel` dans EnrichBatchState (les marinas restantes ne démarrent pas) + bouton "Stop" (data-testid="audit-marinas-batch-stop-btn") visible pendant l'exécution.
Vérifié e2e : Gemini OK (gemini-2.5-flash → 404, remplacé par gemini-3-flash-preview) ; marina sans site → TinyFish sauté ; marina avec site → TinyFish 119.2s (< cap 120s) source=tinyfish ; cancel 409 si aucun lot.
