# Cahier des charges — Projets de conservation marine

Document de cadrage du mode **Projets** de Blue Intelligence.
Il relit le code, le PRD, l’architecture, le seed GeoJSON, et le cahier des charges Formalités (PoE).
Il est écrit en langage simple : c’est le contrat de ce que l’on cherche, et de ce que l’on refuse.

Version 1.0 — 7 septembre 2026. Document **complet** (objet, stratégies, règles, outils, code, données, interface, recette, risques, annexes).

**Sommaire**

1. En une phrase
2. Pourquoi ce travail existe
3. Ce que l’on veut obtenir
4. Ce que l’on ne veut pas
5. Vocabulaire
6. Les deux stratégies
7. Règles
8. Sources et outils
9. Le code — où vit chaque brique
10. Score S_ocean
11. Contraintes dures
12. Critères d’acceptation
13. État actuel et écarts
14. Ordre de travail recommandé
15. Documents et conversations dont ce cahier hérite
16. Qui fait quoi
17. Cycle de vie d’un projet
18. Le second livrable : les portails financeurs
19. Algorithme (découverte, extraction, Follow the Money)
20. Modèle de données
21. Ce que voit l’utilisateur
22. Inventaire des MasterSeeds
23. Gatekeeper et taxonomie
24. Exemples concrets
25. Recette
26. Risques
27. Hors périmètre
28. Annexes

---

## 1. En une phrase

Retrouver **tous les projets de conservation, restauration ou protection marine réellement menés** (un projet = une page, un lieu, un financeur), les poser sur la carte mondiale, et **ne jamais y coller** un programme terrestre, une page d’accueil, ou un point GPS inventé.

---

## 2. Pourquoi ce travail existe

Les grandes fondations océaniques publient leurs actions sur des dizaines de sites, dans des langues et des structures différentes : listing `/projects`, campagnes, Hope Spots, programmes CORDIS, pages « where we work ». Il n’existe pas de carte mondiale unique, à jour, de ces projets.

Blue Intelligence les cartographie pour l’expédition Berry-Mappemonde et, plus largement, pour quiconque veut voir **où** se fait le travail de conservation marine, **qui** le finance, et **sur quelle page** le lire. Les points restent **indicatifs** : un GPS de projet n’est pas une frontière d’AMP, ni une preuve juridique.

Le stock actuel (~4 463 projets, ~860 financeurs) est à la fois le livrable v1 **et** le jeu d’entraînement du gatekeeper marin. Le perdre, c’est perdre les deux.

---

## 3. Ce que l’on veut obtenir

Deux livrables, indissociables :

1. **La carte des projets marins.**
   Pour chaque projet : titre officiel, URL canonique, description courte (impact écologique), financeur(s), lieu, coordonnées en mer ou sur le littoral, catégorie, image si la page en a une, score S_ocean, et d’où vient le GPS.

2. **Les portails qui les listent.**
   Pour chaque organisation MasterSeed (et, plus tard, chaque partenaire découvert) : l’URL du listing, la date du dernier scan, les pages projet déjà vues (`deeplink_pages`), pas la home « À propos / Donate ».

Un projet sans GPS précis n’est pas un échec : on le géocode, on le recale à la côte si besoin, on **étiquette** le recale. Un projet clairement terrestre est un échec du filtre, pas un point à publier.

---

## 4. Ce que l’on ne veut pas

- Des **projets terrestres ou d’eau douce** (montagne, forêt intérieure, lac, bassin fluvial) présentés comme marins, sauf estuaire à impact côtier direct.
- Des **pages génériques** : home de fondation, actualités, dons, jobs, boutique, FAQ, mentions légales.
- Un **point dans l’océan au hasard** (`ocean_fallback_coords`) affiché comme un site réel.
- Une carte qui **écrase** `projects` par un `clear_db` ou un `DELETE /api/projects`.
- Republier Wikipedia, TripAdvisor, ou un communiqué de presse sans page projet.
- Inventer un titre, un GPS, ou un partenaire absents de la page.
- Coller le siège social d’une ONG (Washington, Londres, Paris) à la place du récif / de l’AMP.
- Le mode Marinas (corridor de route) et le mode Formalités (PoE) : autres produits.

---

## 5. Vocabulaire

| Mot | Sens ici |
|-----|----------|
| **Projet** | Une action marine **individuelle** (restauration, AMP, campagne, recherche appliquée, pêche durable…) décrite sur **une** URL. |
| **Portail / MasterSeed** | Site d’une fondation ou d’un institut dont on parcourt le listing. Les 21 graines sont dans `static_data/seeds.py`. |
| **Financeur** | Organisation rattachée au projet (`funder` + tableau `funders`). Un même projet peut en avoir plusieurs après fusion. |
| **Swarm** | Pipeline de découverte + extraction. Mode `test` (3 graines, 6 URLs/graine) ou `full` (21 graines, 20 URLs/graine). |
| **Carte v1** | Collection `projects` actuellement affichée (~4 463 points). Trésor d’entraînement. Aucune purge. |
| **DeepLinkCache** | Collection `deeplink_pages` : URLs projet déjà vues, avec financeur et source. |
| **Gatekeeper** | Filtre marin vs terrestre, avant toute extraction. ML local → LLM → heuristique. |
| **S_ocean** | Score 0–1 de pertinence marine (technicité + fiabilité de source + localisation océanique). |
| **Snapped** | Le GPS a été recalé vers la mer (`snap_to_ocean`) parce que le géocodeur a posé le point à terre. |
| **Follow the Money** | Découverte récursive d’un **partenaire** nommé sur une page projet, hors MasterSeeds, plafonnée. |
| **Run** | Génération versionnée dans un espace à part. **N’existe pas encore** pour les projets (écart). |
| **Gold Dataset** | Revue humaine d’un échantillon. Il n’existe pas encore. La carte v1 n’en est pas un, même si elle entraîne le ML. |

---

## 6. Les deux stratégies

On ne choisit pas l’une ou l’autre. On les **fait travailler ensemble**.

Le Top-Down répond : *« Ce portail de fondation, quelles pages projet publie-t-il ? »*

Le Bottom-Up répond : *« Cette URL déjà connue, est-ce vraiment un projet marin à cartographier ? »*

### 6.1 Top-Down — du portail vers les pages

On part d’une **organisation**, pas d’un nom de projet.

