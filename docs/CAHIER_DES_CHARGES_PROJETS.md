# Cahier des charges — Projets de conservation marine

Document de cadrage du mode **Projets** de Blue Intelligence.
Il relit le code, le PRD, l’architecture, le seed GeoJSON, le cahier Formalités (PoE),
et la **revue du 7 septembre 2026** (32 commentaires Berry-Mappemonde sur la v1.0).

Écrit en langage simple : c’est le contrat de ce que l’on cherche, et de ce que l’on refuse.

Version **2.0** — 7 septembre 2026. Document **complet** + **plan d’implémentation** (phases, fichiers, API, recette).

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
14. Plan d’implémentation
15. Documents et conversations dont ce cahier hérite
16. Qui fait quoi
17. Cycle de vie d’un projet
18. Le second livrable : les portails financeurs
19. Algorithme (découverte, sites, Follow the Money)
20. Modèle de données
21. Ce que voit l’utilisateur
22. Inventaire des MasterSeeds
23. Gatekeeper et taxonomie
24. Exemples concrets
25. Recette
26. Risques
27. Hors périmètre
28. Annexes
29. Trace des commentaires de revue (v1 → v2)

---

## 1. En une phrase

Retrouver tous les projets de conservation, restauration ou protection marine **réellement menés** (une page, un ou plusieurs lieux, plusieurs financeurs possibles), **financés par des fondations**, **reliés à un endroit du monde assez précis et théoriquement accessible en bateau**, les poser sur la carte, et ne jamais y coller un programme terrestre, une page d’accueil, un siège d’ONG, ou un GPS inventé.

Ceci **exclut** les projets trop généraux, ou qui ne sont pas clairement localisés à un ou plusieurs endroits accessibles en bateau. On fait clairement de **l’éco-tourisme** : un skipper doit pouvoir se dire « je peux aller voir ça ».

---

## 2. Pourquoi ce travail existe

Les fondations océaniques publient leurs actions sur des centaines de sites. La carte v1 (~4 463 points, ~861 financeurs) a déjà ramassé ce web. Beaucoup de points ne sont **pas visitables** : siège à Washington, centroïde de pays, rectangle océanique hashé, recale `snap_to_ocean` à des dizaines de kilomètres du vrai lieu.

Blue Intelligence les cartographie pour l’expédition Berry-Mappemonde et pour l’éco-tourisme : **où** aller, **qui** finance, **quelle page** lire. Un GPS n’est pas le périmètre d’une AMP.

Le stock v1 reste un **trésor** (restauration, revue, futur Gold). Le perdre, c’est perdre les deux.

---

## 3. Ce que l’on veut obtenir

Deux livrables, indissociables :

1. **La carte des sites visitables.**
   Un projet peut avoir **plusieurs points** (plusieurs actions d’un même programme).
   Chaque point : nom du site, GPS du **lieu d’action** (pas le HQ), accessibilité bateau, URL, financeur(s), description, S_ocean, `geo_source`.

2. **Les portails financeurs.**
   MasterSeeds = les **~861 financeurs déjà découverts** (plus ceux que Follow the Money ajoutera), pas seulement les 21 portails curés d’origine. Pour chacun : nom, URL de listing si connue, dernier scan, pages vues.

Un projet sans site assez précis **n’est pas publié**. Il reste en graine / file de revue (`unlocated`). On ne recale pas vers « une mer proche » pour faire semblant.

---

## 4. Ce que l’on ne veut pas

- Des projets **terrestres ou d’eau douce** (sauf estuaire côtier / mangrove / delta accessibles).
- Des programmes **trop généraux** (« protéger les océans ») sans site nommé.
- Des **pages génériques** : home, news, dons, jobs, boutique.
- Un **GPS inventé** : `ocean_fallback_coords`, estimation au milieu d’un bassin, centroïde de pays.
- Un **siège social** (Paris, Londres, Washington, Monaco-ville de l’ONG) présenté comme le projet.
- **`snap_to_ocean`** comme rustine : le point recalé ne veut plus rien dire.
- Une carte qui **écrase** `projects` (`clear_db`, `DELETE /api/projects`). Ces fonctions **disparaissent**.
- TinyFish **Agent** en moteur quotidien (crédits). Search et Fetch sont les outils TinyFish normaux.
- Inventer un titre, un site, ou un financeur absents des sources.

---

## 5. Vocabulaire

