# Contrats des modes

**Ce que je cherche à faire.** Transformer le web maritime vivant en une base géospatiale fiable, posée sur une carte mondiale : sites d’action accessibles en bateau, ports d’entrée officiels, marinas, capitaineries, aires protégées — sans confondre un siège, une page institutionnelle ou un port commercial avec ce dont un plaisancier a besoin.

Les cinq modes ont été câblés séparément. Des jobs qui posent **la même question** n’utilisent pas les mêmes outils. Ce document recadre les pipelines sur **7 familles** (pas 5 : « qualification » ne doit pas devenir un fourre-tout), puis nomme les jumeaux à faire converger.

## Ce que chaque mode cherche

| Mode | Contrat |
| --- | --- |
| **Projets** | Trouver les projets de conservation marine financés par des fondations, extraire le **lieu d’action** (un GPS par page, pas le siège), n’en garder que ce qui est accessible en bateau, scorer (S_ocean), écrire un run isolé — sans vider la carte live. |
| **Ports d’entrée** | Pour **chaque polygone VLIZ** (`mrgid`, jamais un pays), retrouver la page ou le PDF d’État qui liste les ports d’entrée plaisance, et n’écrire un GPS que s’il tombe dans *ce* polygone. Top-down : polygone → liste. Bottom-up : lieu déjà connu → preuve, et catalogue entier si la page en est un. Noonsite, OSM et le WPI sont des signaux / contre-liste, pas une preuve. Publication carte = revue / Gold. |
| **Marinas** | Annuaire mondial `leisure=marina` (identité OSM stable), signal Google `/maps/place/` s’il existe vraiment, contacts et services **sans inventer**. Mouillages OSM à part, le long de la route. Runs isolés. |
| **Capitaineries** | Recenser les **bureaux** (le bâtiment, pas le plan d’eau ni la marina), en tirer téléphone et VHF, sans jamais les rattacher aux marinas. |
| **AMP** | Polygones ProtectedSeas sur une **façade** (pas le monde), et **deux URL distinctes** : gestionnaire (`manager_url`) vs visite / entrée / permis / mouillage (`visit_url`). La visite n’est jamais la homepage gestionnaire. |

Légende des jobs web : **P** Projets swarm · **TD** PoE top-down · **BU** PoE bottom-up · **MM** Marinas Maps · **ME** Marinas enrich · **CE** Capitaineries enrich · **AV** AMP visit.

Les dumps OSM (marinas, capitaineries, mouillages) et les polygones AMP n’enchaînent pas les 7 familles. Ce n’est pas un trou : ce n’est pas le même objet.

---

## 1. Recherche — où est la page ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | Découvrir les URL de projets sur chaque listing | Crawler httpx + BeautifulSoup sur un **MasterSeed déjà connu** ; TinyFish **Agent** si 0 URL |
| TD | Chercher l’URL d’État qui porte la liste | SearXNG + Serper ; TinyFish Search selon variante ; OpenRouter `:online` en dernier |
| BU | Chercher la page d’État de ce nom | TinyFish Search paginé (`tf_search_pages`) seulement |
| MM | Ouvrir le lien Maps et ramasser `/place/` | TinyFish **Fetch** d’une URL Maps **déjà construite** ; Search sauté |
| ME | Trouver un site s’il n’y a pas de tag OSM | DuckDuckGo HTML (pas TinyFish Search) |
| CE | Trouver des pages de contact | TinyFish Search, puis DuckDuckGo HTML si vide |
| AV | Chercher visite `site:` puis web ouvert | TinyFish Search seulement (pas DDG, pas SearXNG) |

## 2. Filtre de source — cette URL a-t-elle le droit d’être lue ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | Écarter contact / dons / news du listing | Liste noire de chemins **dans le crawler**, pas `serp_filter` |
| TD | Domaines d’État + jeter forums / OTA | Whitelist ISO2 + `serp_filter` + classifieur ML SERP |
| BU | Whitelist d’abord, puis sans si 0 hit | `include_domains` dans Search ; `url_allowed` ; **pas** `serp_filter` |
| MM | Une fiche marina proche, pas un resto | Nom / slug + 8 km |
| CE | Ignorer réseaux / OTA | `SEARCH_EXCLUDE_SNIPS` maison + `_url_ok` ; **pas** `serp_filter` |
| AV | Homepage interdite ; hits Search jugés | `serp_filter` **puis** score local **puis** juge NIM JSON |

