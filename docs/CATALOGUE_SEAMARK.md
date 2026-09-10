# Catalogue de référence des tags `seamark:*` et tags portuaires exploitables

Inspiré du dépôt [Open Waters: Seamap](https://github.com/openwatersio/seamap)
(`src/main/java/Seamark.java`, `bin/audit-tags.ts`) : documenter noir sur blanc
**ce que nos pipelines lisent** dans OpenStreetMap, et ce qui reste exploitable
demain. La version machine est `backend/data/seamark_catalog.json`, consommée
par `scripts/audit_tags.py`.

Règle d'or héritée de Blue Intelligence : **on n'invente rien**. Un tag absent
reste absent ; un badge, un téléphone ou un canal VHF n'apparaît que si un tag
l'atteste.

## Comment lire ce catalogue

- **exploité** — lu aujourd'hui par un pipeline (dump marinas, capitaineries,
  badges services, enrichissement).
- **candidat** — documenté ici, exploitable dans une itération future ; le
  rapport d'audit mesure sa présence réelle dans nos données.
- L'audit (`python scripts/audit_tags.py`) compare ce catalogue aux données
  Mongo réelles et liste les clés **hors catalogue** : c'est un rapport, pas un
  contrôle CI — les données OSM réelles contiennent des typos, un œil humain
  tranche (voir `docs/audits/`).

## Mode Marinas

| Tag | Statut | Usage |
|---|---|---|
| `leisure=marina` | exploité | identité du dump mondial |
| `seamark:type=harbour` + `seamark:harbour:category` | exploité | catégorie (marina, yacht_harbour…) — 68 % des fiches |
| `seamark:harbour:capacity`, `capacity` | exploité | badge **Amarrage** |
| `seamark:harbour:draught`, `max_depth`, `depth` | exploité | badge **Amarrage** (tirant d'eau) |
| `mooring` | exploité | badge **Amarrage** |
| `fuel`, `drinking_water`, `electricity`, `shop` | exploité | badge **Avitaillement** |
| `seamark:small_craft_facility:category` | exploité | badge selon valeur (fuel → Avitaillement, slipway/crane/boat_hoist/pump_out → Technique, toilets/showers/laundrette → À terre, visitor_berth → Amarrage) |
| `pumpout`, `sanitary_dump_station`, `waste_disposal` | exploité | badge **Technique** |
| `shower`, `toilets`, `restaurant`, `wifi`, `internet_access`, `wheelchair` | exploité | badge **À terre** |
| `website`, `contact:website`, `url` | exploité | site officiel (vérifié palier 2) |
| `phone`, `contact:phone`, `email`, `contact:email`, `opening_hours`, `operator`, `fee`, `charge`, `description` | exploité | fiche |
| `seamark:type=berth` + `seamark:berth:category` | candidat | postes visiteurs à quai |
| `seamark:type=harbour_basin`, `dock`, `marina` (typo fréquente) | candidat | variantes observées par l'audit |

## Mode Capitaineries

| Tag | Statut | Usage |
|---|---|---|
| `office=harbour_master`, `seamark:building:function=harbour_master`, `harbour=harbour_master` | exploité | identité |
| `phone`, `contact:phone`, `telephone`, `mobile`, `contact:mobile` | exploité | téléphone (jamais inventé) |
| `vhf`, `vhf_channel`, `channel`, `harbour:vhf`, `communication:vhf`, `seamark:communication:channel`, `seamark:harbour:vhf`, `comcha`, `shom:comcha` | exploité | canal VHF |
| `seamark:information`, `inform`, `ninfom`, `note`, `shom:*`, `noaa:*` | exploité | notes / overlay SHOM & NOAA |

## Mode Mouillages (corridor de route)

| Tag | Statut | Usage |
|---|---|---|
| `seamark:type=anchorage` + `seamark:anchorage:category` | candidat | zones de mouillage officielles |
| `seamark:type=anchor_berth` | candidat | postes numérotés |
| `seamark:type=mooring` + `seamark:mooring:category` | candidat | bouées / coffres |
| `seamark:type=restricted_area` + `seamark:restricted_area:restriction=no_anchoring` | candidat | mouillage interdit — croisement AMP |

## Route NAVIGUIDE (atterrissages, dangers)

| Tag | Statut | Usage |
|---|---|---|
| `seamark:type=light` + `character/colour/period/range` | candidat | feux d'atterrissage aux escales (`Fl(3)WRG.10s`) |
| `seamark:type=rock` / `wreck` / `obstruction` | candidat | dangers le long du corridor |

## Ajouter un tag au catalogue

1. Lancer l'audit : `python scripts/audit_tags.py --out docs/audits/$(date +%F)-tags.md`.
2. Regarder les sections « hors catalogue » / « sous-clés non documentées » ;
   attention aux typos OSM (`seamark:type=no`, `marina`…), c'est justement le
   rôle de l'œil humain.
3. Ajouter l'entrée dans `backend/data/seamark_catalog.json` (statut
   `candidat`, puis `exploite` quand un pipeline le lit vraiment).
4. Mettre à jour ce document et, si le tag alimente un badge, la table
   `SERVICE_TAG_QUESTIONS` de `backend/app/services/marina_world.py`.

## Références

- [OpenSeaMap — Seamark tag values](https://wiki.openstreetmap.org/wiki/OpenSeaMap/Seamark_Tag_Values)
- [openwatersio/seamap](https://github.com/openwatersio/seamap) — `Seamark.java`, `SeamarkZoomRules.java`, `bin/audit-tags.ts`
- `backend/app/services/marina_build.py` (`KEPT_TAGS`) et `capitainerie_world.py` (`kept_tags`)
