# Cahier des charges — Onglet Review

Document de cadrage de la **fonctionnalité Review** et de l’**onglet Review** de Blue Intelligence.

Il relit le code (`review_queue`, `poe_zone_fiche`, `ReviewView`), les cahiers Formalités (PoE) et Projets, la PR #34 (7 septembre 2026), et la **revue Word du 8 septembre 2026** (Berry-Mappemonde, 20 commentaires).

Écrit en langage simple : c’est le **contrat** de ce que l’on cherche, et de ce que l’on refuse.

Version **1.1** — 8 septembre 2026. Les corrections Word sont tracées au §22.

**Sommaire**

1. En une phrase
2. Pourquoi cet onglet existe
3. Le contrat
4. Ce que l’on veut obtenir
5. Ce que l’on ne veut pas
6. Vocabulaire
7. Les trois files (les trois modes)
8. Fiche Formalités multi-runs
9. Contrats de fiche
10. Commentaire, motifs, règles
11. Bouton Gold
12. Le code — où vit chaque brique
13. API
14. Modèle de données
15. Ce que voit l’utilisateur
16. Qui fait quoi
17. Quel espace de travail pour le job
18. État actuel et écarts
19. Recette
20. Risques
21. Hors périmètre
22. Trace des commentaires de revue (Word 8 sept)
23. Documents dont ce cahier hérite

---

## 1. En une phrase

Relire **une fiche à la fois**, dans **un des trois modes** (Projets, Marinas, Formalités), voir **tous les résultats déjà payés dédupliqués**, commenter, **choisir** les bonnes preuves, **écarter** les mauvaises, puis **Gold** : poser la fiche acceptée sur la carte.

---

## 2. Pourquoi cet onglet existe

La carte et la Console **produisent**. Review **juge**, puis **publie l’accepté**.

Les cahiers Formalités et Projets exigent une **relecture humaine** avant toute publication (§12 PoE : liste officielle par polygone ; phase D Projets : Gold). Sans écran dédié, la revue reste un script Mongo ou un clic carte trop chargé.

Le geste Formalités : **une fiche par polygone VLIZ** (France hexagone ≠ Mayotte — **pas** une fiche « France » ni une fiche par pays), les URLs Top-Down **de tous les runs**, la **liste des PoE dédupliquée**, les URLs Bottom-Up **par port**, **sans bouton Générer**. Le même geste, adapté, vaut pour un projet et pour une marina.

Blue Intelligence a **trois modes**, pas quatre : **Projets**, **Marinas**, **Formalités** (PoE + polygone **sur la même fiche**). Review est le **troisième onglet** (Map / Console / Review). Ce n’est pas un quatrième mode. L’onglet Review ouvre la file du **mode actif**.

---

## 3. Le contrat

Cette section **prime** sur l’UI, les labels et les implémentations dès qu’il y a conflit. Elle prime aussi, pour l’écran Review, sur la phrase PoE « n’afficher qu’une URL TD » : en Review on **montre tout**, on **choisit**.

### 3.1 Objet

Review est une **file de relecture qui aboutit au Gold**.

Elle n’est pas une carte. Elle n’est pas un crawler. Elle n’est pas un « goldiseur silencieux » (sauver un commentaire ≠ Gold).

Une **fiche** = l’objet du mode, **cumul dédupliqué de tous les runs** (plus la v1), affiché **seul**, avec un commentaire et des **choix** (garder / écarter).

### 3.2 Trois files = trois modes

Pas un kind `eez` à côté d’un kind `poe`. Formalités = **une** file, **une** fiche par polygone.

| Mode | Une fiche = | Identifiant | Ce qu’on y voit |
|------|-------------|-------------|-----------------|
| **Projets** | un projet | `_id` ou `url` | v1 + occurrences `project_run_*` du même projet, dédupliquées |
| **Formalités** | **un polygone VLIZ** (`mrgid`) | `str(mrgid)` | URLs TD de tous les runs + ports dédupliqués + 1+ URLs BU par port |
| **Marinas** | une marina | `_id` | `marinas` (pas de `marina_run_*` aujourd’hui) |

**Pourquoi l’implémentation v1.0 a séparé `eez` et `poe`.** Deux collections Mongo (`eez_zones` / `poe_ports`) ont produit deux onglets. Ce n’est **pas** une règle métier. Le réviseur Formalités juge **le polygone et ses ports ensemble**. Un port sans son polygone, ou un polygone sans ses ports, n’est pas le geste.

