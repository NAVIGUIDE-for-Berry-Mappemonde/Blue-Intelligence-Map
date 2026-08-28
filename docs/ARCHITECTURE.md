# Architecture & analyse du code — Blue Intelligence

Ce document présente (1) l'analyse fichier par fichier du code, (2) le nettoyage
effectué, (3) la proposition de rangement et de découpage cible.

---

## 1. Analyse du code

### Backend (`backend/`, FastAPI + MongoDB)

| Fichier | Rôle | Fonctions / classes clés |
|---------|------|--------------------------|
| `server.py` (~1 750 l.) | Point d'entrée FastAPI : settings, projets, imports/exports GeoJSON, marinas, mouillages, enrichissement, dons Stripe, ZEE crossings, manuel utilisateur | `get_settings`, `project_to_feature`, endpoints `/api/*`, `_run_marina_enrich_one`, `_run_project_enrich`, `_stripe`, états in-memory (`EnrichBatchState`, `ZeeComputeState`) |
| `llm_core.py` | **Adaptateur LLM unique (OpenRouter)** — toutes les complétions IA | `ask_json`, `ask_text`, `gatekeeper_check`, `extract_project`, `extract_ports`, `llm_geocode`, `grounded_search`, `parse_json_flexible` |
| `pipeline.py` | Swarm de découverte/extraction des projets marins (TinyFish SSE → crawler HTTP → Readability → LLM) | classe `Swarm` (`deploy`, `stop`, `status`, workers), `pick_image` |
| `poe.py` | Pipeline souverain [ZEE → Ports d'Entrée] : référentiel VLIZ, recherche multilingue, whitelist gouvernementale, collecte, extraction, géocodage, monitoring MD5/sémantique | `build_referential`, `generate_zone_poe`, `build_whitelist`, `url_allowed`, `qualify_unclos`, `zone_to_item`, `ports_to_geojson` |
| `poe_routes.py` | Endpoints du mode Formalités + rafraîchissement automatique + reprise de jobs | `TaskState`, `_auto_refresh_loop`, endpoints `/api/poe/*` |
| `marinas.py` | Build du dataset marinas (Overpass OSM + SHOM + curated, corridor ±25 NM, dédup géohash) | `build_marinas`, `marinas_to_geojson`, `BuildState` |
| `anchorages.py` | Build des mouillages (Overpass uniquement, mêmes corridors) | `build_anchorages`, `anchorages_to_geojson` |
| `enrichment.py` | Enrichissement des marinas — chaîne OpenRouter → TinyFish → tags OSM, garde-fou crédits | `enrich_marina`, `enrich_via_openrouter`, `enrich_via_tinyfish`, `enrich_from_osm_tags`, `openrouter_check_credit` |
| `geo_core.py` | Géospatial unifié : géocodage Nominatim → GeoNames (cache + rate-limit), masque terrestre, snap côtier, point-in-EEZ, anomalies spatiales | `geocode`, `geocode_port`, `haversine_km`, `is_ocean`, `snap_to_ocean`, `coast_distance_km` |
| `extract_core.py` | Cascade de parsing N1 (trafilatura/PyMuPDF) → N2 (Readability/BS4) → N3 (TinyFish capé), filtrage SERP, follow-ups internes | `extract_cascade`, `serp_filter`, `internal_followups` |
| `dedup_core.py` | Déduplication spatio-textuelle non-destructive (Haversine < 500 m + fuzzy > 60 %) | `is_duplicate`, `deduplicate_list`, `merge_docs`, `normalize_name` |
| `rag_core.py` | RAG local : chunking ~500 c., sélection par similarité cosinus, monitoring sémantique (sentence-transformers, repli TF-IDF) | `select_context`, `content_changed`, `semantic_rerank` |
| `ml_core.py` | ML local (weak supervision) : gatekeeper TF-IDF+LogReg, classifieur SERP, NER spaCy, anomalies IsolationForest/DBSCAN | `predict_relevance`, `predict_serp`, `extract_entities`, `train_*` |
| `ml_routes.py` | Endpoints `/api/ml/*` (entraînements, prédictions, anomalies, NER) | états `TRAIN_STATE`… |
| `osm_validate.py` | Validation Bottom-Up des PoE via Overpass (`osm_confidence`) | `validate_ports` |
| `zee.py` | Traversées ZEE de la route officielle (intersection shapely, 4 niveaux de fallback) | `build_zee_crossings`, `crossings_to_summary`, `filter_french_territories` |
| `tinyfish_client.py` | Client HTTP TinyFish (run sync/async + polling) | `tf_run_sync`, `tf_run_async`, `tf_get_run`, schémas JSON |
| `seeds.py` / `categories.py` | Données statiques : MasterSeeds des fondations, taxonomie des catégories | `MASTER_SEEDS`, `CATEGORY_GROUPS`, `normalize_category` |
| `tests/` | Suite pytest (14 fichiers) — la plupart exigent le serveur lancé (`REACT_APP_BACKEND_URL`) | — |

### Frontend (`frontend/src/`, React CRA + Leaflet + Tailwind)

| Fichier | Rôle |
|---------|------|
| `index.js` / `App.js` | Bootstrap + état global (mode actif, settings, statut swarm, i18n) |
| `api.js` | Client axios vers `REACT_APP_BACKEND_URL/api` |
| `i18n.js` | Dictionnaires EN/FR |
| `components/MapView.js` | Carte Leaflet : clusters projets/marinas/mouillages, choroplèthe ZEE, popups, route officielle |
| `components/Header.js` | Bascule de mode, dons, langue, thème clair/sombre |
| `components/ProjectList.js`, `MarinasPanel.js`, `FormalitiesPanel.js` | Bandeaux latéraux par mode (recherche, filtres, listes) |
| `components/AuditView.js` + `BatchHub.js` + `AgentConsole.js` | Console opérateur : KPIs, télémétrie, déclencheurs batch, live view des agents |
| `components/SettingsPanel.js` | Paramètres transverses (docs, import/export, carte, clés API) |
| `components/Donations.js`, `ReportModal.js`, `SwarmPanel.js` | Cagnotte Stripe, signalement de projet, statut du swarm |

---

## 2. Nettoyage effectué

### Supprimés (l'historique git les conserve)

| Élément | Raison |
|---------|--------|
| `prototype_ai_studio/` | Prototype Google AI Studio (Vite/TS) totalement déconnecté de l'app |
| `.emergent/` | Outillage interne de la plateforme Emergent (cron/webhooks du pod) |
| `test_reports/`, `test_result.md`, `backend_test.py` | Artefacts historiques des itérations de tests de la plateforme |
| `tests/` (racine) | Tests d'itérations legacy, redondants avec `backend/tests/` |
| `memory/test_credentials.md` | Notes d'environnement obsolètes (mentionnait les clés Emergent) |
| `package-lock.json` (racine) | Orphelin — aucun `package.json` à la racine |
| `backend/ai.py`, `backend/geo.py` | Wrappers de rétrocompatibilité vides — fusionnés dans `llm_core.py` / `geo_core.py` |
| `backend/data/route.geojson.bak_antimeridian` | Fichier de sauvegarde |
| `backend/data/cached_pdfs/`, `backend/data/.tld_cache/` | Caches runtime (désormais gitignorés) |
| Dépendances `emergentintegrations`, `litellm` (wheel privée), `google-generativeai` & co, `openai`, `tiktoken` | Plus aucun appel Gemini/Emergent — Stripe migré vers le SDK officiel `stripe` |

### Déplacés

- `memory/PRD.md` → `docs/PRD.md`
- `design_guidelines.json` → `docs/design_guidelines.json`

---

## 3. Proposition de rangement cible (non appliquée — évolution future)

Le backend actuel est plat (18 modules au même niveau) et `server.py` concentre
~1 750 lignes. Découpage proposé, à iso-fonctionnalités :

```
backend/
├── app/
│   ├── main.py                 # create_app(), middlewares, startup (≈80 l.)
│   ├── config.py               # settings Mongo + DEFAULT_SETTINGS + env
│   ├── db.py                   # client Motor, index
│   ├── routers/                # 1 fichier = 1 domaine REST
│   │   ├── projects.py         #   /projects, /import, /export, /categories, /report-project
│   │   ├── swarm.py            #   /swarm/*, /failed/*, /stats, /telemetry
│   │   ├── marinas.py          #   /marinas/*, /anchorages/*
│   │   ├── formalities.py      #   /poe/* (act. poe_routes.py)
│   │   ├── ml.py               #   /api/ml/* (act. ml_routes.py)
│   │   ├── donations.py        #   /donations/*, /payments/*, webhook Stripe
│   │   └── misc.py             #   /settings, /manual, /route, /zee/*
│   ├── services/               # logique métier (aucun import FastAPI)
│   │   ├── swarm_pipeline.py   #   act. pipeline.py
│   │   ├── poe_pipeline.py     #   act. poe.py
│   │   ├── marina_build.py     #   act. marinas.py + anchorages.py
│   │   ├── marina_enrich.py    #   act. enrichment.py
│   │   ├── zee_crossings.py    #   act. zee.py
│   │   └── osm_validate.py
│   ├── core/                   # briques transverses réutilisables
│   │   ├── llm.py              #   act. llm_core.py (OpenRouter)
│   │   ├── geo.py              #   act. geo_core.py
│   │   ├── extract.py          #   act. extract_core.py
│   │   ├── dedup.py            #   act. dedup_core.py
│   │   ├── rag.py              #   act. rag_core.py
│   │   ├── ml.py               #   act. ml_core.py
│   │   └── tasks.py            #   TaskState générique (act. dupliqué 4×)
│   └── static_data/            # seeds.py, categories.py
├── data/ · models/ · tests/
```

Fonctions à re-découper en priorité :

1. **`poe.generate_zone_poe` (~280 l.)** → 5 étapes pures : `refresh_known_sources`,
   `search_candidates`, `collect_texts`, `extract_and_geocode`, `persist_zone` ;
2. **`server.py`** → éclater en routers (le gros du gain de lisibilité) ;
3. **États de tâches** (`TaskState`, `EnrichBatchState`, `ZeeComputeState`,
   `BuildState`) → une seule classe générique `core/tasks.py`, voire une
   collection Mongo `jobs` pour survivre aux redémarrages ;
4. **Frontend** : `MapView.js` (>900 l.) → séparer par couche
   (`layers/ProjectsLayer.js`, `layers/MarinasLayer.js`, `layers/EezLayer.js`)
   et extraire les popups en composants ; `BatchHub.js` → 1 carte par fichier
   (`audit/ProjectsCard.js`, `audit/MarinasCard.js`, `audit/FormalitiesCard.js`).

Cette migration est mécanique (déplacements + imports) et peut se faire
progressivement, un domaine à la fois, la suite `backend/tests/` servant de
filet de sécurité.
