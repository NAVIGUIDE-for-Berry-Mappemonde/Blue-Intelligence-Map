# Contrats de Review par mode

Le cahier `docs/CAHIER_DES_CHARGES_REVIEW.md` v1.1 est le **contrat de relecture des PoE** : une fiche par polygone VLIZ, toutes les preuves déjà payées, choix garder / écarter, puis **Gold**. Les autres modes n’y ont qu’une esquisse (§7.1, §7.3, §9.2, §11.1).

Ce document propose le **même geste Review**, adapté à chaque mode produit. Review reste le **troisième onglet** (Map / Console / Review) : il ouvre la file du **mode actif**.

Formalités est le **mode de référence** (documents, pas les ports ; Proposer ; leçons Gold ; extract après Gold). Les autres files calquent **le geste**, pas l’objet, pas les jetons `habilitados` / `jorf`, pas le filtre EN·FR·ES. AMP / Projets ont un lot Proposer ; marinas / capitaineries un juge de champs **par fiche** (pas de lot OSM).

**Science** et **Climatologie** n’ont **pas** de file Review en V1 (plan C8) : moisson / snapshot, pas un run Gold. L’onglet Review y affiche un placeholder. Ce document ne les couvre pas.

Hérite de : `docs/CAHIER_DES_CHARGES_REVIEW.md`, `docs/CONTRATS_MODES.md`, `docs/CAHIER_DES_CHARGES_POE.md`, `docs/CAHIER_DES_CHARGES_PROJETS.md`.

---

## 0. Méta-contrat (commun à toutes les files)

Cette section **prime** dès qu’il y a conflit avec une UI ou un kind d’implémentation.

Review est une **file de relecture qui aboutit à un run certifié**. Ce n’est pas une carte, pas un crawler, pas un goldiseur silencieux.

| Règle | Sens |
|-------|------|
| **Une fiche = l’objet du mode** | Cumul **dédupliqué** de la v1 + de **tous** les runs. Pas un canari. Pas un `run_id` comme espace Gold. |
| **Une fiche à la fois** | Commentaire, choix (garder / écarter), puis Gold. |
| **Commentaire ≠ live** | Sauver un texte n’écrit pas `projects` / `poe_ports` / `eez_zones` / `marinas` / `capitaineries` / `amp_sites`. |
| **Gold = entrée dans le run certifié** | Clic explicite. Alimente le run Review du mode. Pas `generate-batch`. Pas une mutation au Enregistrer. **N’affiche rien tout seul sur Map.** |
| **Pas de Générer** | Hors Review. |
| **Run isolé = debug** | Utile pour comprendre un moteur. On ne goldise pas un canari / smoke / seed-enrich. |
| **Clé de commentaire** | `{mode}:{entity_id}` sur la fiche union. Plus `{kind}:{run_id}:{id}` comme clé de job. |
| **Listing-control** | Reste en Console. Pas une file Review. |
| **Gold = la preuve, pas la liste dérivée** | On tranche le document / l’identité / le couple d’URLs. On ne goldise pas 137 ports, ni chaque mention financeur, ni le polygone AMP. |
| **Montrer toutes les preuves** | Le pipeline range ; l’UI ne cache rien « pour faire propre ». Une home reste visible pour qu’on l’écarte. |
| **« Aucune preuve » est une décision** | UNCLOS / `none` (Formalités), `no_visit` (AMP), `unlocated` (Projets, **pas** un GPS inventé), « pas une marina / pas un bureau ». |
| **Proposer ≠ Gold** | Un juge (local ∥ LLM) peut pré-remplir. Il écrase cases et commentaires. **Il ne Gold pas.** Il n’écrit pas le live. |
| **Gold d’abord, dérivé ensuite** | Le snapshot fige la preuve. Un job plus tard extrait / nettoie **depuis cette preuve seulement**. |
| **Pré-Gold = file, pas certificat** | « OSM a un point » range la fiche. Ça n’allume pas Gold. |

**Phrase de test.** Un test qui enregistre un commentaire et voit la collection live mutée **casse le contrat**. Un test qui clique Gold et ne voit **pas** la fiche dans le run certifié **casse aussi le contrat**. Un test qui clique Gold et voit la Map **changer sans** « Afficher la review » **casse le contrat**. Un test où Proposer allume Gold **casse le contrat**.

