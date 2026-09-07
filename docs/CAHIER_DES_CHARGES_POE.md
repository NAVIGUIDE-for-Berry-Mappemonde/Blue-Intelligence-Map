# Cahier des charges — Ports d’Entrée plaisance

Document de cadrage du mode **Formalités** de Blue Intelligence.
Il relit le code, le PRD, l’architecture, et les décisions des agents précédents.
Il est écrit en langage simple : c’est le contrat de ce que l’on cherche, et de ce que l’on refuse.

Version 1.1 — 6 septembre 2026. Document **complet** (objet, stratégies, règles, outils, code, données, interface, recette, risques, annexes).

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
10. Score de confiance
11. Contraintes dures
12. Critères d’acceptation
13. État actuel et écarts
14. Ordre de travail recommandé
15. Documents et conversations dont ce cahier hérite
16. Qui fait quoi
17. Cycle de vie d’un port
18. Le second livrable : les sources officielles par ZEE
19. Algorithme des deux faisceaux (D et P)
20. Modèle de données
21. Ce que voit l’utilisateur
22. Inventaire OpenStreetMap
23. World Port Index et UN/LOCODE
24. Exemples concrets
25. Recette
26. Risques
27. Hors périmètre
28. Annexes

---

## 1. En une phrase

Pour chaque Zone économique exclusive (ZEE) du monde, retrouver **tous les Ports d’Entrée officiels utilisables par un bateau de plaisance étranger**, et **les pages d’État qui les listent**.

---

## 2. Pourquoi ce travail existe

Il n’existe pas de liste mondiale unique, officielle et à jour, des ports où un yacht étranger peut accomplir ses formalités (douane, immigration, clearance).

Chaque État désigne ses propres points d’entrée, dans sa langue, sur ses propres supports : site des douanes, gazette, décret, PDF, arrêté, portail maritime. Ces listes changent. Certaines parlent de plaisance. D’autres listent tous les ports désignés, y compris des terminaux de commerce.

Blue Intelligence cartographie ces listes pour l’expédition Berry-Mappemonde et, plus largement, pour tout skipper qui traverse des ZEE. Les informations restent **indicatives** : on vérifie toujours auprès des autorités avant le départ.

---

## 3. Ce que l’on veut obtenir

Deux livrables, indissociables, **par ZEE** (identifiant VLIZ `mrgid`) :

1. **La liste des Ports d’Entrée (PoE) officiels pour la plaisance.**
   Pour chaque port : nom officiel, ville si connue, coordonnées, ZEE d’appartenance, URLs des sources, score de confiance, et d’où vient le signal (extraction, OSM, listing, run, juge).

2. **Les sources officielles qui listent ces ports.**
   Pour chaque ZEE : la ou les pages d’État réellement utiles (décret, gazette, liste douanière, catalogue SCT, etc.), pas un forum, pas un blog, pas Noonsite.

Une ZEE sans port physique n’est pas un échec : on la qualifie en droit (UNCLOS : île inhabitée, revendication chevauchante, régime conjoint, entrée via l’État souverain, Antarctique).

---

## 4. Ce que l’on ne veut pas

- Des **ports de commerce ou industriels** présentés comme PoE plaisance (terminaux conteneurs, pétroliers, minéraliers, pêche industrielle), sauf si l’État les désigne **aussi** pour les navires de plaisance étrangers.
- Toutes les **marinas OSM** du monde. Une marina n’est un PoE que si une source officielle (ou un faisceau équivalent) dit qu’on peut y faire sa clearance.
- Les **aéroports**, bureaux de poste, postes-frontières terrestres, ports d’un autre pays cités par comparaison.
- Une carte qui **écrase** la base actuelle (`poe_ports`) par un crawl automatique.
- Republier Noonsite, ni le traiter comme une vérité officielle.
- Inventer un nom de port absent des extraits.

---

## 5. Vocabulaire

| Mot | Sens ici |
|-----|----------|
| **ZEE** | Polygone maritime d’un État ou territoire, référentiel Marine Regions / VLIZ v12 (~285 zones). Clé : `mrgid`. |
| **PoE** | Port d’Entrée : lieu **désigné** où un navire étranger de **plaisance** peut accomplir ses formalités. |
| **Port de plaisance** | Infrastructure qui accueille des yachts (marina, port mixte, havre avec formalités plaisance). Ce n’est pas forcément un PoE. |
| **Port de commerce / industriel** | Infrastructure fret, pêche industrielle, militaire. Utile comme **contre-liste**, pas comme livrable carte Formalités. |
| **Source officielle** | Page ou PDF d’un domaine d’État (douane, gazette, autorité portuaire, ministère). Chaque PoE doit citer au moins une `ref_url` / `source_urls`. |
| **Graine** | Candidat déjà connu (nom ± coordonnées), **pas encore** promu sur la carte. |
| **Run** | Génération versionnée dans un espace à part (`poe_run_*`), sans toucher la carte v1. |
| **Carte v1** | Collection `poe_ports` actuellement affichée. Trésor d’entraînement. Aucune purge. |
| **Listing Noonsite** | Inventaire communautaire (harvest 2026-09-05) : signal, pas Gold Dataset. |
| **Gold Dataset** | Revue humaine + source officielle. Il n’existe pas encore. |

---

## 6. Les deux stratégies

On ne choisit pas l’une ou l’autre. On les **fait travailler ensemble**.

Le Top-Down répond : *« Cette ZEE, quelle liste officielle publie-t-elle ? »*

Le Bottom-Up répond : *« Ce lieu déjà connu, est-ce vraiment un PoE plaisance ? »*

### 6.1 Top-Down — de la ZEE vers la liste

On part du **pays / de la ZEE**, pas d’un nom de port.

1. Prendre le polygone VLIZ (nom, ISO2, souverain, géométrie).
2. Construire la **whitelist** des domaines d’État de ce pays (motifs `gov`, `gouv`, `gob`… × code ISO, plus exceptions mémorisées).
3. **Chercher** les pages qui listent les ports d’entrée : requêtes multilingues (*ports d’entrée, puertos habilitados, designated ports, douane, gazette, décret*), SearXNG et/ou TinyFish Search, filet sur les domaines officiels, dernier recours recherche groundée OpenRouter.
4. **Télécharger** les pages (HTTP, Readability, rendu Chromium, PDF hors process). Jeter les interstitiels anti-bot.
5. **Extraire** les noms (parseur de tableau/décret d’abord ; sinon LLM ∥ NER ; Claude en second lecteur si le budget est ouvert).
6. **Géocoder** (Nominatim ∥ GeoNames), vérifier que le point est dans **cette** ZEE (ou sur son bord terrestre, exception rivière encadrée).
7. **Stocker** sans détruire l’existant, avec les URLs utilisées.