| Mot | Sens ici |
|-----|----------|
| **Projet** | Une action marine décrite sur une URL, financée par une ou plusieurs fondations. |
| **Site** | Un lieu d’action **assez précis** et **accessible en bateau** (baie, récif, AMP, marina, île, estuaire). Un projet peut avoir *n* sites. |
| **Accessible en bateau** | Un skipper peut théoriquement s’y rendre (mer, côte, havre, AMP côtière). Pas un bureau, pas une ville intérieure. |
| **Financeur** | Organisation dans `funders`. MasterSeed = l’union des ~861 déjà vus. |
| **Swarm** | Découverte + extraction. N’écrit **plus** la carte v1 : seulement un **run**. |
| **Carte v1** | Collection `projects` actuelle. Trésor. Revue, pas purge. |
| **Run** | Génération isolée `project_run_*`, calquée sur `poe_run_*`. Promotion manuelle ensuite. |
| **Snapped / fallback** | Défauts v1. Interdits en publication nouvelle. Candidats à la revue, exclus du futur Gold. |
| **Gold Dataset** | N’existe pas encore (aucune cartographie de ce type n’existait). On peut en **créer** un : v1 **moins** snapped **moins** fallback océan, après revue. |
| **Revue** | UI opérateur : accepter / rejeter / éditer un site, promouvoir un run. |
| **Règles configurables** | Seuils gatekeeper, distances, plafonds : dans `settings` / JSON, **pas en dur** dans le code. |

---

## 6. Les deux stratégies

On ne choisit pas. On les fait travailler ensemble.

### 6.1 Top-Down — du portail vers les pages

On part d’un **financeur** (les ~861, pas seulement 21).

1. URL de listing si on l’a ; sinon la déduire des `url` déjà en base pour ce financeur.
2. Découvrir les pages projet : crawler HTTP → TinyFish **Search / Fetch** (gratuits, quotas) → Agent **seulement** si toujours 0.
3. Cache `deeplink_pages` + file du **run**.
4. Extraire, juger « est-ce un projet localisable ? », trouver les **sites**.
5. Écrire dans `project_run_projects`, jamais dans `projects`.

### 6.2 Bottom-Up — de l’URL / du point v1 vers le site

On part du stock :

- carte v1 (y compris snapped / fallback : à revoir, pas à republier tels quels) ;
- DeepLinkCache ;
- signalements skipper ;
- file `failed` / `unlocated`.

Pour chaque graine : la page décrit-elle **un ou plusieurs lieux accessibles en bateau** ? Si oui, extraire ces sites. Si non, `unlocated` — pas de rustine GPS.

### 6.3 Recoupement

| | Top-Down | Bottom-Up |
|---|---|---|
| Départ | un financeur / listing | une URL ou un point v1 |
| Question | quelles pages projet ? | quels **sites visitables** sur cette page ? |
| Produit | URLs + extraits dans un run | verdict + sites, ou `unlocated` |
| Faiblesse | bruit, homes | ne découvre pas un portail neuf |
| Force | trouve les listings | capitalise les 4 463 et les 861 |

---

## 7. Règles

### 7.1 Règle d’or

On ne publie que des **actions marines financées par des fondations**, avec URL, et **au moins un site assez précis pour qu’un bateau puisse s’y rendre**.

Conséquences :

- Forêt, montagne, lac intérieur : non.
- Estuaire, mangrove, delta, blue carbon côtier : oui, si le lieu est nommé.
- Programme mondial : **chercher chaque lieu d’action**. Plusieurs points > un centroïde « global ». Pas de GPS représentatif inventé.
- Siège de l’ONG : **jamais** un site. Le géocodeur doit les refuser.
- Page about / donate / news : non.
- `snap_to_ocean` : **interdit** pour publier. On cherche le vrai lieu, ou on laisse `unlocated`.
- `ocean_fallback_coords` : **interdit** en carte et en run promu.

### 7.2 Sources

- Preuve = la page projet (`url`) + les pages de sites qu’elle cite.
- Financeurs = ceux de la page / du seed, fusionnables, jamais inventés.
- OSM, Nominatim, GeoNames, polygones AMP : **aident à situer**, ne prouvent pas le projet.
- Claude Haiku **peut** servir (filtre, juge de lieu, second lecteur) si le budget est ouvert. Ce n’est plus réservé aux PoE.
- TinyFish Search / Fetch : outils normaux. Agent : dernier recours, compteur, cap.

### 7.3 Géographie

Un site publié a un GPS **du lieu d’action** :