1. Prendre un MasterSeed (nom, URL de listing, pays, priorité, catégorie d’origine).
2. **Découvrir** les URLs projet : crawler HTTP gratuit d’abord (liens internes `/project`, `/campaign`, `/initiative`…) ; TinyFish Agent seulement si le crawler rend 0 URL (sites JS / pagination).
3. Écrire chaque URL dans `deeplink_pages` (cache) et la mettre en file.
4. **Télécharger** la page (cascade N1 trafilatura ∥ N2 Readability → N3 Chromium → miroir Jina / TinyFish Fetch). Jeter les interstitiels anti-bot.
5. **Filtrer** (gatekeeper marin). Rejeter le terrestre.
6. **Extraire** (LLM JSON, ou heuristique sans clé) : titre, description ≤ 250 c., lieu, GPS si écrits, catégorie, partenaires.
7. **Géocoder** si pas de GPS : lieu → Nominatim/GeoNames → estimation LLM → **pas** un océan aléatoire comme point publié.
8. Recaler à la mer si le point est à terre, **en le marquant** `snapped`.
9. **Dédupliquer** (URL, ou nom proche + < 500 m) : fusionner les financeurs, ne pas dupliquer.
10. Stocker **sans détruire** l’existant.

Question métier : *quels projets marins cette organisation mène-t-elle réellement, et où ?*

Le Top-Down est le seul moyen de **découvrir une page nouvelle**. Il est aussi bruyant : homes, campagnes-pays, sièges sociaux. D’où le gatekeeper et le Bottom-Up.

### 6.2 Bottom-Up — de l’URL déjà connue vers la preuve

On part des **projets et URLs déjà retrouvés**, et on demande pour chacun : *est-ce que CETTE page est un projet marin cartographiable ?*

Les graines viennent de l’union :

- la **carte v1** (`projects`) ;
- le **DeepLinkCache** (`deeplink_pages`) ;
- les **signalements** skipper (`reported_projects`, file « Projet manquant ? ») ;
- la **file d’échecs** (`failed` : gatekeeper, extract, discover) ;
- plus tard un **export GeoJSON** réimporté (upsert non destructif).

Ensuite, pour le résidu (page jamais extraite, ou projet pauvre / périmé) :

1. re-télécharger l’URL (enrich à la demande, ou Force Extract TinyFish si la cascade a échoué) ;
2. gatekeeper **toujours** (y compris sur Force Extract) ;
3. extraire et, si les champs nouveaux sont meilleurs, **mettre à jour sans effacer** ce qui était déjà bon ;
4. ne pas bouger le GPS d’un projet v1 sauf si le nouveau point est clairement meilleur (lieu plus spécifique, pas un siège, pas un fallback).

Le juge (ici : gatekeeper + extracteur) ne reçoit pas le badge « déjà en carte ». On évite le biais de confirmation. La carte v1 sert **après**, pour la dédup et le score.

### 6.3 Comment les deux se recoupent

| | Top-Down | Bottom-Up |
|---|---|---|
| Point de départ | un portail MasterSeed | une URL / un projet déjà vu |
| Question | quelles pages projet ? | cette page est-elle un projet marin ? |
| Produit principal | URLs nouvelles + extraits | verdict + enrichissement |
| Faiblesse | bruit, homes, pagination JS | ne découvre pas un portail inconnu |
| Force | trouve les listings | capitalise le stock déjà payé |

L’algorithme cible :

- faisceau **L** (listing) : toutes les pages que le portail présente comme projet / campagne / initiative ;
- faisceau **M** (marin) : celles qui passent le gatekeeper et ont un lieu océanique ou côtier ;
- on les mène **en parallèle**, on compare, on tranche les discordants.
- Une page L rejetée par M **ne va pas** sur la carte (elle peut rester dans `failed` / cache).
- Une page M sans listing MasterSeed (signalement communautaire) reste une **graine**, extraite comme les autres, avec `funder = "Community Report"`.

---

## 7. Règles

### 7.1 Un projet de ce produit est une action marine située

Règle d’or : **on ne publie sur la carte Projets que des actions de conservation / restauration / protection / recherche marine, océanique ou côtière, avec une URL et un lieu défendable.**

Conséquences :

- Forêt intérieure, montagne, savane, lac : **non**.
- Estuaire, mangrove, delta, blue carbon côtier : **oui**.
- Programme mondial sans site unique : **oui**, mais le GPS doit être un site représentatif **écrit** ou un lieu nommé, pas un océan aléatoire ; `location` peut dire « global ».
- Listing « where we work » pays entier : extraire les **sites**, pas le centroïde du pays.
- Siège de l’ONG : **jamais** comme GPS du projet.
- Page actualité / don / recrutement : **non** (blacklist de crawl + gatekeeper).

### 7.2 Sources

- Extraire **depuis la page du projet**. Chaque entrée cite son `url`.
- Le financeur vient du MasterSeed (ou du signalement), pas d’une invention.
- OSM, Nominatim, GeoNames **prouvent un lieu**, pas que c’est un projet de conservation.
- Ne jamais inventer un titre hors page. Conserver l’orthographe officielle.
- TinyFish Agent = **dernier recours** (découverte JS, Force Extract), pas le moteur quotidien.

### 7.3 Géographie

Le point doit être **en mer ou sur le littoral** du site du projet :

- déjà océanique : on le garde ;
- à terre : `snap_to_ocean` jusqu’à une distance raisonnable (réglage `max_coast_km`, défaut 50 km **métier** ; le code actuel élargit trop — voir § 13) ;
- trop loin à l’intérieur : **rejeté** ou laissé en graine sans publication, pas un snap de 500 km ;
- GPS (0, 0) : invalide ;
- **interdit en publication** : `ocean_fallback_coords` (quatre rectangles océaniques hashés sur le titre). C’est un filet de debug, pas un lieu.

Contrairement au mode Formalités, le snap côtier **est** légitime ici : un projet « Banc d’Arguin » géocodé sur la ville doit pouvoir glisser vers l’eau adjacente, **badge `snapped` visible**.

### 7.4 Carte et runs

- `projects` : **aucune purge**, upsert / insert non destructif. Les champs déjà remplis (image, catégorie, GPS v1) sont conservés sauf enrichissement **meilleur**.
- Un run from scratch **devrait** écrire dans `project_run_*`, jamais dans la carte. Aujourd’hui le swarm écrit **directement** dans `projects` : écart majeur, à corriger.
- Interdit : `clear_db=true` sur `/api/swarm/deploy`, `DELETE /api/projects`, `/api/deploy clear_db=true`.
- Import GeoJSON : skip URL déjà connue, fusion titre proche + cellule 0,1°, backfill catégorie seulement si vide.