Question métier : *quels ports ce pays désigne-t-il officiellement pour l’entrée des navires étrangers de plaisance ?*

Le Top-Down est le seul moyen de **découvrir une liste officielle** que personne n’avait encore dans nos graines. Il est aussi le plus bruyant : les canaris 12 ZEE (septembre 2026) ont montré trop de fragments de loi, trop peu de recoupement listing, et des ZEE à zéro port alors que la carte v1 en avait. D’où le pivot Bottom-Up pour **vérifier**, sans abandonner le Top-Down pour **trouver les sources**.

### 6.2 Bottom-Up — du lieu déjà connu vers la preuve

On part des **ports candidats déjà retrouvés**, et on demande pour chacun : *est-ce que CE lieu est un Port d’Entrée plaisance ?*

Les graines viennent de l’union (dédupliquée, pas un croisement exclusif) :

- la **carte v1** (`poe_ports`) ;
- les **runs mondiaux** déjà faits (`poe_run_ports`) ;
- le **listing Noonsite** (noms, souvent sans GPS) ;
- **OpenStreetMap** (havres, douanes, parfois marinas près d’un contrôle) ;
- plus tard le **World Port Index** (ports de commerce / industriels, pour contraster).

Une graine vue seulement dans OSM, seulement dans Noonsite, ou seulement en v1 **reste** dans l’union. VLIZ sert à savoir **à quelle ZEE** le point appartient, plus à lancer un crawl de toute la zone.

Ensuite, pour le résidu (nom sans point, ou point sans preuve officielle) :

1. géocoder le nom ;
2. TinyFish Search sur **ce nom** + whitelist du pays ;
3. Fetch des pages d’État trouvées ;
4. un **juge** (Claude Haiku, Sonnet si le listing ou le doute l’exigent, sinon OpenRouter) répond oui / non / insuffisant **pour ce lieu** ;
5. Agent TinyFish seulement si la page officielle est bloquée.

Le juge ne reçoit pas le badge Noonsite ni les tags OSM : on évite le biais de confirmation. Noonsite et OSM servent **après**, pour le score.

### 6.3 Comment les deux se recoupent

| | Top-Down | Bottom-Up |
|---|---|---|
| Point de départ | une ZEE | un lieu candidat |
| Question | quelle liste officielle ? | ce lieu est-il un PoE plaisance ? |
| Produit principal | URLs d’État + noms extraits | verdict par graine |
| Faiblesse | bruit, catalogues mal lus, ZEE difficiles à 0 | ne découvre pas une liste inconnue |
| Force | trouve le décret | capitalise le stock déjà payé |

L’algorithme cible, déjà formulé dans les discussions (Mexique SCT) :

- faisceau **D** : tous les points **désignés** par l’État (liste générale) ;
- faisceau **P** : ceux qui sont clairement **plaisance / turística / yacht clearance** ;
- on les mène **en parallèle**, on compare, on tranche les discordants.
- Un port D sans indice plaisance **ne va pas** tel quel sur la carte Formalités.
- Un port P sans page d’État reste une graine, pas un PoE officiel.

---

## 7. Règles

### 7.1 Un PoE de ce produit est un port de plaisance désigné

Règle d’or : **on ne publie sur la carte Formalités que des lieux où un bateau de plaisance étranger peut, d’après une source d’État, accomplir son entrée.**

Conséquences :

- Terminal conteneur, pétrolier, minéralier, chantier, port militaire : **non**, sauf mention explicite plaisance / yacht / recreo / turística.
- Marina OSM sans texte réglementaire : **non**.
- Port mixte (commerce + plaisance, capitanía, yacht clearance) : **oui**.
- Liste d’État « plaisance uniquement » (ex. PDF douane française des ports de plaisance rattachés) : **oui**, c’est le cas le plus propre.
- Liste d’État générale avec un champ d’activité (ex. Mexique SCT) : ne garder que **Turística** (et le mixte qui inclut le tourisme). Commerce / pêche / *sin actividad* : hors carte Formalités.
- Liste d’État unique, sans distinction : on **extrait** (le mot « plaisance » n’est pas exigé pour *lire* la liste), puis on **filtre** avec OSM plaisance, listing Noonsite, absence WPI commerce-only, et le juge.

### 7.2 Sources

- Extraire **uniquement** depuis des pages officielles. Chaque entrée cite sa source.
- `noonsite.com` est **blacklisté** pour le crawl et n’entre jamais dans `source_urls`.
- Un match Noonsite **augmente** la confiance. L’absence Noonsite **ne réfute rien**.
- OSM, WPI, GeoNames, Nominatim **prouvent un lieu**, pas le statut juridique « port d’entrée plaisance ».
- Ne jamais inventer un nom hors extraits. Plafond 150 ports par zone. Conservé l’orthographe officielle.

### 7.3 Géographie

Le point doit être dans **cette** ZEE, ou sur son bord :

- dans le polygone, ou à ≤ 2,2 km (quai / sliver) ;
- à terre, ≤ 15 km du trait de côte de cette ZEE ;
- exception rivière : jusqu’à 400 km, **dans ce pays** (ISO2 de la zone, pas le souverain), et seulement si c’est un **vrai port** (pas une ville intérieure).
- Hors ZEE en mer, trop loin, ou hallucination GPS : rejeté.
- On n’utilise **pas** `snap_to_ocean` pour les PoE (patch du mode Projets).

### 7.4 Carte et runs

- `poe_ports` : **aucune purge**, upsert non destructif. Les champs OSM / anomalies déjà calculés sont conservés.
- Un run from scratch écrit dans `poe_run_*`, jamais dans la carte.
- Promotion carte = **manuelle**, port par port ou ZEE par ZEE, après revue.
- Interdit en automatique : `generate-batch` sans limite, `force` sur la carte, `/api/deploy clear_db=true`.

