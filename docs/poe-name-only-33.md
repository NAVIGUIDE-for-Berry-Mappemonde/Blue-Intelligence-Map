# 33 graines `name_only` — dossier de revue manuelle

Snapshot Atlas du **2026-09-07** (collection `poe_seed_ports`, inventaire
construit le 2026-09-06T09:29:28Z, géocode le 2026-09-06 entre 09:36 et 09:44Z).
Listing source : `backend/data/listing_control/all_countries.json`
(généré 2026-09-05T10:39:03Z, 1193 PoE communautaires).

Ce n’est **pas** une vérité officielle. C’est tout ce que le système a sur
ces 33 fiches, plus les rapprochements trouvés dans `poe_ports` (carte v1),
les autres graines, le listing et l’index ZEE VLIZ.

**Ne pas** relancer `POST /api/poe/seeds/build` après correction : le build
vide `poe_seed_ports` et efface les jugements déjà faits.

---

## Pourquoi ces 33 existent

Une graine est `name_only` si le listing Noonsite dit « PoE » **et** qu’on
n’a **pas** de point accepté. Ici, les 33 ont toutes :

| Champ | Valeur commune |
|---|---|
| `verify_verdict` | `name_only` |
| `listing_role` | `poe` |
| `seed_sources` | `["listing"]` seulement — ni v1, ni run, ni OSM au build |
| `has_coords` / `lat` / `lon` | `false` / `null` |
| `judge_status` | absent — Claude n’a pas été appelé |
| `osm_*` | vides (pas de prior OSM ≤ 800 m) |
| `source_urls` | `[]` |
| `search_exclude_domains` | `["noonsite.com"]` |
| `extraction_engine` | `seed` |
| `geocoded_at` | posé — une tentative a eu lieu ; `_needs_geocode` les sautera |

Le run `name_only` a géocodé 572 fiches : **537 ok**, **33 miss**. Ces 33
sont le reliquat. Relancer l’enrich ne les regéocodera pas (sentinel
`geocoded_at`).

---

## Comment le géocode a échoué

Le filtre spatial (`classify_poe_point`) n’accepte un point que s’il est
dans **cette** ZEE (`mrgid`), à ≤ 2,2 km (sliver), ou à terre ≤ 15 km du
littoral de cette ZEE (ou exception fluviale ≤ 400 km si « harbour-like »).

| `spatial_kind` | n | Sens |
|---|---:|---|
| `miss` | 26 | Nominatim/GeoNames n’ont rien renvoyé d’utilisable (souvent un nom composé « A / B ») |
| `other_water` | 3 | Point en mer, hors polygone — coords **trouvées puis jetées** (`lat`/`lon` restent null) |
| `inland` | 4 | Point à terre trop loin, ou mauvais pays — coords jetées |

Les 7 rejets spatiaux ont `geocode_arbitration: spatial_rejected`. Le
système a parfois un GPS interne, mais il ne le persiste pas.

---

## Tableau synoptique

| # | Nom listing | Pays listing | ZEE (`mrgid`) | Échec | Dist. | Doublon / piste déjà en base |
|---|---|---|---|---|---:|---|
| 1 | Geelong | Australia | Australia (8323) | ow | 3.4 | — |
| 2 | Newcastle and Port Stephen | Australia | Australia (8323) | miss | — | v1+probable `Newcastle` (Port Stephens à part) |
| 3 | Port Kembla / Shellharbour | Australia | Australia (8323) | miss | — | v1 `Port Kembla / Wollongong` |
| 4 | Big Creek / Placencia | Belize | Belize (8457) | miss | — | v1 `Big Creek`; `Placencia` probable |
| 5 | West End/Sopers Hole | British Virgin Islands | British Virgin Islands (8411) | miss | — | v1 `Soper’s Hole Dock / West End Ferry Terminal`; `West End` probable |
| 6 | Grand Mannan Harbour (Grand Manan Island) | Canada | Canada (8493) | miss | — | — |
| 7 | Marigot Bay (St Martin) | St. Martin | Collectivity of Saint Martin (8495) | miss | — | — |
| 8 | Oyster Pond - St Martin | St. Martin | Collectivity of Saint Martin (8495) | miss | — | — |
| 9 | Marina Los Morros | Cuba | Cuba (8406) | miss | — | — |
| 10 | Cassis | France | France (5677) | ow | 2.3 | — |
| 11 | Gironde Estuary & Bordeaux | France | France (5677) | miss | — | `Bordeaux` probable |
| 12 | Gulfe de Fos (Port St Louis, Port Napoleon, St-Gervais) | France | France (5677) | miss | — | — |
| 13 | Christmas Island/Kiritimati | Kiribati | Gilbert Islands (8488) | ow | 2529.9 | `Christmas Island Port` unverified |
| 14 | Tyrell Bay & Hillsborough (Carriacou) | Grenada | Grenada (8419) | miss | — | v1 `Port of Hillsborough` |
| 15 | Barbers Point Harbour (Ko Olina) | Hawaii | Hawaii (8453) | miss | — | — |
| 16 | Andaman Islands | India | India (8480) | inl | 697.8 | v1 `Port of Port Blair` sur ZEE 8333 |
| 17 | Bandar Bintan Telani (BBT) – Bintan Island | Indonesia | Indonesia (8492) | miss | — | `Bandar Bintan Telani` probable; `Tanjung Pinang (Bintan Island, Riau Islands)` confirmed |
| 18 | Bowden Harbour/Port Morant | Jamaica | Jamaica (8459) | miss | — | — |
| 19 | Khuludhufushi | Maldives | Maldives (8345) | miss | — | — |
| 20 | Puerto Vallarta/ Banderas Bay | Mexico | Mexico (8429) | miss | — | v1 `Puerto Vallarta` |
| 21 | Colonia, Yap Island | Federated States of Micronesia | Micronesia (8316) | miss | — | — |
| 22 | Lele/Leluh Harbour | Federated States of Micronesia | Micronesia (8316) | miss | — | — |
| 23 | Tanapag Harbour (Saipan) | Northern Marianas | Northern Mariana Islands (48980) | miss | — | `Saipan` probable |
| 24 | Longyearbyen | Norway | Norway (5686) | inl | 520.2 | — |
| 25 | San Carlos - Vista Mar Marina | Panama | Panama (8423) | miss | — | — |
| 26 | Prince Edward Island | Marion & Prince Edward Island | Prince Edward Islands (8384) | inl | 13906.6 | — |
| 27 | Britannia Bay, Lovell | St. Vincent & the Grenadines | Saint Vincent and the Grenadines (8421) | miss | — | v1 `Mustique` |
| 28 | Lata, Ndendo Island (Santa Cruz Islands) | Solomon Islands | Solomon Islands (8314) | miss | — | `Lata` probable |
| 29 | Ria de Vigo and Baiona | Spain | Spain (5693) | miss | — | — |
| 30 | Cowes & R. Medina (Isle of Wight) | United Kingdom | United Kingdom (5696) | miss | — | — |
| 31 | Oban/Dunstaffnage | United Kingdom | United Kingdom (5696) | miss | — | — |
| 32 | Ketchikan | USA | United States (8456) | inl | 919.9 | v1+probable `Ketchikan Small Boat Harbor` **8463** ; `Ketchikan, Alaska` rejected sur 8456 |
| 33 | Unalaska/Port of Dutch Harbor | USA | United States (8456) | miss | — | v1+probable `Dutch Harbor Small Boat Harbor` **8463** |


