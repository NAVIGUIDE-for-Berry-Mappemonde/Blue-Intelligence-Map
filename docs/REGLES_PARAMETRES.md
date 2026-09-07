# Règles et paramètres — principe, catalogue, snapshot par run

Les cahiers des charges (Projets, Formalités, Marinas) listent des **chiffres**.
Beaucoup étaient en dur dans le Python, choisis une fois, sans dire *pourquoi*.
Ce document fixe **comment on a le droit de poser un nombre**, comment on le
**fait varier** d’un run à l’autre, et comment on **consigne** ce qui a été
choisi.

Catalogue machine : `backend/data/run_rules.json`.
Moteur : `backend/app/core/run_rules.py`.
API : `GET /api/run-rules?mode=projects|formalities|marinas`.

---

## 1. Le principe

**Un chiffre n’est pas une opinion.**

Il appartient à **une** de ces quatre familles. S’il n’appartient à aucune,
il n’a pas le droit d’être dans le code.

| Famille | Sens | On le fait varier ? |
|---------|------|---------------------|
| **Loi** | Contrat métier (pas de snap, pas de purge, sources officielles seulement, Noonsite hors `source_urls`) | Non. On le consigne. On ne le surcharge pas. |
| **Géométrie** | Distance dérivée d’un phénomène physique (quai, havre, journée de mer, marche douane→marina) | Oui, **dans l’intervalle** où c’est encore le même phénomène. |
| **Score** | Seuil de classifieur ou de confiance | Oui, mais la cible est une **calibration** sur un jeu étiqueté (Gold, ROC), pas un nouveau chiffre au feeling. |
| **Budget** | Quota, timeout, concurrence, dollars | Oui. C’est un choix d’opérateur. Toujours consigné. |

### Comment on fixe le défaut et l’intervalle

1. **Nommer le phénomène.** « Hinterland d’une ville-havre », pas « 15 km parce que ça marchait ».
2. **Ancrer le défaut** sur une mesure (0,02° VLIZ → 2,2 km ; 10 min de marche → 800 m ; 4–5 h à 5–6 nœuds → 25 NM).
3. **Poser l’intervalle** comme la plage où *on parle encore de la même chose*.
   - En dessous : on jette des vrais cas (Cassis à 2,3 km si le sliver tombe à 2,0).
   - Au-dessus : on accepte autre chose (un siège à Washington si `max_inland_km` = 80).
4. **Un run ne sort pas de l’intervalle.** Sortir = changer de règle, donc changer le CDC d’abord.

L’intervalle est la **prétention scientifique**. Le défaut est le **point d’opération**.

---

## 2. Comment on fait varier, et comment on consigne

Trois couches, jamais un secret dans le snapshot :

```
override de run  >  profil (cdc_default | strict | recall)  >  settings Mongo  >  défaut catalogue
```

Au démarrage d’un run (Projets, Formalités, build Marinas / mouillages) :

1. On résout toutes les règles du mode (+ `shared`).
2. On écrit `params.rules` : `hash`, `profile`, `chosen[id].{value, source, unit, principle}`, `overrides`.
3. On **bind** le snapshot dans le context async : `get_rule("formalities.eez_sliver_km")` lit ce run, pas le fichier.
4. À la reprise, on **garde** le snapshot d’origine (comme le `git_sha`).

Comparer deux runs = comparer `params.rules.hash` et le détail `source=override|profile|settings|catalog`.

### API

```http
GET  /api/run-rules
GET  /api/run-rules?mode=formalities&profile=strict
POST /api/poe/runs          { "profile": "recall", "rules": { "formalities.eez_sliver_km": 3.5 } }
POST /api/projects/runs     { "mode": "test", "profile": "strict" }
POST /api/marinas/build     { "profile": "cdc_default", "corridor_radius_nm": 20 }
```

Une surcharge hors intervalle, une règle de **loi**, ou un id inconnu → **400**.

### Profils

| Profil | Idée |
|--------|------|
| `cdc_default` | Point d’opération des CDC. |
| `strict` | Rappel bas : on jette plus, on ose publier. |
| `recall` | Rappel haut : on garde plus pour la **revue**, pas pour la carte publique. |

Ne pas publier un run `recall` comme s’il était `strict`. Le profil fait partie du snapshot.

---

## 3. Inventaire par mode (CDC + code)

Les valeurs ci-dessous sont les **défauts**. Le détail (principe, intervalle, fichier) est dans le JSON.

### 3.1 Projets — `docs/CAHIER_DES_CHARGES_PROJETS.md`