### 7.5 ZEE sans PoE

Qualifier, ne pas inventer : `sovereign_entry`, `uninhabited`, `overlapping_claim`, `joint_regime`, `antarctic`. Effacer la qualification dès que la zone a des ports.

---

## 8. Sources et outils

### 8.1 Ce qui nourrit les listes (preuves)

| Outil | Rôle | Ce que ce n’est pas |
|-------|------|---------------------|
| **Sites d’État** (douane, gazette, décret, autorité portuaire) | Seule **preuve** du statut PoE | — |
| **SearXNG** | Trouver les URLs. Instance locale d’abord, publiques en secours | Pas un extracteur |
| **TinyFish Search** | Recherche ciblée (ZEE ou nom de graine), filet `include_domains` | Pas une vérité |
| **TinyFish Fetch** | Miroir de pages (souvent en parallèle de Jina / HTTP) | Pas pour naviguer un site JS |
| **TinyFish Agent** | 1 URL officielle **déjà connue** si anti-bot, 2 en parallèle, cap crédits | Pas un crawl mondial |
| **OpenRouter** | Recherche groundée `:online`, extraction, juge de repli | N’invente pas un port |
| **Claude** (Haiku, parfois Sonnet) | Second lecteur (Top-Down) ou **juge oui/non** (Bottom-Up). Budget local, stop à 90 % | Pas un moteur de recherche. Éteint si `CLAUDE_BUDGET_USD` = 0 |
| **Playwright / Chromium** | Rendu local des pages JS, gratuit | Sauté sur challenge dur |
| **PyMuPDF** (sous-processus) | Texte des PDF officiels, timeout, cache SHA-256 | Crashait le worker s’il restait in-process |

### 8.2 Ce qui nourrit les graines et le contrôle (signaux)

| Outil | Rôle | Attention |
|-------|------|-----------|
| **VLIZ Marine Regions v12** | Cadre ZEE, clé `mrgid` | Ne pas en faire un moteur de crawl aveugle |
| **Runs précédents** | Stock versionné déjà payé (v1, v2, tinyfish, best-of) | Beaucoup de bruit : à vérifier, pas à republier tel quel |
| **Carte v1** | ~1 170–1 280 PoE géocodés, jeu d’entraînement | Ne jamais l’écraser |
| **Listing Noonsite** | 196 pays, **1 193** PoE, **1 092** autres ports (harvest 2026-09-05). Rôles `poe` / `other`. Contrôle et graine de nom | Pas Gold. Pas d’URL Noonsite en source. Les `other` non appariés (marinas) ne partent pas en revue « listing seul » |
| **OpenStreetMap** | Lieu, marina, havre, douane, `port_of_entry`. Overpass + Taginfo | ~32 000 `leisure=marina` : trop pour tout prendre. Une marina + douane proche = **candidat**, pas un PoE |
| **World Port Index (WPI)** | Inventaire NGA des **ports de commerce et industriels** (~3 700, domaine public US) | **Pas encore branché dans le code.** Sert à reconnaître un port fret, pas à prouver la clearance yacht |
| **UN/LOCODE** | Code lieu + fonction portuaire | Même logique que WPI : existence, pas statut plaisance |
| **Nominatim** | Géocodage OSM, ~1 req/s, cache Mongo | Peut pointer une ville, pas le quai |
| **GeoNames** | Second géocodeur, quota horaire | Accord < 2 km = bon signal |
| **spaCy NER** | Noms de ports dans le texte, en parallèle du LLM | Ne lit pas le droit |
| **Classifieur SERP** | Trie les URLs avant téléchargement | Un domaine d’État n’est jamais jeté pour un score bas |

### 8.3 Ce qui est volontairement exclu de l’extraction

Blacklist `backend/data/territories.json` : Noonsite, forums skippers, Wikipedia, TripAdvisor, magazines voile, etc. On peut **comparer des noms** à Noonsite ; on ne **télécharge** pas Noonsite dans le pipeline.

---

## 9. Le code — où vit chaque brique

Le backend est dans `backend/app/`. `backend/server.py` ne fait que charger l’application.

### 9.1 Top-Down (pipeline par ZEE)

Fichier : `backend/app/services/poe_pipeline.py`

| Fonction | Rôle |
|----------|------|
| `build_referential` | Charge les ~285 ZEE VLIZ (WFS), simplifie, écrit la carte |
| `build_whitelist` / `url_allowed` | Domaines d’État du pays |
| `localized_query` / `search_hint_queries` | Requêtes dans la langue du pays |
| `search_searxng` / `search_grounded` | Recherche d’URLs |
| `rank_candidates_ml` | Tri SERP avant fetch |
| `_find_sources` | SearXNG ∥ TinyFish, filet officiel, retry douane |
| `_collect_texts` / `fetch_and_parse` | Cascade N1/N2/N3 |
| `extract_ports_llm` | Catalogue local, puis LLM ∥ NER, Claude second lecteur |
| `_extract_and_geocode` | Noms → GPS → filtre ZEE |
| `_persist_zone` | Upsert non destructif dans `poe_ports` |
| `_persist_zone_run` | Écriture dans l’espace d’un run |
| `generate_zone_poe` | Orchestrateur d’une ZEE |
| `qualify_unclos` | Statut juridique des ZEE sans port |

Variantes de recherche (`normalize_variant`) :

- `v1` : SearXNG anglais, puis langue locale si vide ;
- `v2` : SearXNG anglais **et** local **en parallèle** ;
- `tinyfish` (défaut) : union SearXNG ∥ TinyFish Search.

### 9.2 Runs versionnés

| Fichier | Fonctions clés |
|---------|----------------|
| `services/poe_runs.py` | `execute_run`, `new_run_id` — from scratch, reprise, timeout 900 s/zone |
| `services/poe_diff.py` | `diff_run_vs_baseline` — v1 ↔ run |
| `services/poe_report.py` | `build_run_report`, `report_to_markdown` |
| `services/poe_bestof.py` | `synthesize_best_of`, `is_legal_fragment` — synthèse inter-runs, **jamais** écrite en v1 |
| `services/run_fingerprint.py` | Empreinte du code + paramètres du run |
| `routers/runs.py` | API `/api/poe/runs*` |

### 9.3 Bottom-Up (graines, juge, OSM)

