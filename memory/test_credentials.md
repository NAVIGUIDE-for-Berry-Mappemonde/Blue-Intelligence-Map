# Test Credentials & Environment Notes

## Authentication
**This app has NO authentication** — all API endpoints are public.

## Environment (backend/.env)
- MONGO_URL=mongodb://localhost:27017, DB_NAME=blueintel_db
- EMERGENT_LLM_KEY (LLM cascade: emergent), OPENROUTER_API_KEY (fallback + recherche :online)
- TINYFISH_API_KEY (N3 dernier recours uniquement), GEONAMES_USERNAME=BerryMappemonde
- Pas de GEMINI_API_KEY directe (le routage llm_core saute ce backend)

## Données restaurées (2026-08-26) — NE JAMAIS PURGER
- db.projects : 4463 projets (restaurés via POST /api/import/geojson)
- db.poe_ports : 1169 PoE géocodés restaurés + nouveaux extraits (upsert non-destructif)
- db.eez_zones : 285 zones VLIZ (référentiel rebuild), 165 en statut "ia" (backfill)
- Sauvegardes source : /tmp/projects_backup.geojson, /tmp/poe_backup.geojson
- Script restauration : python3 /app/scripts/restore_data.py {poe <file>|zones}

## Architecture Core (refactor 2026-08)
- llm_core.py : cascade LLM emergent→openrouter (+gemini si clé), gatekeeper, extract_ports, grounded_search
- geo_core.py : Nominatim→GeoNames, snap_to_ocean, point_in_eez, anomalies (IF/DBSCAN)
- dedup_core.py : Haversine<500m + fuzzy>60%, upsert non-destructif
- extract_core.py : cascade N1 (trafilatura/PyMuPDF) → N2 (Readability) → N3 (TinyFish capé 120s)
- rag_core.py : chunking 500c + sentence-transformers (all-MiniLM-L6-v2, installé), monitoring sémantique
- ml_core.py : gatekeeper TF-IDF+LogReg (modèle: backend/models/gatekeeper_tfidf_logreg.joblib, entraîné, acc=1.0)
- osm_validate.py : validation Overpass (miroir fr fonctionne depuis ce pod)

## Endpoints clés nouveaux
- GET /api/ml/status · POST /api/ml/train/gatekeeper · POST /api/ml/gatekeeper/predict {"text":...}
- POST /api/ml/anomalies/scan · GET /api/ml/anomalies/report · POST /api/ml/ner/export-dataset
- POST /api/poe/validate-osm {"limit":N} · GET /api/poe/validate-osm/status

## Avertissements testing
- NE PAS appeler POST /api/deploy avec clear_db=true (purge projets!)
- NE PAS lancer /api/poe/generate-batch sans limit (crédits LLM)
- SearXNG bloqué depuis le pod (fallback OpenRouter :online opérationnel)
- overpass.openstreetmap.fr = seul miroir Overpass accessible
