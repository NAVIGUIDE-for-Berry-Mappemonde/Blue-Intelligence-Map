# Audit GPS des graines `confirmed`

Étape du 2026-09-07. **Pas de rebuild** (`POST /api/poe/seeds/build` interdit).
**Pas de lot** `unverified` / `probable` tant que les flags restants n’ont pas
été relus. On ne touche aux 781 `confirmed` **que** pour un GPS clairement faux.
Tanjung Pinang et Bandar Bintan Telani restent deux marinas distinctes.

Export machine : [`data/poe-confirmed-gps-audit.json`](data/poe-confirmed-gps-audit.json).

## Méthode

Sur les **781** `confirmed` géocodés, sans réseau :

1. **Reclasser** le GPS contre le polygone VLIZ (`spatial_class_for_point`).
   - `inland_far` : `inland_river` > 30 km, ou `inland` / `other_water` > 8 km
   - `outside_eez_far` : hors polygone et loin de la côte (même seuil 30 km
     pour `inland_river`, pour ne pas noyer Shanghai / Bristol)
2. **`homonym_paren_mismatch`** : le nom (ou `listing_name`) a une parenthèse
   (Bintan Island, Oregon, Georgia…) dont les tokens ne collent pas au GPS.
   Suggestion = **centroïde d’île** (Bintan 1,08°N / 104,42°E), jamais le GPS
   d’une autre marina (pas Bandar Bintan Telani).
3. **`listing_group_outlier`** : isolé > 300 km du cluster *sain* (in_eez /
   côtier) du même `listing_group` + `mrgid`. Un confirmed déjà in_eez n’est
   flaggé que s’il est > 1 500 km (Astoria NY vs côte ouest).
4. **`nominatim_inland_listing_only`** : `seed_sources=["listing"]`,
   `geocode_source=nominatim`, GPS inland > 30 km.

`verify_verdict` / `confirmation_status` ne bougent pas.

### Corrections automatiques (cas évidents seulement)

- **Tanjung Pinang** : Nominatim a pris le village de Sumatra (Palembang), pas
  Bintan. Centroïde Bintan, `geocode_source=manual_audit`.
- Tout `confirmed` spatialement hors côte **et** > 30 km **dont une observation
  in_eez du même `name_norm` existe** : on prend ce GPS,
  `geocode_source=observation`.

Si un homonyme reste possible (St-Nazaire Gard vs Loire-Atlantique, Astoria NY
vs Oregon, Safi, Gabes, Savannah sans obs côtière) : **flag seulement**, pas de
changement `lat`/`lon`.

`poe_ports` (1280) n’est modifié que si la même `dedup_key` y porte **le même**
GPS aberrant. Log : `poe_audit_log.action = gps_audit_correct`.

Code : `backend/app/services/poe_confirmed_gps_audit.py`.  
API atelier : `GET /api/poe/seeds/gps-audit` (dry-run).  
Script : `python3 backend/scripts/audit_confirmed_gps.py [--persist]`.

## Résultat Atlas (2026-09-07T08:01:30Z)

Avant / après persist :

| | avant | après |
|---|---:|---:|
| `poe_seed_ports` | 4034 | 4034 |
| `poe_ports` | 1280 | 1280 |
| `confirmed` | 781 | 781 |
| `gps_audit_status=corrected` | 0 | **4** |
| `gps_audit_status=flagged` | 0 | **16** |
| `gps_audit_status=ok` | 0 | 761 |
| `poe_ports` patchés (même clé + même GPS aberrant) | — | 3 |
| fusions de clés | 0 | 0 |

20 flags au scan (13 haute, 7 moyenne) ; 4 corrections évidentes.

### Corrigés

| Clé | Nom | GPS avant | GPS après | Source |
|---|---|---|---|---|
| `8492:tanjungpinangbintanislandriauislands` | Tanjung Pinang (Bintan Island) | −3,356 / 104,657 (Sumatra) | **1,08 / 104,42** (centroïde Bintan) | `manual_audit` |
| `8429:ensenada` | Ensenada | 24,06 / −106,70 | 31,85 / −116,63 (Baja) | `observation` |
| `8429:lapaz` | La Paz | 19,35 / −98,96 | 24,16 / −110,33 (BCS) | `observation` |
| `5675:parnu2parnuport` | Pärnu 2 (Pärnu Port) | 57,77 / 26,03 (inland) | 58,38 / 24,50 (côte) | `observation` |

Les trois derniers existaient dans `poe_ports` avec le même GPS aberrant :
corrigés aussi, count 1280 inchangé. Tanjung Pinang n’était pas dans
`poe_ports` (listing-only).

### Corrigés ensuite (recherche UN/LOCODE / autorités)

15 GPS tranchés, `geocode_source=manual_audit`. Pas de fusion de clés.
Pas de centroïde de groupe (Savannah ≠ Delaware, Vancouver ≠ Prince Rupert).