| Fichier | Fonctions clés |
|---------|----------------|
| `services/poe_seeds.py` | `union_extracted`, `attach_listing_seeds`, `attach_osm_seeds`, `verdict_for_seed`, `build_seed_union`, `persist_verify_run` |
| `services/poe_seed_enrich.py` | `geocode_one`, `judge_one`, `execute_enrich`, `apply_judge_verdict` |
| `services/osm_seeds.py` | `is_marina_only`, `is_seed_candidate`, `refresh_osm_cache`, `osm_inventory` |
| `services/osm_validate.py` | `overpass_around`, `score_confidence`, `validate_ports` — osm_confidence **sans** changer nom/GPS |
| `services/listing_ref.py` | `project_listing` — slug Noonsite → mrgid |
| `services/listing_control.py` | `compare_to_listing`, `persist_review` — file de revue |
| `services/poe_confidence.py` | `score_port` (0–100 : source, lecture, carte, externe) |

Verdicts de graine (`verdict_for_seed`) :

- `confirmed` — listing ∩ (v1 ou run ou OSM) + coordonnées ;
- `probable` — OSM fort, ou ≥ 2 sources extraites, ou listing ∩ extrait sans GPS ;
- `unverified` — une seule source extraite : à juger ;
- `name_only` — listing sans point : géocoder d’abord.

### 9.4 Cœur partagé

| Fichier | Fonctions utiles aux PoE |
|---------|--------------------------|
| `core/extract.py` | `serp_filter`, `extract_cascade`, `looks_blocked`, `extract_structured_ports`, `catalog_is_sufficient` |
| `core/geo.py` | `geocode_port_dual`, `classify_poe_point`, `harbour_evidence`, `inland_exception_flags` |
| `core/llm.py` | `extract_ports`, `grounded_search`, `ask_json` |
| `core/claude.py` | Extraction JSON (règles + few-shots), cache préfixe, budget |
| `core/tinyfish.py` | `tf_search_pages`, `tf_fetch`, `tf_poe_agent` |
| `core/dedup.py` | `merge_docs`, `find_duplicate_in_list`, `normalize_name` |
| `core/rag.py` | `select_list_context`, `content_changed` |
| `core/ml.py` | `predict_serp`, `extract_entities`, `scan_poe_anomalies` |
| `core/pdf_worker.py` | Parse PDF isolé (P0) |

### 9.5 Données embarquées

| Fichier | Contenu |
|---------|---------|
| `data/listing_control/all_countries.json` | Listing communautaire PoE / other |
| `data/listing_control/slug_overrides.json` | Jointure slug → mrgid |
| `data/poe_exceptions.json` | Domaines et URLs d’État mémorisés |
| `data/territories.json` | Référentiel curé France / outre-mer + blacklist |
| `data/curated_marinas.json` | Marinas de la **route** (mode Marinas, autre sujet) |

### 9.6 API Formalités (rappel)

- `POST /api/poe/zones/{mrgid}/generate` — Top-Down une ZEE (peut écrire `poe_ports`)
- `POST /api/poe/runs` · `/multi` · `/best-of` — runs isolés
- `GET /api/poe/seeds/union` · `POST /api/poe/seeds/verify` · `POST /api/poe/seeds/enrich`
- `GET /api/poe/seeds/osm` · `POST /api/poe/seeds/osm/refresh`
- `POST /api/poe/validate-osm` · `POST /api/poe/qualify-unclos`
- `GET /api/poe/runs/{id}/listing-control`

Le mode **Marinas** (`marina_build.py`, tag `leisure=marina` le long de la route) n’est **pas** le mode Formalités. Les deux se croisent seulement comme signal : une marina OSM près d’une douane peut devenir une **graine**.

---

## 10. Score de confiance

Ce n’est pas une vérité officielle. C’est un faisceau, 0–100 :

| Brique | Points max | Idée |
|--------|------------|------|
| Source | 30 | Domaine d’État / gazette vs synthèse web |
| Lecture | 25 | Catalogue, accord LLM ∩ NER, second lecteur Claude |
| Carte | 25 | Dans la ZEE, géocodeurs d’accord |
| Externe | 20 | Listing Noonsite `poe`, OSM, plusieurs runs |

Un port vu seulement dans une synthèse web reste bas. Un décret + deux GPS d’accord + OSM + listing monte.

Contrôle listing (hors extraction) :

- listing PoE ∩ run → `confident` (signal) ;
- listing `other` ∩ run PoE → `contradiction` (revue) ;
- run seul / listing PoE seul / nom ambigu → revue.

---

## 11. Contraintes dures

1. **Les données en base sont un trésor.** 4 463 projets + 1 171+ PoE : aucune purge.
2. **Sources officielles uniquement** pour le statut juridique.
3. **PoE = plaisance désignée**, pas « n’importe quel port du World Port Index ».
4. **Claude est un scalpel**, pas le moteur : budget, cache, stop à 90 %, repli OpenRouter.
5. **P0 « survive »** : PDF hors process, cache géocode Mongo, verrou sur `poe_exceptions.json`. L’argent n’est plus le risque principal ; les crashs et les hangs l’étaient.
6. **Un seul chef de file** pour les boutons dangereux (Générer / generate-batch).
7. Mentions légales carte : données **indicatives**.

---

## 12. Critères d’acceptation

On considère le travail réussi pour une ZEE quand :

1. On a identifié **la ou les sources officielles** qui listent les points d’entrée (URL stable, domaine d’État), **ou** on a justifié l’absence (UNCLOS).
2. Tous les PoE **plaisance** de cette liste sont sur la carte (nom + GPS dans la bonne ZEE + `source_urls`).
3. Les ports **commerce-only** (WPI / activité commerciale sans plaisance) n’y sont pas.
4. Les marinas sans formalité n’y sont pas.
5. Un skipper peut cliquer un point et voir **pourquoi** on y croit (source + score).
6. La carte v1 n’a pas été écrasée par un batch.

À l’échelle monde : couverture des ZEE habitées, file de revue vide (ou volontairement reportée), promotion manuelle tracée.

---

## 13. État actuel et écarts

### Déjà en place