Ce qui change par mode : **la question que le réviseur tranche**, **ce qui est une preuve**, **quand Gold s’allume**. L’effet Map est **le même** pour tous les modes (§8).

---

## 0.1 Leçons Formalités — ce qu’on calque, ce qu’on ne copie pas

Ces règles viennent du contrat Formalités déjà en prod (Gold documents, juge vision, lot Proposer, `review_lessons`). Elles **priment** sur une copie naïve du code `review_doc_picker.py`.

### Ce qu’on calque (geste)

| Leçon | Sens pour les autres files |
|-------|----------------------------|
| **Une question par mode** | Gold s’allume quand *cette* question est tranchée, pas quand tout est coché. |
| **Grain de l’objet** | France hexagone ≠ Mayotte (`mrgid`). Un projet à n sites ≠ un centroïde mondial. Un bureau ≠ la marina à 400 m. Une AMP = un `site_id` sur **une** façade. |
| **Blacklist au grain du chemin / de l’objet** | Une actu `gob.mx` nulle n’interdit pas le PDF officiel du même domaine. On blackliste un **chemin** ou un `mrgid`, pas un hostname entier par défaut. |
| **Local ∥ LLM, liste fermée** | L’heuristique tourne en parallèle du LLM. Le LLM **n’invente aucune URL** hors des candidats déjà sur la fiche. Vision utile si la preuve est une page / un PDF ; inutile pour un tag OSM. |
| **HITL** | Proposer écrit `review_suggest`. Gold écrit `review_lessons` (écart keep/drop). Le lot suivant relit ces leçons (few-shot + score de chemin). Le rapport dit « Proposer s’est trompé ici » — **il n’écrit pas les règles**. |
| **Clés par `kind`** | `review_lessons` / `review_suggest` : `eez:`, `amp:`, `project:`, `marina:`, `capitainerie:`. Pas un fourre-tout Formalités. |

### Ce qu’on ne copie pas (métier Formalités)

- Jetons de chemin `habilitados`, `jorf`, `puertos` — chaque mode a **sa** liste.
- Filtre de langue EN / FR / ES du pilote Toloka / SERP Formalités.
- Cases `ports_ok` / un clic par objet dérivé comme condition Gold.
- Gold automatique parce que « la source a l’air officielle » (OSM ⇒ marina certifiée ; toutes les capitaineries `gold_on`).
- Une QA LLM qui **rejoue** Proposer (même pages, même question) au lieu d’auditer l’humain.
- Relancer un crawl, SearXNG, ou écrire `poe_ports` / live « pour voir la carte tout de suite ».

### Ordre suivi (déjà implémenté)

1. **AMP** — même geste « parmi ces URLs, laquelle est *la* preuve de *cet* objet ». Lot `scope=all`, clés `amp:`, `no_visit`.
2. **Projets** — deux questions (URL projet + site `site_ok`). Lot `scope=all`, clés `project:`. Le juge refuse `snap_to_ocean` / HQ et n’invente aucune URL.
3. **Marinas / Capitaineries** — juge de **champs sourcés** sur **une fiche** (`scope=one`). `POST /review/suggest` `scope=all` → 400. Clés `marina:` / `capitainerie:`.

Infrastructure à **factoriser** (pas le prompt) : job `TaskState` + `GET /review/suggest/status`, `compare_verdicts`, few-shot par proximité (pays / façade / souverain), cascade vision déjà dans `complete_json_cascade`, rapport en lecture seule.

**Crowd / Toloka** (hors V1) : si on délègue, on délègue **le même geste** (ces liens sont-ils la bonne preuve de *cet* objet ?), pas l’extraction des ports / sites / VHF. Ça n’entre pas dans ce contrat produit.

---

## 1. Tableau des files

Cinq modes produit, **cinq files**. Pas de file `poe` séparée (accident d’implémentation : deux collections Mongo). Pas de file pays à la place d’un `mrgid`.