- déjà en mer, ou sur le littoral / havre (quelques kilomètres, seuil **configurable**, défaut serré ~15 km) ;
- le point reste **là où le géocodeur l’a trouvé** — on ne le fait pas glisser vers l’eau ;
- trop à l’intérieur, HQ, (0,0), bassin océanique aléatoire : `unlocated` ;
- plusieurs sites = plusieurs géométries rattachées au même `project_id`.

### 7.4 Carte et runs

- `projects` : **aucune purge**. Upsert non destructif à la **promotion** seulement.
- Tout crawl / swarm écrit dans `project_run_*`.
- `clear_db` et `DELETE /api/projects` : **supprimés** (API 410 / 400, plus de case Console).
- Import GeoJSON : skip URL connue, fusion, pas d’écrasement GPS v1 sauf revue.

### 7.5 Règles hors du code compilé

Seuils ML (0,85 / 0,12), `min_marine_score`, `max_inland_km`, plafonds TinyFish Agent, `max_partner_orgs` : **`settings` + éventuellement `backend/data/project_rules.json`**. Changer une règle ne doit pas exiger un commit Python, seulement un réglage.

---

## 8. Sources et outils

### 8.1 Preuves (pages)

| Outil | Rôle | Ce que ce n’est pas |
|-------|------|---------------------|
| Pages projet / sites | Preuve du projet et des lieux | — |
| Crawler HTTP N1 | Listings simples, gratuit | Pagination JS |
| TinyFish **Search** | Trouver listings et pages site | Pas Agent |
| TinyFish **Fetch** | Miroir de page (gratuit, quota) | Pas Agent |
| TinyFish **Agent** | JS / pagination si Search+Fetch+crawler = 0 | Moteur quotidien |
| Cascade N1/N2/N3 | Texte (trafilatura ∥ Readability → Chromium → miroir) | N’invente pas |
| OpenRouter | Extraction, gatekeeper zone grise | — |
| **Claude** | Juge de lieu / second lecteur, budget partagé | Pas obligatoire |
| RAG local | Pages longues | Pas un GPS |

### 8.2 Signaux (graines et contrôle)

| Outil | Rôle | Attention |
|-------|------|-----------|
| Carte v1 | 4 463 projets, ~861 financeurs | Ne jamais l’écraser ; snapped/fallback → revue |
| MasterSeeds élargis | Union des financeurs v1 + 21 listings curés | URL de listing parfois inconnue : à découvrir |
| DeepLinkCache | URLs déjà vues | Homes possibles |
| Signalements | Skipper, `Community Report` | Même contrat de site |
| Nominatim / GeoNames | Lieu nommé | HQ et villes : à filtrer |
| Polygones AMP (ex-`/api/mpa`) | Indice de géocodage d’un nom d’AMP | Pas une preuve de projet ; couche carte toujours hors livrable |
| `dedup_core` | URL, ou nom+distance | Fusionner tous les champs vides (`merge_docs`) |

### 8.3 Exclus de la découverte

`CRAWL_BLACKLIST` (configurable) : contact, about, donate, news, shop, jobs…

---

## 9. Le code — où vit chaque brique

Aujourd’hui (à faire évoluer, § 14) :

| Fichier | Rôle actuel | Cible v2 |
|---------|-------------|----------|
| `services/swarm_pipeline.py` | Découvre + **écrit `projects`** | Découvre + écrit **`project_run_*`** ; plus de snap / fallback |
| `routers/swarm.py` | deploy (`clear_db`), Force Extract | `clear_db` refusé ; Force Extract = même pipeline, gatekeeper, run |
| `routers/projects.py` | liste, import, enrich, `DELETE` | `DELETE` → 410 ; enrich ne snap pas ; sites[] |
| `static_data/seeds.py` | 21 portails | Chargeur des ~861 (`data/master_seeds.json`) |
| `core/llm.py` | `extract_project`, gatekeeper | Sites multiples ; seuils lus dans settings ; Claude optionnel |
| `core/geo.py` | `snap_to_ocean`, `ocean_fallback_coords` | Conservés pour d’autres usages / debug ; **pipeline Projets ne les appelle plus** |
| `core/tinyfish.py` | Agent + Search/Fetch | Search/Fetch d’abord ; Agent capé |
| `services/poe_runs.py` | Modèle de run isolé | **Calquer** `project_runs.py` |

Frontend : `SwarmPanel`, `ProjectList`, `useProjectsLayer`, `ProjectsCard`, `ReportModal`, `AuditView`. Cible : case clear_db **disparue** ; écran revue ; un projet = plusieurs marqueurs.

---

## 10. Score S_ocean