| Id | Défaut | Famille | Phénomène / ancrage |
|----|--------|---------|---------------------|
| `projects.max_inland_km` | 15 km | géométrie | Hinterland de ville-havre. Au-delà → sièges (Paris, Washington). CDC §7.3. |
| `projects.min_marine_score` | 0,5 | score | Coupe du faisceau S_ocean. Recalibrer sur Gold (phase D). |
| `projects.gatekeeper_accept` | 0,85 | score | Borne haute historique v1. Cible : ROC sur Gold. |
| `projects.gatekeeper_reject` | 0,12 | score | Borne basse historique v1. Idem. |
| `projects.max_partner_orgs` | 5 | budget | Plafond Follow the Money, plus en dur (CDC §18). |
| `projects.test_max_urls_per_seed` | 6 | budget | Run test. |
| `projects.full_max_urls_per_seed` | 20 | budget | Run full : un listing, pas un site. |
| `projects.saturation_limit` | 50 | budget | N vides d’affilée = listing épuisé. |
| `projects.rescan_after_days` | 7 | budget | Aligné sur le retry Formalités. |
| `projects.allow_tinyfish_agent` | true | budget | Agent = scalpel. |
| `projects.extract_concurrency` | 6 | budget | Borné par Nominatim 1 req/s. |
| `projects.max_coast_km` | 50 | géométrie **legacy** | Reliquat du snap. Le CDC a refusé le snap borné. À retirer. |
| `projects.no_hq_as_site` | true | **loi** | Un siège n’est pas un site. |
| `shared.dedup_dist_km` | 500 m | géométrie | Même quai. CDC §17. |

Déjà dans `settings` Mongo : inland, scores, partenaires, URLs, saturation, Agent. Le catalogue ajoute le **pourquoi** et l’**intervalle**.

### 3.2 Formalités — `docs/CAHIER_DES_CHARGES_POE.md`

| Id | Défaut | Famille | Phénomène / ancrage |
|----|--------|---------|---------------------|
| `formalities.eez_sliver_km` | 2,2 km | géométrie | 0,02° × 111 km/°. Cassis 2,3 km / Geelong 3,4 km = quasi-succès. CDC §7.3. |
| `formalities.coastal_land_km` | 15 km | géométrie | Même hinterland que Projets. |
| `formalities.inland_river_max_km` | 400 km | géométrie | Duisburg ~250 km, Rouen ~120 km, marge. |
| `formalities.geocode_agree_km` | 2 km | géométrie | Même complexe portuaire. CDC §8.2. |
| `formalities.marina_control_m` | 800 m | géométrie | ~10 min à pied douane→marina. CDC §22. |
| `formalities.wpi_proximity_km` | 1 km | géométrie | Même terminal WPI. CDC §23. |
| `formalities.osm_validate_radius_m` | 3 km | géométrie | Havre + douane adjacente. |
| `formalities.catalog_min_coords` | 3 | géométrie | 1 = mention, 2 = comparaison, 3+ = liste. CDC §6.3. |
| `formalities.catalog_looks_like_min_coords` | 1 | géométrie | Catalogue déjà reconnu + 1 GPS. |
| `formalities.catalog_lat_hits` | 8 | géométrie | Table SCT-like (`latitud:`). |
| `formalities.max_ports_per_zone` | 150 | budget | Anti-hallucination LLM, pas un cap métier. |
| `formalities.inland_far_km` | 30 km | géométrie | Audit GPS au-delà du hinterland. |
| `formalities.other_water_far_km` | 8 km | géométrie | Mer hors sliver, autre ZEE. |
| `formalities.group_outlier_km` | 300 km | géométrie | Cluster côtier d’un listing pays. |
| `formalities.group_outlier_in_eez_km` | 1 500 km | géométrie | Autre façade (Astoria). |
| `formalities.listing_sim_high` / `_low` | 0,90 / 0,60 | score | Appariement listing. Recalibrer. |
| `formalities.listing_auto_threshold` | 0,86 | score | Jointure slug→mrgid. |
| `formalities.listing_role_sim` | 0,72 | score | Entre low et high. |
| `formalities.listing_coverage_publish` | **0,90** | score | Le CDC disait « écrasante majorité » **sans chiffre**. 9/10 des PoE listing. Intervalle 0,80–0,95. |
| `formalities.osm_confidence_hi` | 0,5 | score | Milieu 0–1 ; 678/1171 v1 ≥ 0,5. Recalibrer. |
| `formalities.confidence_*_max` | 30 / 25 / 25 / 20 | score | Politique de faisceau, pas une physique. |
| `formalities.zone_timeout_s` | 900 | budget | 3× un run v2 normal. |
| `formalities.stale_days` | 180 | budget | Badge « pas revue » = semestre. |
| `formalities.refresh_after_days` | 30 | budget | Re-fetch mensuel. CDC §21. |
| `formalities.error_retry_days` | 7 | budget | Anti-bot transitoire. |
| `formalities.cycle_every_h` | 12 | budget | 2 cycles / jour. |
| `formalities.max_per_cycle` | 60 | budget | 285 ZEE ≈ 2,5 jours. |
| `formalities.geocode_ttl_*` | 180 j / 14 j | budget | Hit = semestre ; miss = 2 semaines. |
| `formalities.enrich_limit` | 200 | budget | Lot Bottom-Up. |
| `formalities.whitelist_domain_cap` | 15 | budget | Filet TinyFish. |
| `formalities.max_parallel_runs` | 4 | budget | v1+v2+tinyfish + 1. |
| `formalities.official_sources_only` | true | **loi** | |
| `formalities.noonsite_blacklist` | true | **loi** | |
| `formalities.wpi_first_port_ignored` | true | **loi** | |