### 7.5 Page sans projet extractible

Qualifier, ne pas inventer : `rejected` (gatekeeper), `failed` (fetch/extract), `generic` (home / don). Garder l’URL dans le cache ou la file d’échec pour un retry, **ne pas** créer de point.

---

## 8. Sources et outils

### 8.1 Ce qui nourrit les listes (preuves)

| Outil | Rôle | Ce que ce n’est pas |
|-------|------|---------------------|
| **Pages projet des fondations** | Seule **preuve** du projet (titre, texte, image, liens) | — |
| **Crawler HTTP N1** | Découverte gratuite des liens internes | Ne rend pas le JS / la pagination infinie |
| **TinyFish Agent** | Découverte JS si N1 = 0 ; Force Extract d’une URL déjà connue | Pas un crawl mondial quotidien |
| **Cascade N1/N2/N3** | Texte de la page (trafilatura ∥ Readability → Chromium → miroir) | N’invente pas de champs |
| **OpenRouter** | Gatekeeper LLM, extraction JSON, géocodage intelligent | Éteint sans `OPENROUTER_API_KEY` |
| **Gatekeeper ML** | TF-IDF + LogReg entraîné sur la carte v1 ; décision sans LLM si score ≥ 0,85 ou ≤ 0,12 | Biaisé par la v1 : un faux positif v1 se reproduit |
| **Playwright / Chromium** | Rendu local des pages JS, gratuit | Sauté sur challenge Akamai dur |
| **RAG local** | Pages > 6 000 c. : seuls les chunks marins partent au LLM | Ne remplace pas le gatekeeper |

### 8.2 Ce qui nourrit les graines et le contrôle (signaux)

| Outil | Rôle | Attention |
|-------|------|-----------|
| **MasterSeeds** | 21 portails curés (priorité 1 et 2) | Liste courte ; Follow the Money l’étend un peu |
| **Carte v1** | ~4 463 projets, ~861 financeurs, seed `seed/projects.geojson` | Ne jamais l’écraser |
| **DeepLinkCache** | URLs déjà vues, rejouées en mode `full` si pas encore en carte | Peut contenir des homes |
| **Signalements** | Skipper : nom + URL → file + email Resend optionnel | Pas Gold. Gatekeeper au prochain run |
| **Nominatim** | Géocodage OSM, ~1 req/s, cache Mongo | Peut pointer la ville / le HQ |
| **GeoNames** | Second géocodeur | Accord < 2 km = bon signal |
| **snap_to_ocean** | Recale un point terrestre vers l’eau | Trop large aujourd’hui (jusqu’à 500 km) |
| **dedup_core** | Haversine < 500 m + similarité > 60 %, ou similarité > 90 % | Le swarm ne fusionne que `funders` |

### 8.3 Ce qui est volontairement exclu de la découverte

`CRAWL_BLACKLIST` dans `seeds.py` : contact, about, privacy, donate, blog, news, team, login, shop, event, job, press, faq, cookies, newsletter, sitemap, search, tag.

On peut **lire** une page d’actualité si quelqu’un la signale ; on ne la **parcourt** pas depuis un listing.

Claude Haiku n’est **pas** un outil Projets (budget PoE seulement).

---

## 9. Le code — où vit chaque brique

Le backend est dans `backend/app/`. `backend/server.py` ne fait que charger l’application.

### 9.1 Swarm (pipeline portail → carte)

Fichier : `backend/app/services/swarm_pipeline.py`

| Fonction / méthode | Rôle |
|--------------------|------|
| `Swarm.deploy` | Démarre test/full ; **refuse** si déjà running ; option `clear_db` (à interdire) |
| `Swarm.stop` | Annule workers et file |
| `_run` | Charge les seeds, file, workers, attend Follow the Money |
| `_discover` | TTL `rescan_after_days` (défaut 7 j) ; N1 crawler puis TinyFish si vide |
| `_crawl_discover` | Liens internes, motifs `URL_PATTERNS`, sinon 8 liens hors blacklist |
| `_tinyfish_discover` | SSE d’abord, polling 360 s sinon ; schéma `{projects:[{url,title}]}` |
| `_extract_worker` | Consomme la file |
| `_process_url` | Skip si URL déjà en carte → cascade → gatekeeper → RAG → extract → géocode → snap → dédup → insert |
| `_dedup_merge` | `is_duplicate` puis `$set` des financeurs seulement |
| `_queue_partner` | Follow the Money, `max_partner_orgs` (défaut 5), depth=1, 6 URLs |
| `_bump_saturation` | Auto-stop après N extractions sans **nouveau** projet (défaut 50) ; un skip URL ne compte pas |

Modes :

- `test` : `MASTER_SEEDS[:3]`, `test_max_urls_per_seed` (6) ;
- `full` : 21 seeds, `full_max_urls_per_seed` (20), rejoue le DeepLinkCache.

### 9.2 API Projets et Swarm

| Fichier | Rôle |
|---------|------|
| `routers/projects.py` | Liste GeoJSON, financeurs, catégories, import/export, enrich, signalement |
| `routers/swarm.py` | deploy / stop / status, stats, telemetry, failed, Force Extract |
| `routers/ml.py` | Entraînement / prédiction gatekeeper (et NER, SERP, anomalies — partagés) |

Endpoints utiles :

- `GET /api/projects` · `GET /api/funders` · `GET /api/categories`
- `POST /api/import/geojson` · `GET /api/export/geojson`
- `POST /api/projects/{id}/enrich` · `GET .../enrich/status`
- `POST /api/report-project` · `GET /api/reports`
- `POST /api/swarm/deploy` · `POST /api/swarm/stop` · `GET /api/swarm/status`
- `GET /api/stats?mode=projects` · `GET /api/telemetry` · `GET /api/failed`
- `POST /api/failed/{id}/force` · `POST /api/failed/force-all`
- `DELETE /api/projects` — **dangereux**, UI Settings l’a retiré, l’API reste

### 9.3 Cœur partagé