| Mode | Une fiche = | Identifiant | Preuve que le réviseur juge | Gold quand |
|------|-------------|-------------|-----------------------------|------------|
| **Formalités** | un polygone VLIZ + ses ports | `mrgid` | URLs d’**État** (TD toutes runs). WPI = contre-preuve. Noonsite hors fiche. | ≥ 1 TD gardée (ou UNCLOS `none`) ; ports extraits ensuite des docs |
| **Projets** | un projet (n sites) | `_id` ou `url` | URL de **page projet** + GPS du **lieu d’action** visitable en bateau | URL projet + ≥ 1 site accepté (pas snapped / fallback / HQ) |
| **Marinas** | une marina | `osm_id` | Identité OSM + GPS du bassin. Enrichissement (VHF, places, tirant) **sans inventer**. `/maps/place/` = signal. | Identité + GPS acceptés. Champs enrichis : garder seulement s’ils sont sourcés |
| **Capitaineries** | un **bureau** | `osm_id` et/ou `shom_id` / `noaa_id` | Bâtiment (pas le plan d’eau). Tél + VHF sourcés (tags ou page officielle). Calque 250 m ≠ fusion 500 m. | Bureau + GPS acceptés. Contact : garder seulement s’il n’est pas inventé |
| **AMP** | un site ProtectedSeas (façade) | `site_id` | **Deux** URL distinctes : `manager_url` ≠ `visit_url`. Candidats visite tous visibles. | Couple tranché : visite gardée **distincte**, ou « pas de visite » assumé |

---

## 2. Formalités — contrat de référence (déjà écrit)

C’est `docs/CAHIER_DES_CHARGES_REVIEW.md` §3.4 / §7.2 / §11. On ne le réécrit pas. On le **nomme** pour que les autres files calquent le geste, pas l’objet. État code (référence, pas à recopier mot à mot) : `review_doc_picker.py`, `review_lessons.py`, `review_extract.py`.

**Question.** Parmi toutes les TD déjà trouvées pour **ce** `mrgid`, laquelle (ou lesquelles) est *la* liste d’État de **ce** polygone ? Gold fige ces documents. Les ports sont extraits ensuite depuis ces URLs (pas un clic par nom). Sinon UNCLOS.

**Interdit.** Pays à la place du polygone. File ports séparée. Cacher des TD « pour n’en garder qu’une ». Noonsite / wiki / forum comme preuve. WPI comme preuve **positive** de plaisance (sauf mixte explicite). Goldiser un canari. Cocher les ports comme condition Gold. Blacklister un domaine entier parce qu’une actu est nulle.

**Écritures Review.** Commentaire ; keep/drop **TD** (et URLs collées) au grain `mrgid` ; pin / blacklist de **chemin** (secours ISO2) ; Gold = snapshot `{sources_td, ports: [], ports_status: pending_extract}` dans le **run certifié**. Le job extract remplit ensuite `review_gold.snapshot` seulement — jamais `poe_ports`. Map Formalités reste le **run unique** tant que « Afficher la review » est décoché.

**Proposer (déjà là).** Un clic lance le lot sur **toutes** les fiches Formalités (`POST /api/review/suggest` `scope=all`). Écrase cases et commentaires. **Ne Gold pas.** Au Gold : `review_lessons` compare la dernière proposition à tes keep/drop. Le lot suivant réinjecte few-shot + score de chemin. Le rapport a une section **« Proposer s’est trompé ici »**.

---

## 3. Projets — contrat de Review proposé

Calque : CDC Projets v2 phase D + Review §7.1 / §11.1.

### 3.1 Objet

Une fiche = **un projet**, union v1 + `project_run_*` du même projet (`same_site` : 500 m + nom). Un programme mondial = **plusieurs sites** sur **la même** fiche, pas un centroïde « global ».

### 3.2 Question du réviseur

1. L’URL est-elle une **page projet** (pas une home fondation, donate, news, jobs) ?
2. Chaque `sites[]` est-il un **lieu d’action** assez précis et **accessible en bateau** — pas le siège, pas une ville intérieure, pas un `snap_to_ocean`, pas un `ocean_fallback` ?
3. S’il n’y a aucun site tenable : `unlocated` (reste en file), **pas** un GPS inventé.

### 3.3 Ce qu’on voit sur la fiche

| Élément | Sens | Interdit |
|---------|------|----------|
| **URLs** | Toutes les URLs du projet, tous runs, dédupliquées, cliquables | Une seule URL cachée ; home financeur présentée comme *la* page |
| **Financeurs** | Ceux de la page / du seed, fusionnés | Inventer un financeur |
| **Sites** | Nom, GPS, `geo_source`, `site_ok`, preuve textuelle | Un point unique HQ ; snapped laissé tel quel |
| **Verdicts pipeline** | `snapped` / `fallback` / `hq_suspect` / `unlocated` / discordance run↔v1 | Les prendre pour Gold sans clic |

