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

Certains jobs posent la même question (« où est la page ? », « quel texte a-t-on ? », « est-ce le bon objet ? ») mais ont été écrits chacun dans leur mode. Ils peuvent s’aligner sur les mêmes outils, sans devenir un seul gros pipeline.

### 1. Lire une page web

Quand Projets ou le PoE top-down veulent le texte d’une URL, ils passent par `extract_cascade` : d’abord un téléchargement simple, puis trafilatura ou Readability, puis le PDF (PyMuPDF, Tesseract si besoin), puis Playwright si la page est en JavaScript, puis un miroir Jina ou TinyFish Fetch, puis Wayback. Le PoE bottom-up, l’enrichissement capitainerie, la visite AMP et le signal Maps des marinas font presque la même chose — obtenir du texte — mais appellent TinyFish Fetch tout seuls. L’enrichissement marina, lui, se contente de `fetch_readable` (httpx + Readability). Les capitaineries ont déjà commencé à emprunter cette fonction aux marinas, en repli.

Conséquence : un décret PDF trouvé par le bras bottom-up, ou un site de marina tout en JavaScript, casse plus facilement que la même page vue par le swarm ou par le top-down. L’objectif n’est pas trois lecteurs, c’est une seule porte : « voici une URL, donne-moi le texte ». Cette porte, c’est `extract_cascade`. TinyFish Fetch tout seul reste légitime seulement quand on a vraiment besoin du DOM rendu, comme la page Google Maps `/place/`.

### 2. Chercher la page officielle d’un nom

Le PoE bottom-up, les capitaineries, les AMP et, en dernier recours, l’enrichissement marina cherchent tous « la page officielle de *ce* nom ». Ils ne s’y prennent pas de la même façon. Le bottom-up n’utilise que TinyFish Search, filtré par une whitelist, sans filet si la clé manque. Les capitaineries font TinyFish Search, puis DuckDuckGo HTML si ça revient vide, et filtrent avec une liste de bouts d’URL maison au lieu de `serp_filter`. Les AMP font TinyFish Search, passent les hits dans `serp_filter`, puis un score, et n’ont pas de DuckDuckGo. L’enrichissement marina ne cherche même pas avec TinyFish : si OSM n’a pas de site, il tape DuckDuckGo. Le top-down PoE est un autre métier : il cherche une *liste d’État pour un polygone*, avec SearXNG, Serper, parfois TinyFish, et `:online` en dernier.

L’alignement utile, c’est donc pour les recherches *nommées* (bottom-up, capitaineries, AMP, marina sans site) : TinyFish Search, le filtre `serp_filter` déjà partagé par le top-down et les AMP, et DuckDuckGo seulement quand il n’y a pas de clé TinyFish. On n’installe pas SearXNG sur les marinas, les capitaineries ou les AMP : cet outil sert une liste réglementaire par ZEE, pas une fiche d’un lieu.

### 3. Remplir téléphone, VHF et services depuis un site

`marina_enrich` et `capitainerie_enrich` sont déjà les plus proches. Les deux refusent d’inventer un champ, les deux passent par la chaîne NIM `page`, puis OpenRouter avec un garde-fou de crédit, puis un Agent TinyFish en dernier recours. Ils partagent déjà DuckDuckGo et `fetch_readable`.

Ils divergent sur l’ordre. Les capitaineries cherchent le web avant de lire, parce qu’elles n’ont souvent pas d’URL. Les marinas lisent d’abord le tag OSM, et ne cherchent sur DuckDuckGo que s’il n’y a pas de site. Les capitaineries extraient téléphone et VHF par regex *avant* d’appeler le LLM ; les marinas appellent le LLM d’abord et ne tombent sur les tags OSM qu’en repli. L’Agent marina peut partir d’une URL trouvée sur DuckDuckGo ; l’Agent capitainerie n’accepte qu’un site officiel.

On peut viser le même enchaînement partout : partir des tags ; chercher seulement s’il n’y a pas d’URL ; lire la page (Fetch ou cascade) ; extraire par regex ce qui est trivial (un numéro, un canal) ; puis NIM `page`, OpenRouter, et l’Agent seulement si l’URL est officielle.

### 4. Décider si c’est le bon objet ou la bonne page

Trois jobs disent oui ou non après avoir vu des résultats ou du texte, avec trois prompts et trois rôles NIM différents. Le gatekeeper Projets demande : est-ce un projet marin ? Le juge bottom-up demande : ce lieu est-il un port d’entrée plaisance, ou du cargo ? Le juge AMP demande : parmi *ces* URL déjà trouvées, laquelle est une page de visite — et il n’a pas le droit d’en inventer une. Cette dernière règle (choisir dans une liste fermée) est celle qu’il faut garder pour ne pas halluciner une `visit_url`.

On n’écrit pas un seul prompt pour les trois. On écrit un même adaptateur — un JSON du type « j’accepte ou je refuse, éventuellement cette URL, voici pourquoi » — et on laisse les trois schémas et les chaînes NIM (`judge`, `json`, gatekeeper) telles qu’elles sont.

### 5. Balayer le monde avec Overpass

Les dumps marinas, capitaineries et mouillages partagent déjà la grille mondiale et Overpass. Ce n’est pas là que ça diverge. Ce qu’il ne faut pas fusionner, c’est la règle d’identité : coller un point SHOM ou NOAA sur un OSM à 250 mètres, ce n’est pas la même chose que fusionner deux projets à moins de 500 mètres avec un nom proche. Le premier est un overlay de cartes ; le second est un doublon métier.

### 6. Poser un GPS dans le bon espace

Projets et PoE utilisent Nominatim et GeoNames, mais pas la même fonction. Projets appelle `geocode()` l’un après l’autre, puis un LLM si besoin, puis vérifie qu’on est en mer ou dans un havre à moins de 15 km. Le PoE (top-down et bottom-up) appelle `geocode_port_dual` en parallèle, départage au LLM s’il y a désaccord, puis exige que le point tombe dans *ce* polygone de ZEE.

Les deux géocodeurs peuvent devenir le même appel parallèle. Ce qui doit rester différent, c’est le test d’espace : « accessible en bateau » d’un côté, « dans ce polygone VLIZ » de l’autre.

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
