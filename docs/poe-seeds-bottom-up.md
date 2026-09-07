# Vérification bottom-up des Ports d’Entrée

## En langage simple

On ne part plus d’une carte du monde découpée en zones (ZEE) pour demander à
une IA : « liste-moi tous les ports d’entrée de ce pays ».

On part de ce qu’on a **déjà trouvé** : la carte v1, les runs mondiaux
précédents, le listing communautaire Noonsite, et OpenStreetMap. Chaque lieu
connu devient une **graine** — une fiche. Sur cette fiche on garde toutes les
origines (qui l’a vu, sous quel nom, avec ou sans GPS, douane OSM à côté,
etc.). On n’écrase pas ça en un seul oui/non.

Ensuite, pour chaque fiche encore douteuse, on fait deux choses :

1. **TinyFish cherche ce lieu-là** — le nom du port, pas la zone entière.
   Noonsite est exclu : on a déjà extrait cette liste.
2. **Claude lit les pages trouvées** et répond seulement : *est-ce que CE
   lieu est un Port d’Entrée officiel ?* Oui, non, ou on ne peut pas dire.

Les ports déjà recoupés (listing + un run + coordonnées) ne sont pas
retouchés. La carte v1 (`poe_ports`) n’est jamais écrasée automatiquement.

C’est tout. Inventaire → recherche ciblée → jugement. Pas de découverte
mondiale, pas de canari sur les ZEE les plus dures.

---

## Pourquoi on a changé d’approche

L’ancien pipeline (top-down) faisait, pour chaque ZEE VLIZ :

recherche web de la zone → extraire une liste de ports → géocoder.

Le canari 12 ZEE visait justement les trous et les erreurs. Il mesurait le
pire cas, pas le monde. Relancer un 6ᵉ run mondial de découverte reproduisait
le même bruit, au risque de polluer v1.

Les sources existantes couvrent déjà une grande partie du listing (près de
la moitié après union, contre ~10 % sur le canari). Il manquait un
**inventaire unique** et une **vérification lieu par lieu**.

---

## Inventaire : une graine = un lieu

### Identité

Clé : `mrgid` VLIZ + nom normalisé (`dedup_key`, ex. `8447:alofi`).
VLIZ sert à savoir **où** est le port, pas à lancer un crawl de zone.

L’appariement est local à la ZEE (fuzzy + alias « Port of / Port de / (…) »).
Un même toponyme dans deux ZEE reste deux graines.

### Sources (union, pas intersection)

| Source | Collection / fichier | Ce qu’elle apporte |
|---|---|---|
| Carte v1 | `poe_ports` | Nom, coords, URLs — **intacte** |
| Runs mondiaux | `poe_run_ports` | Extraíts versionnés (5 runs 285 ZEE par défaut) |
| Listing Noonsite | `backend/data/listing_control/all_countries.json` | Rôle `poe` ou `other`, souvent sans GPS |
| OSM cache | Mongo `osm_port_seeds` | Havres commerciaux, `port_of_entry`, contrôles |
| Priors OSM | `backend/data/osm_port_priors.json` | Harbour / marina ≤ 800 m d’une douane ou `border_control` |

Une graine vue seulement par v1, seulement par OSM ou seulement par le
listing **reste** dans l’union. On ne jette pas un nom parce qu’une autre
source ne le connaît pas.

Chaque fusion ajoute une **observation** (origine, nom vu, coords, tags).
On n’aplatit pas listing / OSM / runs en un champ `is_poe`.

### Verdicts (tri du travail, pas une vérité officielle)

| Verdict | Règle | Action |
|---|---|---|
| `confirmed` | listing PoE ∩ (v1 \| run \| osm) **et** coordonnées | Auditer le GPS (homonymes Nominatim, inland_river) avant tout lot probable. |
| `probable` | OSM confiance ≥ 0,5, ou ≥ 2 sources extraites, ou listing ∩ extrait sans point | Plus tard, optionnel |
| `unverified` | Une seule source extraite + coords | Juger |
| `name_only` | Listing PoE sans point | Géocoder, puis juger |

Un jeton absent (`osm:customs`, `listing:poe`…) signifie **inconnu**, jamais
« faux ».

### Collection

`POST /api/poe/seeds/build` reconstruit `poe_seed_ports` (delete + insert).
Ne touche pas `poe_ports` ni `poe_run_ports`.

Chaque document porte au minimum :

- identité : `name`, `mrgid`, `zone_name`, `lat` / `lon`, `dedup_key`
- `seed_sources`, `observations`
- signaux OSM / listing
- `verify_verdict`
- `search_query` — **c’est ça que TinyFish doit chercher**
- `search_exclude_domains` : `noonsite.com`
- `seed_line` — résumé humain des jetons, **pas envoyé à Claude**

Mesure Atlas du 2026-09-06 (v1 + 5 runs + listing + priors OSM, cache OSM
Mongo vide) : **4027** graines — 592 confirmed, 1805 probable, 1058
unverified, 572 name_only.

Après le run name_only + reprise unverified : 33 `name_only` restants
(échec géocode). Dossier de revue : [`poe-name-only-33.md`](poe-name-only-33.md).

---