Files d’entrée (CDC phase D) : `snapped`, `fallback`, `unlocated`, `hq_suspect`, discordances run↔v1. Ce sont des **filtres de la même file**, pas cinq modes.

### 3.4 Choix

| Cible | Actions | Règle nourrie |
|-------|---------|---------------|
| URL | garder / blacklister (chemin donate, home) | `CRAWL_BLACKLIST` / règles projet |
| Site | accepter / rejeter / **éditer GPS** (puis Gold) | — |
| Projet entier | Gold / laisser en file | Gold dataset gatekeeper |

Éditer le GPS **sans** Gold : hors périmètre Review v1.1 (CDC Review §21). Proposition : le GPS édité vit dans `review_choices` jusqu’au clic Gold.

### 3.5 Gold

**Actif si** : au moins une URL de **projet** gardée **et** au moins un site `site_ok` accepté (GPS de lieu d’action, pas snapped / fallback / HQ).

**Le clic** : fige URLs + sites acceptés ; écrit la fiche dans le **run certifié** (`review_gold` kind `project`). Map Projets continue d’afficher le **run unique**. Le run certifié n’apparaît que si « Afficher la review » est coché. Sert ensuite à recalibrer le gatekeeper (CDC D2–D3) — **après** un Gold, pas avant.

**Ne fait pas** : goldiser tout le run d’un coup ; republier un `ocean_fallback` ; coller un polygone AMP comme preuve de projet ; retirer un projet de la carte par défaut ; goldiser parce que le pipeline a dit `site_ok`.

### 3.6 Ce que Review ne décide pas

Relancer le swarm. Purger `projects`. Traiter un financeur comme un projet. Croiser projet ↔ PoE (hors périmètre CDC).

### 3.7 Ce qu’on calque de Formalités (implémenté)

Lot Proposer `kind=project` (`review_project_picker.py`), **après AMP** (§0.1).

- **Question du juge.** Parmi les URLs déjà sur la fiche, lesquelles sont une **page projet** ? Parmi les `sites[]`, lesquels sont un **lieu d’action** `site_ok` (pas HQ, pas snapped, pas fallback) ?
- **Liste fermée.** Aucune URL inventée. Aucun GPS inventé. `unlocated` reste en file.
- **Montrer tout.** Toutes les URLs, tous les sites, tous les verdicts pipeline — visibles, pas une URL « pour faire propre ».
- **HITL.** `review_suggest` kind `project` ; leçons au Gold ; few-shot prioritaire même pays / même financeur ; score de chemin `donate` / `careers` / `news` / `jobs` (liste **Projets**, pas les jetons Formalités).
- **Après Gold.** Recalibrer le gatekeeper (CDC D2–D3) à partir du rapport, **pas** en écrivant `projects` depuis Proposer.
- **Vision.** Utile (page projet vs listing / donate). Même cascade que Formalités, autre prompt.

---

## 4. Marinas — contrat de Review proposé

Calque : Review §7.3 / CONTRATS_MODES « Marinas » / `REGLES_PARAMETRES` §3.3.

### 4.1 Objet

Une fiche = **une marina** (`osm_id`). Union du run unique + enrichissements. Les **mouillages** (`marina_run_anchorages`, corridor de route) **ne sont pas** cette file.

### 4.2 Question du réviseur

Est-ce bien une **marina de plaisance visitable** (bassin `leisure=marina`), au bon GPS, **sans** la confondre avec un PoE ni avec la capitainerie d’à côté ?

L’enrichissement (VHF, places visiteurs, tirant, tél) est-il **lu** sur une page / un tag, ou inventé ?

### 4.3 Ce qu’on voit sur la fiche

| Élément | Sens | Interdit |
|---------|------|----------|
| Identité OSM | `osm_id`, tags name / seamark | Fusionner deux bassins au `same_site` 500 m des projets |
| GPS | Point OSM du bassin | Recaler vers une douane, un PoE, un siège |
| `/maps/place/` | Signal (point plus gros) s’il existe vraiment | Inventer une fiche Maps ; filtrer la couche si absent |
| Website | Tag OSM ou Search nommé **officielle** | Tripadvisor / OTA comme source d’enrichissement Agent |
| Champs métier | VHF, places, tirant, services — sourcés | Un LLM qui remplit un trou par hallucination |
| Douane ≤ 800 m | **Graine P** Formalités, lien sortant | Preuve sur la fiche polygone Formalités |