| Fichier | Fonctions utiles aux projets |
|---------|------------------------------|
| `core/extract.py` | `extract_cascade`, `looks_blocked`, `page_metadata` (`ext_links`) |
| `core/geo.py` | `geocode`, `is_ocean`, `snap_to_ocean`, `ocean_fallback_coords` (à ne plus publier) |
| `core/llm.py` | `gatekeeper_check`, `extract_project`, `heuristic_*`, `llm_geocode` |
| `core/ml.py` | `train_gatekeeper`, `predict_relevance` — dataset = titres/descriptions v1 |
| `core/dedup.py` | `is_duplicate`, `merge_docs` (ce dernier **n’est pas** utilisé par le swarm) |
| `core/rag.py` | `select_context` au-delà de 6 000 caractères |
| `core/tinyfish.py` | `discovery_goal`, `extract_goal`, `DISCOVERY_SCHEMA`, `EXTRACT_SCHEMA`, SSE |
| `static_data/seeds.py` | `MASTER_SEEDS`, `URL_PATTERNS`, `CRAWL_BLACKLIST`, `TEST_SEED_COUNT` |
| `static_data/categories.py` | `CATEGORY_GROUPS`, `normalize_category` |

### 9.4 Frontend

| Fichier | Rôle |
|---------|------|
| `components/SwarmPanel.js` | Bandeau : recherche, financeur, légende-filtre, liste, bouton signalement |
| `components/ProjectList.js` | 100 premières lignes filtrées |
| `components/map/useProjectsLayer.js` | Clusters, couleur de catégorie, popup, bouton enrich |
| `components/audit/ProjectsCard.js` | Console : test/full, deploy/stop, réglages swarm + filtre marin |
| `components/ReportModal.js` | Formulaire « Projet manquant ? » |
| `components/AuditView.js` | KPIs, télémétrie, Force Extract |
| `App.js` | `__biEnrichProject` (poll 202) |

Le mode **Marinas** et le mode **Formalités** ne partagent avec Projets que le cœur (extract, geo, LLM, dédup). Un projet n’est pas une marina ; une marina n’est pas un projet.

---

## 10. Score S_ocean

Ce n’est pas une vérité scientifique. C’est un faisceau 0–1, écrit par l’extracteur (LLM) ou, sans clé, recopié du score heuristique du gatekeeper.

| Brique | Idée |
|--------|------|
| Gatekeeper | Le texte est-il marin ? Seuil `min_marine_score` (défaut 0,5). ML local si très sûr. |
| Extracteur | `s_ocean` : technicité + fiabilité de source + localisation océanique. |
| Carte | Point océanique ou `snapped` ; géocodeurs d’accord. |
| Catégorie | Une des 9 familles ; `normalize_category` recase les libellés libres. |

Un projet vu seulement par heuristique (pas de LLM) reste moyen. Une page fondation + lieu nommé + GPS océanique monte.

Le seuil `min_marine_score` **coupe** à l’entrée (gatekeeper). Il ne masque pas a posteriori les points déjà en carte. Changer le curseur Console ne réécrit pas les 4 463 S_ocean.

---

## 11. Contraintes dures

1. **Les données en base sont un trésor.** 4 463 projets + 1 171+ PoE : aucune purge.
2. **Marin seulement.** Le gatekeeper avant l’insert, y compris Force Extract et signalements.
3. **Une URL = une preuve.** Pas de projet sans `url` http(s). Pas d’invention de titre / GPS.
4. **OpenRouter est le moteur LLM Projets.** Claude est réservé aux PoE. Sans clé : heuristique + ML, l’app reste utilisable.
5. **TinyFish est un scalpel** : découverte si crawler vide, Force Extract ciblé, cap d’agents (1–2).
6. **Un seul chef de file** pour Deploy / Force Extract All / import massif.
7. Mentions carte : données **indicatives**. Un point n’est pas le périmètre de l’AMP.

---

## 12. Critères d’acceptation

On considère le travail réussi pour un **portail** quand :

1. On a identifié **la page de listing** utile (pas la home), mémorisée dans `discovery_state`.
2. Les pages projet individuelles sont en DeepLinkCache.
3. Chaque projet **marin** de ce listing est sur la carte (titre + URL + GPS défendable + financeur + catégorie).
4. Les pages terrestres / génériques n’y sont pas.
5. Un visiteur peut cliquer un point et voir **pourquoi** on y croit (URL + S_ocean + badge snapped).
6. La carte v1 n’a pas été vidée par un batch.

À l’échelle monde : couverture des 21 MasterSeeds (et partenaires plafonnés), file `failed` traitée ou volontairement reportée, signalements extraits, **aucun** `geo_source = ocean-region-fallback` publié.

---

## 13. État actuel et écarts

### Déjà en place

- Swarm Top-Down : MasterSeeds, crawler N1, TinyFish N3 de secours, TTL 7 jours, DeepLinkCache, workers concurrents.
- Cascade d’extraction partagée avec les PoE (N1/N2/N3 + miroir), gatekeeper ML → LLM → heuristique.
- Géocodage cascade (extrait → lieu → LLM → titre), snap côtier, dédup spatio-textuelle.
- Follow the Money (max 5 partenaires, depth 1).
- Auto-stop saturation (défaut 50).
- Carte Leaflet : catégories, financeurs, recherche, clusters, plafond `max_markers` (1 000).
- Enrichissement à la demande (popup ↻).
- Crowdsourcing « Projet manquant ? » + email Resend + file.
- Import/export GeoJSON non destructif (4 463 dans `seed/projects.geojson`).
- Console : test/full, logs, télémétrie, Force Extract.
- Gatekeeper entraîné sur ~4 462 projets (acc. rapportée 1,0 — à relire : le jeu est biaisé).

Répartition seed (7 septembre 2026, 4 463 points) :

| Catégorie | n |
|-----------|---|
| Research | 890 |
| Conservation | 765 |
| Policy & Advocacy | 490 |
| Other | 474 |
| MPA | 402 |
| Pollution | 391 |
| Coastal & Habitat | 389 |
| Fisheries | 361 |
| Education | 301 |

### Écarts par rapport à ce cahier