Légende échec : `miss` = pas de point ; `ow` = `other_water` ; `inl` = `inland`.

---

## Ce qui est le plus rentable à la main

Trois familles, par ordre de ROI.

### A. Fusionner (ne pas recréer un 34ᵉ port)

Le listing a un nom **composé** ou une variante, et le lieu existe déjà
sous un autre `dedup_key` (souvent v1 + `probable`) :

| Fiche `name_only` | Déjà en base | Action suggérée |
|---|---|---|
| Port Kembla / Shellharbour | `Port Kembla / Wollongong` v1+probable | Fusionner (Shellharbour = voisin) |
| Big Creek / Placencia | `Big Creek` + `Placencia` v1+probable | Scinder / rattacher aux deux |
| West End/Sopers Hole | `Soper’s Hole Dock / West End Ferry Terminal` | Fusionner |
| Gironde Estuary & Bordeaux | `Bordeaux` v1+probable | Fusionner (ou bureau estuaire) |
| Puerto Vallarta/ Banderas Bay | `Puerto Vallarta` v1+probable | Fusionner |
| Bandar Bintan Telani (BBT) – Bintan Island | `Bandar Bintan Telani` probable | Fusionner |
| Tanapag Harbour (Saipan) | `Saipan` probable | Fusionner ou préciser le quai |
| Lata, Ndendo Island (Santa Cruz Islands) | `Lata` v1+probable | Fusionner |
| Britannia Bay, Lovell | `Mustique` v1 | Fusionner (même île) |
| Tyrell Bay & Hillsborough (Carriacou) | `Port of Hillsborough` v1 | Fusionner Hillsborough ; Tyrell à part |
| Newcastle and Port Stephen | `Newcastle` v1+probable | Fusionner Newcastle ; Port Stephens à part |
| Ketchikan | `Ketchikan Small Boat Harbor` v1+probable **mrgid 8463** | Fusionner vers l’Alaska, pas 8456 |
| Unalaska/Port of Dutch Harbor | `Dutch Harbor Small Boat Harbor` v1+probable **mrgid 8463** | Idem |

### B. Corriger la ZEE puis regéocoder

Le point est bon, le **polygone** est le mauvais (listing slug → premier
`mrgid` de `slug_overrides.json`).

| Fiche | ZEE actuelle | ZEE probable | Preuve |
|---|---|---|---|
| Ketchikan | 8456 United States | **8463 Alaska** | v1 déjà en 8463 ; inland 920 km |
| Unalaska/Port of Dutch Harbor | 8456 United States | **8463 Alaska** | v1 déjà en 8463 |
| Christmas Island/Kiritimati | 8488 Gilbert Islands | **8441 Line Group** | listing group = Line Islands ; ow 2529 km |
| Andaman Islands | 8480 India | **8333 Andaman and Nicobar** | Port Blair v1 en 8333 ; inland 698 km |
| Longyearbyen | 5686 Norway (continent) | ZEE Svalbard (absente de l’assignation) | listing group = Svalbard ; inland 520 km, géocodeurs d’accord |
| Barbers Point (Ko Olina) | 8453 Hawaii | 8453 OK | iso2 VLIZ null, pas un bug |

`slug_overrides.json` mappe `usa` → `[8456, 8463, 8453]` et `kiribati` →
`[8488, 8450, 8441]`. Le build listing prend **un** mrgid ; les ports
Alaska / Line Islands tombent sur le premier de la liste.

### C. Quasi-succès spatial (2–4 km)

| Fiche | Kind | Dist. | Accord géocodeurs |
|---|---|---:|---|
| Cassis | other_water | 2,3 km | oui |
| Geelong | other_water | 3,4 km | oui |

Le sliver accepté est 2,2 km. Ces deux-là sont juste au-delà. Un GPS
manuel dans le port, ou un assouplissement ponctuel, suffit.

### D. Vrais orphelins (recherche humaine)

Aucun jumeau v1/graine fiable : Grand Manan (faute Mannan), Marigot Bay
et Oyster Pond (Saint-Martin, pas Sainte-Lucie), Marina Los Morros,
Golfe de Fos (nom cassé), Ko Olina, Bowden/Port Morant, Khulhudhuffushi
(faute Khuludhufushi), Colonia Yap, Lelu/Leluh, Vista Mar Panama, Prince
Edward subantarctique (homonyme Canada), Ría de Vigo & Baiona, Cowes,
Oban/Dunstaffnage.

---

## Pièges d’homonymie

| Ne pas confondre | Avec |
|---|---|
| Marigot Bay (Saint-Martin, 8495) | Marigot Bay Marina, Sainte-Lucie (8416) v1 |
| Prince Edward Island (8384, Marion SA) | Île-du-Prince-Édouard, Canada |
| Christmas Island/Kiritimati (Kiribati) | Christmas Island (Australie) |
| Colonia, Yap | Colonia del Sacramento (Uruguay) v1 |
| San Carlos – Vista Mar (Panama) | San Carlos Baja / Sonora (Mexique) v1 |
| Ketchikan listing sur 8456 | Ketchikan Small Boat Harbor sur 8463 |

---

## Fiches détaillées

### 1. Geelong

**Australia** · groupe listing `Victoria (Australia)` · `8323:geelong`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8323:geelong` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Australia / `australia` |
| Listing groupe | Victoria (Australia) |
| `mrgid` / `zone_name` | 8323 / Australia |
| ZEE VLIZ | Australia — Australian Exclusive Economic Zone (`iso2`=AU, `pol_type`=200NM, souverain=Australia) |
| `country_iso2` graine | AU |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:36:16Z |
| `geocode_query` | `Geelong` |
| `spatial_kind` | `other_water` — point trouvé mais en mer hors de la ZEE assignée → rejeté |
| `distance_km` | 3.4 |
| `geocode_agree` | True |
| `geocode_arbitration` | spatial_rejected |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Geelong official port of entry OR clearance OR "puerto habilitado" Australia` |
| `seed_line` | `Geelong | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Geelong`, sans GPS |

**Lecture**

Nominatim et GeoNames sont d’accord (`geocode_agree: true`) mais le point est à 3,4 km hors polygone ZEE Australie (`other_water`). Quasi-succès : le filtre spatial a tout jeté. Relancer le géocode avec un nom plus précis (Geelong Harbour / Port of Geelong) ou accepter un sliver > 2,2 km.

---

### 2. Newcastle and Port Stephen

**Australia** · groupe listing `New South Wales` · `8323:newcastleandportstephen`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8323:newcastleandportstephen` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Australia / `australia` |
| Listing groupe | New South Wales |
| `mrgid` / `zone_name` | 8323 / Australia |
| ZEE VLIZ | Australia — Australian Exclusive Economic Zone (`iso2`=AU, `pol_type`=200NM, souverain=Australia) |
| `country_iso2` graine | AU |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:36:06Z |
| `geocode_query` | `Newcastle and Port Stephen` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Newcastle and Port Stephen official port of entry OR clearance OR "puerto habilitado" Australia` |
| `seed_line` | `Newcastle and Port Stephen | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Newcastle and Port Stephen`, sans GPS |

**Lecture**