**Pas d’URL d’État exigée.** Une marina n’est pas un décret.

### 4.4 Choix

| Cible | Actions |
|-------|---------|
| Identité / GPS | accepter / « pas une marina » (dry stack, resto, club à terre) |
| URL Maps / website | garder / blacklister (OTA, forum) |
| Chaque champ enrichi | garder / écarter (vide ≠ faux) |

### 4.5 Gold

**Actif si** : identité OSM + GPS acceptés.

**Le clic** : entre la fiche dans le **run certifié**. Map Marinas continue d’afficher le run unique.

**Ne fait pas** : transformer une marina en PoE ; rattacher le téléphone de la capitainerie comme champ marina sans source ; goldiser un mouillage ; masquer le run unique.

### 4.6 Écart code

`GOLD_KINDS` contient `marina`. `gold_pressed` ignore le pré-Gold (Gold = override allumé). `is_pre_gold_marina` range encore **tout le dump OSM avec GPS** dans le filtre « pré-Gold » de la file : ça reste un **interrupteur de file trop large**, pas un certificat. Le contrat exige un **clic** (identité + GPS vus). Ne pas relire « pré-Gold » comme « déjà certifié ».

### 4.7 Ce qu’on calque de Formalités (implémenté)

Juge de champs **par fiche** (`review_field_picker.py`). L’objet est un point OSM, pas une page d’État. Pas de lot mondial.

- **Pas de lot mondial** sur tout le dump OSM (coût, bruit, geste différent).
- **Oui** : un petit juge de **champs sourcés** (VHF, places, tirant, tél) — garder le tag / la page, écarter l’hallucination. Liste fermée de champs déjà affichés.
- **« Pas une marina »** = l’équivalent UNCLOS (`dry stack`, resto, club à terre) : décision, pas un Gold silencieux.
- **Blacklist** : OTA / Tripadvisor **par chemin**, pas « tout `google.com` » à cause d’un `/maps/place/` utile.
- Vision : peu utile pour l’identité OSM. Inutile de copier le picker Formalités tel quel.

---

## 5. Capitaineries — contrat de Review proposé

Mode produit (README, CONTRATS_MODES). **Absent** du CDC Review v1.1 (trois modes). L’UI a déjà `CapitainerieFiche`. `GOLD_KINDS` contient désormais `capitainerie` ; Gold reste un **clic**.

### 5.1 Objet

Une fiche = **un bureau** (le bâtiment), pas le plan d’eau, pas la marina. Identité : `osm_id` et/ou calque SHOM / NOAA à **0,25 km, distance seule** (`find_building`). Un nom différent n’empêche pas le calque. Un nom proche à 400 m **ne colle pas** deux bureaux.

### 5.2 Question du réviseur

1. Le point est-il le **bâtiment** harbour-master, pas un ponton, pas un `leisure=marina` ?
2. Le téléphone et le VHF viennent-ils des **tags** ou d’une **page officielle** — pas d’un avis TripAdvisor, pas d’une invention LLM ?
3. Le calque SHOM/NOAA colle-t-il le **même** bâtiment (≤ 250 m) ou a-t-on fusionné deux bureaux ?

### 5.3 Ce qu’on voit sur la fiche

| Élément | Sens | Interdit |
|---------|------|----------|
| Sources | OSM, SHOM `CATSCF=6`, NOAA — **toutes** visibles | Last-wins qui efface un id |
| GPS | Bâtiment | GPS du bassin marina « parce que c’est à côté » |
| Website | Page contact officielle | Réseau social / OTA |
| Tél / VHF | Regex tags → page → LLM seulement s’il reste un trou | Écraser un tag OSM déjà rempli |
| Lien marina | **Aucun rattachement** | Copier `telephone_capitainerie` depuis la fiche marina comme preuve |

### 5.4 Choix

| Cible | Actions | Règle |
|-------|---------|-------|
| Bureau | garder / « pas un bureau » (plan d’eau, marina) | — |
| Overlay | accepter le calque / détacher (deux bâtiments) | Ne pas élargir `merge_km` hors intervalle |
| URL | garder / blacklister | `serp_filter` |
| Tél / VHF | garder / vider (suspect) | Un champ vide vaut mieux qu’un faux |

### 5.5 Gold

**Actif si** : identité bâtiment + GPS acceptés. Tél / VHF optionnels, mais s’ils sont affichés ils doivent être **gardés** (sourcés).