- Pipeline Top-Down complet (recherche, whitelist, cascade, extraction, géocodage, score, UNCLOS).
- Runs isolés, comparaison, best-of, empreinte de code, P0 anti-crash.
- Listing-control Noonsite (juge passif).
- Union Bottom-Up des graines (v1 + 5 runs mondiaux + OSM + listing).
- Enrichissement par lots (géocode `name_only`, juge `unverified`) **sans** écrire `poe_ports`.
- Validation OSM a posteriori des PoE v1.

Runs mondiaux déjà en base (à réutiliser, pas à refaire en crawl) :

- `20260905-201122-91f6da` (best-of)
- `20260905-084036-fe1e08` (v2)
- `20260905-084036-5ecfa7` (tinyfish)
- `20260904-073236-8748b2`
- `20260829-003645-d7ab2e`

Run graines (0 crawl) : `20260906-071347-6a9509`.

Canaris Top-Down 12 ZEE : **NO-GO** qualité (bruit, listing ~10 %, Venezuela à 0). Ne pas relancer un mondial Top-Down « pour voir ».

### Écarts par rapport à ce cahier

| Écart | Détail |
|-------|--------|
| **WPI absent du code** | Spécifié ici comme contre-liste commerce/industriel. À brancher en signal Bottom-Up, comme OSM : jamais comme preuve PoE. |
| **Marinas OSM exclues des graines** | `is_marina_only` écarte `leisure=marina` (31 792 objets). Or le livrable est bien la **plaisance**. Il faut réintroduire les marinas **comme candidats** (surtout près d’une douane / `border_control`), sans les promouvoir automatiquement. |
| **Juge trop « port désigné »** | Le prompt actuel accepte un designated port même cargo, et refuse une « marina » trop vite. Il doit exiger la **plaisance** (ou un mixte explicite) pour `is_poe=true`. |
| **Top-Down encore bruyant** | Utile pour découvrir les **URLs officielles par ZEE** (2ᵉ livrable), pas pour remplir la carte d’un coup. |
| **Promotion manuelle** | Pas d’UI de revue → carte. |
| **Gold Dataset** | N’existe pas. Le listing n’en est pas un. |

---

## 14. Ordre de travail recommandé

1. Garder l’union des graines ; **ne pas** relancer un crawl mondial Top-Down.
2. Finir l’enrichissement Bottom-Up par lots (noms sans GPS, puis non vérifiés).
3. Brancher **WPI** (et éventuellement UN/LOCODE) comme signal « commerce/industriel ».
4. Traiter les **marinas OSM proches d’une douane** comme graines P, pas comme PoE.
5. Recaler le juge et le filtre SCT-like (faisceaux D et P).
6. Pour chaque ZEE, **mémoriser l’URL officielle** dès qu’elle est prouvée (`poe_exceptions.json` / seeds d’URL).
7. Revue humaine, puis promotion **manuelle** vers `poe_ports`.

---

## 15. Documents et conversations dont ce cahier hérite

- `docs/PRD.md` — problème d’origine, contrainte non-destructivité, historique 2026-08.
- `docs/ARCHITECTURE.md` — rangement du code après refactor.
- `README.md` — les trois modes (Projets, Marinas, Formalités).
- Décisions agents : pipeline Top-Down, stratégie Claude, harvest Noonsite, P0, listing-control, canaris NO-GO, pivot Bottom-Up, union des graines, inventaire Taginfo OSM.

Ce cahier **prime** sur les détails d’implémentation dès qu’il y a conflit (ex. « toutes les marinas » vs « marinas = graines seulement » ; « liste d’État cargo » vs « carte plaisance »).

---

## 16. Qui fait quoi

| Acteur | Ce qu’il fait | Ce qu’il ne fait pas |
|--------|----------------|----------------------|
| **Skipper** (carte publique) | Consulte les ZEE, les PoE, les sources, le score. Vérifie toujours auprès des autorités avant de partir. | Ne lance pas de génération. Ne vote pas encore (crowdsourcing = backlog). |
| **Opérateur** (Console) | Construit le référentiel ZEE, lance un run isolé, relance l’enrichissement des graines, consulte diffs et listing-control. Un seul chef de file pour les boutons dangereux. | N’écrase pas `poe_ports` par un `generate-batch` mondial. |
| **Juge automatique** (Claude / OpenRouter) | Dit si **ce lieu** est un PoE plaisance d’après des extraits officiels. | N’invente pas de nom. Ne voit pas le badge Noonsite ni les tags OSM (anti-biais). |
| **Réviseur humain** | Tranche les discordants D/P, les `contradiction` listing, les `unverified`. Promeut un port vers la carte. | Ne « goldise » pas Noonsite. |
| **Pipeline** | Cherche, télécharge, extrait, géocode, unionne, note. | Ne purge jamais la carte v1. |

---

## 17. Cycle de vie d’un port

Un lieu ne naît pas PoE. Il traverse des états.

```
candidat (graine)
    → géocodé dans la bonne ZEE
        → jugé sur extraits officiels
            → recoupé (listing / OSM / WPI / multi-run)
                → revu si doute
                    → promu manuellement sur la carte
                        → revalidé OSM (osm_confidence)
                            → rafraîchi seulement si la page d’État a changé (MD5, 30 jours)
```

| État | Sens | Où ça vit |
|------|------|-----------|
| `name_only` | Un nom (souvent Noonsite), pas de GPS | `poe_run_ports` / graines |
| `unverified` | Un point, une seule source extraite | idem |
| `probable` | Plusieurs signaux, pas encore preuve d’État + listing | idem |
| `confirmed` | Listing ∩ extrait + GPS — **signal fort, pas encore la carte** | idem |
| `accepted` / `rejected` / `inconclusive` | Verdict du juge sur **ce** nom | champs `judge_*` |
| **sur la carte** | Promu dans `poe_ports` | mode Formalités |
| `stale` | Source pas revue depuis 180 jours (affichage) ; auto-refresh à 30 jours | `eez_zones` |

Un `rejected` du juge **reste `unverified`**. On ne le promeut pas, on ne le détruit pas.

Déduplication : même ZEE + nom proche (fuzzy) ou points à moins de 500 m. On fusionne, on ne duplique pas « Port of X » et « X ».

---

## 18. Le second livrable : les sources officielles par ZEE

Le skipper ne doit pas seulement voir des points. Il doit voir **la page d’État** de cette ZEE.