## Recherche : la graine pilote TinyFish

Pour une graine à vérifier :

```
{nom} official port of entry OR clearance OR "puerto habilitado" {zone}
```

Exemple : `Alofi official port of entry OR clearance OR "puerto habilitado" Niue`.

Aucun jeton listing/OSM dans la requête (ça biaiserait vers les forums).

### Filtres

1. **`exclude_domains=noonsite.com`** sur l’API Search TinyFish.
2. Filet côté client : toute URL `noonsite.com` est jetée avant Fetch.
3. Premier passage : `include_domains` = whitelist gouvernementale de la ZEE
   (ISO2 / souverain).
4. Si zéro hit officiel : même requête **sans** whitelist, toujours sans
   Noonsite.
5. Fetch : tous les hits whitelistés, cap 10, 150 URL/min.
6. Search : pagination (≤ 3 pages), 30 req/min PAYG, **une requête logique
   par graine**.

L’Agent TinyFish (lite puis stealth) n’est appelé que si Fetch renvoie
`bot_blocked`, sur **une** URL officielle déjà connue, 2 concurrents, cap
crédits.

---

## Jugement : Claude lit les extraits, pas la fiche

Claude reçoit uniquement :

- le nom du candidat
- la zone VLIZ (nom + ISO2)
- les extraits (pages Fetch, ou extraits Agent, ou à défaut snippets SERP)

Il répond en JSON strict :

```json
{"is_poe": true, "confidence": 0, "reason": "", "official_name": null}
```

- `true` : une source **officielle** désigne **ce** lieu comme PoE / clearance
  / puerto habilitado / designated port.
- `false` : marina, ville, autre pays, ou port sans désignation d’entrée.
- `null` : extraits insuffisants.

Escalade : Haiku → Sonnet si listing ou `inconclusive` → OpenRouter si échec
ou budget.

Les jetons `listing:poe` / `osm:customs` **ne vont pas** dans le prompt.
Les passer ferait confirmer Noonsite au lieu de lire l’officiel.

Après jugement :

- `accepted` + listing + coords → peut passer `confirmed`
- `accepted` sans listing → `probable`
- `rejected` → reste `unverified` (jamais promu tout seul)
- un `confirmed` existant n’est **jamais** rétrogradé

Écriture : `poe_seed_ports` (source `seeds`) ou `poe_run_ports` (run
versionné). **Jamais** `poe_ports`.

---

## Enchaînement d’un run

```
POST /api/poe/seeds/build          inventaire, 0 crawl
POST /api/poe/seeds/enrich         source=seeds
        name_only  → géocode → juge
        unverified → juge
        (probable optionnel)
```

Reprise : saute `geocoded_at` / coords déjà là, et `judge_status` déjà posé.

Lots : `limit: 200` possible. `limit: 0` = tout le verdict demandé, en
géocodant d’abord les `name_only` pour ne pas juger deux fois la même fiche.

Interdit pour la découverte mondiale : `POST /api/poe/runs` avec `limit: 0`,
`generate-batch`, `extract_ports` par ZEE.

Promotion vers la carte = **manuelle**.

---

## API

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/api/poe/seeds/build` | Reconstruit `poe_seed_ports` |
| GET | `/api/poe/seeds` | Lecture filtrable (`mrgid`, `verdict`) |
| GET | `/api/poe/seeds/line` | `search_query` + résumé humain |
| GET | `/api/poe/seeds/union` | Comptes sans persister |
| POST | `/api/poe/seeds/verify` | Option run versionné `poe_run_ports` |
| POST | `/api/poe/seeds/enrich` | Géocode + juge (`source=seeds` par défaut) |
| GET | `/api/poe/seeds/enrich/status` | Suivi (`run_id=seed-enrich`) |
| POST | `/api/poe/seeds/enrich/cancel` | Stoppe les graines pas encore parties |
| GET/POST | `/api/poe/seeds/osm` | Cache / refresh Overpass |

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `backend/app/services/poe_seeds.py` | Union, verdicts, `search_query`, persistance |
| `backend/app/services/poe_seed_enrich.py` | Géocode, Search/Fetch/Agent, juge |
| `backend/app/services/osm_seeds.py` | Cache Overpass v3 |
| `backend/app/core/tinyfish.py` | Search paginé, `exclude_domains`, Agent |
| `backend/app/core/claude.py` | `complete_json_claude` (juge Haiku/Sonnet) |
| `backend/app/routers/runs.py` | Routes ci-dessus |
| `backend/data/osm_port_priors.json` | 967 harbours/marinas près d’un contrôle |
| `backend/scripts/run_seed_enrich_full.py` | Enchaîne name_only puis unverified |

---

## Invariants

1. Aucun upsert automatique vers `poe_ports`.
2. Listing = signal, pas gold.
3. OSM = infra / prior, pas désignation (sauf `port_of_entry=yes` comme
   signal fort, pas comme verdict seul).
4. Noonsite absent des recherches TinyFish.
5. Une graine = une recherche = un jugement. Claude ne liste pas d’autres
   ports.
6. Hints SERP sans liste de noms de ports (leçon Niue / Mexique).
7. Runs versionnés comparables ; promotion carte manuelle.