| Écart | Détail |
|-------|--------|
| **Écriture directe dans `projects`** | Pas d’espace `project_run_*`. Un swarm `full` insère en live. PoE a déjà les runs isolés : à calquer. |
| **`clear_db` et `DELETE /api/projects`** | Toujours dans l’API / la case Console. Le bouton Settings « tout vider » a été retiré : **garder l’API fermée** (404 ou garde-fou). |
| **`ocean_fallback_coords` publié** | Si tout géocodage échoue, le swarm pose un point dans un rectangle océanique hashé. Interdit en carte. Laisser `lat/lon` nuls, ou graine `name_only`. |
| **Snap trop large** | `max_km=max(500, max_coast_km*4)` : un HQ parisien peut atterrir en Manche. Plafonner au `max_coast_km` métier (50). |
| **Force Extract sans gatekeeper** | TinyFish Agent insère avec `s_ocean=0.7` fixe, sans catégorie. Doit passer par `_process_url`. |
| **Dédup pauvre** | Fusion = liste de financeurs. `merge_docs` existe et n’est pas appelé (description, image, catégorie perdues). |
| **Enrich ne géocode pas** | Re-extrait titre/description/lieu/catégorie/image/S_ocean, **ne bouge pas** le GPS. Souvent bien (non-destructif) ; un mauvais fallback v1 n’est jamais corrigé. |
| **Crawler superficiel** | Une page de listing, même hôte, pas de pagination. D’où TinyFish trop souvent. |
| **Pas de runs / promotion** | Contrairement aux PoE : pas de diff, pas de best-of, pas de revue → carte. |
| **Télémétrie sans `dataset`** | Les lignes swarm n’écrivent pas `dataset: "projects"` (le filtre stats rattrape l’absence de champ). À normaliser. |
| **Gold Dataset** | N’existe pas. La v1 entraîne le ML : les erreurs v1 se **renforcent**. |
| **Couche AMP retirée** | `/api/mpa` → 410. Le croisement projet ↔ polygone AMP est hors livrable actuel. |

---

## 14. Ordre de travail recommandé

1. **Neutraliser les purges** : ignorer `clear_db`, désactiver `DELETE /api/projects` (ou le protéger par un secret hors UI).
2. **Ne plus publier le fallback océan** : insert seulement si GPS géocodé ou extrait ; sinon DeepLinkCache + `failed`.
3. Caler `snap_to_ocean` sur `max_coast_km` (50 km), badge `snapped` inchangé.
4. Faire passer Force Extract **et** les signalements par le même `_process_url` (gatekeeper inclus).
5. Fusionner avec `merge_docs` (champs vides seulement).
6. Introduire des **runs isolés** (`project_runs` / `project_run_projects`), calqués sur `poe_runs`, puis promotion manuelle.
7. Approfondir le crawler (pagination, `?page=`, liens « load more » simples) pour moins dépendre de TinyFish.
8. Revue d’un échantillon v1 (sièges sociaux, fallback, `Other`) → Gold Dataset pour ré-entraîner le gatekeeper.
9. Enrichissement GPS **opt-in** (bouton déjà là) seulement si `geo_source` est faible.

---

## 15. Documents et conversations dont ce cahier hérite

- `docs/PRD.md` — deux pipelines, contrainte non-destructivité, historique 2026-08.
- `docs/ARCHITECTURE.md` — rangement `swarm_pipeline`, routers `projects` / `swarm`.
- `docs/CAHIER_DES_CHARGES_POE.md` — même contrat de forme ; Formalités est l’**autre** produit.
- `README.md` — les trois modes (Projets cyan, Marinas, Formalités).
- `seed/projects.geojson` — 4 463 features, vérité de restauration.
- Décisions : cascade N1→N3 pour économiser TinyFish, gatekeeper ML bootstrappé, Follow the Money, saturation auto-stop, retrait du bouton « vider », crowdsourcing projets (le PoE n’en a pas encore).

Ce cahier **prime** sur les détails d’implémentation dès qu’il y a conflit (ex. « fallback océan pour toujours avoir un point » vs « pas de GPS inventé » ; « clear_db pratique en test » vs « trésor »).

---

## 16. Qui fait quoi

| Acteur | Ce qu’il fait | Ce qu’il ne fait pas |
|--------|----------------|----------------------|
| **Visiteur** (carte publique) | Consulte les projets, filtre, ouvre l’URL source, signale un oubli. | Ne lance pas le swarm. Ne vide pas la base. |
| **Opérateur** (Console) | Lance un swarm **test**, puis full sans `clear_db`, Force Extract ciblé, import GeoJSON, enrich. Un seul chef de file. | N’envoie pas `clear_db`. Ne clique pas Force All à l’aveugle (crédits TinyFish). |
| **Gatekeeper** (ML / OpenRouter / heuristique) | Dit si **cette page** est marine. | N’invente pas de titre. Ne géocode pas. |
| **Extracteur LLM** | Remplit titre, description, lieu, GPS écrits, catégorie, partenaires. | N’invente pas de coordonnées hors page (le géocodeur s’en charge ensuite). |
| **Réviseur humain** | Tranche les `failed`, les sièges sociaux, les `Other`. Promeut un run vers la carte (quand les runs existeront). | Ne « goldise » pas tout le seed d’un coup. |
| **Pipeline** | Découvre, télécharge, filtre, extrait, géocode, fusionne. | Ne purge jamais `projects`. |

---

## 17. Cycle de vie d’un projet

Une URL ne naît pas projet carte. Elle traverse des états.

```
URL (listing, cache, signalement)
    → téléchargée (cascade, pas un challenge)
        → acceptée par le gatekeeper
            → extraite (titre, lieu, catégorie)
                → géocodée (extrait / Nominatim / LLM) — pas de fallback océan
                    → recalée mer si besoin (snapped)
                        → dédupliquée (URL ou nom+distance)
                            → insérée ou fusionnée
                                → enrichie plus tard si la page a changé
```

| État | Sens | Où ça vit |
|------|------|-----------|
| `cached` | URL vue, pas encore extraite | `deeplink_pages` |
| `queued` | Dans la file du swarm vivant | `Swarm.queue` |
| `rejected` | Gatekeeper : pas marin | `failed` (stage `gatekeeper`) |
| `failed` | Fetch / extract cassé | `failed` (stage `discover` / `extract`) |
| `merged` | Doublon : on a ajouté un financeur | `projects` + télémétrie `MERGED` |
| **sur la carte** | Document `projects` | mode Projets |
| `enriched` | Re-extrait à la demande | champs `enriched`, `enriched_at` |
| `reported` | Signalement skipper, pas encore extrait | `reported_projects` + cache |

Un `rejected` **reste en `failed`**. On ne le publie pas, on ne le détruit pas.

Déduplication : même URL, **ou** similarité de titre ≥ 90 %, **ou** < 500 m et similarité ≥ 60 %. On fusionne les financeurs (et, cible, les champs vides via `merge_docs`).