**Le clic** : Gold kind `capitainerie` ; fiche dans le **run certifié**. Map Capitaineries continue d’afficher le run unique.

**Ne fait pas** : fusionner avec une marina ; réutiliser `same_site` 500 m ; goldiser sans GPS de bâtiment.

### 5.6 Écart code

`gold_pressed` n’allume plus Gold tout seul. `is_pre_gold_capitainerie` = bâtiment + GPS : **filtre de file**, pas certificat. Vérifier qu’aucune UI / API ne repose encore `gold_on: true` par défaut (ancien écart : toutes les capitaineries certifiées sans geste).

### 5.7 Ce qu’on calque de Formalités (implémenté)

Même juge de champs que les marinas (`kind=capitainerie`) : pas un lot mondial. Overlay SHOM/NOAA accepté ou écarté.

- Juge de **champs** (tél / VHF) : sourcé (tag, page officielle) vs inventé / TripAdvisor.
- Overlay : accepter ou **détacher** (deux bâtiments). Ne pas élargir `merge_km` parce que le juge « a fusionné ».
- « Pas un bureau » (plan d’eau, ponton, marina) = décision `none`.
- Aucun rattachement marina ↔ capitainerie comme preuve.

---

## 6. AMP — contrat de Review proposé

Mode produit. Fiche UI déjà là (`AmpFiche`) : `visit_candidates`, keep/drop visite, case « pas de visite ». `GOLD_KINDS` contient `amp`. Proposer + leçons kind `amp` (`review_amp_picker.py`).

### 6.1 Objet

Une fiche = **un site ProtectedSeas** (`site_id`) sur une **façade** (pas le monde). Géométrie = polygone déjà là. Review ne redessine pas le polygone. Review tranche les **deux URL**.

### 6.2 Question du réviseur

Parmi les candidats déjà trouvés, quelle URL est la **visite** (permis, mouillage, entrée, plaisance) de **ce** site — et laquelle est seulement le **gestionnaire** ?

La visite n’est **jamais** la homepage gestionnaire, ni une copie de `manager_url`, ni une URL hors liste (anti-hallucination `ask_yes_no`).

### 6.3 Ce qu’on voit sur la fiche

| Élément | Sens | Interdit |
|---------|------|----------|
| `manager_url` | Champ ProtectedSeas (Website) | La prendre pour *la* visite |
| **Candidats `visit_url`** | Tous les hits Search / liens Fetch, **dédupliqués, cliquables** | N’en afficher qu’une « pour faire propre » ; en inventer une hors liste |
| Statuts pipeline | `found` / `rejected_same_as_manager` / `not_found` / `none` | `found` alors que URL ≡ manager |
| LFP, désignation, autorité | Contexte | Critère Gold (LFP ne goldise pas) |
| Pays / façade | Filtre de file | Une file mondiale unique comme vérité |

Même esprit que les TD Formalités : **montrer tout, choisir**. Le pipeline propose un rang ; ce n’est pas un filtre qui cache.

### 6.4 Choix

| Cible | Actions | Règle |
|-------|---------|-------|
| `visit_url` | garder une parmi les candidates / écarter les homepages | Blacklist **chemin** blog / mouillage générique — pas le domaine entier d’une autorité |
| « Pas de visite » | assumer `not_found` / `none` | Fiche Gold **incomplète** ou Gold « sans visite » explicite |
| `manager_url` | corriger si ProtectedSeas a collé un pipe d’URLs | Ne jamais écrire manager dans visit |

### 6.5 Gold

**Actif si** : une `visit_url` **gardée** et **distincte** de `manager_url`, **ou** confirmation explicite « pas de page visite » (équivalent UNCLOS `none` côté Formalités).

**Le clic** : snapshot `{manager_url, visit_url}` dans le **run certifié**. Map AMP continue d’afficher le run unique. Le polygone ProtectedSeas n’est pas redessiné.

**Ne fait pas** : goldiser la homepage ; servir le cache tuile 30 j. comme fusion de fiches ; lancer SearXNG (ce n’est pas une liste d’État par ZEE).

### 6.6 Écart code

Proposer + leçons `amp:` + rapport multi-kind sont en place. Si un run n’écrit pas `visit_candidates`, l’UI retombe sur une seule `visit_url` — le pipeline doit **toujours** exposer la liste.

### 6.7 Ce qu’on calque de Formalités (première file à doter)