Pour chaque ZEE on veut, au minimum :

| Champ | Sens |
|-------|------|
| `mrgid` | Identifiant VLIZ |
| `urls` | Pages ou PDF d’État qui **listent** les PoE (pas la home des douanes) |
| `kind` | `pleasure_list` (liste plaisance dédiée) · `general_list` (liste générale d’entrée) · `gazette` · `catalog` (tableau type SCT) · `none` (UNCLOS) |
| `covers_pleasure` | La source parle-t-elle de yachts / recreo / turística, ou seulement de navires en général ? |
| `collected_at` | Date de collecte |
| `md5` | Pour savoir si le texte a changé |
| `official` | Domaine dans la whitelist de **ce** pays |

Aujourd’hui ces informations sont éparpillées : `eez_zones.sources`, `source_hashes`, `poe_exceptions.json` (domaines et URLs mémorisés), `source_urls` de chaque port. Le cahier demande d’en faire **une fiche source par ZEE**, visible dans le popup (déjà commencé : bloc « sources officielles utilisées ») et exportable.

Règles de la fiche :

- une URL Noonsite, forum ou Wikipedia **n’entre pas** ;
- une home `douane.gouv.fr` sans liste **ne suffit pas** ;
- si plusieurs PDF / pages, on les garde toutes dès qu’elles nomment des ports ;
- si aucune source et ZEE inhabitée / revendiquée : `kind = none` + code UNCLOS.

Le Top-Down sert surtout à **remplir cette fiche**. Le Bottom-Up s’en sert ensuite comme `include_domains` pour juger les graines de **cette** ZEE.

---

## 19. Algorithme des deux faisceaux (D et P)

On ne choisit pas entre « toute liste d’État » et « seulement la plaisance ». On calcule les deux, puis on décide.

### Faisceau D — désigné par l’État

Entrée : pages de la fiche source de la ZEE.

Sortie : tout lieu que le texte nomme comme port d’entrée / clearance / puerto habilitado / designated port, **y compris** un terminal commerce si l’État l’écrit.

Outils : parseur de tableau, LLM + NER, Claude second lecteur. Le mot « plaisance » n’est **pas** exigé pour *lire*.

### Faisceau P — plaisance

Entrée : les mêmes pages **plus** les graines plaisance (listing Noonsite `poe`, marinas OSM près d’une douane, PDF « ports de plaisance rattachés », champ SCT *Turística*).

Sortie : lieux où un yacht étranger peut faire sa clearance.

### Décision

| D | P | Décision |
|---|---|----------|
| oui | oui | **PoE carte** — le cas propre (port mixte ou liste plaisance) |
| oui | non | **pas sur la carte Formalités** — port commerce/industriel (WPI aide à le confirmer). On peut le garder en coulisse `designated_other` |
| non | oui | **graine**, pas PoE officiel — marina ou listing sans décret. Le juge cherche encore une page d’État |
| non | non | ignoré |

Cas Mexique : le catalogue SCT a un champ d’activité. D = toutes les lignes « port designated ». P = lignes *Turística* (et mixte qui contient le tourisme). Seul P ∩ D va sur la carte.

Cas France métropolitaine : le PDF douane des ports de plaisance rattachés **est déjà P**. Pas besoin de WPI.

---

## 20. Modèle de données

MongoDB. On n’invente pas une sixième collection à chaque idée : on réutilise.

### Carte (v1) — ne pas écraser

| Collection | Une ligne = |
|------------|-------------|
| `eez_zones` | une ZEE (polygone, iso2, statut, `poe_count`, `sources`, `unclos`, `confidence_avg`) |
| `poe_ports` | un PoE **publié** (nom, lat/lon, `mrgid`, `source_urls`, `confidence`, `osm_*`, `spatial_kind`) |

Clé métier d’un port : `dedup_key = "{mrgid}:{nom normalisé}"`.

Champs utiles d’un `poe_ports` :

- identité : `name`, `city`, `note`, `mrgid`, `zone_name`, `country_iso2`
- carte : `lat`, `lon`, `validated`, `spatial_kind` (`in_eez` / `coastal_land` / `inland_river` / rejeté)
- preuve : `source_urls`, `extraction_engine`, `extraction_agreement`, `claude_agreement`, `from_synthesis`
- score : `confidence`, `confidence_parts`, `confidence_reasons`, `listing_role`
- OSM : `osm_confidence`, `osm_tags`, `osm_id`, `osm_checked_at`
- anomalies : `spatial_anomaly` (IsolationForest / DBSCAN, flag additif)

### Espace de travail (runs / graines)

| Collection | Une ligne = |
|------------|-------------|
| `poe_runs` | un run (label, variant, empreinte code, progression) |
| `poe_run_zones` | résultat d’**une** ZEE dans **un** run |
| `poe_run_ports` | un port extrait ou une graine enrichie, lié à `run_id` |
| `poe_run_events` | journal d’une micro-étape (recherche, fetch, juge…) |
| `poe_listing_review` | file de revue (contradiction, run seul, listing seul, ambigu) |
| `osm_port_seeds` | objet OSM nommé, rattaché à une ZEE |
| `jobs` | reprise des tâches longues (validation OSM, enrich) |
| `geocode_cache` | Nominatim / GeoNames, TTL 180 j / 14 j |

Le run graines `20260906-071347-6a9509` vit dans `poe_run_ports`. `wrote_poe_ports: false` tant qu’on n’a pas promu.

### Fichiers à côté de la base

- `backend/data/listing_control/all_countries.json` — 196 pays, 1 193 PoE, 1 092 other
- `backend/data/listing_control/slug_overrides.json` — slug → mrgid
- `backend/data/listing_control/eez_index.json` — 285 ZEE pour la jointure
- `backend/data/poe_exceptions.json` — domaines d’État hors motif `gov` + URLs productives
- `backend/data/territories.json` — France / outre-mer curés + blacklist
- `backend/data/eez_world_map.geojson` — polygones simplifiés pour Leaflet

---

## 21. Ce que voit l’utilisateur

### Skipper — mode Formalités