---

## 18. Le second livrable : les portails financeurs

Le visiteur ne doit pas seulement voir des points. L’opérateur doit voir **quel listing** a été lu.

Pour chaque MasterSeed on veut, au minimum :

| Champ | Sens |
|-------|------|
| `name` / `url` | Identité du portail |
| `country` / `priority` | Curés dans `seeds.py` |
| `last_scan` | Dernier passage découverte |
| `urls_found` / `new_urls` | Compteurs du scan |
| `listing_kind` | `projects_index` · `campaigns` · `hope_spots` · `grants` · `where_we_work` · `other` |
| `engine` | `crawler` ou `tinyfish` |

Aujourd’hui c’est éparpillé : `MASTER_SEEDS`, `discovery_state`, `deeplink_pages`. Le cahier demande d’en faire **une fiche portail**, visible en Console (nombre de projets par graine, âge du scan, 0 URL = alerte).

Règles de la fiche :

- une home « About / Donate » **n’est pas** un listing ;
- si le crawler rend 0 et TinyFish aussi : `urls_found = 0`, pas d’invention ;
- Follow the Money crée une fiche **partenaire** distincte, plafonnée, jamais un 22ᵉ MasterSeed silencieux.

Le Top-Down sert à **remplir ces fiches**. Le Bottom-Up s’en sert pour savoir quelles URLs retry.

---

## 19. Algorithme (découverte, extraction, Follow the Money)

### Faisceau L — listing

Entrée : URL MasterSeed.

Sortie : URLs canoniques (sans `#` ni query), même hôte, chemin qui ressemble à un projet.

Outils : crawler (motifs `/project`, `/campaign`, `/initiative`, `/hope-spot`, `/programs`, `/grants`, `/projets`, `/nos-actions`…) ; TinyFish `discovery_goal` si vide, en mode incrémental (exclure les URLs déjà cachées).

### Faisceau M — marin cartographiable

Entrée : une URL L (ou un signalement).

Sortie : document projet, ou rejet.

Étapes : cascade texte → gatekeeper → RAG si long → `extract_project` → géocode → snap borné → dédup.

### Follow the Money

Si l’extracteur renvoie jusqu’à 3 `partners` avec URL, et que le domaine n’est pas déjà connu, on lance **une** découverte depth=1 (6 URLs) tant que `partner_count < max_partner_orgs`.

Ce n’est pas un crawl du web entier. C’est un saut vers l’ONG **nommée sur la page**.

### Décision

| L | M | Décision |
|---|---|----------|
| oui | oui | **projet carte** (ou fusion) |
| oui | non | `failed` / `rejected` — listing générique ou terrestre |
| non | oui | signalement ou partenaire : extraire comme les autres |
| non | non | ignoré |

Cas Ocean Foundation : listing `/projects/` → beaucoup de L. M écarte les pages « our team ».

Cas siège Pew à Washington : L oui, lieu = HQ → M doit **refuser le GPS ville** et chercher le site marin, ou rester sans point publié.

---

## 20. Modèle de données

MongoDB. On n’invente pas une sixième collection à chaque idée : on réutilise, et on ajoute des runs **sur le modèle PoE** le jour où on les code.

### Carte (v1) — ne pas écraser

| Collection | Une ligne = |
|------------|-------------|
| `projects` | un projet **publié** (titre, url, lat/lon, financeurs, catégorie, S_ocean) |

Clé métier : **`url`** (dédup primaire). Secondaire : titre+distance.

Champs utiles d’un `projects` :

- identité : `_id`, `title`, `url`, `description`, `funder`, `funders`
- carte : `lat`, `lon`, `location`, `snapped`, `geo_source`
- preuve : `image`, `engine`, `extract_level`, `s_ocean`
- classe : `category`, `category_group`
- dates : `created_at`, `enriched`, `enriched_at`, `enrichment_source`

`geo_source` observé ou cible : `extracted` · `geocoded:location` · `llm-geocoded` · `geocoded:title` · `import` · `tinyfish-force` · ~~`ocean-region-fallback`~~ (à cesser).

GeoJSON public (`project_to_feature`) : Point `[lon, lat]`, propriétés `id`, `title`, `url`, `description`, `funder` (financeurs joints), `location`, `s_ocean`, `snapped`, `image`, `category`, `category_group`.

### Espace de travail

| Collection | Une ligne = |
|------------|-------------|
| `deeplink_pages` | une URL découverte (`url`, `funder`, `source`, `ts`) |
| `discovery_state` | un portail scanné (`seed_url`, `last_scan`, compteurs) |
| `telemetry` | un essai d’agent (`url`, `engine`, `status`, `duration_ms`) — ajouter `dataset: "projects"` |
| `failed` | une URL en échec (`stage`, `reason`, `funder`) |
| `reported_projects` | un signalement skipper |
| `settings` | `_id: global` (concurrence, saturation, seuils marins, clés) |
| `jobs` | (PoE surtout) — à réutiliser si enrich batch un jour |
| `geocode_cache` | Nominatim / GeoNames, TTL 180 j / 14 j |

Cible (pas encore créé) : `project_runs`, `project_run_projects`, sur le modèle `poe_runs` / `poe_run_ports`.

### Fichiers à côté de la base

- `backend/app/static_data/seeds.py` — 21 MasterSeeds + motifs + blacklist
- `backend/app/static_data/categories.py` — 9 groupes + couleurs + règles
- `backend/models/gatekeeper_tfidf_logreg.joblib` — classifieur marin
- `seed/projects.geojson` — restauration 4 463 features

Réglages défaut (`DEFAULT_SETTINGS`) : `tinyfish_agents=2`, `extract_concurrency=6`, `max_coast_km=50`, `min_marine_score=0.5`, `test_max_urls_per_seed=6`, `full_max_urls_per_seed=20`, `follow_the_money=true`, `max_partner_orgs=5`, `saturation_limit=50`, `rescan_after_days=7`, `max_markers=1000`.

---

## 21. Ce que voit l’utilisateur

### Visiteur — mode Projets (cyan)

- Carte mondiale, clusters, points colorés par `category_group`.
- Bandeau gauche : compteur, recherche, filtre organisation (~861 noms), légende cliquable = filtre catégorie, liste (100 lignes).
- Popup : image, titre, financeur, badge snapped, catégorie, description, lien source, S_ocean, bouton ↻ enrichir.
- Pied : **Signaler un projet oublié** (nom + URL + description).
- Plafond d’affichage : `max_markers` (défaut 1 000) — le reste reste en base, pas sur la carte.