Source de vérité **révisable en PR** : [`data/poe-gps-arbitrated.json`](data/poe-gps-arbitrated.json)
(plus un dict Python). Chargeur : `backend/app/services/poe_gps_registry.py`.
Atelier : `GET /api/poe/seeds/gps-arbitrated` (lecture git, pas de persist).

| Clé | Nom | GPS avant | GPS après |
|---|---|---|---|
| `8456:savannah` | Savannah | Finger Lakes NY | **32,08 / −81,09** (USSAV) |
| `8456:astoria` | Astoria | Queens NY | **46,19 / −123,83** (Oregon) |
| `5677:stnazaire` | St Nazaire | Gard | **47,28 / −2,20** (FRSNR). Clé `nantessaintnazaire` inchangée |
| `8367:safi` | Safi | hinterland | **32,31 / −9,25** (MASFI) |
| `8366:gabes` | Gabes | hinterland | **33,91 / 10,10** (TNGAE) |
| `8479:portofmtwara` | Port of Mtwara | 86 km inland | **−10,27 / 40,20** (TZMYW) |
| `8479:portoftanga` | Port of Tanga | 82 km inland | **−5,07 / 39,11** (TZTGT) |
| `8464:recife` | Recife | Paraná | **−8,06 / −34,87** (BRREC) |
| `8493:vancouver` | Vancouver | Gold River / Nootka | **49,29 / −123,11** (Canada Place) |
| `8456:brunswick` | Brunswick | NY inland | **31,13 / −81,54** (Géorgie) |
| `8484:tpdanang` | Tp Da Nang | Quảng Nam inland | **16,10 / 108,23** (VNDAD) |
| `5697:canakkale` | Çanakkale | hinterland | **40,10 / 26,38** (Kepez) |
| `5697:mersin` | Mersin | hinterland Mut | **36,80 / 34,64** (TRMER) |
| `8349:portofkilifi` | Port of Kilifi | hinterland | **−3,64 / 39,86** (Kilifi Creek) |
| `8324:portofmadang` | Port of Madang | −5,0 / 145,5 | **−5,21 / 145,80** (PGMAG) |

`5693:puertodemelilla` : GPS déjà le quai (~400 m de Wikipedia). Faux positif
VLIZ (enclave). Registre `action=keep` → `gps_audit_status=ok`, lat/lon inchangés.

Sidney BC (`8493:portofsidney`) : **ok**, pas flaggé malgré des obs Sydney NS.

## Scorer d'homonymes (géocodage)

`geocode_port_dual` / `pick_geocode` notent jusqu'à **10** candidats (filet Nominatim ;
le système c'est parenthèses, `listing_group`, pairs, et le registre JSON) :

- parenthèses conservées dans la requête (Bintan avant Sumatra)
- polygone VLIZ de **ce** mrgid + classe OSM harbour
- `listing_group` comme filtre (West Coast USA → lon < −90°), jamais un GPS à copier
- pairs côtiers du même groupe : proximité, pas fusion
- deux bassins à score proche **sans** hint → `geocode_status=ambiguous`, on ne
  pose pas de GPS (et on n'écrase pas un GPS existant)
- `geocode_one` consulte le registre `accepted` **avant** Nominatim
  (`geocode_arbitration=gps_registry`). Claude ne choisit pas un point.

`_needs_geocode` : `name_only` sans point, ou `inland_far` / `ambiguous`.
Les confirmed `ok` / `corrected` ne sont **pas** re-géocodés.

17 `unverified` inland_far ont été re-géocodés avec le scorer (Ibiza Madrid →
Ibiza, Semarang, Huatulco, Punta Cana, etc.). Trois retours : **Sevilla**
(port fluvial Guadalquivir), **Kingston** (saut Terre-Neuve), **Hokkaido**
(île, pas Sapporo). Le scorer refuse désormais un quai lointain dont le
libellé n’est pas le toponyme, et un pair listing à > 1 500 km.

## Tanjung Pinang — avant / après

Nominatim a renvoyé le village *Tanjung Pinang, Ogan Ilir, Sumatera Selatan*
(−3,36 / 104,66) au lieu de la ville *Tanjungpinang, Kepulauan Riau*
(~0,92 / 104,45). Le juge Claude avait dit OUI (textes Bintan). Le GPS était
faux.

| | lat | lon | source | spatial |
|---|---:|---:|---|---|
| Avant | −3,3564491 | 104,6571166 | nominatim | inland_river 40,8 km |
| Après | **1,08** | **104,42** | manual_audit | in_eez (sliver 1,4 km) |
| Bandar Bintan Telani (inchangé) | 1,1605006 | 104,3201677 | — | — |
| name_only `…bbtbintanisland` | — | — | — | toujours name_only, pas fusionné |

La suggestion n’est **pas** le GPS de Bandar Bintan Telani (autre marina,
1,1605 / 104,3202).

## Ce qu’on ne fait pas maintenant

- `POST /api/poe/seeds/build`
- Enrich `unverified` / `probable` (~1 805) — seulement les graines
  `inland_far` / `ambiguous`, pas les 781 confirmed ok
- Fusion de clés

**Prochain pas** : lot `unverified` (hors confirmed ok).