Faisceau 0–1 (extracteur ou heuristique). Le seuil `min_marine_score` coupe à l’**entrée**. Il ne réécrit pas la v1.

Nouveau signal, distinct : **`site_ok`** (bool + raison) — le lieu est-il assez précis et accessible en bateau ? Sans `site_ok`, pas de publication, même si S_ocean est haut.

---

## 11. Contraintes dures

1. **Trésor.** 4 463 projets + 1 171+ PoE : aucune purge.
2. **Site visitable.** Pas de point sans lieu d’action accessible en bateau.
3. **Pas de rustine GPS.** Ni snap, ni fallback océan, ni HQ.
4. **Runs isolés.** Le swarm ne touche pas `projects`.
5. **Purges supprimées.** Plus de `clear_db`, plus de `DELETE /api/projects`.
6. **TinyFish Agent = scalpel.** Search/Fetch d’abord.
7. **Claude autorisé** pour les Projets si le budget est ouvert.
8. **Règles configurables.** Pas de magie 0,85 / 0,12 / 500 km dans le source.
9. Carte **indicative**. Un point n’est pas le polygone de l’AMP.

---

## 12. Critères d’acceptation

Pour un **financeur** :

1. Fiche portail (nom, listing ou « listing inconnu », dernier scan).
2. Chaque **site** publié : nom, GPS du lieu d’action, URL, financeurs, pas HQ, pas snapped, pas fallback.
3. Les pages génériques / programmes sans lieu : `unlocated` ou `rejected`, pas sur la carte.
4. Un programme à 4 îles → jusqu’à 4 points, même `project_id`.
5. Popup : URL + lieu + S_ocean. Le visiteur comprend où aller.
6. La v1 n’a perdu aucun document, sauf rejet **écrit** en revue.

Pour un **run** : `wrote_projects: false` jusqu’à promotion ; compteurs `sites` / `unlocated` / `rejected` ; pas d’appel à `snap_to_ocean` ni `ocean_fallback_coords`.

---

## 13. État actuel et écarts

### Déjà là

- Swarm Top-Down 21 seeds, crawler, TinyFish Agent de secours, DeepLinkCache, saturation.
- Gatekeeper ML → LLM → heuristique, extraction JSON, catégories 9 familles.
- Carte, filtres, signalement, enrich ↻ (re-texte, **pas** le GPS).
- Import/export GeoJSON, seed 4 463.
- Console test/full.

Répartition seed (4 463) : Research 890, Conservation 765, Policy 490, Other 474, MPA 402, Pollution 391, Coastal 389, Fisheries 361, Education 301. ~861 financeurs. ~43 `snapped` dans le GeoJSON d’export (le champ `geo_source` n’y est pas : le fallback océan se voit en base, pas dans le seed).

### Écarts v2 (ce que le code doit rattraper)

| Écart | Cible |
|-------|--------|
| Écriture live dans `projects` | `project_run_*` + promotion |
| `clear_db` / `DELETE` | **Supprimés** |
| `ocean_fallback` / `snap_to_ocean` dans le swarm | **Plus appelés** ; inland → `unlocated` |
| 21 MasterSeeds | **~861 financeurs** |
| Un point par projet | **n sites** |
| Force Extract sans gatekeeper | Même `_process_url` / run |
| Dédup = financeurs seulement | `merge_docs` |
| Seuils en dur | `settings` / `project_rules.json` |
| Claude Projets « interdit » | Autorisé si budget |
| Agent TinyFish trop tôt | Search/Fetch d’abord |
| Pas d’UI revue | File + promouvoir |
| Catégories figées | Entraînables plus tard (**non prioritaire**) |
| Télémétrie sans `dataset` | Champ `projects` (cosmétique) |
| `/api/mpa` 410 | Réutiliser les polygones **en coulisse** pour géocoder un nom d’AMP |

---

## 14. Plan d’implémentation

Quatre phases. On ne relance **aucun** swarm mondial sur `projects` avant la phase B.

### Phase A — Ne plus casser le contrat (en premier)

Objectif : le prochain clic Deploy ne peut plus vider la base ni poser un îlot fantôme.