Nom composé « A and B » : le géocodeur n’a rien posé. Sur la même ZEE, la graine `Newcastle` existe déjà en `probable` (-32.9266, 151.7840) et dans `poe_ports` v1. Port Stephens (orthographe listing : Stephen) est un second lieu. Décider : fusionner avec Newcastle, ou créer deux points.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Newcastle | carte affichée | -32.9265876, 151.7839674 |
| `poe_seed_ports` | Newcastle | probable | -32.9265876, 151.7839674 |

`Port Kennedy (Thursday Island and Horn Island)` a matché par tokens (`port`) : **faux ami** (coords WA 115.75°E, pas NSW). Ignorer.

---

### 3. Port Kembla / Shellharbour

**Australia** · groupe listing `New South Wales` · `8323:portkemblashellharbour`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8323:portkemblashellharbour` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Australia / `australia` |
| Listing groupe | New South Wales |
| `mrgid` / `zone_name` | 8323 / Australia |
| ZEE VLIZ | Australia — Australian Exclusive Economic Zone (`iso2`=AU, `pol_type`=200NM, souverain=Australia) |
| `country_iso2` graine | AU |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:36:09Z |
| `geocode_query` | `Port Kembla / Shellharbour` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Port Kembla / Shellharbour official port of entry OR clearance OR "puerto habilitado" Australia` |
| `seed_line` | `Port Kembla / Shellharbour | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Port Kembla / Shellharbour`, sans GPS |

**Lecture**

Nom composé A / B. v1 et une graine `probable` portent déjà `Port Kembla / Wollongong` (-34.4809, 150.9013). Shellharbour est une ville voisine, pas le même quai. Fusion probable avec Port Kembla / Wollongong, ou point distinct à Shellharbour.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Port Kembla / Wollongong | carte affichée | -34.480919, 150.9012821 |
| `poe_seed_ports` | Port Kembla / Wollongong | probable | -34.480919, 150.9012821 |

---

### 4. Big Creek / Placencia

**Belize** · `8457:bigcreekplacencia`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8457:bigcreekplacencia` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Belize / `belize` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 8457 / Belize |
| ZEE VLIZ | Belize — Belizean Exclusive Economic Zone (`iso2`=BZ, `pol_type`=200NM, souverain=Belize) |
| `country_iso2` graine | BZ |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:36:43Z |
| `geocode_query` | `Big Creek / Placencia` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Big Creek / Placencia official port of entry OR clearance OR "puerto habilitado" Belize` |
| `seed_line` | `Big Creek / Placencia | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Big Creek / Placencia`, sans GPS |

**Lecture**

Deux ports Belize déjà dans v1 et en `probable` : Big Creek (16.5203, -88.4104) et Placencia (16.5156, -88.3672). La fiche listing colle deux lieux. Ne pas recréer : fusionner ou scinder.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Big Creek | carte affichée | 16.5203083, -88.4103792 |
| `poe_seed_ports` | Placencia | probable | 16.5156113, -88.3671785 |
| `poe_seed_ports` | Big Creek | probable | 16.5203083, -88.4103792 |

---

### 5. West End/Sopers Hole

**British Virgin Islands** · groupe listing `Tortola` · `8411:westendsopershole`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8411:westendsopershole` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | British Virgin Islands / `british-virgin-islands` |
| Listing groupe | Tortola |
| `mrgid` / `zone_name` | 8411 / British Virgin Islands |
| ZEE VLIZ | British Virgin Islands — British Exclusive Economic Zone (British Virgin Islands) (`iso2`=VG, `pol_type`=200NM, souverain=United Kingdom) |
| `country_iso2` graine | VG |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:36:58Z |
| `geocode_query` | `West End/Sopers Hole` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `West End/Sopers Hole official port of entry OR clearance OR "puerto habilitado" British Virgin Islands` |
| `seed_line` | `West End/Sopers Hole | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `West End/Sopers Hole`, sans GPS |

**Lecture**

v1 + graine `probable` : `Soper’s Hole Dock / West End Ferry Terminal` (18.3875, -64.7034), plus une graine `West End`. C’est le même lieu Tortola. Fusion, pas nouveau port.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Soper’s Hole Dock / West End Ferry Terminal | carte affichée | 18.3875292, -64.7033916 |
| `poe_seed_ports` | Soper’s Hole Dock / West End Ferry Terminal | probable | 18.3875292, -64.7033916 |
| `poe_seed_ports` | West End | probable | 18.3875292, -64.7033916 |

**Autres noms listing proches (à traiter avec prudence)** : `West End` (Bahamas).

---

### 6. Grand Mannan Harbour (Grand Manan Island)

**Canada** · groupe listing `New Brunswick` · `8493:grandmannanharbourgrandmananisland`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8493:grandmannanharbourgrandmananisland` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Canada / `canada` |
| Listing groupe | New Brunswick |
| `mrgid` / `zone_name` | 8493 / Canada |
| ZEE VLIZ | Canada — Canadian Exclusive Economic Zone (`iso2`=CA, `pol_type`=200NM, souverain=Canada) |
| `country_iso2` graine | CA |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:37:13Z |
| `geocode_query` | `Grand Mannan Harbour (Grand Manan Island)` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Grand Mannan Harbour (Grand Manan Island) official port of entry OR clearance OR "puerto habilitado" Canada` |
| `seed_line` | `Grand Mannan Harbour (Grand Manan Island) | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Grand Mannan Harbour (Grand Manan Island)`, sans GPS |

**Lecture**

Orthographe listing « Mannan » au lieu de Manan. Aucun match v1/graine. Piste : Grand Manan, New Brunswick (Canada).

**Autres noms listing proches (à traiter avec prudence)** : `Grand Harbour` (Malta).

---

### 7. Marigot Bay (St Martin)

**St. Martin** · `8495:marigotbaystmartin`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8495:marigotbaystmartin` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | St. Martin / `st-martin` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 8495 / Collectivity of Saint Martin |
| ZEE VLIZ | Collectivity of Saint Martin — French Exclusive Economic Zone (Collectivity of Saint Martin) (`iso2`=MF, `pol_type`=200NM, souverain=France) |
| `country_iso2` graine | MF |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:42:42Z |
| `geocode_query` | `Marigot Bay (St Martin)` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Marigot Bay (St Martin) official port of entry OR clearance OR "puerto habilitado" Collectivity of Saint Martin` |
| `seed_line` | `Marigot Bay (St Martin) | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Marigot Bay (St Martin)`, sans GPS |

**Lecture**

Ne pas confondre avec `Marigot Bay Marina` v1 à Sainte-Lucie (mrgid 8416). Ici : Collectivity of Saint Martin (mrgid 8495). Le listing a aussi `Marigot` (autre nom). Géocode du nom composé a miss.

**Autres noms listing proches (à traiter avec prudence)** : `Marigot` (Dominica), `Marigot Bay` (St. Lucia), `St Martin's` (United Kingdom).

---

### 8. Oyster Pond - St Martin

**St. Martin** · `8495:oysterpondstmartin`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8495:oysterpondstmartin` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | St. Martin / `st-martin` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 8495 / Collectivity of Saint Martin |
| ZEE VLIZ | Collectivity of Saint Martin — French Exclusive Economic Zone (Collectivity of Saint Martin) (`iso2`=MF, `pol_type`=200NM, souverain=France) |
| `country_iso2` graine | MF |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:42:41Z |
| `geocode_query` | `Oyster Pond - St Martin` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Oyster Pond - St Martin official port of entry OR clearance OR "puerto habilitado" Collectivity of Saint Martin` |
| `seed_line` | `Oyster Pond - St Martin | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Oyster Pond - St Martin`, sans GPS |