### Opérateur — Console

- Test / Full, Deploy, Stop, logs live, agents, file.
- Case « Vider la base avant de démarrer » : **à traiter comme un piège** jusqu’à suppression.
- Réglages : agents TinyFish (1–2), concurrence 1–20, Follow the Money, plafond partenaires, auto-stop, TTL rescan, `max_coast_km`, `min_marine_score`.
- KPIs : extractions, taux de succès, items mapped.
- Télémétrie + file `failed` + Force Extract (clé TinyFish obligatoire).
- Paramètres transverses : import/export GeoJSON du mode actif, zoom, clés API.

Ce qui **manque** à l’UI (écart) : fiche par MasterSeed, écran de revue, runs isolés, bouton **Promouvoir vers la carte**, filtre `geo_source`, masquage des fallback océan.

---

## 22. Inventaire des MasterSeeds

Liste curée au 7 septembre 2026 (`MASTER_SEEDS`, 21 portails). Priorité 1 = cœur ; 2 = extension.

| Nom | Pays | Prio | Listing |
|-----|------|------|---------|
| The Ocean Foundation | US | 1 | `oceanfdn.org/projects/` |
| Oceana | US | 1 | `oceana.org/campaigns/` |
| Blue Marine Foundation | UK | 1 | `bluemarinefoundation.com/projects/` |
| Fondation de la Mer | FR | 1 | `fondationdelamer.org/` |
| Pure Ocean Foundation | FR | 1 | `pure-ocean.org/` |
| Fondation CMA CGM | FR | 1 | `cmacgm-group.com/fr/fondation` |
| IFREMER | FR | 1 | `ifremer.fr/fr` |
| Prince Albert II Foundation | MC | 1 | `fpa2.org/en/initiatives` |
| Institut Océanographique Paul Ricard | FR | 2 | `institut-paul-ricard.org/` |
| SHOM | FR | 2 | `shom.fr/fr` |
| CORDIS Europe | EU | 2 | `cordis.europa.eu/projects/en` |
| Coral Reef Alliance | US | 2 | `coral.org/en/where-we-work/` |
| Mission Blue | US | 2 | `missionblue.org/hope-spots/` |
| Seacology | US | 2 | `seacology.org/projects/` |
| Ocean Conservancy | US | 2 | `oceanconservancy.org/programs/` |
| Pew Charitable Trusts | US | 2 | `pewtrusts.org/en/projects` |
| WWF Oceans | INT | 2 | `worldwildlife.org/initiatives/oceans` |
| Packard Foundation | US | 2 | `packard.org/what-we-fund/ocean/` |
| Rare Fish Forever | US | 2 | `rare.org/program/fish-forever/` |
| Fauna & Flora Oceans | UK | 2 | `fauna-flora.org/environments/oceans/` |
| Wildlife Conservation Society Marine | US | 2 | `wcs.org/our-work/oceans` |

Mode **test** = les **3 premiers** seulement.

Ajouter un 22ᵉ portail se fait **ici** (table) puis dans `seeds.py`, pas en dur dans le swarm. Un partenaire Follow the Money n’entre dans cette table que par revue humaine.

Le SHOM et l’IFREMER sont des instituts, pas des fondations : on n’y cherche pas des « grants », on y cherche des **programmes / campagnes** marins. Si le listing n’en a pas, 0 URL est un succès honnête.

---

## 23. Gatekeeper et taxonomie

### Gatekeeper

Trois étages, dans l’ordre :

1. **ML local** (`predict_relevance`) si le modèle a ≥ 500 positifs : accepté si score ≥ 0,85, rejeté si ≤ 0,12.
2. **OpenRouter** : « marine/ocean/coastal conservation, restoration or protection ? » — rejets montagne / lac / rivière sauf estuaire côtier. Seuil `min_marine_score`.
3. **Heuristique** : compteurs `MARINE_KW` vs `LAND_KW`, au moins 3 hits marins et score ≥ seuil. Repli si pas de clé ou LLM en échec.

Le modèle s’entraîne sur les **titres + descriptions déjà en carte** (positifs) et les `failed` gatekeeper + corpus terrestre synthétique (négatifs). Conséquence : **ne pas y mettre de terrestes**, sinon le classifieur les aime.

### Neuf familles (`CATEGORY_GROUPS`)

| Groupe | Couleur carte | Indices (normalize_category) |
|--------|---------------|------------------------------|
| MPA | `#00f0ff` | protected area, mpa, hope spot |
| Conservation | `#39ff14` | conserv, species, wildlife, whale, shark, turtle… |
| Research | `#c084fc` | research, science, monitor, expedition, survey |
| Fisheries | `#fbbf24` | fisher, bycatch, aquaculture |
| Policy & Advocacy | `#f472b6` | policy, advocacy, legislation, governance |
| Pollution | `#ff4a4a` | pollution, plastic, debris, spill |
| Coastal & Habitat | `#34d399` | coastal, mangrove, reef, seagrass, blue carbon… |
| Education | `#60a5fa` | educat, awareness, outreach, citizen |
| Other | `#94a3b8` | rien n’a matché |

L’extracteur doit renvoyer **exactement** un de ces libellés. `normalize_category` rattrape le libre. 474 `Other` dans le seed : dette de classification, pas un groupe métier noble.

---

## 24. Exemples concrets

### Hope Spot Mission Blue

Listing `missionblue.org/hope-spots/` : chaque Hope Spot = un projet. Lieu = le spot, GPS en mer ou `snapped` depuis la côte. Catégorie MPA. Pas le bureau de l’ONG.

### CORDIS

Listing européen bruyant (tous projets UE). Le gatekeeper doit **jeter** l’aéronautique et garder l’océano. Si le crawler ramène des homes CORDIS, M = non.

### Signalement skipper

Un visiteur envoie « Coral Gardeners Moorea » + URL. → `reported_projects` + `deeplink_pages` (`Community Report`). Si le swarm tourne, file immédiate ; sinon, prochain `full`. Même règle M que les MasterSeeds.

### Siège à terre

Géocodeur pose « Ocean Conservancy » sur Washington D.C. Aujourd’hui : snap vers la baie de Chesapeake à des dizaines/centaines de km, `snapped=true`. Cible : si `coast_distance_km` > `max_coast_km`, **pas de point publié**, `location` textuel conservé.