| Tâche | Fichiers | Détail |
|-------|----------|--------|
| A1. Tuer les purges | `routers/projects.py`, `routers/swarm.py`, `swarm_pipeline.py`, `ProjectsCard.js` | `DELETE /api/projects` → **410**. `clear_db=true` → **400**, ignoré dans `deploy`. Case Console retirée. |
| A2. Plus de rustine GPS | `swarm_pipeline.py`, `routers/swarm.py` | Ne plus appeler `snap_to_ocean` ni `ocean_fallback_coords`. Si pas de GPS de lieu, ou point trop inland : `failed` stage `unlocated`. Point côtier : on **garde** le GPS géocodé (terre de havre OK). |
| A3. Règles hors code | `config.py`, `routers/misc.py`, `core/llm.py`, `core/ml.py` | `project_rules` dans settings : `gatekeeper_accept`, `gatekeeper_reject`, `min_marine_score`, `max_inland_km` (défaut 15), `allow_tinyfish_agent`, `max_partner_orgs`. `core` lit ces clés. |
| A4. Tests | `tests/test_project_contract.py` | 410 sur DELETE ; 400 sur clear_db ; process_url / helper : inland → pas d’insert ; pas d’import de `ocean_fallback` dans le chemin publish. |

Critère de sortie A : pytest du contrat vert ; l’UI n’offre plus « vider la base ».

### Phase B — Runs isolés (avant tout nouveau crawl)

Calquer Formalités. Harmoniser les fonctions de run entre modes (même empreinte, mêmes événements, même Console).

| Tâche | Fichiers | Détail |
|-------|----------|--------|
| B1. Collections | `project_runs.py` (nouveau), `main.py` indexes | `project_runs`, `project_run_projects` (1 ligne = 1 site ou 1 projet+sites[]), `project_run_events`. `wrote_projects: false`. |
| B2. Brancher le swarm | `swarm_pipeline.py` | `deploy` prend `run_id` ; insert → `project_run_projects`. Plus d’`insert_one` dans `projects`. |
| B3. API | `routers/project_runs.py` ou `/api/projects/runs` | POST run, GET status/diff/report, POST promote (plus tard, manuel). |
| B4. Console | `ProjectsCard.js`, `FormalitiesCard` comme modèle | Lancer un run, pas « Deploy sur la carte ». |
| B5. Force Extract / signalements | `swarm.py`, `projects.py` | Même pipeline, même run (ou run `enrich`). Gatekeeper obligatoire. |
| B6. `dataset: "projects"` | `telemetry()` | Alignement stats. |

Critère de sortie B : un run test (3 seeds) remplit `project_run_*`, `projects.count` inchangé.

### Phase C — Lieux d’action (cœur métier)

| Tâche | Fichiers | Détail |
|-------|----------|--------|
| C1. Schéma `sites[]` | `llm.py` `extract_project` | JSON : `sites: [{name, location, lat, lon, evidence}]` + financeurs[]. Un programme mondial → plusieurs sites ou `sites: []` + `unlocated`. |
| C2. Juge de lieu | `project_geocode.py` (nouveau) | Refus HQ (ville du financeur, mots headquarters/siège). Nominatim + GeoNames. Claude ou OpenRouter : « ce toponyme est-il un lieu d’action marin visitable ? ». Polygone AMP si le nom matche (géocodage, pas couche carte). |
| C3. Multi-points | `project_to_feature` / couche Leaflet | Un `project_id`, *n* Features, ou GeometryCollection. Popup : nom du **site**. |
| C4. TinyFish | `_discover` | Crawler → Search → Fetch ; Agent si `allow_tinyfish_agent` et toujours 0. |
| C5. MasterSeeds 861 | script `scripts/export_master_seeds.py`, `data/master_seeds.json` | Union distincte de `funders` + 21 URLs curées. Listing URL : domaine le plus fréquent des projets de ce financeur, ou à découvrir. Plus de plafond 5 partenaires en dur : même table, `max_partner_orgs` settings. |
| C6. Dédup | `_dedup_merge` | Appeler `merge_docs`. |

Critère de sortie C : sur un échantillon (Hope Spots, un programme multi-îles, un siège Pew), les sites publiés dans le **run** sont visitables ; 0 HQ ; 0 fallback.

### Phase D — Revue, Gold, ML

| Tâche | Fichiers | Détail |
|-------|----------|--------|
| D1. File de revue | collection `project_review`, UI Console | Files : `snapped` v1, `fallback`, `unlocated`, `hq_suspect`, discordances run↔v1. Actions : accepter site, éditer GPS, rejeter, promouvoir run→carte. |
| D2. Gold | export | v1 **moins** snapped **moins** fallback, **plus** les acceptés revue. Sert au gatekeeper. |
| D3. Ré-entraîner le gatekeeper | `ml.py` | **Après** D2, pas avant le premier run isolé. Le modèle v1 est biaisé ; le relancer maintenant recopie les sièges. |
| D4. Catégories | plus tard | Entraîner les indices `normalize_category`. **Non prioritaire** (les 9 familles restent un bonus d’affichage). |