**Lecture**

Listing a aussi `Oyster Pond` (sans suffixe). Frontière FR/NL de l’île. Pas de match v1 sur 8495.

**Autres noms listing proches (à traiter avec prudence)** : `Oyster Pond` (Sint Maarten), `St Martin's` (United Kingdom).

---

### 9. Marina Los Morros

**Cuba** · `8406:marinalosmorros`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8406:marinalosmorros` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Cuba / `cuba` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 8406 / Cuba |
| ZEE VLIZ | Cuba — Cuban Exclusive Economic Zone (`iso2`=CU, `pol_type`=200NM, souverain=Cuba) |
| `country_iso2` graine | CU |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:38:01Z |
| `geocode_query` | `Marina Los Morros` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Marina Los Morros official port of entry OR clearance OR "puerto habilitado" Cuba` |
| `seed_line` | `Marina Los Morros | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Marina Los Morros`, sans GPS |

**Lecture**

Aucune occurrence v1/OSM/runs. Nom manquant dans les extraits. Recherche manuelle Cuba (Los Morros / marina).

---

### 10. Cassis

**France** · groupe listing `Mediterranean Coast (France)` · `5677:cassis`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `5677:cassis` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | France / `france-2` |
| Listing groupe | Mediterranean Coast (France) |
| `mrgid` / `zone_name` | 5677 / France |
| ZEE VLIZ | France — French Exclusive Economic Zone (`iso2`=FR, `pol_type`=200NM, souverain=France) |
| `country_iso2` graine | FR |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:38:43Z |
| `geocode_query` | `Cassis` |
| `spatial_kind` | `other_water` — point trouvé mais en mer hors de la ZEE assignée → rejeté |
| `distance_km` | 2.3 |
| `geocode_agree` | True |
| `geocode_arbitration` | spatial_rejected |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Cassis official port of entry OR clearance OR "puerto habilitado" France` |
| `seed_line` | `Cassis | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Cassis`, sans GPS |

**Lecture**

Comme Geelong : accord Nominatim/GeoNames, rejeté à 2,3 km hors ZEE France (`other_water`). Le port est dans la calanque, souvent juste hors polygone. Quasi-succès spatial.

---

### 11. Gironde Estuary & Bordeaux

**France** · groupe listing `Atlantic (France)` · `5677:girondeestuarybordeaux`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `5677:girondeestuarybordeaux` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | France / `france-2` |
| Listing groupe | Atlantic (France) |
| `mrgid` / `zone_name` | 5677 / France |
| ZEE VLIZ | France — French Exclusive Economic Zone (`iso2`=FR, `pol_type`=200NM, souverain=France) |
| `country_iso2` graine | FR |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:38:43Z |
| `geocode_query` | `Gironde Estuary & Bordeaux` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Gironde Estuary & Bordeaux official port of entry OR clearance OR "puerto habilitado" France` |
| `seed_line` | `Gironde Estuary & Bordeaux | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Gironde Estuary & Bordeaux`, sans GPS |

**Lecture**

Région + ville, pas un quai. Graine `Bordeaux` déjà `probable` (44.8412, -0.5800) et dans v1. Fusionner vers Bordeaux, ou pointer un bureau (Pauillac / Le Verdon) si le listing vise l’estuaire.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| `poe_seed_ports` | Bordeaux | probable | 44.841225, -0.5800364 |

---

### 12. Gulfe de Fos (Port St Louis, Port Napoleon, St-Gervais)