## 3. Lecture — quel texte a-t-on ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P + TD | Extraire pages et PDF | **`extract_cascade`** : httpx, trafilatura ∥ Readability, PyMuPDF / Tesseract, Playwright, Jina ∥ TinyFish Fetch, Wayback |
| BU | Télécharger les hits whitelistés | TinyFish Fetch ; Agent si `bot_blocked`. **Pas** de cascade, **pas** Playwright |
| ME | Lire le site officiel | `fetch_readable` (httpx + Readability) seulement |
| CE | Télécharger les pages contact | TinyFish Fetch, **puis** `fetch_readable` si vide |
| MM | Lire la page Maps rendue | TinyFish Fetch (besoin du JS Maps) |
| AV | Lire le `manager_url` | TinyFish Fetch ; scoring **sans** LLM |

P et TD partagent déjà `extract_cascade`. ME / CE / BU / AV relisent le web avec trois autres chemins.

## 4. Filtre de contenu / objet — est-ce le bon objet ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | Projet marin, puis accessible en bateau | Gatekeeper ML → NIM → OpenRouter → Claude ; puis `site_publishable` |
| TD | L’objet « port » sort à l’extraction (le filtre fort est la source d’État) | Parseur catalogue / NER plus tard |
| BU | Juger seulement le résidu | NIM `judge` → OpenRouter → Claude |
| Dump marinas | Marina de plaisance | Overpass `leisure=marina` |
| Dump capitaineries | Bureau, pas plan d’eau | Overpass `office=harbour_master` (+ seamark / harbour) |
| Mouillages | Objet mouillage | Tags Overpass anchorage / baie nommée |
| AV (Fetch) | Lien visite dans le HTML | Score heuristique, pas de juge |
| AV (Search) | Bonne page visite | Juge JSON NIM → OpenRouter → Claude |

Le dump OSM et le juge LLM ne sont pas la même implémentation ; la **question** est la même.

## 5. Extraction structurée — quels champs ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | Nom, lieu, S_ocean, partenaires | NIM `extract` → OpenRouter → Claude ; heuristique |
| TD | Noms de ports (+ lat/lon dans le texte) | Parseur catalogue d’abord ; NIM `extract` / `legal` ∥ spaCy ; Claude en dernier |
| ME | VHF, places, tirant, services, tél | NIM `page` → OpenRouter → TinyFish Agent ; tags OSM |
| CE | Téléphone, canal VHF | Regex d’abord ; NIM `page` → OpenRouter → Agent ; tags |
| AV | Pas des champs métier : une URL | Liens extraits du Fetch ; pas de schéma JSON page |

ME et CE sont le jumeau « JSON sur du texte de page » (`page`). P et TD sont le jumeau « JSON métier sur un corpus long » (`extract`).

## 6. Géocodage — ce point est-il dans le bon espace ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | GPS du lieu d’action | `geocode()` Nominatim **puis** GeoNames ; LLM si besoin ; havre ≤ 15 km |
| TD | Coller le port dans **ce** polygone | `geocode_port_dual` Nominatim **∥** GeoNames ; départage LLM ; in-EEZ / 15 km / rivière 400 km |
| BU | Géocoder les noms sans point | **Le même** `geocode_port_dual` + filtre polygone |
| MM / dumps / AMP | — | GPS déjà dans OSM / SHOM / NOAA / ProtectedSeas |

P et PoE n’appellent pas le même géocodeur alors que la question « un point dans le bon espace » est la même (espace = havre vs polygone VLIZ).

## 7. Identité / doublon — est-ce déjà là ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P + TD | Fusionner deux fiches du même lieu | `app.core.dedup` : 500 m + similarité 60 % / 90 % |
| BU catalogue | Noms déjà sur la liste : juge sauté | Identité **de nom dans un catalogue**, pas un merge GPS |
| Dump marinas | Upsert | `osm_id` |
| Dump capitaineries | Coller SHOM / NOAA sur OSM | 0,25 km |
| Mouillages | Doublons de corridor | nom + geohash6 |
| AMP carte | Ne pas retélécharger | Cache tuile 30 j. (pas un merge d’entités) |

---

## Jumeaux réels (à faire converger)

Fonctions qui posent la même question et qui, dans le code, ont divergé.

### 1. Lecture web (famille 3) — le plus gros écart

`extract_cascade` (P, TD) vs `tf_fetch` (BU, CE, AV, MM) vs `fetch_readable` (ME, repli CE).

- CE a déjà importé `fetch_readable` depuis `marina_enrich`.
- BU, si Fetch est vide ou JS, n’a ni Playwright ni cascade : un décret PDF PoE BU est plus fragile qu’en TD.
- ME n’a pas Playwright : un site de marina tout JS échoue plus tôt que le swarm.