Critère de sortie D : un opérateur peut nettoyer la v1 sans script Mongo ; un Gold exportable existe.

### Ordre et dépendances

```
A (sûreté) → B (runs) → C (sites + 861 seeds) → D (revue / Gold / ML)
                ↑
         aucun crawl carte avant B
```

On n’implémente **pas** un « snap borné à 50 km » : la revue a tranché, ce n’est plus une étape.

### Charge d’implémentation (technique, pas calendaire)

- **A** : peu de fichiers, risque faible, tests unitaires suffisent.
- **B** : copie raisonnable du module PoE runs (~même forme, autre collection).
- **C** : le morceau invasif (prompt, géocode, GeoJSON multi-points, seeds).
- **D** : surtout frontend + file Mongo.

---

## 15. Documents et conversations dont ce cahier hérite

- `docs/PRD.md`, `docs/ARCHITECTURE.md`, `README.md`.
- `docs/CAHIER_DES_CHARGES_POE.md` — même forme ; **modèle des runs** à calquer.
- `seed/projects.geojson` — 4 463 features.
- CDC Projets **v1.0** (7 sept. 2026) et **32 commentaires** Berry-Mappemonde (même jour) — § 29.

Ce cahier **v2 prime** sur la v1 et sur le code dès qu’il y a conflit.

---

## 16. Qui fait quoi

| Acteur | Fait | Ne fait pas |
|--------|------|-------------|
| **Visiteur** | Carte, filtres, URL, signalement | Swarm, revue, purge |
| **Opérateur** | Run isolé, revue, promotion, import | `clear_db`, Force All à l’aveugle |
| **Gatekeeper** | Page marine vs non | Inventer un site |
| **Juge de lieu** | Ce toponyme est-il visitable en bateau ? | Recaler vers n’importe quelle mer |
| **Réviseur** | Tranche snapped / HQ / unlocated, goldise un échantillon | Goldiser tout le seed d’un coup |
| **Pipeline** | Découvre, extrait, propose des sites dans un run | Toucher `projects` tout seul |

---

## 17. Cycle de vie d’un projet

```
URL (listing 861 / cache / signalement)
    → texte (cascade, pas un challenge)
        → gatekeeper marin
            → sites extraits (0..n)
                → chaque site géocodé (lieu d’action, pas HQ)
                    → site_ok → écrit dans le run
                    → sinon unlocated
                        → revue humaine
                            → promu vers projects (n Features)
```

| État | Sens | Où |
|------|------|-----|
| `cached` | URL vue | `deeplink_pages` |
| `unlocated` | Marin mais pas de site visitable | run / `failed` |
| `rejected` | Pas marin / page générique | `failed` gatekeeper |
| `run_site` | Site proposé | `project_run_projects` |
| `review` | Discordance ou v1 snapped/fallback | `project_review` |
| **carte** | Promu | `projects` (+ `sites[]`) |
| `reported` | Signalement | `reported_projects` |

Dédup : même URL, ou même site (nom+<500 m). Fusion `merge_docs` + union des financeurs.

---

## 18. Le second livrable : les portails financeurs

Une fiche par financeur (~861+) :

| Champ | Sens |
|-------|------|
| `name` | Nom tel que vu en base / page |
| `url` | Listing si connu, sinon domaine déduit |
| `priority` | 1 = les 21 listings curés (URLs sûres) ; 2 = le reste des 861 |
| `last_scan` / `urls_found` | Découverte |
| `listing_kind` | `projects_index` · `unknown` · … |

Follow the Money **écrit dans cette table** (plus une liste parallèle plafonnée à 5 en dur). Le plafond settings évite la dérive, il n’empêche pas d’intégrer une fondation déjà vue en v1.

---

## 19. Algorithme (découverte, sites, Follow the Money)

### Listing (L)

Financeur → pages projet (crawler, Search, Fetch ; Agent si 0 et autorisé).

### Marin + sites (M)

Page → gatekeeper → extract `sites[]`.  
Pour chaque site : juge de lieu → GPS ou `unlocated`.

### Décision

| L | M (au moins 1 site_ok) | Décision |
|---|------------------------|----------|
| oui | oui | sites dans le run |
| oui | non | `unlocated` / `rejected` |
| non | oui | signalement / partenaire : idem |
| non | non | ignoré |

Programme mondial : M = la **liste des lieux d’action**, pas « global ».

---

## 20. Modèle de données