Pas de cinquième file « listing ». Pas d’agrégat pays à la place d’un `mrgid`.

### 3.3 Grain VLIZ (Formalités)

Une fiche Formalités = **un polygone** (`mrgid`), jamais un pays. La France a 23 fiches. `France (hexagone)` ≠ `France (Mayotte)`.

Les **règles** extraites de la revue (domaines à garder, blacklist) s’éditent au grain polygone et peuvent s’**agréger par souverain** quand c’est le même droit.

### 3.4 Fiche Formalités — contrat UI

Pour chaque `mrgid`, **sans** bouton Générer :

| Élément | Sens | Interdit |
|---------|------|----------|
| **URLs Top-Down** | **Toutes** les pages/PDF d’État déjà trouvés pour **ce** polygone, **tous runs confondus**, **dédupliquées**, **cliquables** | En cacher une « pour simplifier » ; home douane sans liste présentée comme *la* liste ; Noonsite ; wiki ; forum |
| **Liste des PoE** | Ports rattachés à **ce** `mrgid`, **tous runs + v1 + graines**, dédupliqués par identité (`dedup_key` / nom) | Agrégat pays ; un run qui **remplace** les autres |
| **URLs Bottom-Up par port** | Pages d’État ouvertes en cherchant **ce** nom, **tous runs**, dédupliquées, cliquables | Une seule URL cachée ; pile BU orpheline au niveau zone sans port |

Le réviseur **sélectionne** la ou les meilleures URLs TD. Il **désélectionne** celles à côté de la plaque. Les écartées vont en **blacklist** (domaine et/ou URL), mémoire pour les règles de crawl.

Même URL vue TD **et** BU = `from_arm = both` (source d’or). ZEE sans source ni port : `kind = none` + bloc UNCLOS si un code existe.

**WPI = preuve inverse.** Les ports WPI sont de **pêche industrielle, d’industrie ou de commerce**. Un hit WPI **n’est pas** un PoE plaisance, **sauf** s’il est **explicitement mixte** (décret / catalogue qui le dit). WPI n’est jamais une URL de fiche. Noonsite n’apparaît pas sur la fiche.

### 3.5 Écritures

| Écriture | Quand | Où |
|----------|-------|-----|
| Commentaire | Enregistrer / autosave navigation | `review_comments` |
| Choix (URL gardée, URL blacklist, port accepté / écarté) | Clic garder / écarter | collections de revue + **règles** (grain polygone, agrégat pays) |
| **Gold** | Clic **Gold** sur une fiche acceptée | jeu Gold **et** couche carte du mode |

Sauver un commentaire **ne touche pas** `projects` / `poe_ports` / `eez_zones` / `marinas`.

Le clic **Gold** est le **seul** geste Review qui pose l’accepté sur la carte. Ce n’est pas un `generate-batch`. Ce n’est pas une mutation silencieuse.

`generate` / `generate-batch` : **code mort à supprimer** du produit (routes déjà 410). Ils n’apparaissent plus dans le contrat Review.

**Phrase de test, dite simplement.** Un test qui enregistre un commentaire, puis voit `poe_ports` ou `projects` changés **sans** clic Gold, **casse le contrat**. Un test qui clique Gold et ne voit **ni** le Gold **ni** la carte mise à jour **casse aussi le contrat**.

### 3.6 Commentaire

- Texte libre dès le premier passage.
- Les **motifs récurrents** (TD pourrie, port cargo, mauvais polygone…) se **décèlent en reviewant**. On en fera des verdicts structurés **au fur et à mesure**, pas un enum figé avant d’avoir lu 285 fiches.
- Clé de commentaire : `{mode}:{entity_id}` sur la fiche **multi-runs** (un seul fil par polygone / projet / marina). Un `run_id` n’est plus la clé du job.
- Vider le texte et sauver = commentaire vide (le point vert disparaît).
- Persister avant de changer de fiche ou de mode (bouton **et** autosave).

### 3.7 L’espace de travail du job = fiche unique multi-runs

Le libellé UI « Published map (v1) » est **trompeur**. Le job n’est pas « relire la v1 parce qu’elle est publiée ». Le job est : **une fiche qui cumule v1 + tous les runs, dédupliqués**.