### 3.3 Marinas (pas de CDC dédié — README + code + hors-périmètre PoE §27)

| Id | Défaut | Famille | Phénomène / ancrage |
|----|--------|---------|---------------------|
| `marinas.corridor_radius_nm` | 25 NM | géométrie | 4–5 h à 5–6 nœuds = saut côtier. Bande ±25 = 50 NM. |
| `marinas.corridor_step_nm` | 25 NM | géométrie | Pas ≤ 2× rayon pour recouvrement des disques. |
| `marinas.waypoint_radius_nm` | 10 NM | géométrie | ~2 h d’approche d’escale. Settings `marina_search_radius_nm`. |
| `marinas.priority_escale_nm` | 15 NM | géométrie | « Près de cette escale » (prio 1/2). |
| `marinas.max_bbox_span_nm` | 500 NM | budget | Overpass time-out. |
| `marinas.enrich_stale_days` | 365 | budget | VHF / places : l’année. |
| `marinas.batch_concurrency` | 2 | budget | Garde-fou LLM. |
| `marinas.openrouter_min_credits_usd` | 0,50 | budget | Stop avant un batch à sec. |
| `marinas.tinyfish_enrich_budget_s` | 150 s | budget | Un site JS, pas un crawl. |

Un build marinas / mouillages écrit maintenant un document `marina_runs` avec le même `params.rules`.

### 3.4 Shared

| Id | Défaut | Famille |
|----|--------|---------|
| `shared.no_snap` / `no_ocean_fallback` / `no_purge` / `no_invented_names` | true | **loi** |
| `shared.dedup_dist_km` | 0,5 km | géométrie |
| `shared.dedup_sim_low` / `_high` | 0,60 / 0,90 | score |
| `shared.claude_stop_ratio` | 0,90 | budget (10 % de marge) |
| `shared.claude_budget_usd` | 0 | budget |
| `shared.nominatim_interval_s` | 1,1 s | budget **non modulable à la baisse** (ToS) |
| `shared.tinyfish_search_rpm` / `fetch_rpm` | 30 / 150 | budget **plafonné par le fournisseur** |

---

## 4. Autres idées (au-delà du snapshot)

1. **Balayage A/B.** Même graines, deux profils (`strict` vs `recall`). On compare `listing-control.coverage`, `unlocated`, `confirmed`. Le hash dit ce qui a changé.
2. **Calibration Gold, pas l’habitude.** `gatekeeper_*`, `min_marine_score`, `listing_*`, `osm_confidence_hi` n’ont pas de phénomène physique. Dès qu’un Gold existe (CDC Projets phase D), on pose le seuil sur une courbe précision-rappel (ex. précision ≥ 0,95 pour `accept`).
3. **Analyse de sensibilité.** Un script qui rejoue `classify_poe_point` / `catalog_is_sufficient` / `site_publishable` sur le stock en faisant glisser *un* paramètre dans son intervalle. On ne module que ce qui **bouge** les comptes.
4. **Retirer `max_coast_km`.** Reliquat du snap. L’UI Settings le montre encore ; le pipeline Projets ne doit plus s’en servir.
5. **Un CDC Marinas.** Le corridor 25 NM n’a pas de cahier. Ce document en donne le phénomène ; un CDC route le figerait (escale vs corridor vs mouillage).
6. **Ne jamais varier une loi pour « voir ».** Si on veut tester un snap borné, ce n’est plus Blue Intelligence v2.
7. **Le hash dans le rapport markdown.** Une ligne `rules: abc123 / profile=strict` en tête de `GET …/report` pour qu’un humain compare sans ouvrir Mongo.
8. **Settings = défaut opérateur, pas vérité.** Changer 15 → 12 dans l’UI change les *prochains* runs, pas les anciens. C’est voulu.

---

## 5. Recette

```bash
cd backend && python3 -m pytest tests/test_run_rules.py tests/test_run_fingerprint.py tests/test_project_runs.py -q
```

- Le catalogue charge et chaque défaut (hors `loi` / bool) est **dans** son intervalle.
- Les défauts géométrie Formalités / dédup / WPI / marina-contrôle **égalent** les constantes Python actuelles (anti-dérive).
- Une surcharge hors intervalle ou une loi → `RuleError`.
- `open_run` écrit `params.rules.hash` et `chosen`.
- `get_rule` + bind fait varier `catalog_is_sufficient` (3 → 5 ports).

---

*Toute évolution de chiffre : d’abord le phénomène et l’intervalle ici / dans le JSON, ensuite le code.*