**Cible.** Une porte unique « donne-moi le texte » (`extract_cascade`, Fetch en miroir N3 comme aujourd’hui dans la cascade). TinyFish Fetch **seul** seulement quand on a besoin du DOM rendu (Maps `/place/`).

### 2. Recherche web ouverte (famille 1) — CE, AV, BU, et le DDG de ME

Tous cherchent « la page officielle de *ce* nom ».

| Job | Search payant | Filet gratuit | Filtre hits |
| --- | --- | --- | --- |
| BU | TinyFish Search | aucun | whitelist, pas `serp_filter` |
| CE | TinyFish Search | DuckDuckGo HTML | snips maison |
| AV | TinyFish Search | aucun | `serp_filter` + score |
| ME | aucun | DuckDuckGo HTML | — |
| TD | SearXNG + Serper ± TinyFish | `:online` | `serp_filter` + ML |

**Cible.** `tf_search` + `serp_filter` (déjà dans `extract.py`, déjà utilisé par TD et AV) + DDG comme filet **uniquement** si pas de clé TinyFish — le filet que CE a et que BU / AV n’ont pas.

**Ne pas** coller SearXNG sur CE / AV / ME : SearXNG chez TD sert une **liste d’État par polygone**, pas une fiche nommée.

### 3. Enrichissement page (familles 3+5) — `marina_enrich` et `capitainerie_enrich`

Déjà les plus proches : même chaîne NIM `page`, OpenRouter + crédit, Agent en dernier, « jamais inventé », DDG et `fetch_readable` partagés.

Écarts à refermer :

- CE cherche **avant** de lire (Search) ; ME lit le tag OSM d’abord, DDG seulement si pas de site.
- CE : regex **avant** le LLM ; ME : LLM d’abord, tags OSM en repli.
- ME : Agent peut partir d’une URL DDG ; CE : Agent seulement si site officiel.

**Cible.** Même squelette : `tags → (Search si pas d’URL) → Fetch/cascade → regex champs triviaux → NIM page → OpenRouter → Agent si URL officielle`.

### 4. Juge « est-ce la bonne page / le bon objet ? » (familles 2+4)

BU `judge`, AV juge JSON, P gatekeeper : trois prompts, trois rôles NIM, même idée — accepter ou jeter **après** lecture ou SERP.

- AV juge **parmi une liste fermée** d’URL (ne pas inventer) : bon modèle pour ne pas halluciner une `visit_url`.
- BU juge un **lieu** (plaisance vs cargo).
- P juge un **projet marin**.

**Cible.** Un contrat juge commun `{accept, url?, reason}` + chaînes NIM déjà dans `CHAINS`. Pas un seul prompt : trois schémas, **un** adaptateur.

### 5. Dumps Overpass tuilés

`marina_world`, `capitainerie_world`, `anchorage_build` partagent déjà `WORLD_TILES` / Overpass. Les fusions 0,25 km capitaineries ne doivent **pas** copier le `dedup` 500 m des projets : ce n’est pas le même grain (overlay SHOM vs deux projets au même GPS).

### 6. Géocodeurs (famille 6)

`geocode()` séquentiel (P) vs `geocode_port_dual` parallèle (TD/BU). Même Nominatim + GeoNames. P n’a pas le départage LLM ni le polygone.

**Cible.** `geocode_port_dual` (ou un `geocode_pair`) partout, puis **prédicat d’espace** différent (`site_publishable` vs in-EEZ).

---

## Ce qu’il ne faut pas unifier

- **MM Fetch Maps** : il faut un navigateur (TinyFish) sur une URL Google, pas `extract_cascade` sur un HTML d’État.
- **Dumps OSM** : ce n’est pas de la recherche web ; Overpass est le bon outil.
- **Cache tuile AMP** : ce n’est pas un merge d’entités.
- **SearXNG sur l’enrich marina / capitainerie** : mauvais outil (pas une liste réglementaire par ZEE).
- **Playwright sur chaque Fetch TinyFish** : coût ; le garder dans la cascade quand httpx / Fetch suffisent.

---

## Ordre d’amélioration

1. **Lecture.** Brancher CE / ME / BU (PDF, JS) sur `extract_cascade` là où TinyFish Fetch ne rend pas un décret / un site JS.
2. **Recherche nommée.** `tf_search` + `serp_filter` + DDG filet pour CE, AV, ME (et BU filet DDG si pas de clé).
3. **Enrich ME/CE.** Un seul orchestrateur `page`.
4. **Géocode P** → dual + prédicat havre.
5. **Juge.** Adaptateur commun, prompts séparés.