Un sélecteur « un run isolé » peut rester pour **déboguer un pipeline**. Il n’est **pas** l’espace Gold. On ne goldise pas un canari.

### 3.8 Navigation

- Une fiche visible. Précédent / suivant. Flèches clavier (hors champ texte).
- Liste latérale + filtre (`q`).
- Pagination `offset` / `limit` (défaut 500, max 2000). Le `total` ne se perd pas.
- Compteur `position / total`.

### 3.9 Ce que Review décide / ne décide pas

| Review **fait** | Review **ne fait pas** |
|-----------------|------------------------|
| Commenter | Relancer un crawl |
| Choisir / blacklister des URLs | Prendre Noonsite pour preuve |
| Accepter / écarter des ports sur **cette** fiche | Écraser la v1 par un batch SERP |
| **Gold** : fiche acceptée → Gold + carte | Goldiser en silence via « Enregistrer » |
| Nourrir les **règles** (blacklist, domaines) | Inventer un GPS |

---

## 4. Ce que l’on veut obtenir

Trois livrables, indissociables :

1. **La file relisible.**  
   Trois modes, une fiche complète **multi-runs**, un commentaire, un parcours clavier. Volumes : ~4 465 projets, 285 polygones (ports **dessus**), marinas de la route.

2. **La mémoire exploitable.**  
   Commentaires + choix + blacklist dans une base dont on **édite des règles** (polygone, puis pays). Pas un pad jetable.

3. **Le Gold visible.**  
   Les fiches reviewées **et acceptées** (bouton **Gold**) s’affichent sur la carte du mode. C’est le but, pas un à-côté.

---

## 5. Ce que l’on ne veut pas

- Un bouton **Générer** / `generate-batch` / `force`.
- Une écriture carte **sans** clic Gold.
- Un pays à la place d’un `mrgid`.
- Une file « ports » **séparée** de la file polygones Formalités.
- Noonsite, wiki, forum comme preuve. WPI comme preuve **positive** de plaisance.
- Republier un run SERP parce que le compteur dit 285.
- Confondre « Published map (v1) » et « carte Formalités publiée ».
- Un commentaire global au run (le commentaire est **par fiche**).
- Poller la carte pendant que Review est ouvert.
- Afficher les sidebars Swarm / Marinas / Formalités dans Review.
- Cacher des URLs TD « pour n’en garder qu’une » avant le réviseur.

---

## 6. Vocabulaire

| Mot | Sens ici |
|-----|----------|
| **Onglet Review** | `view === "review"`, à côté de Map et Console (`audit`). |
| **Mode** | Projets \| Marinas \| Formalités. **Trois.** Review n’en ajoute pas un quatrième. |
| **Fiche** | Vue **multi-runs dédupliquée** d’un projet, d’un polygone (+ ses ports), ou d’une marina. |
| **File** | Liste paginée des fiches du **mode**. |
| **v1 affichable** | `projects` / `poe_ports` / `marinas` d’aujourd’hui. Pas une publication métier. |
| **Run isolé** | Snapshot `project_run_*` / `poe_run_*`. Utile pour comparer un moteur, **pas** pour goldiser. |
| **Commentaire** | Note reviewer. Les motifs répétés deviendront des verdicts. |
| **Blacklist** | URL ou domaine écarté par le réviseur. Alimente les règles. |
| **Gold** | Fiche **acceptée** par un humain + preuves d’État (Formalités) ou critères Projets. **S’affiche sur la carte.** |
| **Bouton Gold** | Geste explicite : cette fiche entre dans le Gold **et** sur la carte. |
| **Listing-control** | Contrôle Noonsite. Reste en Console. Pas une file Review. |

---

## 7. Les trois files (les trois modes)

### 7.1 Projets

File : titre A–Z. Sous-titre = financeurs ou verdict.

Fiche : titre, URL(s) de tous les runs, financeurs, lieu, GPS, `s_ocean`, catégorie, `sites[]`, `snapped`. Occurrences run dédupliquées sur **la même** fiche.

Job : URL de **projet** (pas une home fondation) ? GPS = lieu d’action visitable ? `snapped` / fallback = à noter, exclu du Gold tant que non accepté.

### 7.2 Formalités (polygone + ports)

File : libellé désambiguïsé (`zoneDisplayName`). Sous-titre = souverain. Extra : nombre de ports **dédupliqués**.

