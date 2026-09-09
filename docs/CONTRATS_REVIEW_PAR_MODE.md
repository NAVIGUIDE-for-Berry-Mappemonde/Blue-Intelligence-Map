# Contrats de Review par mode

Le cahier `docs/CAHIER_DES_CHARGES_REVIEW.md` v1.1 est le **contrat de relecture des PoE** : une fiche par polygone VLIZ, toutes les preuves déjà payées, choix garder / écarter, puis **Gold**. Les autres modes n’y ont qu’une esquisse (§7.1, §7.3, §9.2, §11.1).

Ce document propose le **même geste Review**, adapté à chaque mode produit. Il n’invente pas un sixième mode. Review reste le **troisième onglet** (Map / Console / Review) : il ouvre la file du **mode actif**.

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

**Phrase de test.** Un test qui enregistre un commentaire et voit la collection live mutée **casse le contrat**. Un test qui clique Gold et ne voit **pas** la fiche dans le run certifié **casse aussi le contrat**. Un test qui clique Gold et voit la Map **changer sans** « Afficher la review » **casse le contrat**.

Ce qui change par mode : **la question que le réviseur tranche**, **ce qui est une preuve**, **quand Gold s’allume**. L’effet Map est **le même** pour tous les modes (§8).

---

## 1. Tableau des files

Cinq modes produit, **cinq files**. Pas de file `poe` séparée (accident d’implémentation : deux collections Mongo). Pas de file pays à la place d’un `mrgid`.

| Mode | Une fiche = | Identifiant | Preuve que le réviseur juge | Gold quand |
|------|-------------|-------------|-----------------------------|------------|
| **Formalités** | un polygone VLIZ + ses ports | `mrgid` | URLs d’**État** (TD toutes runs, BU par port). WPI = contre-preuve. Noonsite hors fiche. | ≥ 1 TD gardée (ou UNCLOS `none`) **et** chaque port tranché |
| **Projets** | un projet (n sites) | `_id` ou `url` | URL de **page projet** + GPS du **lieu d’action** visitable en bateau | URL projet + ≥ 1 site accepté (pas snapped / fallback / HQ) |
| **Marinas** | une marina | `osm_id` | Identité OSM + GPS du bassin. Enrichissement (VHF, places, tirant) **sans inventer**. `/maps/place/` = signal. | Identité + GPS acceptés. Champs enrichis : garder seulement s’ils sont sourcés |
| **Capitaineries** | un **bureau** | `osm_id` et/ou `shom_id` / `noaa_id` | Bâtiment (pas le plan d’eau). Tél + VHF sourcés (tags ou page officielle). Calque 250 m ≠ fusion 500 m. | Bureau + GPS acceptés. Contact : garder seulement s’il n’est pas inventé |
| **AMP** | un site ProtectedSeas (façade) | `site_id` | **Deux** URL distinctes : `manager_url` ≠ `visit_url`. Candidats visite tous visibles. | Couple tranché : visite gardée **distincte**, ou « pas de visite » assumé |

---

## 2. Formalités — contrat de référence (déjà écrit)

C’est `docs/CAHIER_DES_CHARGES_REVIEW.md` §3.4 / §7.2 / §11. On ne le réécrit pas. On le **nomme** pour que les autres files calquent le geste, pas l’objet.

**Question.** Parmi toutes les TD déjà trouvées pour **ce** `mrgid`, laquelle (ou lesquelles) est *la* liste d’État de **ce** polygone ? Les ports D∩P restent ; les WPI commerce-only sortent ; chaque port accepté a au moins une BU d’État, ou on le note. Sinon UNCLOS.

**Interdit.** Pays à la place du polygone. File ports séparée. Cacher des TD « pour n’en garder qu’une ». Noonsite / wiki / forum comme preuve. WPI comme preuve **positive** de plaisance (sauf mixte explicite). Goldiser un canari.

**Écritures Review.** Commentaire ; `keep_td` / `blacklist_url` / `blacklist_domain` / `keep_port` / `drop_port` (grain `mrgid`, agrégat souverain) ; Gold = snapshot dans le **run certifié**. Map Formalités reste le **run unique** tant que « Afficher la review » est décoché.

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

**Ne fait pas** : goldiser tout le run d’un coup ; republier un `ocean_fallback` ; coller un polygone AMP comme preuve de projet ; retirer un projet de la carte par défaut.

### 3.6 Ce que Review ne décide pas

Relancer le swarm. Purger `projects`. Traiter un financeur comme un projet. Croiser projet ↔ PoE (hors périmètre CDC).

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

`GOLD_KINDS` contient déjà `marina`. `is_pre_gold_marina` = source OSM → **tout le dump est pré-Gold**. C’est un interrupteur trop large : le contrat proposé exige un **clic** (identité + GPS vus), pas « OSM ⇒ Gold ».

---

## 5. Capitaineries — contrat de Review proposé

Mode produit (README, CONTRATS_MODES). **Absent** du CDC Review v1.1 (trois modes). L’UI a déjà `CapitainerieFiche` ; Gold **n’est pas** dans `GOLD_KINDS`.

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