### Carte v1 (ne pas écraser)

`projects` : aujourd’hui 1 document ≈ 1 point. Cible : 1 document projet + `sites: [{name, lat, lon, geo_source, site_ok}]`.  
Export GeoJSON : **une Feature par site** (même `project_id`).

Champs à conserver : `title`, `url`, `funders`, `description`, `s_ocean`, `category_group`, `image`.  
`snapped` / `geo_source=ocean-region-fallback` : flags de revue, plus des sources de publication.

### Runs (à créer)

| Collection | Une ligne = |
|------------|-------------|
| `project_runs` | un run (comme `poe_runs`) |
| `project_run_projects` | un projet/site du run |
| `project_run_events` | micro-étapes |
| `project_review` | file de revue |

Réutiliser `run_fingerprint`, `events.RunRecorder`, `TaskState`.

### Ailleurs

`deeplink_pages`, `discovery_state`, `telemetry` (+ `dataset`), `failed`, `reported_projects`, `settings`, `geocode_cache`.

Fichiers : `data/master_seeds.json`, `data/project_rules.json` (défauts), `seed/projects.geojson`.

---

## 21. Ce que voit l’utilisateur

**Visiteur.** Carte cyan, clusters, un marqueur **par site**, recherche, financeur, légende catégorie (bonus), liste, signalement, popup (lieu + URL + S_ocean). Plus de badge « snapped » comme qualité : un snapped v1 est à revoir, pas à vanter.

**Opérateur.** Lancer un **run**, logs, télémétrie. Plus de case « vider la base ». File de revue + promouvoir. Import/export. Réglages : seuils, `max_inland_km`, Agent on/off, budget Claude.

Manques actuels (= phase B/D) : runs, revue, multi-sites, fiche 861 portails.

---

## 22. Inventaire des MasterSeeds

**Cible : ~861 financeurs** issus de la v1, pas 21 lignes.

Les 21 listings curés restent **priority 1** (URL de listing connue) :

The Ocean Foundation, Oceana, Blue Marine Foundation, Fondation de la Mer, Pure Ocean, Fondation CMA CGM, IFREMER, Prince Albert II, Institut Paul Ricard, SHOM, CORDIS, Coral Reef Alliance, Mission Blue, Seacology, Ocean Conservancy, Pew, WWF Oceans, Packard, Rare Fish Forever, Fauna & Flora Oceans, WCS Marine.

Les autres ~840 : `priority: 2`, nom tel qu’en base, URL à découvrir (Search sur `"{name}" marine projects`).

SHOM / IFREMER : instituts — 0 URL projet reste un succès honnête s’il n’y a pas de listing d’actions.

---

## 23. Gatekeeper et taxonomie

Trois étages, **seuils dans settings** :

1. ML local si assez entraîné : accept / reject selon `gatekeeper_accept` / `gatekeeper_reject` (défauts historiques 0,85 / 0,12).
2. OpenRouter ou Claude (si budget).
3. Heuristique mots-clés + `min_marine_score`.

Ré-entraînement : **après** Gold (phase D), pas pour « débloquer » un run.

Neuf familles : utiles à l’affichage, **chantier non prioritaire**. Plus tard : entraîner les indices.

---

## 24. Exemples concrets

**Hope Spot.** Chaque spot = un site visitable. Pas le bureau Mission Blue.

**Programme mondial à 4 récifs.** 4 sites, 1 projet, 4 points. Pas un point « Pacifique ».

**Pew / siège Washington.** L = pages projet ; M refuse Washington ; cherche l’AMP / la côte nommée ; sinon `unlocated`.

**Signalement « Coral Gardeners Moorea ».** Site Moorea si la page le dit. `Community Report` dans `funders`.

**v1 snapped ou fallback.** Invisible comme « bon point » : file de revue, exclu du Gold tant que non accepté.

---

## 25. Recette

### Portail / financeur

1. Fiche dans MasterSeeds élargis.
2. Chaque site carte : GPS d’action, URL, financeurs, `site_ok`.
3. 0 HQ, 0 fallback, 0 snap, 0 (0,0).
4. Programme multi-lieux : autant de points que de sites extraits.
5. Compte `projects` v1 non diminué sans revue écrite.

### Run

1. `wrote_projects: false`.
2. Aucun appel `snap_to_ocean` / `ocean_fallback_coords` dans les traces.
3. `clear_db` impossible (400).
4. Tests : `test_project_contract.py` + suites existantes non-destructives (`>= 4463`).

### Interdit

