# Blue Intelligence

**Blue Intelligence** transforme le web vivant des données maritimes en une base géospatiale exploitable, présentée sur une carte mondiale interactive.

Application publiée sur **[blueintelligence.online](https://blueintelligence.online)** — un projet [Berry-Mappemonde](https://berrymappemonde.org).

## Les quatre modes

| Mode | Couleur | Contenu |
|------|---------|---------|
| **Projets** | cyan | ~4 500 projets de conservation marine découverts et extraits automatiquement depuis les portails des grandes fondations (swarm d'agents web + LLM) |
| **Marinas** | rouge | Annuaire mondial `leisure=marina` (OpenStreetMap), identité `osm_id`, lien Google Maps déterministe. Point plus gros si une fiche `/maps/place/` a été trouvée (TinyFish Search / tag OSM) — on n'en filtre aucune. Les mouillages restent sur le corridor de la route. Hors Formalités / PoE. |
| **Capitaineries** | ciel | Bureaux `office=harbour_master` OSM (monde) + overlay SHOM CATSCF=6 (France). Téléphone et VHF lus dans les tags, puis les sites officiels. Pas de rattachement aux marinas. |
| **Formalités** | ambre | Les ~285 Zones Économiques Exclusives mondiales (Marine Regions v12) et leurs **Ports d'Entrée officiels** pour la plaisance, extraits des sources gouvernementales |

S'y ajoute une **Console de supervision** (déclencheurs batch, télémétrie, KPIs), un onglet **Review** (relecture puis Gold — voir `docs/CAHIER_DES_CHARGES_REVIEW.md`) et des exports/imports GeoJSON contextuels.

## Architecture

```
blue-intelligence/
├── backend/            API FastAPI (Python 3.11+) + MongoDB
│   ├── server.py       Point d'entrée, endpoints REST /api/*
│   ├── llm_core.py     Adaptateur LLM — NIM (complétions) ou OpenRouter ; :online reste OpenRouter
│   ├── pipeline.py     Swarm de découverte/extraction des projets marins
│   ├── poe.py          Pipeline [ZEE → Ports d'Entrée] (poe_routes.py = endpoints)
│   ├── marinas.py      Dump mondial OSM leisure=marina ; mouillages = corridor route
│   ├── enrichment.py   Enrichissement marinas (OpenRouter → TinyFish → tags OSM)
│   ├── geo.py / geo_core.py       Géocodage, snap côtier, validation spatiale
│   ├── extract_core.py            Cascade de parsing N1 trafilatura → N2 Readability → N3 TinyFish
│   ├── dedup_core.py / rag_core.py / ml_core.py   Dédup, RAG local, modèles ML locaux
│   ├── zee.py          Traversées ZEE de la route officielle
│   ├── data/           Référentiels embarqués (route, ZEE, marinas curatées)
│   └── models/         Modèles ML locaux entraînés (gatekeeper, classifieur SERP, NER)
├── frontend/           React (CRA) + Leaflet + Tailwind
│   └── src/components/ MapView, BatchHub (audit), SettingsPanel, panneaux par mode
├── docs/               PRD, CDC Projets, CDC Formalités (PoE), CDC Review, règles/paramètres, architecture
└── scripts/            Outillage d'exploitation (restauration de sauvegardes)
```

### Intelligence artificielle : NIM pour l'inférence, OpenRouter pour le web

Les complétions JSON (gatekeeper, extraction, géocodage, juge PoE) passent par **[NVIDIA NIM](https://build.nvidia.com)** si `NVIDIA_API_KEY` est présente, sinon par **[OpenRouter](https://openrouter.ai)**. La recherche web groundée (`:online`) reste OpenRouter :

- **Complétions** : `NVIDIA_API_KEY` (hosted NIM — Laguna / Muse / Kimi) si présente ; sinon OpenRouter ;
- **Recherche web** : `OPENROUTER_API_KEY` uniquement (`:online`) — NIM n'a pas de plugin web ;
- **Modèle OpenRouter** : `OPENROUTER_MODEL` (défaut `openai/gpt-4o-mini`) ;
- **Sans clé**, l'application reste fonctionnelle en mode dégradé : heuristiques par mots-clés + modèles ML locaux (TF-IDF, spaCy NER) sans aucun appel réseau IA.

Le pipeline **n'invente jamais de contenu** : chaque champ non trouvé dans les sources reste `null`, chaque port d'entrée est géocodé puis validé spatialement dans son polygone de ZEE.

## Démarrage local

### Prérequis

- Python 3.11+, Node.js 18+, MongoDB en local (ou MongoDB Atlas)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # rendu local des pages JS (pipeline PoE)
cp .env.example .env        # puis renseigner les variables (voir ci-dessous)
uvicorn server:app --host 0.0.0.0 --port 8001
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env        # laisser REACT_APP_BACKEND_URL vide (même-origine)
npm start                   # http://localhost:3000 (dev, hot reload)
```

### Preview Cloud Agent / accès distant (un seul port)

Pour visualiser l'application depuis l'interface Cursor (onglet **Ports** ou **Browser**) sans problème de `localhost` côté client :

```bash
bash .cursor/preview.sh     # build + UI + API sur http://localhost:8001
```

Ouvrir le port **8001** (« Application UI + API ») dans l'onglet **Ports** de la page de l'agent Cursor, puis cliquer sur le lien **Open in Browser**. L'UI et l'API partagent la même origine — aucun appel réseau vers `localhost:8001` depuis le navigateur distant.

Le serveur de dev CRA (port 3000) reste disponible pour le hot reload pendant le développement.

## Variables d'environnement (secrets)

### `backend/.env`

| Variable | Obligatoire | Rôle |
|----------|-------------|------|
| `MONGO_URL` | ✅ | Chaîne de connexion MongoDB |
| `DB_NAME` | ✅ | Nom de la base MongoDB |
| `CORS_ORIGINS` | ✅ | Origines autorisées, séparées par des virgules (`https://blueintelligence.online` en prod) |
| `NVIDIA_API_KEY` | recommandé | Clé NVIDIA NIM (`nvapi-…`) — juge / extracteur PoE (Muse, Kimi) |
| `LLM_PROVIDER` | optionnel | `auto` (défaut : NVIDIA si clé), `nvidia`, ou `openrouter` |
| `NVIDIA_MODEL` | optionnel | Lecteur principal (défaut `meta/muse-glimmer-30b`) |
| `NVIDIA_MODEL_SECONDARY` | optionnel | Recours juge si distinct du principal (défaut Muse ; Laguna hors service) |
| `NVIDIA_MODEL_LEGAL` | optionnel | Décrets / gazettes (défaut `moonshotai/kimi-k3`) |
| `OPENROUTER_API_KEY` | recommandé | Clé OpenRouter — recherche web `:online` et fallback si NIM absent |
| `OPENROUTER_MODEL` | optionnel | Modèle OpenRouter (défaut `openai/gpt-4o-mini`) |
| `ANTHROPIC_API_KEY` | optionnel | Claude Haiku 4.5 pour l'extraction PoE seulement — inerte si `CLAUDE_BUDGET_USD` (ou le plafond UI) est 0 |
| `CLAUDE_BUDGET_USD` | optionnel | Plafond local Claude (USD). Stop à 90 %. Défaut 0 = Claude éteint |
| `TINYFISH_API_KEY` | optionnel | Agent TinyFish (swarm projets & enrichissement marinas — le pipeline PoE utilise le rendu Playwright local) |
| `GEONAMES_USERNAME` | optionnel | Compte GeoNames (géocodage parallèle Nominatim ∥ GeoNames). Sur [geonames.org/manageaccount](https://www.geonames.org/manageaccount) : **Click to enable** le webservice gratuit — sans ça l'API renvoie l'erreur 10 et le pipeline désactive GeoNames pour le process |
| `SEARXNG_URL` | optionnel | Instance SearXNG auto-hébergée (voir `infra/searxng/`) — prioritaire sur les instances publiques pour la recherche PoE |
| `RESEND_API_KEY` | optionnel | Envoi d'emails de signalement de projets (Resend) |
| `SENDER_EMAIL` / `REPORT_RECIPIENT` | optionnel | Expéditeur / destinataire des signalements |

### `frontend/.env`

| Variable | Obligatoire | Rôle |
|----------|-------------|------|
| `REACT_APP_BACKEND_URL` | optionnel | URL publique du backend (sans slash final). **Laisser vide pour le mode même-origine** : en dev le proxy CRA route `/api` vers `localhost:8001`, en production le reverse proxy sert `/api/*`. Ne renseigner que si le backend vit sur un autre domaine |

## Déploiement sur blueintelligence.online

1. **Frontend** : `npm run build` → servir `frontend/build/` statiquement (Nginx, Netlify, Vercel…). Avec le reverse proxy ci-dessous, laisser `REACT_APP_BACKEND_URL` vide (mode même-origine).
2. **Backend** : `uvicorn server:app --host 0.0.0.0 --port 8001` derrière un reverse proxy qui route `/api/*` vers le port 8001 (le backend n'expose que des routes `/api/*`).
3. **MongoDB** : instance managée (Atlas) recommandée ; les index sont créés automatiquement au démarrage.

## API (aperçu)

- `GET /api/` — santé du service · `GET /docs` — OpenAPI interactif
- `GET /api/projects` · `GET /api/funders` · `GET /api/categories` — mode Projets
- `POST /api/swarm/deploy` · `GET /api/swarm/status` — pipeline de découverte
- `GET /api/marinas` · `POST /api/marinas/build` · `POST /api/marinas/enrich-batch` — mode Marinas
- `GET /api/capitaineries` · `POST /api/capitaineries/build` · `POST /api/capitaineries/enrich-batch` — mode Capitaineries
- `GET /api/poe/zones` · `GET /api/poe/ports` — mode Formalités (`POST …/generate` et `generate-batch` : 410)
- `POST /api/poe/runs` · `GET /api/poe/runs/{id}/status` · `GET /api/poe/runs/{id}/diff` · `GET /api/poe/runs/{id}/report` — runs versionnés PoE
- `GET /api/export/{geojson|marinas.geojson|capitaineries.geojson|poe.geojson}` — exports GeoJSON

## Données initiales (seed)

Le dossier `seed/` contient les exports GeoJSON de production :

```bash
# Projets (4 463) — via l'API
curl -X POST http://localhost:8001/api/import/geojson \
  -H "Content-Type: application/json" --data-binary @seed/projects.geojson
# Ports d'Entrée (1 169) + statuts des zones — via le script
python scripts/restore_data.py poe seed/ports_of_entry.geojson
python scripts/restore_data.py zones
```

Le référentiel des 285 ZEE se construit depuis la Console (mode Formalités → « Construire le référentiel ZEE »).

## Tests

```bash
cd backend && source .venv/bin/activate
python -m pytest tests/ -x -q          # certains tests exigent le serveur lancé (REACT_APP_BACKEND_URL)
```

## Données & attributions

- **ZEE** : Flanders Marine Institute — [Marine Regions](https://marineregions.org), Maritime Boundaries v12 (CC-BY 4.0)
- **Marinas / géocodage** : © contributeurs [OpenStreetMap](https://openstreetmap.org) (ODbL), Nominatim, Overpass, GeoNames
- **Route** : route officielle de l'expédition Berry-Mappemonde

> ⚠️ Les informations du mode Formalités sont **indicatives** — vérifiez toujours auprès des autorités avant le départ.