Geste le plus proche : « parmi ces URLs, laquelle est *la* visite de **ce** `site_id` ? »

- **Liste fermée.** Candidats Search / Fetch seulement. Jamais `visit_url == manager_url`. Jamais une URL hors liste (`ask_yes_no` anti-hallucination).
- **`no_visit`** = UNCLOS Formalités : Gold possible sans page.
- **Proposer + HITL.** Même job `TaskState` / `GET …/status` ; clés `amp:{site_id}` ; few-shot par façade / pays ; score de chemin homepage vs permis / mouillage / plaisance (liste **AMP**).
- **Vision.** Utile (page permis vs home gestionnaire).
- **Après Gold.** Snapshot `{manager_url, visit_url}` seulement. Pas de redraw du polygone. Pas de SearXNG depuis Review.
- LFP / désignation = contexte, **pas** critère Gold.

---

## 7. Ce que Review fait / ne fait pas (par mode)

| | Formalités | Projets | Marinas | Capitaineries | AMP |
|---|------------|---------|---------|---------------|-----|
| Commenter | oui | oui | oui | oui | oui |
| Choisir des URLs | TD + BU | pages projet | website / Maps | page contact | candidats visite |
| Tranche l’objet | pages / PDF d’État (pas chaque port) | sites keep/drop/édit GPS→Gold | marina vs non | bureau vs plan d’eau | visite vs manager |
| « Aucune preuve » goldisable | UNCLOS / `none` | non (`unlocated` reste en file) | « pas une marina » | « pas un bureau » | `no_visit` |
| Blacklist → règles | chemin / `mrgid` (pas le domaine entier) | chemins listing | OTA (chemin) | OTA / réseaux | homepages visite (chemin) |
| Proposer (juge) | **oui** (lot, ne Gold pas) | **oui** (lot, ne Gold pas) | **oui** (fiche, pas de lot OSM) | **oui** (fiche, pas de lot) | **oui** (lot, ne Gold pas) |
| Leçons HITL / rapport écarts | **oui** (`eez:`) | **oui** (`project:`) | **oui** (`marina:`) | **oui** (`capitainerie:`) | **oui** (`amp:`) |
| Relancer un crawl | non | non | non | non | non |
| Inventer un GPS / une URL | non | non | non | non | non |
| Écrire la live sans Gold | non | non | non | non | non |
| Changer Map sans « Afficher la review » | non | non | non | non | non |

---

## 8. Map et Review — un seul interrupteur

L’onglet **Map** a une couche **par défaut**, indépendante de la Review. Gold n’y touche pas.

Le **run unique** correspondra au run de test que l’on va lancer sous peu.

| Mode | Carte par défaut |
|------|------------------|
| **Projets** | le run unique |
| **Formalités / PoE** | le run unique |
| **Marinas** | le run unique |
| **Capitaineries** | le run unique |
| **AMP** | le run unique |

La Review constitue **un run certifié par l’humain** (les fiches goldisées, avec leurs choix). C’est un run de plus, le même objet pour tous les modes.

Sur Map, un bouton **Afficher la review**, décoché par défaut :

- **coché** → la carte montre le run certifié du mode actif ;
- **décoché** → retour à la couche par défaut du tableau ci-dessus.

Pas de régime « publication exclusive Formalités ». Pas de « filtre skipper Projets ». Pas de « badge OSM ». Un interrupteur, cinq couches par défaut.

---

## 9. Hors périmètre (ces contrats)

- File `poe` séparée de la fiche polygone.
- File listing-control / Noonsite.
- File **mouillages** (corridor Marinas) — dump OSM, pas d’enrichissement ; faux positifs = plus tard.
- File **financeurs** (~861 portails) — second livrable Projets, pas une file Review v1.
- Comparateur split-screen run A \| run B (remplacé par l’union).
- Crowdsourcing skipper depuis Review.
- Relance de crawl depuis Review.
- SearXNG sur marina / capitainerie / AMP.
- Review / Gold des modes **Science** et **Climatologie** (C8).
- Copier le picker Formalités (jetons, prompt, filtre EN·FR·ES) tel quel sur un autre mode.
- QA LLM / crowd qui **rejoue** Proposer au lieu d’auditer le geste humain.
- Lot Proposer mondial sur le dump OSM marinas / capitaineries.

---

## 10. Recette minimale (quand on implémente)