### Fallback océan

Titre sans toponyme, pas de `location`. Aujourd’hui : point hashé dans un des 4 rectangles (Pacifique, Atlantique, Indien…). Cible : rester `cached` / `failed`, jamais un îlot fantôme au milieu du Pacifique.

---

## 25. Recette

On ne « sent » pas que le mode Projets est bon. On coche.

### Pour un portail (recette unitaire)

1. Fiche seed : `last_scan` récent, listing URL stable.
2. Chaque projet carte issu de ce portail a : titre, URL http(s), GPS océanique ou snapped **borné**, `funders` contenant le seed, `category_group` ∈ 9 familles, `s_ocean`.
3. Aucune page about/donate. Aucun GPS (0,0). Aucun `ocean-region-fallback`.
4. Popup : lien source cliquable + S_ocean.
5. `projects` n’a pas perdu un point v1 de ce financeur, sauf rejet **écrit**.

### Pour un swarm (recette run)

1. `clear_db` n’a **pas** été envoyé (idéalement : le backend l’ignore).
2. Mode test : ≤ 3 seeds, ≤ 6 URLs/seed.
3. Compteurs SUCCESS / MERGED / REJECTED / FAILED journalisés.
4. Skip URL déjà en carte **sans** incrémenter la saturation.
5. Gatekeeper : `accepted=false` ⇒ pas d’insert.
6. Tests automatiques verts (ci-dessous).

### Interdit pendant la recette

Cocher « Vider la base ». `DELETE /api/projects`. Force Extract All sans quota. Relancer un `full` « pour voir » sur la carte v1.

Commande locale :

```bash
cd backend && python3 -m pytest tests/test_blue_intelligence.py tests/test_import_and_regression.py tests/test_zoom_and_new_features.py tests/test_refactor_core.py -q
```

Ces tests exigent souvent l’API et Mongo (données v1 présentes). Ils **vérifient** que le stock n’a pas fondu (`>= 4463`).

---

## 26. Risques

| Risque | Effet | Parade déjà là / à faire |
|--------|--------|---------------------------|
| Purge `clear_db` / DELETE | Perte du jeu d’entraînement et de la carte | UI Settings déjà sans bouton ; **fermer l’API** ; runs isolés |
| Fallback océan | Points fantômes au milieu des bassins | Ne plus publier ; filtrer `geo_source` |
| Snap 500 km | HQ urbain → mer lointaine | Plafond `max_coast_km` |
| Terrestre en carte | Gatekeeper + ML contaminés | Seuil, revue `Other`, ré-entraînement sur Gold |
| TinyFish partout | Crédits, lenteur | N1 d’abord ; Agent seulement si 0 URL ou Force |
| Follow the Money | Dérive hors conservation | Plafond 5, depth 1, gatekeeper sur les pages partenaires |
| Saturation trop basse | Stop avant d’avoir vidé la file | 50 par défaut ; skip URL ne compte pas |
| Anti-bot | Texte vide, faux extraits | `looks_blocked`, Chromium, miroir, jamais ingérer l’interstitiel |
| Biais ML | La v1 se copie elle-même | Gold Dataset ; le LLM tranche la zone grise 0,12–0,85 |
| Import mal ciblé | GeoJSON marinas dans `projects` | Contrôle UI du mode actif |
| Enrich qui échoue au gatekeeper | Projet v1 « trop terrestre » à la relecture | Ne pas supprimer le point ; loguer l’erreur (comportement actuel) |
| Plafond 1 000 marqueurs | Le visiteur croit qu’il n’y a que 1 000 projets | Compteur bandeau = total base ; zoom / filtres |

---

## 27. Hors périmètre

Ce cahier **ne couvre pas** :

- le mode **Formalités** (PoE, ZEE, UNCLOS) — voir `docs/CAHIER_DES_CHARGES_POE.md` ;
- le mode **Marinas** / mouillages de la route Berry-Mappemonde ;
- la **couche polygones AMP** (retirée, `/api/mpa` = 410) ;
- le crowdsourcing PoE avec lien de loi (backlog P1 du PRD Formalités) ;
- Claude Haiku comme extracteur de projets ;
- la promotion automatique depuis un run (les runs n’existent pas encore) ;
- le croisement « un projet près d’un PoE » (idée P2 du PRD) ;
- un annuaire exhaustif de **toutes** les ONG marines du monde (seulement MasterSeeds + partenaires plafonnés + signalements).

---

## 28. Annexes

### A. Statuts télémétrie

| Status | Sens |
|--------|------|
| `SUCCESS` | Projet inséré |
| `MERGED` | Doublon fusionné |
| `REJECTED` | Gatekeeper |
| `FAILED` | Fetch / parse / extract / TinyFish |
| `CANCELLED` | Stop opérateur |

### B. API (rappel court)

Lecture carte : `GET /api/projects`.  
Écriture swarm : `POST /api/swarm/deploy` — **dangereux** si `clear_db`.  
Enrich : `POST /api/projects/{id}/enrich`.  
Signalement : `POST /api/report-project`.  
Import : `POST /api/import/geojson` (non destructif).  
Force : `POST /api/failed/{id}/force` (clé TinyFish).  
Interdit : `DELETE /api/projects`.

### C. Restauration

```bash
curl -X POST http://localhost:8001/api/import/geojson \
  -H "Content-Type: application/json" --data-binary @seed/projects.geojson
```

L’import saute les URLs déjà connues. Ce n’est pas une purge.

### D. Tests automatiques concernés

`backend/tests/test_blue_intelligence.py`, `test_import_and_regression.py`, `test_zoom_and_new_features.py` (catégories, report, saturation), `test_refactor_core.py` (compte ≥ 4 463, gatekeeper predict), `test_ml_jobs.py` (non-destructivité).

Il **manque** une suite unitaire du swarm (découverte, `_process_url`, interdiction du fallback) comparable à `test_poe_seeds.py`.

### E. Attribution

Projets : pages des organisations listées au § 22, extraites automatiquement.  
Géocodage : contributeurs OpenStreetMap (ODbL), Nominatim, GeoNames.  
Carte : Blue Intelligence / Berry-Mappemonde.  
Les descriptions sont des **synthèses** de pages publiques, pas des textes officiels des fondations.

---

*Fin du cahier des charges. Toute évolution de règle (plus de fallback océan, runs isolés, fermeture des purges, snap borné) se fait d’abord ici, puis dans le code.*
