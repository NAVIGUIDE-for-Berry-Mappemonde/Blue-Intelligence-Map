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
| `marina_world.py` | Dump mondial `leisure=marina` (tuiles Overpass, identité `osm_id`, slim GeoJSON, lien Maps) | `build_world_marinas`, `marinas_to_slim_geojson` |
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

## 3. Rangement cible (APPLIQUÉ)

Le backend plat historique (18 modules au même niveau, `server.py` ~1 750 l.)
a été réorganisé en paquet `app/` — la surface de routes est restée
byte-identique (85/85 vérifiées contre `main`) :

```
backend/
├── server.py                   # shim : `from app.main import app` (uvicorn server:app inchangé)
├── app/
│   ├── main.py                 # assemblage FastAPI, middlewares, startup/shutdown
│   ├── config.py               # chemins (DATA_DIR, MODELS_DIR, ROUTE_FILE), env, DEFAULT_SETTINGS
│   ├── db.py                   # client Motor + get_settings
│   ├── state.py                # singletons partagés (swarm)
│   ├── routers/                # 1 fichier = 1 domaine REST
│   │   ├── projects.py         #   /projects, /import|export geojson, /categories, enrich, /report-project
│   │   ├── swarm.py            #   /swarm/*, /stats, /telemetry, /failed/* (Force Extract)
│   │   ├── marinas.py          #   /marinas/*, /anchorages/*, enrich unitaire + batch
│   │   ├── formalities.py      #   /poe/* (ex poe_routes.py)
│   │   ├── ml.py               #   /api/ml/* (ex ml_routes.py)
│   │   ├── donations.py        #   /donations/*, /payments/*, webhook Stripe
│   │   └── misc.py             #   santé, /settings, /manual, /route, /zee/*
│   ├── services/               # logique métier (aucun import FastAPI)
│   │   ├── swarm_pipeline.py   #   ex pipeline.py
│   │   ├── poe_pipeline.py     #   ex poe.py
│   │   ├── marina_build.py     #   corridor / SHOM (mouillages + helpers)
│   │   ├── marina_world.py     #   dump mondial leisure=marina
│   │   ├── anchorage_build.py  #   ex anchorages.py
│   │   ├── marina_enrich.py    #   ex enrichment.py
│   │   ├── zee_crossings.py    #   ex zee.py
│   │   └── osm_validate.py
│   ├── core/                   # briques transverses réutilisables
│   │   ├── llm.py              #   ex llm_core.py (OpenRouter)
│   │   ├── geo.py              #   ex geo_core.py
│   │   ├── extract.py          #   ex extract_core.py
│   │   ├── dedup.py            #   ex dedup_core.py
│   │   ├── rag.py              #   ex rag_core.py
│   │   ├── ml.py               #   ex ml_core.py
│   │   ├── tinyfish.py         #   ex tinyfish_client.py
│   │   └── tasks.py            #   TaskState générique (remplace 4 classes dupliquées)
│   └── static_data/            # seeds.py, categories.py
├── data/ · models/ · tests/
```

Fonctions re-découpées :

1. **`poe_pipeline.generate_zone_poe`** → orchestrateur + 5 étapes :
   `_skip_if_unchanged` (monitoring MD5/sémantique), `_find_sources`
   (recherche + gatekeeper + Level-2 + bootstrapping), `_collect_texts`
   (cascade N1/N2/N3), `_extract_and_geocode`, `_persist_zone` (upsert
   non-destructif) ;
2. **`server.py`** → 7 routers par domaine (voir ci-dessus) ;
3. **États de tâches** (`TaskState`, `EnrichBatchState`, `ZeeComputeState`,
   `BuildState`) → une seule classe `app/core/tasks.TaskState` + helpers
   `prune_tasks` / `new_task` ;
4. **Frontend** :
   - `MapView.js` (899 l. → ~300 l.) : orchestrateur + modules par couche sous
     `components/map/` (`constants.js`, `zonePopup.js`, `useRouteLayer.js`,
     `useProjectsLayer.js`, `useMarinasLayer.js`, `useAnchoragesLayer.js`,
     `useFormalitiesLayers.js`) ;
   - `BatchHub.js` (709 l. → 36 l.) : dispatcheur + 1 carte par fichier sous
     `components/audit/` (`CardShell.js`, `ProjectsCard.js`, `MarinasCard.js`,
     `FormalitiesCard.js`) — le polling d'une carte ne tourne que lorsqu'elle
     est montée.

## 4. Renommages

### Features visibles (appliqués)

| Avant | Après | Raison |
|-------|-------|--------|
| « Swarm Intelligence Audit » (bouton d'en-tête) | **Console** (titre : « Console de supervision » / "Operations Console") | Plus court, décrit la fonction réelle (supervision + déclencheurs), sans jargon |
| Bouton « Soutenir Blue Intelligence » (dons Stripe) | **supprimé** | Stripe abandonné — tout le code dons/paiement a été retiré |
| Sélecteur « Moteur d'extraction » (Gemini/GPT/Claude/OpenRouter) | badge statique **OpenRouter** | Un seul moteur désormais |
| Menu déroulant « Filtre par catégorie » (mode Projets) | **supprimé** | Redondant avec la légende cliquable, qui filtre déjà |
| Bouton « Rafraîchir » (bandeau Marinas) | **supprimé** | La liste se rafraîchit automatiquement toutes les 8 s |

### Fonctions du code (proposition — à appliquer au fil de l'eau)

| Actuel | Proposé | Raison |
|--------|---------|--------|
| `swarm_pipeline.Swarm.deploy` | `Swarm.start_discovery` | « deploy » évoque un déploiement d'infrastructure |
| `poe_pipeline.generate_zone_poe` | `generate_ports_of_entry` | Expliciter l'objet produit |
| `marina_enrich.enrich_via_tinyfish` | `scrape_official_site` | Décrit l'action, pas le fournisseur |
| `core.llm.ask_json` / `ask_text` | `complete_json` / `complete_text` | Vocabulaire standard des complétions LLM |
| `core.geo.snap_to_ocean` | inchangé | Nom déjà exact |
| `routers/swarm._force_extract_one` | `force_extract_failed_url` | Préciser la cible (URL en échec) |
| `core.rag.select_context` | `select_relevant_chunks` | Décrit le mécanisme (similarité par chunks) |
| État `ia` / `ia_sans_source` (statuts ZEE) | `generee` / `generee_sans_source` | « ia » est ambigu ; migration à faire côté données + UI en une passe dédiée |

## 5. Évolutions futures possibles

- Persister les états de tâches dans une collection Mongo `jobs` pour survivre
  aux redémarrages (déjà fait pour la validation OSM) ;
- Extraire les prompts LLM dans des fichiers dédiés (`app/core/prompts/`) ;
- Basculer la lecture des réglages sur un cache TTL pour éviter un aller-retour
  Mongo par requête ;
- Catalogue des règles modulables : `data/run_rules.json` + `core/run_rules.py`
  (snapshot `params.rules` par run — voir `docs/REGLES_PARAMETRES.md`).
