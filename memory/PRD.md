# Blue Intelligence — PRD

## Original Problem Statement
Application OSINT de cartographie à deux pipelines : (1) scraper de Ports d'Entrée maritimes douaniers (PoE, approche Top-Down par ZEE mondiales VLIZ) et (2) scraper de Projets de conservation marine financés par des fondations. React (Leaflet) + FastAPI + MongoDB.

**Refactoring massif 2026-08** : mutualisation des deux pipelines en architecture Core, cascade d'extraction hybride pour préserver les crédits TinyFish, bootstrapping ML (weak supervision) sur les données existantes, validation Bottom-Up.

**CONTRAINTE ABSOLUE** : les données en base (4463 projets + 1171+ PoE) sont un trésor (jeu d'entraînement) — aucune purge, upsert non-destructif partout.

## Architecture Core (refactor 2026-08-26)
- `llm_core.py` — Adaptateur LLM universel : cascade Gemini REST (si clé) → Emergent (gemini-2.5-flash) → OpenRouter (gpt-4o-mini JSON mode) avec fallback auto. Gatekeeper marin (ML local → LLM → heuristique), extraction JSON stricte des PoE, recherche groundée (Gemini google_search ou OpenRouter :online avec annotations).
- `geo_core.py` — Géocodage Nominatim (rate-limit 1.1s + cache) → GeoNames, variantes de noms de ports, re-ranking sémantique des candidats, snap_to_ocean/masque terrestre, point-in-EEZ shapely, IsolationForest/DBSCAN.
- `dedup_core.py` — Haversine <500m + fuzzy >60% (ratio brut/normalisé/tokens triés), >90% seul. merge_docs non-destructif, upsert_with_dedup.
- `extract_core.py` — Cascade N1 (httpx + trafilatura/PyMuPDF, gratuit) → N2 (Readability/BS4) → N3 (TinyFish, capé 120s, opt-in). Filtrage SERP regex, métadonnées page, depth=2 sélectif (liens /annuaire, /contacts, /clearance).
- `rag_core.py` — Chunking 500 chars aligné phrases, sentence-transformers all-MiniLM-L6-v2 (installé, fallback TF-IDF), top_chunks/select_context, monitoring sémantique (content_changed ≥0.95 = skip), rerank_candidates.
- `ml_core.py` — Gatekeeper TF-IDF+LogReg entraîné sur 4462 projets BDD (acc 1.0), scan anomalies PoE (IsolationForest offsets zone + DBSCAN haversine, flags additifs), export dataset NER (5634 lignes, PORT_NAME/PROJECT_NAME/LOCATION).
- `osm_validate.py` — Validation Bottom-Up Overpass (harbour/marina/customs/border_control/seamark) → osm_confidence 0-1, sans toucher nom/coords. Miroir fr accessible.
- `ai.py` / `geo.py` — wrappers de rétrocompat vers llm_core/geo_core.
- `pipeline.py` (Swarm projets) — discovery N1 crawler d'abord, TinyFish N3 dernier recours ; extraction via cascade + RAG (>6000 chars) ; dedup via dedup_core.
- `poe.py` — monitoring MD5 + sémantique, Level-2 Retry Query (organisation douanière), cascade N1/N2 + 1 seul TinyFish max/zone, RAG >15000 chars, stockage upsert non-destructif (préserve osm_*, anomalies).
- `ml_routes.py` — /api/ml/status, /train/gatekeeper, /gatekeeper/predict, /anomalies/scan+report, /ner/export-dataset.
- `poe_routes.py` — + /api/poe/validate-osm (start/status/cancel).

## Environnement
- Clés (backend/.env) : EMERGENT_LLM_KEY, OPENROUTER_API_KEY, TINYFISH_API_KEY, GEONAMES_USERNAME=BerryMappemonde. Pas de clé Gemini directe.
- sentence-transformers + torch CPU installés (~2 Go — impact taille image de déploiement).
- SearXNG bloqué depuis le pod → fallback OpenRouter :online opérationnel.
- Fond de carte : Esri Dark/Light Gray Canvas (CARTO watermarkait "API KEY REQUIRED").

## Données (restaurées 2026-08-26)
- projects: 4463 (import GeoJSON), poe_ports: 1171+ (1169 restaurés — l'export ne contenait que les géocodés sur 1864), eez_zones: 285 (165 backfillées "ia").
- Restauration : /app/scripts/restore_data.py + POST /api/import/geojson.

## What's been implemented (historique)
- [avant fork] App complète : Swarm projets, PoE ZEE, marinas, formalities UI, batch hub, crowdsourcing "Projet manquant ?", exports GeoJSON.
- [2026-08-26] Refactor Core complet (étapes 1-3 du ticket), restauration BDD, bascule tuiles Esri, tests 25/25 (pytest) + validation testing agent (non-destructivité prouvée par diff Mongo champ-à-champ).

## Backlog priorisé
- P1 : Entraînement NER spaCy réel depuis models/ner_dataset.jsonl (dataset prêt) ; validation OSM complète des 1171 PoE (≈25 min à 1.2s/port, endpoint prêt) ; croisement projets ↔ douanes.
- P2 : Qualification juridique UNCLOS des ZEE sans PoE ; Cross-Encoder dédié (ms-marco) pour re-ranking géocodage ; UI badges osm_confidence/spatial_anomaly sur les popups PoE ; harmonisation des shapes de statut de jobs (logs vs logs_tail).
- P2 : Ré-import des ~695 PoE non géocodés perdus (absents de l'export GeoJSON) — nécessite une sauvegarde complète de la collection si elle existe.

## Notes testing
- Regression rapide : `cd /app/backend && python3 -m pytest tests/ -p no:randomly`.
- INTERDIT : /api/deploy clear_db=true, generate-batch sans limite, régénérer des zones ≠ 8397.