- Carte mondiale des ZEE colorées par statut (pas encore générée / générée / sans source officielle / erreur).
- Points ambre = PoE publiés. Clic : nom, ZEE, score, badge OSM, anomalie spatiale, jusqu’à 3 URLs sources, mention « indicatif ».
- Bandeau gauche : les ~285 ZEE, recherche, filtre de statut, nombre de PoE, confiance moyenne.
- Popup ZEE : sources officielles, bloc UNCLOS si pas de port, bouton Générer (opérateur / debug — pas le geste skipper).
- Mention fixe : *vérifiez auprès des autorités avant le départ.*

### Opérateur — Console

- Construire le référentiel ZEE (VLIZ), une fois.
- Lancer un **run isolé** (`/api/poe/runs`), pas un batch carte.
- Union des graines, enrichissement par lots, refresh OSM.
- Diff run ↔ v1, rapport markdown, listing-control, file de revue.
- Auto-refresh : toutes les 12 h, max 60 ZEE, re-télécharge les sources de plus de 30 jours, ne ré-extrait que si le MD5 a changé ; réessaie les erreurs après 7 jours.

Ce qui **manque** à l’UI (écart de ce cahier) : écran de revue (D/P, juge, listing) + bouton **Promouvoir vers la carte**.

---

## 22. Inventaire OpenStreetMap

OSM n’a pas d’objet « Port d’Entrée plaisance ». On assemble des tags. Comptes Taginfo du 5 septembre 2026.

### Signaux utiles (graines ou validation)

| Tag | Ordre de grandeur | Usage |
|-----|-------------------|--------|
| `port_of_entry=yes` | 59 | Seul tag qui **dit** PoE. Très rare. Graine forte. |
| `port_of_entry=no` | 411 | Signal négatif, pas une vérité absolue. |
| `government=customs` / `amenity=customs` / `office=customs` | milliers, souvent inland | Douane. Un bureau ≠ un port. Utile **près** d’un havre / d’une marina. |
| `barrier=border_control` | idem | Souvent route ou aéroport. Filtrer : dans ou à ≤ 15 km de la ZEE. |
| `industrial=port` / `landuse=harbour` / `harbour=yes` | quelques milliers | Infrastructure. Graine D, pas preuve plaisance. |
| `leisure=marina` | ~31 792 | **Plaisance.** Trop nombreux pour tout prendre. Graine P **seulement** si douane / border / `port_of_entry` à ≤ 800 m, ou déjà dans listing/v1. |
| CATHAF `marina` / `marina_no_facilities` | ~21 800 | OpenSeaMap plaisance. Même règle que `leisure=marina`. |

Aujourd’hui le code (`is_marina_only`) **écarte** les marinas des graines. Ce cahier inverse la logique : marina = candidat P, jamais PoE tout seul.

### À ne pas prendre comme PoE

- `amenity=ferry_terminal` seul (bonus de score OSM +0,1, pas une graine).
- Aéroports (filtre sur le nom).
- Objets à plus de 15 km de la ZEE (Rhin, Danube, Grands Lacs, ports secs).
- `seamark:type=harbour` en masse (25 070, dont 21 344 aussi marina).

Validation a posteriori (`osm_validate.py`) : autour d’un PoE **déjà en carte**, rayon 3 km, on note `osm_confidence` sans bouger le GPS. Déjà fait sur les 1 171 PoE v1 (678 ≥ 0,5 ; 154 sans tag).

---

## 23. World Port Index et UN/LOCODE

**Pas encore dans le code.** Spécifiés ici pour le faisceau D « commerce ».

### WPI (NGA, domaine public US, ~3 700 ports)

Liste de **ports de commerce et industriels** : nom, pays, coordonnées, type de trafic (cargo, tanker, pêche…).

Usage prévu :

1. charger le WPI, rattacher chaque entrée à une ZEE VLIZ (point-in-polygon) ;
2. apparier par nom + proximité (~1 km) aux graines et aux PoE ;
3. poser un jeton `wpi_commercial=true` ;
4. si D oui et P non et WPI oui → confirmer l’écart **hors carte Formalités** ;
5. si P oui et WPI oui → port **mixte**, rester sur la carte si la source d’État le permet.

Le WPI **ne prouve jamais** qu’un yacht peut dédouaner. Il aide à **ne pas** coller un terminal conteneur sur la carte plaisance.

### UN/LOCODE (UNECE)

Code lieu + fonction `1` = port maritime. Même rôle : existence / orthographe / pays, pas le statut juridique plaisance.

---

## 24. Exemples concrets

### France métropolitaine — liste plaisance dédiée

Source : PDF douane *« Liste des ports de plaisance rattachés au dispositif »* (`douane.gouv.fr`).  
La Rochelle, Tino Rossi, Charles Ornano, etc. C’est déjà le faisceau P. On n’a pas besoin du WPI.  
Référentiel curé : `territories.json`. Arrival hors Schengen seulement.

### Mexique — catalogue général + champ d’activité

Source : liste SCT (tableau numéroté, lat/lon, entité fédérative, activité).  
Ensenada, Manzanillo… D = toutes les lignes désignées. P = *Turística* (éventuellement mixte).  
Le parseur de catalogue copie les coordonnées **écrites dans le PDF**, jamais un GPS de mémoire.

### Niue — une phrase de loi

« …through the port of Alofi, the Hanan International Airport, or the Post Office. »  
On garde **Alofi**. On jette l’aéroport et la poste. Pas de marina OSM requise : c’est le seul point d’entrée maritime nommé.

### Marina sans formalité

Une `leisure=marina` en Croatie, sans douane à 800 m, absente du listing `poe` et d’un décret : **graine faible ou rien**. Ce n’est pas un PoE.

### Venezuela au canari Top-Down

Le crawl 12 ZEE a rendu **0** port. La carte v1 en a 12. C’est pourquoi on ne relance pas un mondial Top-Down : il **écraserait** un stock déjà utile. On part des 12 graines et on cherche **leur** décret.

---

## 25. Recette

On ne « sent » pas qu’une ZEE est bonne. On coche.

### Pour une ZEE (recette unitaire)

1. La fiche source a au moins une URL d’État qui liste des ports, **ou** un code UNCLOS.
2. Chaque PoE carte a : nom, GPS dans la ZEE (ou bord / rivière encadrée), au moins une `source_urls` officielle.
3. Aucun aéroport, aucune ville intérieure à 100 km, aucun port d’un autre pays.
4. Aucun terminal WPI commerce-only sans mention plaisance.
5. Popup skipper : source cliquable + score.
6. `poe_ports` de cette ZEE n’a pas perdu un port que la v1 avait, sauf rejet **écrit** (revue).

