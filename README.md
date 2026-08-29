# Blue Intelligence

**Blue Intelligence** transforme le web vivant des données maritimes en une base géospatiale exploitable, présentée sur une carte mondiale interactive.

Application publiée sur **[blueintelligence.online](https://blueintelligence.online)** — un projet [Berry-Mappemonde](https://berrymappemonde.org).

## Les trois modes

| Mode | Couleur | Contenu |
|------|---------|---------|
| **Projets** | cyan | ~4 500 projets de conservation marine découverts et extraits automatiquement depuis les portails des grandes fondations (swarm d'agents web + LLM) |
| **Marinas** | rouge | Marinas et points d'amarrage le long de la route Berry-Mappemonde, curatés depuis OpenStreetMap/SHOM et enrichis par IA (canal VHF, places visiteurs, services…) |
| **Formalités** | ambre | Les ~285 Zones Économiques Exclusives mondiales (Marine Regions v12) et leurs **Ports d'Entrée officiels** pour la plaisance, extraits des sources gouvernementales |

S'y ajoute une **Console de supervision** (déclencheurs batch, télémétrie, KPIs) et des exports/imports GeoJSON contextuels.

## Architecture

```
blue-intelligence/
├── backend/            API FastAPI (Python 3.11+) + MongoDB
│   ├── server.py       Point d'entrée, endpoints REST /api/*
│   ├── llm_core.py     Adaptateur LLM unique — tous les appels IA passent par OpenRouter
│   ├── pipeline.py     Swarm de découverte/extraction des projets marins
│   ├── poe.py          Pipeline [ZEE → Ports d'Entrée] (poe_routes.py = endpoints)
│   ├── marinas.py      Build marinas (Overpass/SHOM), anchorages.py (mouillages)
│   ├── enrichment.py   Enrichissement marinas (OpenRouter → TinyFish → tags OSM)
│   ├── geo.py / geo_core.py       Géocodage, snap côtier, validation spatiale
│   ├── extract_core.py            Cascade de parsing N1 trafilatura → N2 Readability → N3 TinyFish
│   ├── dedup_core.py / rag_core.py / ml_core.py   Dédup, RAG local, modèles ML locaux
│   ├── zee.py          Traversées ZEE de la route officielle
│   ├── data/           Référentiels embarqués (route, ZEE, marinas curatées)
│   └── models/         Modèles ML locaux entraînés (gatekeeper, classifieur SERP, NER)
├── frontend/           React (CRA) + Leaflet + Tailwind
│   └── src/components/ MapView, BatchHub (audit), SettingsPanel, panneaux par mode
├── docs/               PRD, guidelines de design, architecture
└── scripts/            Outillage d'exploitation (restauration de sauvegardes)
```

### Intelligence artificielle : 100 % OpenRouter

Tous les appels LLM (gatekeeper marin, extraction structurée, géocodage intelligent, recherche web groundée `:online`, enrichissement des marinas) passent par **[OpenRouter](https://openrouter.ai)** :

- **Clé** : `OPENROUTER_API_KEY` (ou saisie dans l'UI, Paramètres → Clés API) ;
- **Modèle** : `OPENROUTER_MODEL` (défaut `openai/gpt-4o-mini`) — changer de modèle ne demande aucune modification de code ;
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
| `OPENROUTER_API_KEY` | recommandé | Clé OpenRouter — moteur LLM unique de l'application |
| `OPENROUTER_MODEL` | optionnel | Modèle OpenRouter (défaut `openai/gpt-4o-mini`) |
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
- `GET /api/poe/zones` · `POST /api/poe/zones/{mrgid}/generate` · `GET /api/poe/ports` — mode Formalités
- `POST /api/poe/runs` · `GET /api/poe/runs/{id}/status` · `GET /api/poe/runs/{id}/diff` · `GET /api/poe/runs/{id}/report` — runs versionnés PoE
- `GET /api/export/{geojson|marinas.geojson|poe.geojson}` — exports GeoJSON

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