**France** · groupe listing `Mediterranean Coast (France)` · `5677:gulfedefosportstlouisportnapoleonstgerva`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `5677:gulfedefosportstlouisportnapoleonstgerva` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | France / `france-2` |
| Listing groupe | Mediterranean Coast (France) |
| `mrgid` / `zone_name` | 5677 / France |
| ZEE VLIZ | France — French Exclusive Economic Zone (`iso2`=FR, `pol_type`=200NM, souverain=France) |
| `country_iso2` graine | FR |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:38:44Z |
| `geocode_query` | `Gulfe de Fos (Port St Louis, Port Napoleon, St-Gervais)` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Gulfe de Fos (Port St Louis, Port Napoleon, St-Gervais) official port of entry OR clearance OR "puerto habilitado" France` |
| `seed_line` | `Gulfe de Fos (Port St Louis, Port Napoleon, St-Gervais) | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Gulfe de Fos (Port St Louis, Port Napoleon, St-Gervais)`, sans GPS |

**Lecture**



---

### 13. Christmas Island/Kiritimati

**Kiribati** · groupe listing `Line Islands` · `8488:christmasislandkiritimati`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8488:christmasislandkiritimati` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Kiribati / `kiribati` |
| Listing groupe | Line Islands |
| `mrgid` / `zone_name` | 8488 / Gilbert Islands |
| ZEE VLIZ | Gilbert Islands — Kiribati Exclusive Economic Zone (Gilbert Islands) (`iso2`=KI, `pol_type`=200NM, souverain=Kiribati) |
| `country_iso2` graine | KI |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:40:36Z |
| `geocode_query` | `Christmas Island/Kiritimati` |
| `spatial_kind` | `other_water` — point trouvé mais en mer hors de la ZEE assignée → rejeté |
| `distance_km` | 2529.9 |
| `geocode_agree` | None |
| `geocode_arbitration` | spatial_rejected |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Christmas Island/Kiritimati official port of entry OR clearance OR "puerto habilitado" Gilbert Islands` |
| `seed_line` | `Christmas Island/Kiritimati | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Christmas Island/Kiritimati`, sans GPS |

**Lecture**

Double piège : (1) « Christmas Island » = souvent l’île australienne, pas Kiritimati ; (2) la fiche est rangée en ZEE Gilbert Islands (8488) alors que Kiritimati est dans Line Group (mrgid 8441). Rejet `other_water` à 2529 km. Existe une graine `Christmas Island Port` unverified sans coords. Corriger la ZEE vers 8441 puis géocoder « Kiritimati » / London, Christmas Island.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| `poe_seed_ports` | Christmas Island Port | unverified / rejected | None, None |

---

### 14. Tyrell Bay & Hillsborough (Carriacou)

**Grenada** · `8419:tyrellbayhillsboroughcarriacou`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8419:tyrellbayhillsboroughcarriacou` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Grenada / `grenada` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 8419 / Grenada |
| ZEE VLIZ | Grenada — Grenadian Exclusive Economic Zone (`iso2`=GD, `pol_type`=200NM, souverain=Grenada) |
| `country_iso2` graine | GD |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:39:21Z |
| `geocode_query` | `Tyrell Bay & Hillsborough (Carriacou)` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Tyrell Bay & Hillsborough (Carriacou) official port of entry OR clearance OR "puerto habilitado" Grenada` |
| `seed_line` | `Tyrell Bay & Hillsborough (Carriacou) | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Tyrell Bay & Hillsborough (Carriacou)`, sans GPS |

**Lecture**

Deux baies Carriacou. v1 a `Port of Hillsborough` (12.4833, -61.4568). Tyrell Bay est un autre mouillage. Fusion Hillsborough + point Tyrell, ou scinder.

**Déjà en base (même ZEE, autre `dedup_key`)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Port of Hillsborough | carte affichée | 12.4833286, -61.4567557 |

---

### 15. Barbers Point Harbour (Ko Olina)

**Hawaii** · groupe listing `Oahu` · `8453:barberspointharbourkoolina`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8453:barberspointharbourkoolina` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Hawaii / `hawaii` |
| Listing groupe | Oahu |
| `mrgid` / `zone_name` | 8453 / Hawaii |
| ZEE VLIZ | Hawaii — United States Exclusive Economic Zone (Hawaii) (`iso2`=None, `pol_type`=200NM, souverain=United States) |
| `country_iso2` graine | *(null)* |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:39:33Z |
| `geocode_query` | `Barbers Point Harbour (Ko Olina)` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Barbers Point Harbour (Ko Olina) official port of entry OR clearance OR "puerto habilitado" Hawaii` |
| `seed_line` | `Barbers Point Harbour (Ko Olina) | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Barbers Point Harbour (Ko Olina)`, sans GPS |

**Lecture**

Hawaii (8453), iso2 null côté VLIZ (normal). Ko Olina / Barbers Point, Oahu. Pas de match v1. Honolulu est le sibling listing du groupe Oahu.

---

### 16. Andaman Islands

**India** · `8480:andamanislands`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8480:andamanislands` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | India / `india` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 8480 / India |
| ZEE VLIZ | India — Indian Exclusive Economic Zone (`iso2`=IN, `pol_type`=200NM, souverain=India) |
| `country_iso2` graine | IN |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:39:36Z |
| `geocode_query` | `Andaman Islands` |
| `spatial_kind` | `inland` — point trouvé mais trop à terre / hors exception fluviale → rejeté |
| `distance_km` | 697.8 |
| `geocode_agree` | False |
| `geocode_arbitration` | spatial_rejected |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Andaman Islands official port of entry OR clearance OR "puerto habilitado" India` |
| `seed_line` | `Andaman Islands | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Andaman Islands`, sans GPS |

**Lecture**

Ce n’est pas un port, c’est un archipel. Assigné à la ZEE Inde continentale (8480), alors que Port Blair v1 est en ZEE Andaman and Nicobar (8333) (11.6730, 92.7460). Rejet inland 698 km (mauvais polygone / toponyme trop large). Action : fusionner avec Port Blair ou recréer sur mrgid 8333.

**Déjà en base (autre ZEE)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Port of Port Blair (mrgid **8333**) | carte affichée | 11.6730477, 92.7460414 |

---

### 17. Bandar Bintan Telani (BBT) – Bintan Island

**Indonesia** · groupe listing `Western Indonesia - Bintan, Lingga, Riau and Anambas Islands` · `8492:bandarbintantelanibbtbintanisland`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8492:bandarbintantelanibbtbintanisland` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Indonesia / `indonesia` |
| Listing groupe | Western Indonesia - Bintan, Lingga, Riau and Anambas Islands |
| `mrgid` / `zone_name` | 8492 / Indonesia |
| ZEE VLIZ | Indonesia — Indonesian Exclusive Economic Zone (`iso2`=ID, `pol_type`=200NM, souverain=Indonesia) |
| `country_iso2` graine | ID |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:40:00Z |
| `geocode_query` | `Bandar Bintan Telani (BBT) – Bintan Island` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Bandar Bintan Telani (BBT) – Bintan Island official port of entry OR clearance OR "puerto habilitado" Indonesia` |
| `seed_line` | `Bandar Bintan Telani (BBT) – Bintan Island | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Bandar Bintan Telani (BBT) – Bintan Island`, sans GPS |

**Lecture**

Graine `Bandar Bintan Telani` déjà `probable` (1.1605, 104.3202). `Tanjung Pinang (Bintan Island)` est `confirmed` mais avec lat **-3.36** (Bintan est ~1,2°N : point suspect). Fusionner avec Bandar Bintan Telani.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| `poe_seed_ports` | Bandar Bintan Telani | probable | 1.1605006, 104.3201677 |
| `poe_seed_ports` | Tanjung Pinang (Bintan Island, Riau Islands) | confirmed / accepted | -3.3564491, 104.6571166 |

**Autres noms listing proches (à traiter avec prudence)** : `Tanjung Pinang (Bintan Island, Riau Islands)` (Indonesia).

---

### 18. Bowden Harbour/Port Morant

**Jamaica** · `8459:bowdenharbourportmorant`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8459:bowdenharbourportmorant` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Jamaica / `jamaica` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 8459 / Jamaica |
| ZEE VLIZ | Jamaica — Jamaican Exclusive Economic Zone (`iso2`=JM, `pol_type`=200NM, souverain=Jamaica) |
| `country_iso2` graine | JM |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:40:14Z |
| `geocode_query` | `Bowden Harbour/Port Morant` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Bowden Harbour/Port Morant official port of entry OR clearance OR "puerto habilitado" Jamaica` |
| `seed_line` | `Bowden Harbour/Port Morant | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Bowden Harbour/Port Morant`, sans GPS |

**Lecture**

Nom composé Jamaïque. Pas de v1. Port Morant / Bowden, côte est. Scinder ou un point.

---

### 19. Khuludhufushi

**Maldives** · groupe listing `Upper North Province` · `8345:khuludhufushi`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8345:khuludhufushi` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Maldives / `maldives` |
| Listing groupe | Upper North Province |
| `mrgid` / `zone_name` | 8345 / Maldives |
| ZEE VLIZ | Maldives — Maldivian Exclusive Economic Zone (`iso2`=MV, `pol_type`=200NM, souverain=Maldives) |
| `country_iso2` graine | MV |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:40:56Z |
| `geocode_query` | `Khuludhufushi` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Khuludhufushi official port of entry OR clearance OR "puerto habilitado" Maldives` |
| `seed_line` | `Khuludhufushi | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Khuludhufushi`, sans GPS |

**Lecture**

Très probablement faute pour Khulhudhuffushi (Haa Dhaalu, Maldives). Aucun match. Corriger l’orthographe avant géocode.

---

### 20. Puerto Vallarta/ Banderas Bay

**Mexico** · groupe listing `West Coast (Mexico)` · `8429:puertovallartabanderasbay`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8429:puertovallartabanderasbay` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Mexico / `mexico` |
| Listing groupe | West Coast (Mexico) |
| `mrgid` / `zone_name` | 8429 / Mexico |
| ZEE VLIZ | Mexico — Mexican Exclusive Economic Zone (`iso2`=MX, `pol_type`=200NM, souverain=Mexico) |
| `country_iso2` graine | MX |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:41:18Z |
| `geocode_query` | `Puerto Vallarta/ Banderas Bay` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Puerto Vallarta/ Banderas Bay official port of entry OR clearance OR "puerto habilitado" Mexico` |
| `seed_line` | `Puerto Vallarta/ Banderas Bay | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Puerto Vallarta/ Banderas Bay`, sans GPS |

**Lecture**

v1 + graine `probable` `Puerto Vallarta` (20.6561, -105.2435). Banderas Bay est la baie, pas un second PoE. Fusion.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Puerto Vallarta | carte affichée | 20.6561446, -105.243527 |
| `poe_seed_ports` | Puerto Vallarta | probable | 20.6561446, -105.243527 |

---

### 21. Colonia, Yap Island

**Federated States of Micronesia** · groupe listing `Yap State` · `8316:coloniayapisland`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8316:coloniayapisland` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Federated States of Micronesia / `federated-states-of-micronesia` |
| Listing groupe | Yap State |
| `mrgid` / `zone_name` | 8316 / Micronesia |
| ZEE VLIZ | Micronesia — Micronesian Exclusive Economic Zone (`iso2`=FM, `pol_type`=200NM, souverain=Micronesia) |
| `country_iso2` graine | FM |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:38:40Z |
| `geocode_query` | `Colonia, Yap Island` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Colonia, Yap Island official port of entry OR clearance OR "puerto habilitado" Micronesia` |
| `seed_line` | `Colonia, Yap Island | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Colonia, Yap Island`, sans GPS |

**Lecture**

Colonia (Yap). Pas de v1. Attention à ne pas fusionner avec Colonia del Sacramento (Uruguay) présent en v1.

---

### 22. Lele/Leluh Harbour

**Federated States of Micronesia** · groupe listing `Kosrae` · `8316:leleleluhharbour`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8316:leleleluhharbour` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Federated States of Micronesia / `federated-states-of-micronesia` |
| Listing groupe | Kosrae |
| `mrgid` / `zone_name` | 8316 / Micronesia |
| ZEE VLIZ | Micronesia — Micronesian Exclusive Economic Zone (`iso2`=FM, `pol_type`=200NM, souverain=Micronesia) |
| `country_iso2` graine | FM |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:38:38Z |
| `geocode_query` | `Lele/Leluh Harbour` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Lele/Leluh Harbour official port of entry OR clearance OR "puerto habilitado" Micronesia` |
| `seed_line` | `Lele/Leluh Harbour | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Lele/Leluh Harbour`, sans GPS |

**Lecture**



---

### 23. Tanapag Harbour (Saipan)

**Northern Marianas** · `48980:tanapagharboursaipan`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `48980:tanapagharboursaipan` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Northern Marianas / `northern-marianas` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 48980 / Northern Mariana Islands |
| ZEE VLIZ | Northern Mariana Islands — United States Exclusive Economic Zone (Northern Mariana Islands) (`iso2`=MP, `pol_type`=200NM, souverain=United States) |
| `country_iso2` graine | MP |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:41:49Z |
| `geocode_query` | `Tanapag Harbour (Saipan)` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Tanapag Harbour (Saipan) official port of entry OR clearance OR "puerto habilitado" Northern Mariana Islands` |
| `seed_line` | `Tanapag Harbour (Saipan) | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Tanapag Harbour (Saipan)`, sans GPS |