Fiche : contrat §3.4. **Pas** de second onglet « Ports d’Entrée ».

Job : parmi les TD cliquables, laquelle (ou lesquelles) est *la* liste d’État de **ce** polygone ? Les ports D∩P restent ; les WPI commerce-only sortent ; chaque port accepté a au moins une URL BU d’État, ou on le note. Sinon UNCLOS.

### 7.3 Marinas

File : `marinas` (tant qu’il n’y a pas de runs marinas).

Fiche : nom, source, GPS, enrichissement, VHF, places, tirant, capitainerie, services, avis.

Job : marina visitable le long d’une route, **pas** un PoE. Une marina + douane ≤ 800 m = graine P côté Formalités, pas une preuve sur la fiche polygone.

---

## 8. Fiche Formalités multi-runs

C’est **plus simple à reviewer** qu’un sélecteur de 15 runs.

| Couche | Source | Sur la fiche |
|--------|--------|--------------|
| Référentiel | `eez_zones` | libellé, UNCLOS, souverain |
| Ports v1 | `poe_ports` | dans la liste, marqués v1 |
| Ports des runs | `poe_run_ports` **tous** `run_id` de ce `mrgid` | fusionnés, dédupliqués |
| Graines | `poe_seed_ports` | URLs BU + candidats absents de v1 |
| TD | `sources` / `sources_td` de `eez_zones` **et** de **toutes** les `poe_run_zones` du `mrgid` | **toutes** cliquables, dédupliquées par URL |
| BU | `judge_sources` / `sources_bu` seeds + ports (tous runs) | **par port**, toutes cliquables |

Le réviseur voit d’où vient chaque preuve (quels `run_id`) **sans** changer de fiche.

Les mondiaux SERP restent du **stock à comparer**, déjà **versés dans la fiche**. On ne les republie pas tels quels. Canaris 12 ZEE = NO-GO comme vérité, mais leurs URLs peuvent apparaître : le réviseur les écarte.

Le compteur `(285)` = référentiel VLIZ, pas la qualité.

---

## 9. Contrats de fiche (détail)

### 9.1 Formalités

- Nettoyage URL : `http` seulement ; Noonsite / forums / magazines exclus de la preuve.
- Dédup : une URL = une ligne ; un port = une identité.
- Rang **proposé** (page liste/PDF, `official`, `both`) : c’est un **tri**, pas un filtre qui cache.
- WPI : badge « commerce / industrie » = **contre-preuve** plaisance, sauf mixte explicite.
- `wrote_poe_ports: false` tant que Gold n’a pas été cliqué.

### 9.2 Projets / Marinas

Même esprit : cumul dédupliqué, lecture jusqu’au Gold. Projet sans URL : « Pas d’URL ». Marina : pas d’URL d’État exigée.

---

## 10. Commentaire, motifs, règles

```
review_comments
  _id        = "{mode}:{entity_id}"
  mode       = projects | formalities | marinas
  entity_id  = id de file
  comment    = texte
  updated_at = ISO-8601
```

La file expose `has_comment` (point vert).

**Motifs.** On ne fige pas `accept` / `reject` / `edit-gps` avant d’avoir lu. Quand le même texte revient (« home douane », « cargo WPI », « mauvais mrgid »), on **extrait une règle** et, plus tard, un verdict cliquable.

**Règles.** Chaque garder / écarter (URL, domaine, port) s’écrit dans une base **exploitable** :

- grain = `mrgid` (et `iso2` / souverain pour l’agrégat) ;
- type = `keep_td` | `blacklist_url` | `blacklist_domain` | `keep_port` | `drop_port` ;
- sert au **prochain** crawl et à la fiche (pré-coché).

Autosave commentaire : quitter la fiche, changer de mode, Précédent / Suivant, clic liste.

---

## 11. Bouton Gold

On en a parlé : il est **dans le contrat**, pas hors périmètre.

### 11.1 Quand il est actif

Sur la fiche courante, si le réviseur a de quoi accepter :

- Formalités : au moins une URL TD **gardée** (ou UNCLOS `kind = none` justifié) **et** la liste des ports **tranchée** (acceptés / écartés, y compris « zéro port » assumé) ;
- Projets : URL de projet + site visitable accepté (pas un `snapped` laissé tel quel) ;
- Marinas : identité + GPS acceptés.

