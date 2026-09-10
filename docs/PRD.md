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
- [2026-08-26 soir] Itération conformité spec + 4 features (testing agent 16/16 + 5/5 flows frontend) :
  - NER spaCy local entraîné (F1=0.968, 5041 train) — POST /api/ml/train/ner, POST /api/ml/ner/extract, fallback sans-LLM dans extract_ports_llm. Modèle: backend/models/ner_spacy/.
  - Qualification UNCLOS des 120 ZEE sans PoE (sovereign_entry 69, uninhabited 14, overlapping_claim 25, joint_regime 12) — POST /api/poe/qualify-unclos, bloc bleu "§ Legal status (UNCLOS)" dans le popup de zone. Effacé automatiquement ($unset) quand une zone gagne des ports.
  - Badges carte : popup PoE affiche confiance OSM (vert ≥0.5 / ambre / gris ∅) + badge rouge anomalie spatiale (data-testid: poe-osm-badge, poe-anomaly-badge, zone-unclos-block).
  - Validation OSM Overpass complète lancée sur les 1171 PoE (résumable via only_unchecked ; tuée par tout hot-reload backend — relancer POST /api/poe/validate-osm {"only_unchecked":true}).
  - Conformité : plafonds par pays supprimés (plus de ports[:25], coerce 150), tronquage 10k supprimé (60k/source + RAG), matrice requêtes multilingues 16 langues (localized_query), regex SERP élargie (brochures/tourisme/bagages/VTS/duty-free), Cross-Encoder ms-marco pour re-ranking géocodage (fallback bi-encoder), PDF 60 pages.

- [2026-08-26 nuit] Classifieur SERP + Reprise auto (testing agent 17/17 + 35/36 régression) :
  - Classifieur SERP (ml_core) : TF-IDF char n-grams sur URL + LogReg, weak supervision (195 URLs sources réelles vs négatifs synthétiques touristiques), acc=0.987/f1=0.983. Endpoints POST /api/ml/train/serp, POST /api/ml/serp/predict {"url"}. Intégré au pipeline PoE via poe.rank_candidates_ml (tri avant téléchargement + drop score<0.1 si ≥3 alternatives), appelé après serp_filter et après le Level-2 retry.
  - Reprise auto des jobs : état persisté dans db.jobs (_id='osm_validation', desired/params/resumed), poe_routes._start_osm_task + schedule_job_resume() (délai 20s) appelé au startup de server.py. Respecte params.only_unchecked. Validé E2E (kill simulé → reprise → desired=false) + cas "reprise inutile".
  - Validation OSM COMPLÈTE terminée : 1171/1171 PoE vérifiés, 678 haute confiance (≥0.5), 154 sans tag OSM à 3 km.
  - Tests de régression réutilisables : tests/test_serp_ml_resume.py (rapide, sans coût LLM).

- [2026-09-10] Mode Science (6e mode, violet #a78bfa) — jeux de données océano localisés sur la carte + lien vers leur fiche portail :
  - Sources (API structurées uniquement — pas de LLM, pas de scraping) : Sextant/SISMER + sous-portail ODATIS via l'API JSON Elasticsearch de GeoNetwork 4 (`/geonetwork/{srv|ODATIS}/api/search/records/_search`, geom GeoJSON natif), EDMED SeaDataNet via SPARQL (WKT sur le nœud dct:spatial), flotteurs Argo actifs via l'index ERDDAP Ifremer (`ArgoFloats-index`, dernier profil par WMO, lien fleetmonitoring.euro-argo.eu).
  - Backend : services/science_build.py (bbox GeoJSON/WKT + antiméridien, détection bbox "monde" → fiche conservée mais non placée, upsert non destructif `_id={source}:{native_id}`), routers/science.py (geojson/count/build/status/cancel/runs/export/import), collections science_items + science_runs (snapshot de règles → onglet Runs).
  - Règles catalogue : science.catalog_max_records (2000, cap dur ES 10000), science.argo_window_days (30 j).
  - Frontend : SciencePanel (recherche, filtre par source, légende datasets/Argo), useScienceLayer (popup organisme/résumé/DOI/WMO/cycle + bouton fiche portail), ScienceCard console (sources cochables), Review non branchée (placeholder), export/import science.geojson.
  - Tests : tests/test_science.py (18 unitaires, fetchers injectés — bbox antiméridien, dédup EDMED, dernier profil Argo, isolation d'erreur par source, re-run 100 % updated).

## Conformité spec (Document sans titre (6).md)
- ✅ 23/25 items pleinement conformes (classifieur SERP maintenant fait).
- ⚠️ Partiels : traduction NLP requêtes (matrice statique 16 langues au lieu d'opus-mt local) ; crowdsourcing PoE avec lien de loi (le module existant couvre les projets).

## Backlog priorisé
- P1 : Crowdsourcing PoE (proposition skipper + lien texte de loi + vérification auto).
- P2 : opus-mt local pour traduction dynamique des requêtes ; filtre confiance OSM sur la carte ; croisement projets ↔ douanes ; ré-import des ~695 PoE non géocodés (nécessite sauvegarde complète) ; simplification géométrie ZEE à bas zoom (perfs carte) ; découpage server.py/marinas.py (>700 lignes, dette technique).

## Notes testing
- Regression rapide : `cd /app/backend && python3 -m pytest tests/ -p no:randomly` (test_ner_unclos_osm.py = 16 tests non-destructifs).
- INTERDIT : /api/deploy clear_db=true, generate-batch sans limite. Toute écriture .py sous /app/backend tue les jobs de fond (uvicorn --reload).