**Le clic** : Gold kind `capitainerie` (à ajouter) ; fiche dans le **run certifié**. Map Capitaineries continue d’afficher le run unique.

**Ne fait pas** : fusionner avec une marina ; réutiliser `same_site` 500 m ; goldiser sans GPS de bâtiment.

### 5.6 Écart code

La file pose aujourd’hui `pre_gold: true` / `gold_on: true` pour **toutes** les capitaineries. Ça viole le méta-contrat : Gold sans geste. `is_pre_gold_entity(..., capitainerie)` retourne `True` inconditionnel.

---

## 6. AMP — contrat de Review proposé

Mode produit. Fiche UI déjà là (`AmpFiche`). **Pas** dans `GOLD_KINDS`. Pas de `review_choices`.

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
| `visit_url` | garder une parmi les candidates / écarter les homepages | Blacklist domaine blog mouillage générique |
| « Pas de visite » | assumer `not_found` / `none` | Fiche Gold **incomplète** ou Gold « sans visite » explicite |
| `manager_url` | corriger si ProtectedSeas a collé un pipe d’URLs | Ne jamais écrire manager dans visit |

### 6.5 Gold

**Actif si** : une `visit_url` **gardée** et **distincte** de `manager_url`, **ou** confirmation explicite « pas de page visite » (équivalent UNCLOS `none` côté Formalités).

**Le clic** : snapshot `{manager_url, visit_url}` dans le **run certifié**. Map AMP continue d’afficher le run unique. Le polygone ProtectedSeas n’est pas redessiné.

**Ne fait pas** : goldiser la homepage ; servir le cache tuile 30 j. comme fusion de fiches ; lancer SearXNG (ce n’est pas une liste d’État par ZEE).

### 6.6 Écart code

`GOLD_KINDS` ignore `amp`. La file expose `visit_url` unique, pas la **liste de candidats**. Commentaire possible, pas de choix persistés.

---

## 7. Ce que Review fait / ne fait pas (par mode)

| | Formalités | Projets | Marinas | Capitaineries | AMP |
|---|------------|---------|---------|---------------|-----|
| Commenter | oui | oui | oui | oui | oui |
| Choisir des URLs | TD + BU | pages projet | website / Maps | page contact | candidats visite |
| Tranche l’objet | ports keep/drop | sites keep/drop/édit GPS→Gold | marina vs non | bureau vs plan d’eau | visite vs manager |
| Blacklist → règles | polygone / souverain | chemins listing | OTA | OTA / réseaux | homepages visite |
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

---

## 10. Recette minimale (quand on implémente)

1. Cinq files, une par mode actif. **Zéro** onglet « Ports d’Entrée » à côté de « Polygones ».
2. Commentaire persisté ; collections live **inchangées**.
3. Formalités : déjà le CDC Review (toutes TD, Gold → run certifié).
4. Projets : Gold d’un projet snapped **refusé** tant que le site n’est pas accepté ; Gold d’un projet `site_ok` → fiche dans le run certifié ; le run unique reste sur Map.
5. Marinas / Capitaineries / AMP : Gold → run certifié ; le run unique reste la carte par défaut.
6. Capitaineries : plus de `gold_on: true` par défaut ; Gold après acceptation bâtiment.
7. AMP : plusieurs candidats visite ; Gold refuse `visit_url == manager_url`.
8. Map : « Afficher la review » coché = run certifié ; décoché = couche du §8. Gold seul ne change pas Map.
9. Phrase de test du §0 verte pour **chaque** kind.

---

## 11. Documents

| Document | Rôle |
|----------|------|
| `docs/CAHIER_DES_CHARGES_REVIEW.md` | **Contrat Formalités / PoE** (file, fiche, Gold). Prime sur « 1 TD » du CDC PoE §18. **Sauf** « Gold pose l’accepté sur la carte » : ici Gold alimente le run certifié ; Map ne le montre que via **Afficher la review**. |
| `docs/CAHIER_DES_CHARGES_POE.md` | Objet PoE, grain VLIZ, D∩P, WPI. |
| `docs/CAHIER_DES_CHARGES_PROJETS.md` | Objet projet, phase D, snapped/fallback. |
| `docs/CONTRATS_MODES.md` | Cinq contrats **pipeline** (pas Review). |
| `docs/REGLES_PARAMETRES.md` | Règles que les choix Review doivent pouvoir **écrire**. |

En cas de conflit sur **eez vs poe** : une fiche Formalités.  
En cas de conflit sur **écriture live** : pas de live sans Gold, pas de Gold silencieux.  
En cas de conflit sur **ce que Map affiche** : couche par défaut du §8 ; le run certifié seulement si **Afficher la review** est coché.

*Toute évolution de règle Review se fait d’abord dans le CDC Formalités (`CAHIER_DES_CHARGES_REVIEW.md`) pour les PoE, et ici pour les autres modes, puis dans le code.*