Sans cela, Gold est **désactivé** (ou demande confirmation explicite « Gold incomplet » — à trancher à l’implémentation, défaut = désactivé).

### 11.2 Ce que le clic fait

1. **Fige** la fiche : URLs gardées, ports acceptés, commentaire, horodatage, auteur si connu.
2. **Écrit le Gold** (collection / export du mode). Ce n’est pas Noonsite. Ce n’est pas un run SERP.
3. **Affiche sur la carte** du mode les objets acceptés (ports Formalités, sites Projets, marina). La v1 historique **reste** en mémoire comme étape ; la couche **montrée** au skipper devient le Gold là où une fiche a été goldisée.
4. **Pousse les règles** (blacklist / domaines / ports écartés) vers le store de règles.
5. Marque la fiche « Gold » dans la file (point distinct du simple commentaire).

### 11.3 Ce que le clic ne fait pas

- Il n’écrase pas les 285 polygones d’un coup.
- Il n’écrit pas si on a seulement tapé un commentaire.
- Il ne relance pas de crawl.
- Il ne goldise pas un listing Noonsite.

On s’en **approche** dès que Review + choix d’URLs existent. Le bouton est l’écart **prioritaire** de l’UI actuelle.

---

## 12. Le code — où vit chaque brique

| Brique | Rôle aujourd’hui | Écart 1.1 |
|--------|------------------|-----------|
| `app/routers/review.py` | GET/PUT commentaire | Gold + choix + blacklist |
| `app/services/review_queue.py` | 4 kinds, un `run_id` | 3 modes, fiche union |
| `app/services/poe_zone_fiche.py` | 1 TD affiché (`FICHE_TD_URL_CAP = 1`) | toutes les TD, cliquables |
| `app/services/poe_zone_label.py` | France hexagone ≠ Mayotte | inchangé |
| `frontend/src/components/ReviewView.js` | 4 onglets kind + sélecteur run | 3 modes ; Gold ; multi-select URLs |
| `ZoneFiche.js` | 1 TD + liste ports | toutes TD + ports union |
| `PoeFiche.js` | file ports séparée | **à fusionner** dans la fiche polygone |
| `Header.js` / `App.js` | Map / Console / Review | inchangé (onglets) |

Tests à étendre : union multi-runs, Gold n’écrit pas sans clic, commentaire n’écrit pas la carte.

---

## 13. API (cible 1.1)

Préfixe `/api`.

| Méthode | Route | Rôle |
|---------|-------|------|
| `GET` | `/review/queue?mode=&offset=&limit=&q=` | File du mode (`formalities` = polygones) |
| `GET` | `/review/fiche?mode=&id=` | Fiche **union** + commentaire + choix |
| `PUT` | `/review/comment` | Texte |
| `PUT` | `/review/choice` | garder / blacklister URL ou port |
| `POST` | `/review/gold` | Gold + carte, **une** fiche |

Un `run_id` optionnel sur `fiche` reste permis pour une **vue filtrée debug**. Défaut = union.

`limit` borné à `[1, 2000]`.

L’API actuelle (`kind=project\|eez\|poe\|marina`, `run_id`) est l’écart v1.0.

---

## 14. Modèle de données

| Collection | Rôle |
|------------|------|
| `review_comments` | texte, clé mode + id |
| `review_choices` (cible) | keep / blacklist, URL, port, `mrgid` |
| `review_gold` (cible) | snapshot accepté + `golded_at` |
| règles (cible, ou `run_rules` / store Formalités) | domaines / URLs / motifs **éditables par pays / polygone** |

**Lues** pour assembler : `projects`, `project_run_projects`, `eez_zones`, `poe_ports`, `poe_run_zones`, `poe_run_ports`, `poe_seed_ports`, `marinas`.

**Écrites par Review** : commentaires, choix, Gold. **Carte v1 / `poe_ports` / `projects` : seulement via Gold**, objet par objet.

Index au boot (non fatals) : commentaires `(mode, entity_id)` ; choix `(mode, entity_id)` ; Gold `entity_id`.

---

## 15. Ce que voit l’utilisateur

**En-tête.** Map · Console · Review.

**Review.**

- Gauche : file du **mode** + filtre.
- Haut : le mode (déjà celui de l’app) · compteur · Précédent / Suivant · **Gold**.
- Centre : **une** fiche union. Formalités : **toutes** les TD cliquables (cases garder / écarter) + ports dédupliqués + BU par port.
- Bas : commentaire + Enregistrer.