### Pour un run de graines (recette monde)

1. `wrote_poe_ports: false`.
2. Union ≥ v1 + listing + OSM cache (pas un crawl vide).
3. Compteurs `confirmed` / `probable` / `unverified` / `name_only` journalisés.
4. Juge : `is_poe=true` seulement si extraits **officiels** + **plaisance ou mixte**.
5. Tests automatiques verts : `test_poe_seeds`, `test_poe_seed_enrich`, `test_listing_control`, `test_osm_seeds`, `test_poe_v2_pipeline`, `test_p0_survive`, `test_ner_unclos_osm`.

### Interdit pendant la recette

Cliquer Générer / `generate-batch` / `force` sur la carte. Relancer un mondial Top-Down « pour comparer ».

Commande locale :

```bash
cd backend && python3 -m pytest tests/test_poe_seeds.py tests/test_listing_control.py tests/test_osm_seeds.py tests/test_p0_survive.py -q
```

---

## 26. Risques

| Risque | Effet | Parade déjà là / à faire |
|--------|--------|---------------------------|
| Crawl Top-Down bruyant | Fragments de loi, 0 port sur une ZEE peuplée, listing à 10 % | Plus de mondial Top-Down ; Bottom-Up par graine |
| Trop de commerce sur la carte | Skipper arrive dans un terminal conteneur | Faisceau P + WPI + juge recalibré |
| Trop de marinas | 32 000 points inutiles | Marina = graine seulement près d’une douane / listing |
| Écrasement v1 | Perte du jeu d’entraînement (1 171+ PoE) | Runs isolés, promotion manuelle |
| Anti-bot (Akamai, etc.) | Pages vides, faux extraits (`unblock.federalregister.gov`) | `looks_blocked`, Agent TinyFish ciblé, jamais ingérer l’interstitiel |
| Quota Nominatim / Overpass / TinyFish | Hang 900 s, course lente | Cache Mongo, PDF hors process, lots de 200 |
| Biais du juge | Il dit oui parce que Noonsite ou OSM l’ont dit | Le juge ne reçoit que nom + extraits officiels |
| Noonsite pris pour Gold | On copie des erreurs skippers | Listing = signal ; absence ≠ réfutation |
| Whitelist incomplète | Filet TinyFish vide, ZEE `ia_sans_source` | `poe_exceptions.json` + motifs PSL, seulement pays **avec** ZEE |
| Claude éteint | Budget 0 malgré la clé | Repli OpenRouter ; le run continue |
| Droit / ToS Noonsite | Zone grise du harvest 2026-09-05 | JSON déjà ingéré ; plus de crawl ; pas d’URL dans les sources |

---

## 27. Hors périmètre

Ce cahier **ne couvre pas** :

- le mode **Projets** (swarm fondations, 4 463 projets) — voir `docs/CAHIER_DES_CHARGES_PROJETS.md` ;
- le mode **Marinas** de la route Berry-Mappemonde (corridor ±25 NM, enrichissement VHF / places) — autre produit, autre couche carte ;
- les **mouillages** OSM ;
- le crowdsourcing skipper avec lien de loi (backlog P1 du PRD) ;
- l’abonnement Noonsite premium (refusé) ;
- la traduction automatique opus-mt des requêtes (matrice 16 langues suffisante pour l’instant) ;
- la promotion automatique vers `poe_ports` ;
- les formalités d’**aviation** ou de **frontière terrestre**.

Le croisement « un PoE près d’un projet de conservation » est une idée P2, pas un livrable de ce document.

---

## 28. Annexes

### A. Codes UNCLOS affichés

| Code | Texte skipper (idée) |
|------|----------------------|
| `sovereign_entry` | Pas de PoE listé — dédouanement via les ports de l’État souverain ; transit en passage inoffensif. |
| `uninhabited` | Territoire inhabité — pas de douane locale ; autorisation écrite du souverain. |
| `overlapping_claim` | Eaux disputées — vérifier **tous** les États revendicateurs. |
| `joint_regime` | Régime conjoint — formalités partagées. |
| `antarctic` | Sud de 60°S — pas de régime ZEE ; permis via les programmes antarctiques. |

Fonction : `qualify_unclos`. Le bloc disparaît dès que la zone a des ports.

### B. Collections et API (rappel court)

Écriture carte : `POST /api/poe/zones/{mrgid}/generate` — **dangereux**, upsert `poe_ports`.  
Écriture run : `POST /api/poe/runs` — sûr.  
Lecture graines : `GET /api/poe/seeds/union`.  
Juge : `POST /api/poe/seeds/enrich`.  
OSM : `POST /api/poe/seeds/osm/refresh`, `POST /api/poe/validate-osm`.  
Contrôle : `GET /api/poe/runs/{id}/listing-control`.

### C. Runs à réutiliser (ne pas recrawler)

Mondiaux : `20260905-201122-91f6da`, `20260905-084036-fe1e08`, `20260905-084036-5ecfa7`, `20260904-073236-8748b2`, `20260829-003645-d7ab2e`.  
Graines : `20260906-071347-6a9509`.  
Canaris 12 ZEE (NO-GO) : `20260906-041309-8fb2d2`, `20260906-063439-2ccadf`.

### D. Tests automatiques concernés

`backend/tests/test_poe_seeds.py`, `test_poe_seed_enrich.py`, `test_listing_control.py`, `test_osm_seeds.py`, `test_poe_v2_pipeline.py`, `test_poe_api.py`, `test_p0_survive.py`, `test_ner_unclos_osm.py`, `test_poe_audit_improvements.py`, `test_run_fingerprint.py`, `test_claude_cache.py`.

### E. Attribution

ZEE : Flanders Marine Institute — Marine Regions, Maritime Boundaries v12 (CC-BY 4.0).  
Marinas / géocodage : contributeurs OpenStreetMap (ODbL), Nominatim, Overpass, GeoNames.  
WPI : National Geospatial-Intelligence Agency, domaine public US (quand branché).

---

*Fin du cahier des charges. Toute évolution de règle (plaisance, WPI, marinas-graines, promotion carte) se fait d’abord ici, puis dans le code.*