**Lecture**

Graine `Saipan` déjà `probable` (15.1685). Tanapag est le port commercial de Saipan. Fusion ou point plus précis sur le quai Tanapag.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| `poe_seed_ports` | Saipan | probable / accepted | 15.16847, 145.74081 |

---

### 24. Longyearbyen

**Norway** · groupe listing `Svalbard (Spitsbergen)` · `5686:longyearbyen`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `5686:longyearbyen` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Norway / `norway` |
| Listing groupe | Svalbard (Spitsbergen) |
| `mrgid` / `zone_name` | 5686 / Norway |
| ZEE VLIZ | Norway — Norwegian Exclusive Economic Zone (`iso2`=NO, `pol_type`=200NM, souverain=Norway) |
| `country_iso2` graine | NO |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:41:47Z |
| `geocode_query` | `Longyearbyen` |
| `spatial_kind` | `inland` — point trouvé mais trop à terre / hors exception fluviale → rejeté |
| `distance_km` | 520.2 |
| `geocode_agree` | True |
| `geocode_arbitration` | spatial_rejected |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Longyearbyen official port of entry OR clearance OR "puerto habilitado" Norway` |
| `seed_line` | `Longyearbyen | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Longyearbyen`, sans GPS |

**Lecture**

Accord géocodeurs, mais rejeté `inland` à 520 km de la ZEE Norvège continentale (5686). Longyearbyen est au Svalbard : le polygone 200NM continental ne le couvre pas. Le listing groupe = Svalbard (Spitsbergen). Il manque une ZEE Svalbard dans l’assignation.

---

### 25. San Carlos - Vista Mar Marina

**Panama** · groupe listing `Pacific (Panama)` · `8423:sancarlosvistamarmarina`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8423:sancarlosvistamarmarina` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Panama / `panama` |
| Listing groupe | Pacific (Panama) |
| `mrgid` / `zone_name` | 8423 / Panama |
| ZEE VLIZ | Panama — Panamanian Exclusive Economic Zone (`iso2`=PA, `pol_type`=200NM, souverain=Panama) |
| `country_iso2` graine | PA |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:42:00Z |
| `geocode_query` | `San Carlos - Vista Mar Marina` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `San Carlos - Vista Mar Marina official port of entry OR clearance OR "puerto habilitado" Panama` |
| `seed_line` | `San Carlos - Vista Mar Marina | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `San Carlos - Vista Mar Marina`, sans GPS |

**Lecture**

Ne pas prendre les San Carlos mexicains v1 (Baja / Sonora). Ici : Pacific Panama. Vista Mar Marina, San Carlos (Panama Ouest).

**Autres noms listing proches (à traiter avec prudence)** : `San Carlos` (Mexico).

---

### 26. Prince Edward Island

**Marion & Prince Edward Island** · `8384:princeedwardisland`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8384:princeedwardisland` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Marion & Prince Edward Island / `marion-prince-edward-island` |
| Listing groupe | — |
| `mrgid` / `zone_name` | 8384 / Prince Edward Islands |
| ZEE VLIZ | Prince Edward Islands — South African Exclusive Economic Zone (Prince Edward Islands) (`iso2`=None, `pol_type`=200NM, souverain=South Africa) |
| `country_iso2` graine | *(null)* |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:40:55Z |
| `geocode_query` | `Prince Edward Island` |
| `spatial_kind` | `inland` — point trouvé mais trop à terre / hors exception fluviale → rejeté |
| `distance_km` | 13906.6 |
| `geocode_agree` | False |
| `geocode_arbitration` | spatial_rejected |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Prince Edward Island official port of entry OR clearance OR "puerto habilitado" Prince Edward Islands` |
| `seed_line` | `Prince Edward Island | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Prince Edward Island`, sans GPS |

**Lecture**

Homonyme violent : le listing « Marion & Prince Edward Island » est subantarctique sud-africain (mrgid 8384). Le géocodeur a visé l’Île-du-Prince-Édouard canadienne → inland 13 907 km. Il n’y a probablement pas de PoE plaisance là-bas ; Marion / Prince Edward sont des bases. Vérifier si le listing est pertinent.

---

### 27. Britannia Bay, Lovell

**St. Vincent & the Grenadines** · groupe listing `Mustique` · `8421:britanniabaylovell`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8421:britanniabaylovell` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | St. Vincent & the Grenadines / `st-vincent-the-grenadines` |
| Listing groupe | Mustique |
| `mrgid` / `zone_name` | 8421 / Saint Vincent and the Grenadines |
| ZEE VLIZ | Saint Vincent and the Grenadines — Saint Vincentian Exclusive Economic Zone (`iso2`=VC, `pol_type`=200NM, souverain=Saint Vincent and the Grenadines) |
| `country_iso2` graine | VC |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:42:46Z |
| `geocode_query` | `Britannia Bay, Lovell` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Britannia Bay, Lovell official port of entry OR clearance OR "puerto habilitado" Saint Vincent and the Grenadines` |
| `seed_line` | `Britannia Bay, Lovell | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Britannia Bay, Lovell`, sans GPS |

**Lecture**

Mustique (listing group). v1 a `Mustique` (12.8760, -61.1828). Britannia Bay / Lovell Village = le mouillage principal de Mustique. Fusion probable.

**Déjà en base (même ZEE)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Mustique | carte affichée | 12.8760094, -61.1828409 |

---

### 28. Lata, Ndendo Island (Santa Cruz Islands)

**Solomon Islands** · groupe listing `Outer Islands/Atolls (Solomon islands)` · `8314:latandendoislandsantacruzislands`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8314:latandendoislandsantacruzislands` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Solomon Islands / `solomon-islands` |
| Listing groupe | Outer Islands/Atolls (Solomon islands) |
| `mrgid` / `zone_name` | 8314 / Solomon Islands |
| ZEE VLIZ | Solomon Islands — Solomon Islands Exclusive Economic Zone (`iso2`=SB, `pol_type`=200NM, souverain=Solomon Islands) |
| `country_iso2` graine | SB |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:42:24Z |
| `geocode_query` | `Lata, Ndendo Island (Santa Cruz Islands)` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Lata, Ndendo Island (Santa Cruz Islands) official port of entry OR clearance OR "puerto habilitado" Solomon Islands` |
| `seed_line` | `Lata, Ndendo Island (Santa Cruz Islands) | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Lata, Ndendo Island (Santa Cruz Islands)`, sans GPS |

**Lecture**

v1 + graine `probable` `Lata` (-10.7244, 165.7982). Même île Ndendo. Fusion.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| `poe_seed_ports` | Lata | probable | -10.7244151, 165.7982204 |

**Autres noms listing proches (à traiter avec prudence)** : `Tanjung Pinang (Bintan Island, Riau Islands)` (Indonesia).

---

### 29. Ria de Vigo and Baiona

**Spain** · groupe listing `North West Spain` · `5693:riadevigoandbaiona`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `5693:riadevigoandbaiona` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | Spain / `spain` |
| Listing groupe | North West Spain |
| `mrgid` / `zone_name` | 5693 / Spain |
| ZEE VLIZ | Spain — Spanish Exclusive Economic Zone (`iso2`=ES, `pol_type`=200NM, souverain=Spain) |
| `country_iso2` graine | ES |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:42:31Z |
| `geocode_query` | `Ria de Vigo and Baiona` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Ria de Vigo and Baiona official port of entry OR clearance OR "puerto habilitado" Spain` |
| `seed_line` | `Ria de Vigo and Baiona | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Ria de Vigo and Baiona`, sans GPS |