Pas de quatrième interrupteur « Ports d’Entrée » à côté de « Polygones ZEE ».

EN / FR. Hint : *une fiche à la fois ; tout ce qui a déjà été trouvé est là, dédupliqué ; Gold pose l’accepté sur la carte.*

---

## 16. Qui fait quoi

| Acteur | Il fait | Il ne fait pas |
|--------|---------|----------------|
| **Réviseur** | Défile, ouvre **toutes** les URLs, choisit, commente, **Gold** | Crawler, vider la base, goldiser Noonsite |
| **Opérateur** | Ouvre Review dans le bon mode ; debug run isolé si besoin | Prendre un canari pour vérité |
| **Skipper** | Voit la **carte Gold** là où une fiche l’est | Ouvrir Review |
| **Pipeline** | Alimente v1 et `*_run_*` | Écrire `review_comments` / Gold |
| **Review (code)** | Union + upsert commentaire / choix / Gold | Mutation carte sans Gold |

---

## 17. Quel espace de travail pour le job

**La fiche union (v1 + tous les runs, dédupliquée).** Pas « Published map (v1) parce que c’est publié ». Pas `bestof3-v2` parce que le compteur dit 285.

Un run isolé sert à **comprendre un moteur**. Le Gold se décide sur l’union.

Canaris, `smoke-3-zones`, `seed-enrich` : hors vérité. `example-official-sources` : bac à sable du geste, pas le tour du monde.

Un seul fil de commentaire par fiche union : on ne perd plus les notes en changeant de run.

---

## 18. État actuel et écarts

### En place (PR #34)

Onglet Review, pagination, commentaire persisté, fiche polygone, pas de Générer, pas d’écriture carte au commentaire, poll carte coupé.

### Écarts — le contrat 1.1 n’est pas encore l’UI

| Écart | Détail | Priorité |
|-------|--------|----------|
| **Bouton Gold** | Parlé, comportement §11, **absent** de l’UI | **P0** |
| Files `eez` ≠ `poe` | Accident d’implémentation ; métier = **une** fiche Formalités | **P0** |
| Une seule TD affichée | Montrer **toutes**, cliquables, garder / blacklister | **P0** |
| Sélecteur de run comme espace de travail | L’union est le défaut ; le run isolé = debug | P1 |
| Pas de choix persistés | `review_choices` + règles pays / polygone | P1 |
| Verdicts structurés | **Viennent au fil de la review** (motifs), pas un gap bloquant | P2 |
| Libellé « Published map » | Dire « union / v1+runs » | P2 |
| `generate*` encore dans le dépôt | **Code à supprimer** (déjà 410) | P2 |
| Marinas sans runs | OK tant qu’il n’y en a pas | — |

---

## 19. Recette

1. En-tête : Map, Console, Review.
2. Review : pas de sidebar Swarm / Formalités.
3. Mode Formalités : **285** fiches polygone ; **pas** une seconde file de 1 280 ports.
4. Fiche Albanie : **plusieurs** TD cliquables si plusieurs runs en ont trouvé ; ports dédupliqués ; BU par port.
5. Désélectionner une TD pourrie → blacklist ; elle ne revient pas comme « meilleure » à la fiche suivante du même souverain si la règle est agrégée.
6. Enregistrer un commentaire → `review_comments` ; **`poe_ports` inchangé**.
7. **Gold** → Gold écrit + ports acceptés **visibles sur la carte** Formalités.
8. Suivant : autre polygone ; commentaire / Gold Albanie inchangés.
9. Mode Projets / Marinas : une fiche, pas de `/generate`.
10. Flèches ← → hors textarea.

Tests actuels : `tests/test_review_queue.py`, `tests/test_poe_zone_fiche.py` (à réécrire quand l’union et Gold arrivent).

---

## 20. Risques

| Risque | Contre-mesure |
|--------|----------------|
| Écraser v1 « pour corriger » sans Gold | §3.5 : commentaire ≠ carte |
| Goldiser Noonsite | Hors fiche |
| Relire un canari comme vérité | §17 : union, puis choix humain |
| Perdre des commentaires en changeant de run | Clé **sans** `run_id` de job |
| Timeout si on charge tous les `poe_run_ports` mondiaux | Filtrer **par `mrgid`** ; pas un scan planète |
| Confondre marina et PoE | Modes séparés ; marina n’est pas une preuve Formalités |
| Cacher des TD « pour faire propre » | §3.4 : tout cliquable |