1. Cinq files, une par mode actif. **Zéro** onglet « Ports d’Entrée » à côté de « Polygones ».
2. Commentaire persisté ; collections live **inchangées**. Proposer non plus n’écrit le live ni Gold.
3. Formalités : déjà le CDC Review (toutes TD, Gold documents, extract ensuite, lot Proposer, leçons). **Référence**, pas un module à dupliquer.
4. **Avant tout nouveau Proposer** : cette page à jour (§0.1). Ordre : AMP → Projets → juge de champs marinas / capitaineries. Clés `kind:`.
5. Projets : Gold d’un projet snapped **refusé** tant que le site n’est pas accepté ; Gold d’un projet `site_ok` → fiche dans le run certifié ; le run unique reste sur Map.
6. Marinas / Capitaineries / AMP : Gold → run certifié ; le run unique reste la carte par défaut. Pré-Gold = filtre de file.
7. Capitaineries : plus de `gold_on: true` par défaut ; Gold après acceptation bâtiment.
8. AMP : plusieurs candidats visite ; Gold refuse `visit_url == manager_url` ; `no_visit` goldise.
9. Map : « Afficher la review » coché = run certifié ; décoché = couche du §8. Gold seul ne change pas Map.
10. Phrase de test du §0 verte pour **chaque** kind — y compris « Proposer n’allume pas Gold ».

---

## 11. Documents

| Document | Rôle |
|----------|------|
| `docs/CAHIER_DES_CHARGES_REVIEW.md` | **Contrat Formalités / PoE** (file, fiche, Gold). Prime sur « 1 TD » du CDC PoE §18. **Sauf** « Gold pose l’accepté sur la carte » : ici Gold alimente le run certifié ; Map ne le montre que via **Afficher la review**. |
| `docs/CAHIER_DES_CHARGES_POE.md` | Objet PoE, grain VLIZ, D∩P, WPI. |
| `docs/CAHIER_DES_CHARGES_PROJETS.md` | Objet projet, phase D, snapped/fallback. |
| `docs/CONTRATS_MODES.md` | Cinq contrats **pipeline** (pas Review). |
| `docs/REGLES_PARAMETRES.md` | Règles que les choix Review doivent pouvoir **écrire**. |
| `docs/PLAN_IMPLEMENTATION_FILIERES_CARTO.md` | Review / Gold = filière **contrôle** ; pas un fond de carte. |
| Ce document §0.1 / §3.7 / §4.7 / §5.7 / §6.7 | Ce qu’on calque de Formalités **avant** d’écrire un Proposer ailleurs. |

## 12. Rapport de review

La base garde déjà tout : `review_comments` (clé `{mode}:{entity_id}`), `review_choices`, `review_gold`, `review_suggest` / `review_lessons` **par kind**. Le rapport (`GET /api/review/report`, bouton **Rapport** de l'onglet Review, export JSON ou Markdown) agrège ces collections **en lecture seule** pour préparer les améliorations du pipeline :

- **URLs proposées** : toute URL collée dans un commentaire (ex. liste PoE d'un polygone ZEE trouvée à la main via Gemini) ressort en tête de rapport — candidate à lecture / récupération par le pipeline au run suivant.
- **Écartés** : TD, URLs, sites et champs enrichis écartés — candidats blacklist de **chemin** / correctifs moteur (pas un hostname entier par réflexe).
- **Gold** : fiches certifiées, avec la date.
- **« Proposer s’est trompé ici »** (tous les kinds) : écarts keep/drop, accords, indices pour le code. Matière à few-shot / jetons — **pas** une écriture automatique de `_JUNK_PATH_TOKENS`.

Le rapport n'écrit rien : ni règle, ni collection live, ni Gold. C'est la matière première d'une décision humaine.

---

En cas de conflit sur **eez vs poe** : une fiche Formalités.  
En cas de conflit sur **écriture live** : pas de live sans Gold, pas de Gold silencieux, **pas de Gold par Proposer**.  
En cas de conflit sur **ce que Map affiche** : couche par défaut du §8 ; le run certifié seulement si **Afficher la review** est coché.  
En cas de conflit sur **quoi copier de Formalités** : le geste du §0.1, pas le prompt ni les jetons.

*Toute évolution de règle Review se fait d’abord dans le CDC Formalités (`CAHIER_DES_CHARGES_REVIEW.md`) pour les PoE, et ici pour les autres modes, puis dans le code.*