**Lecture**

Ría (plan d’eau) + Baiona. Deux ports possibles : Vigo et Baiona. Nom composé → miss. Scinder.

---

### 30. Cowes & R. Medina (Isle of Wight)

**United Kingdom** · groupe listing `South Coast` · `5696:cowesrmedinaisleofwight`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `5696:cowesrmedinaisleofwight` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | United Kingdom / `united-kingdom` |
| Listing groupe | South Coast |
| `mrgid` / `zone_name` | 5696 / United Kingdom |
| ZEE VLIZ | United Kingdom — British Exclusive Economic Zone (`iso2`=GB, `pol_type`=200NM, souverain=United Kingdom) |
| `country_iso2` graine | GB |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:43:37Z |
| `geocode_query` | `Cowes & R. Medina (Isle of Wight)` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Cowes & R. Medina (Isle of Wight) official port of entry OR clearance OR "puerto habilitado" United Kingdom` |
| `seed_line` | `Cowes & R. Medina (Isle of Wight) | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Cowes & R. Medina (Isle of Wight)`, sans GPS |

**Lecture**

Cowes + Medina. Nom composé → miss. Pas de v1 Cowes. Siblings listing South Coast : Dover, Falmouth, Plymouth, Portsmouth, Southampton Water.

---

### 31. Oban/Dunstaffnage

**United Kingdom** · groupe listing `Scotland` · `5696:obandunstaffnage`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `5696:obandunstaffnage` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | United Kingdom / `united-kingdom` |
| Listing groupe | Scotland |
| `mrgid` / `zone_name` | 5696 / United Kingdom |
| ZEE VLIZ | United Kingdom — British Exclusive Economic Zone (`iso2`=GB, `pol_type`=200NM, souverain=United Kingdom) |
| `country_iso2` graine | GB |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:43:36Z |
| `geocode_query` | `Oban/Dunstaffnage` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Oban/Dunstaffnage official port of entry OR clearance OR "puerto habilitado" United Kingdom` |
| `seed_line` | `Oban/Dunstaffnage | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Oban/Dunstaffnage`, sans GPS |

**Lecture**

Deux sites Écosse (Oban et marina Dunstaffnage). Nom composé → miss. Scinder ou Oban.

---

### 32. Ketchikan

**USA** · groupe listing `USA - Alaska` · `8456:ketchikan`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8456:ketchikan` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | USA / `usa` |
| Listing groupe | USA - Alaska |
| `mrgid` / `zone_name` | 8456 / United States |
| ZEE VLIZ | United States — United States Exclusive Economic Zone (`iso2`=US, `pol_type`=200NM, souverain=United States) |
| `country_iso2` graine | US |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:44:19Z |
| `geocode_query` | `Ketchikan` |
| `spatial_kind` | `inland` — point trouvé mais trop à terre / hors exception fluviale → rejeté |
| `distance_km` | 919.9 |
| `geocode_agree` | True |
| `geocode_arbitration` | spatial_rejected |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Ketchikan official port of entry OR clearance OR "puerto habilitado" United States` |
| `seed_line` | `Ketchikan | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Ketchikan`, sans GPS |

**Lecture**

Triple problème : (1) listing USA group Alaska mais mrgid 8456 = ZEE United States (côte ouest continentale), pas Alaska 8463 ; (2) géocode OK mais inland 920 km hors polygone 8456 ; (3) le lieu existe déjà en v1 et `probable` comme `Ketchikan Small Boat Harbor` (55.3431, -131.6467) sur mrgid 8463. Une autre fiche `Ketchikan, Alaska` (8456) a été jugée `rejected`. Action : fusionner vers 8463, ne pas republier 8456.

**Déjà en base (même ZEE ou nom proche)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| `poe_seed_ports` | Ketchikan, Alaska (mrgid **8456**) | unverified / rejected | None, None |
| v1 `poe_ports` | Ketchikan Small Boat Harbor (mrgid **8463** Alaska) | carte affichée | 55.3430696, -131.6466819 |
| `poe_seed_ports` | Ketchikan Small Boat Harbor (mrgid **8463**) | probable | 55.3430696, -131.6466819 |

---

### 33. Unalaska/Port of Dutch Harbor

**USA** · groupe listing `USA - Alaska` · `8456:unalaskaportofdutchharbor`