---

## 21. Hors périmètre (1.1)

File listing-control dans Review. Comparateur *split screen* run A \| run B (remplacé par l’union). Crowdsourcing skipper. Relance de crawl depuis Review. Édition libre du GPS sans passage Gold Projets. Deuxième mode « ports seuls ».

**Plus hors périmètre :** bouton Gold, toutes les TD visibles, fiche Formalités unique, blacklist → règles, affichage carte des fiches acceptées.

---

## 22. Trace des commentaires de revue (Word 8 sept 2026)

| # | Passage | Décision reprise |
|---|---------|------------------|
| 0 | « une fiche par polygone VLIZ » | **Oui** : polygone, **pas** une fiche pays / « par ZEE » agrégée |
| 1 | « eez et poe sont séparés » / « il n’y a que trois modes » | **Trois modes.** Formalités = PoE **sur** la fiche polygone |
| 2, 3, 5 | 1 TD / liste PoE / 1 BU | **Tous les runs, dédupliqués**, sur **une** fiche |
| 4 | « WPI comme preuve » | **Preuve inverse** : commerce / industrie / pêche, sauf **mixte explicite** |
| 6 | Une seule TD affichée | **Toutes** visibles ; garder / **blacklister** |
| 7 | `review_comments` seule écriture | Commentaires **et** choix dans une base **pour éditer des règles** (pays / polygone) |
| 8 | `generate` / `generate-batch` | **Code à supprimer** ; hors contrat Review |
| 9 | « Un test qui voit une mutation v1… » | Reformulé §3.5 : commentaire sans Gold **ne** mute pas la carte ; Gold **doit** la muter |
| 10 | « Texte libre » | **Oui** au début ; les **motifs** structurent ensuite |
| 11 | « meilleure parmi les runs » | **Les afficher toutes**, cliquables |
| 12 | « Review ne goldise pas » | **Si** : on **veut** goldiser et **afficher** les fiches acceptées |
| 13 | `eez \| poe` | **Même fiche** par polygone |
| 14 | Fiche = `(kind, run_id, id)` | Fiche = **union multi-runs** |
| 15 | « Gold n’existe pas encore » | On **s’en approche** ; le bouton manque |
| 16 | UI sans Gold | **Manque le bouton Gold** |
| 17 | Pas de verdict structuré | **Ça vient au fil** de la review |
| 18 | Pas de comparateur côte-à-côte | **Une fiche multi-runs** à la place |
| 19 | Gold hors périmètre | **Dans le contrat** ; comportement §11 |

---

## 23. Documents dont ce cahier hérite

- `docs/CAHIER_DES_CHARGES_POE.md` v1.4 — grain VLIZ, D∩P, §12, WPI contre-liste. **Sauf** « n’afficher qu’une TD » : Review 1.1 montre toutes.
- `docs/CAHIER_DES_CHARGES_PROJETS.md` v2.0 — v1 trésor, phase D revue / Gold.
- `docs/REGLES_PARAMETRES.md` — les règles que la revue doit pouvoir **écrire**.
- `docs/ARCHITECTURE.md`, `docs/PRD.md`.
- `docs/CONTRATS_REVIEW_PAR_MODE.md` — même geste Review pour les cinq modes ; Gold = run certifié ; Map via **Afficher la review**.
- PR #34 — premier onglet, API commentaire.

En cas de conflit sur **le grain** (pays vs polygone), §3.3 prime.  
En cas de conflit sur **une écriture live**, §3.5 prime : pas de live sans Gold, pas de Gold silencieux.  
En cas de conflit sur **ce que Map affiche**, `docs/CONTRATS_REVIEW_PAR_MODE.md` §8 prime : couche par défaut du run unique ; le run certifié seulement si **Afficher la review** est coché.  
En cas de conflit sur **eez vs poe**, §3.2 prime : **une** fiche Formalités.

*Fin du cahier des charges Review v1.1. Toute évolution de règle Formalités se fait d’abord ici ; les autres modes dans `CONTRATS_REVIEW_PAR_MODE.md`, puis dans le code.*