Relancer un `full` sur la carte. Réintroduire une case purge. « Juste un petit snap ».

```bash
cd backend && python3 -m pytest tests/test_project_contract.py tests/test_blue_intelligence.py tests/test_import_and_regression.py tests/test_zoom_and_new_features.py tests/test_refactor_core.py -q
```

---

## 26. Risques

| Risque | Parade |
|--------|--------|
| Purge | Fonctions **supprimées** (phase A) |
| Rustine GPS | Plus d’appel ; revue des v1 sales |
| HQ | Juge de lieu + liste de villes siège |
| Programme mondial → 0 point | Extraire *n* sites ; `unlocated` honnête > centroïde |
| 861 seeds = crawl énorme | Runs isolés, TTL, saturation, priority 1 d’abord |
| TinyFish Agent | Search/Fetch ; flag off |
| ML v1 biaisé | Ne pas ré-entraîner avant Gold |
| AMP mal utilisées | Coulisse géocode seulement |
| Multi-points / perf carte | `max_markers` inchangé ; cluster |

---

## 27. Hors périmètre

- Formalités — `docs/CAHIER_DES_CHARGES_POE.md` (on **harmonise** seulement les runs).
- Marinas / mouillages de la route.
- Couche polygones AMP **sur la carte** (l’usage géocode est **dans** le périmètre C2).
- Crowdsourcing PoE.
- Promotion automatique run → carte.
- Croisement projet ↔ PoE (P2 PRD).
- Entraînement des catégories (plus tard).
- Annuaire de toutes les ONG marines hors financeurs v1 + signalements + Follow the Money.

---

## 28. Annexes

### A. Télémétrie

`SUCCESS` (sites dans le run), `MERGED`, `REJECTED`, `UNLOCATED`, `FAILED`, `CANCELLED`. Champ `dataset: "projects"`.

### B. API cible

| Méthode | Effet |
|---------|--------|
| `GET /api/projects` | Carte (1 Feature / site) |
| `POST /api/projects/runs` | Run isolé |
| `POST /api/projects/runs/{id}/promote` | Manuel, plus tard |
| `POST /api/swarm/deploy` | Devient un run ; `clear_db` → 400 |
| `DELETE /api/projects` | **410** |
| `POST /api/report-project` | File + prochain run |

### C. Restauration v1

```bash
curl -X POST http://localhost:8001/api/import/geojson \
  -H "Content-Type: application/json" --data-binary @seed/projects.geojson
```

Skip des URLs connues. Pas une purge.

### D. Tests

Actuels : `test_blue_intelligence.py`, `test_import_and_regression.py`, `test_zoom_and_new_features.py`, `test_refactor_core.py`, `test_ml_jobs.py`.  
À ajouter : `test_project_contract.py` (A), puis tests de runs (B) sur le modèle `test_poe_*`.

### E. Attribution

Pages des fondations ; OSM / Nominatim / GeoNames ; AMP en indice si réutilisées. Synthèses, pas textes officiels.

---

## 29. Trace des commentaires de revue (v1 → v2)

| # | Décision reprise |
|---|------------------|
| 0, 6, 7 | Phrase d’ouverture, éco-tourisme, bateau, plusieurs financeurs |
| 1, 2, 5, 9, 14 | Abandon de `snap_to_ocean` comme publication |
| 3, 21 | Agent cher ; Search/Fetch d’abord |
| 4, 15, 20 | Meilleur géocode + Claude autorisé |
| 8 | *n* sites pour un programme mondial |
| 10, 16, 22 | Créer `project_run_*`, harmoniser les modes, avant un nouveau run |
| 11, 27, 24 | Gold à **créer** (v1 − snapped − fallback) ; ré-entraîner **après** |
| 12, 13, 29 | MasterSeeds = ~861 financeurs |
| 17 | Supprimer purges (pas seulement les cacher) |
| 18, 19 | Plus de fallback ; plus de HQ en sortie de géocode |
| 23 | Télémétrie `dataset` : cosmétique, champ à ajouter (B6) |
| 25 | AMP = indice de géocodage (C2) |
| 26 | UI de revue plutôt qu’un snap borné (D1) |
| 28 | Enrich ↻ = re-texte aujourd’hui ; le GPS se revoit en C/D, pas par snap |
| 30 | Seuils configurables (A3) |
| 31 | Catégories : garder, entraîner plus tard, pas prioritaire |

---

*Fin du cahier des charges v2. Toute évolution de règle se fait d’abord ici, puis dans le code. L’implémentation suit le § 14, phase A en premier.*