| Champ | Valeur |
|---|---|
| `dedup_key` / `_id` | `8456:unalaskaportofdutchharbor` |
| `verify_verdict` | name_only |
| `listing_role` | `poe` (listing `is_port_of_entry: true`) |
| Listing pays / slug | USA / `usa` |
| Listing groupe | USA - Alaska |
| `mrgid` / `zone_name` | 8456 / United States |
| ZEE VLIZ | United States — United States Exclusive Economic Zone (`iso2`=US, `pol_type`=200NM, souverain=United States) |
| `country_iso2` graine | US |
| `seed_sources` | `listing` |
| `has_coords` / lat,lon | False / None, None |
| `validated` | False |
| Géocode le | 2026-09-06T09:44:25Z |
| `geocode_query` | `Unalaska/Port of Dutch Harbor` |
| `spatial_kind` | `miss` — aucun point Nominatim/GeoNames utilisable |
| `distance_km` | — |
| `geocode_agree` | None |
| `geocode_arbitration` | — |
| `geocode_source` | *(null, coords non persistées)* |
| `judge_status` | *(absent — pas jugé)* |
| `search_query` | `Unalaska/Port of Dutch Harbor official port of entry OR clearance OR "puerto habilitado" United States` |
| `seed_line` | `Unalaska/Port of Dutch Harbor | listing:poe · verdict:name_only` |
| `built_at` | 2026-09-06T09:29:28Z |
| OSM | aucun tag / id / customs / border / port_of_entry / kinds |
| `source_urls` | aucun |
| Observations | 1 × listing (`extraction_engine: listing`), nom `Unalaska/Port of Dutch Harbor`, sans GPS |

**Lecture**

Même erreur de ZEE (8456 au lieu de 8463). v1 + `probable` : `Dutch Harbor Small Boat Harbor` (53.8831, -166.5525) sur 8463. Fusion.

**Déjà en base (ZEE Alaska 8463)**

| Source | Nom | Verdict / juge | lat, lon |
|---|---|---|---|
| v1 `poe_ports` | Dutch Harbor Small Boat Harbor | carte affichée | 53.8831064, -166.552545 |
| `poe_seed_ports` | Dutch Harbor Small Boat Harbor | probable | 53.8831064, -166.552545 |

---

## Comment corriger sans casser l’inventaire

1. Pour une fusion : noter le `dedup_key` cible (v1/probable) et abandonner
   la fiche `name_only` — ou copier le GPS cible sur la fiche listing puis
   passer le verdict à `confirmed` si listing + extrait + coords.
2. Pour un GPS nouveau : écrire `lat` / `lon` / `has_coords: true` sur le
   document `poe_seed_ports`, **effacer `geocoded_at`** seulement si on
   veut que l’enrich regéocode (sinon poser le point à la main et juger).
3. Pour une ZEE fausse : changer `mrgid` **et** `dedup_key` (`{mrgid}:{nom
   normalisé}`), sinon collision. Les overrides utiles :
   - Alaska → `8463`
   - Hawaii → `8453` (déjà)
   - Line Group / Kiritimati → `8441`
   - Andaman → `8333`
4. Ensuite seulement : `POST /api/poe/seeds/enrich` avec
   `verdicts: ["name_only"]` **après** avoir retiré `geocoded_at` des
   fiches à retenter — ou juger à la main (listing + GPS → `confirmed`
   sans Claude si un extrait v1/run/OSM est rattaché).
5. Interdit : `POST /api/poe/seeds/build` (delete+insert de toute la
   collection).

## Autres PoE listing du même groupe

Utile pour savoir si le listing parle d’une *région* ou d’un *port*.

| Fiche | Groupe | Autres PoE listing du groupe |
|---|---|---|
| Geelong | Victoria (Australia) | Hastings, Melbourne (Australia), Portland |
| Newcastle and Port Stephen | New South Wales | Coffs Harbour, Port Kembla / Shellharbour, Sydney |
| Port Kembla / Shellharbour | New South Wales | Coffs Harbour, Newcastle and Port Stephen, Sydney |
| Big Creek / Placencia | — | Belize City, Punta Gorda, San Pedro (Ambergris Cay) |
| West End/Sopers Hole | Tortola | Road Harbour |
| Grand Mannan Harbour | New Brunswick | Caraquet, Dalhousie, Saint John |
| Marigot Bay (St Martin) | — | Anse Marcel, Oyster Pond - St Martin |
| Oyster Pond - St Martin | — | Anse Marcel, Marigot Bay (St Martin) |
| Marina Los Morros | — | Cayo Coco-Guillermo, Cienfuegos, Hemingway Marina, Marina Cayo Largo, Puerto de Vita, Santiago de Cuba, Varadero |
| Cassis | Mediterranean Coast (France) | Antibes, Bandol, Cannes, Fos, Hyères, La Ciotat, Le Lavandou, Marseille, Menton, Nice, … |
| Gironde Estuary & Bordeaux | Atlantic (France) | Brest, Hendaye, La Rochelle, Les Sables d’Olonne, Lorient, Nantes, St Nazaire |
| Christmas Island/Kiritimati | Line Islands | *(seul PoE du groupe)* |
| Tyrell Bay & Hillsborough | — | Prickly Bay, St George's |
| Barbers Point Harbour (Ko Olina) | Oahu | Honolulu |
| Andaman Islands | — | Cochin, Madras, Mumbai, Panaji |
| Bandar Bintan Telani (BBT) | Western Indonesia – Bintan… | Tanjung Pinang, Tarempa |
| Bowden Harbour/Port Morant | — | Kingston, Montego Bay, Ocho Rios, Port Antonio |
| Khuludhufushi | Upper North Province | *(seul PoE du groupe)* |
| Puerto Vallarta/ Banderas Bay | West Coast (Mexico) | Acapulco, Cabo, Ensenada, Huatulco, La Paz, Mazatlan, … |
| Colonia, Yap Island | Yap State | Ulithi Atoll |
| Lele/Leluh Harbour | Kosrae | Okat Harbour |
| Tanapag Harbour (Saipan) | — | *(seul PoE du pays listing)* |
| Longyearbyen | Svalbard (Spitsbergen) | *(seul PoE du groupe)* |
| San Carlos - Vista Mar Marina | Pacific (Panama) | Balboa, Mensabe, Pedregal, Puerto Mutis |
| Prince Edward Island | — | *(seul PoE du pays listing)* |
| Britannia Bay, Lovell | Mustique | *(seul PoE du groupe)* |
| Lata, Ndendo Island | Outer Islands/Atolls | *(seul PoE du groupe)* |
| Ria de Vigo and Baiona | North West Spain | Aviles, Bilbao, Finisterre, Gijon, Hondarribia, La Coruna, Santander |
| Cowes & R. Medina | South Coast | Dover, Falmouth, Plymouth, Portsmouth, Southampton Water |
| Oban/Dunstaffnage | Scotland | Largs, Peterhead |
| Ketchikan | USA - Alaska | Anchorage, Juneau, Unalaska/Port of Dutch Harbor |
| Unalaska/Port of Dutch Harbor | USA - Alaska | Anchorage, Juneau, Ketchikan |

## Fichier machine

Export brut des 33 documents Mongo : [`data/poe-name-only-33.json`](data/poe-name-only-33.json)
(mêmes données, sans les rapprochements).

## Constantes de ce snapshot

- Inventaire : 4027 graines ; `name_only` restants : **33**
- `poe_ports` (carte v1 affichée) : **1280** — non modifié
- Crédit Claude du run : non consommé sur ces 33 (géocode seul)
