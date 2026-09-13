# Plan d’implémentation — Mode Climatologie (7ᵉ mode Blue Intelligence)

Document de cadrage et de chantier. Il consigne les décisions de septembre 2026 :
simulation de traversées par **climatologie historique**, pas par prévision GFS/IFS ;
inspiration du plugin OpenCPN `climatology_pi` (esprit et API, pas le code GPL) ;
**septième mode** sur Blue Intelligence ; données **invisibles mais partout** dans
NAVIGUIDE, avec fusion des cartes déjà existantes.

Écrit en langage simple : c’est le contrat de ce que l’on cherche, et de ce que
l’on refuse.

Version **1.0** — 13 septembre 2026.

**Sommaire**

1. En une phrase
2. Pourquoi ce travail existe
3. Ce que l’on veut obtenir
4. Ce que l’on ne veut pas
5. Vocabulaire
6. Partage Blue Intelligence / NAVIGUIDE
7. Inspiration OpenCPN (ce qu’on copie, ce qu’on refuse)
8. État actuel et écarts
9. Coquille commune (7ᵉ mode + API + panes)
10. Produit 1 — Vent 10 m et roses
11. Produit 2 — Houle P50 / P90
12. Produit 3 — Courant de surface
13. Produit 4 — Risque cyclone (IBTrACS)
14. Règles (`run_rules`)
15. Contrats JSON
16. Ordre de chantier
17. Fichiers touchés
18. Licences et attributions
19. Recette
20. Risques
21. Hors périmètre
22. Documents et conversations dont ce plan hérite

---

## 1. En une phrase

Donner au skipper un **atlas mensuel sourcé** (vent en roses, houle P50/P90,
courant, pistes cycloniques) pour **simuler des traversées** de la circumnavigation
Berry-Mappemonde, l’afficher comme **septième mode** de Blue Intelligence, et
s’en servir **sans le peindre** dans NAVIGUIDE.

---

## 2. Pourquoi ce travail existe

NAVIGUIDE est un SADP (système d’aide à la décision plaisancière), pas un ECDIS.
Une jambe de l’expédition dure souvent **plus longtemps que la prévisibilité**
d’un modèle (7 à 10 jours utiles, 15–16 jours en dégradé). Brancher un isochrone
sur le run GFS/IFS de 00 UTC, c’est donner l’illusion d’une arrivée au jour près.

La climatologie historique (moyennes, roses, percentiles, pistes) est l’outil
honnête pour « quel mois, quelle route, quelle durée plausible ». La prévision
reste un complément **tactique** (fenêtre de départ 0–10 jours), pas le moteur
de la simulation.

Le code actuel inverse déjà un peu les rôles, et mal :

- `getWind.py` lit un vent **L4 NRT** Copernicus avec ~48 h de retard (observation
  assimilée, pas une prévision) ;
- `getWave.py` / `getCurrent.py` interrogent des produits **analyse + 10 jours
  de prévision**, mais tronquent à `time=-1` d’hier ;
- le routage isochrone (port 3010, non déployé) appelle `climatology.py` : un
  **atlas dessiné à la main** (zones rectangulaires, un seul couple kn / °), pas
  une grille historique ;
- la simulation carte est encore **géométrique** (polaire + distance), sans vent ;
- Blue Intelligence n’a **aucune** couche météo.

---

## 3. Ce que l’on veut obtenir

Deux livrables, **même snapshot de données**, deux façons de le montrer.

### Blue Intelligence — 7ᵉ mode `climatology`

Un mode du même rang que Projets, Marinas, Capitaineries, Formalités, AMP,
Science : bouton d’en-tête, couleur propre, panneau, carte dédiée.

À l’intérieur du mode (filtres, comme Sextant / Argo en Science) :

| Filtre | Contenu |
|--------|---------|
| Vent | Roses 8 secteurs, % du temps, kn moyen, % calme, % gale, résumés MOST_LIKELY et AVERAGE |
| Houle | Hs P50 et Hs P90, période, direction ; overlay raster |
| Courant | Flèches vers où ça porte (moyenne mensuelle de surface) |
| Cyclones | Pistes IBTrACS du mois affiché |

Curseur **janvier–décembre**. Popups avec provenance (modèle / produit, période,
licence, `sample_count`). Bandeau « ne convient pas à la navigation ».

### NAVIGUIDE — invisibles mais partout

Les **mêmes** grilles alimentent isochrones, simulation, agent météo. Elles ne
sont **pas** une couche carte obligatoire. On fusionne les cartes déjà là
(route, simulation, clic Copernicus, pastilles BI, polar) en **une** MapLibre.
Climatologie, ZEE et WPI restent dans le moteur (requêtes, crossings, briefing)
et **n’ont pas besoin d’être allumés** sur la carte — on peut les retirer du
panneau de pastilles.

---

## 4. Ce que l’on ne veut pas

- Un overlay climatologie **sur tous les modes** BI (ce n’est pas un fond EMODnet).
- Un 8ᵉ interrupteur « Climatologie » dans NAVIGUIDE.
- Présenter une moyenne 1991–2020 comme « le vent de demain ».
- Fondre plusieurs modèles (`best_match`) **sans** écrire le nom du produit.
- Inventer un champ : `null` sur terre, sur pixel `NaN`, si l’échantillon est trop pauvre.
- Un LLM qui produit un vent, une Hs ou une « saison cyclone » sans chiffre.
- Recopier le C++ GPL d’OpenCPN (`climatology_pi`) ni le binaire `0xfeff`.
- Télécharger des cubes GRIB/NetCDF horaires mondiaux **sur le VPS** (4 vCores,
  8 Go RAM, ~35 Go libres après seamap).
- StormGlass, Windy, PredictWind, Meteomatics, OpenWeather comme source du mode.
- Remplacer `getWind` / `getWave` / `getCurrent` (NRT / forecast de départ) par
  la climatologie : **deux `kind` distincts**.

---

## 5. Vocabulaire

| Mot | Sens ici |
|-----|----------|
| **Climatologie** | Statistiques mensuelles sur une période nommée (ex. 1993–2019). `kind: "climatology"`. |
| **Prévision (NWP / IA)** | GFS, IFS, ICON, AIFS… horizon 7–16 jours. Hors livrable V1 du mode. |
| **Analyse / NRT** | Produit Copernicus L4 vent actuel de NAVIGUIDE. Observation récente, pas l’atlas. |
| **Réanalyse** | ERA5, WAVERYS, GLORYS12 : passé homogène, source des grilles. |
| **Rose / atlas** | 8 secteurs : % du temps, kn moyen, % ≤ 3 kn (calme), % ≥ 34 kn (gale). |
| **MOST_LIKELY** | Secteur dominant de la rose (recommandé OpenCPN pour le routage). |
| **AVERAGE** | Moyenne vectorielle u/v (souvent plus faible que le kn scalaire). |
| **P50 / P90** | Percentiles de Hs : « typique » vs « 1 année sur 10 au-dessus ». Le no-go utilise le P90. |
| **Snapshot** | Fichiers précalculés **hors VPS**, versionnés (`metadata` + sha256), seulement **servis** en prod. |

---

## 6. Partage Blue Intelligence / NAVIGUIDE

```
                    snapshot climatologie (hors ligne)
                    vent-roses · houle P50/P90 · courant · IBTrACS
                                    │
                 ┌──────────────────┴──────────────────┐
                 ▼                                     ▼
     Blue Intelligence                          NAVIGUIDE
     7ᵉ mode `climatology`                      moteur, pas la peinture
     Header + panneau + carte                   isochrones, simulation,
     roses / raster / flèches / pistes          agent météo, crossings
                 │                                     │
                 │                          carte unique fusionnée
                 │                          (route, simu, clic Copernicus,
                 │                           pastilles BI utiles)
                 │                          ZEE / WPI / atlas : dans le
                 │                          code, pas forcément à l’écran
```

Phrase de partage : **BI montre l’atlas. NAVIGUIDE s’en sert.**

---

## 7. Inspiration OpenCPN (ce qu’on copie, ce qu’on refuse)

Dépôts : [rgleason/climatology_pi](https://github.com/rgleason/climatology_pi)
(maintenance), [seandepagnier/climatology_pi](https://github.com/seandepagnier/climatology_pi),
données [climatology_pi_data](https://github.com/seandepagnier/climatology_pi_data).
Manuel : [opencpn-manuals…/climatology](https://opencpn-manuals.github.io/plugins/climatology/index.html).
Licence **GPL v3** — on relit pour comprendre, on **réécrit**.

OpenCPN fait déjà le produit vent / courant / cyclone : moyennes ~30 ans
compressées (~7 Mo), curseur de mois, roses (barbules = 5 kn, centre bleu =
calme, rouge = gale), flèches de courant, pistes par bassin, et trois callbacks
pour `weather_routing_pi` (`ClimatologyData`, `ClimatologyWindAtlasData`,
`CycloneTrackCrossings`). Modes AVERAGE / MOST_LIKELY / CUMULATIVE_MAP.
**La houle n’est pas livrée** (« swell and seastate not yet implemented »).

| On copie | On refuse |
|----------|-----------|
| Rose plutôt qu’une flèche unique | Format binaire `wind01.gz` / magic `0xfeff` |
| Calme ≤ 3 kn, gale ≥ 34 kn | Code C++ GPL |
| MOST_LIKELY vs AVERAGE | Pistes Unisys (on prend IBTrACS) |
| `CycloneTrackCrossings` | Jeter les courants &lt; 0,2 sans le nommer |
| Snapshot compressé, pas un cube live | Traiter 180 Go sur le VPS |
| Interpolation entre deux mois | Nuages, foudre, humidité, bathymétrie WOA (Science / EMODnet s’en chargent) |
| Avertissement « grain of salt » | Moyenne El Niño silencieuse sans période écrite |

---

## 8. État actuel et écarts

| Endroit | Aujourd’hui | Cible |
|---------|-------------|-------|
| `frontend/src/App.js` + `Header.js` | 6 modes | 7ᵉ `climatology` |
| `layerOrder.js` | `basemap-gl`, `route`, `amp`, `formalities-escales` | + panes raster/vector climatologie, **allumés seulement** si `mode === "climatology"` |
| `getWind.py` | L4 NRT, `now-2j`, `time=-1` | Inchangé pour le clic « récemment observé » |
| `getWave.py` / `getCurrent.py` | ANFC, dernier pas d’hier | Inchangé pour le départ 0–10 j ; simulation = snapshot climo |
| `climatology.py` | Zones dessinées | Repli si la grille manque ; plus jamais la source |
| `isochrone.py` | `wind_at(lat, lon, month)` unique | MOST_LIKELY + courant + no-go P90 + crossings |
| `SimulationPanel.jsx` | Géométrie seule | Consomme le mois de la jambe, **sans** dessiner l’atlas |
| `MaritimeLayers.jsx` | Pastilles ZEE, WPI, balisage, 5 exports BI | Une carte fusionnée ; ZEE / WPI / climo hors UI si inutile |
| Agent `meteo_agent.py` | StormGlass optionnel + LLM | Compte IBTrACS du mois sur la jambe |

---

## 9. Coquille commune (7ᵉ mode + API + panes)

À poser **avant** les quatre produits. Sans elle, chaque produit réinvente
l’en-tête et le metadata.

| Tâche | Fichiers | Détail |
|-------|----------|--------|
| C0. Mode | `App.js`, `Header.js`, `i18n.js`, `README.md`, `CONTRATS_MODES.md` | `mode === "climatology"`. Couleur propre (ni violet Science, ni cyan Projets). `data-testid="mode-toggle-climatology"`. Commentaire header : plus « Six-mode switch ». |
| C1. Panes | `layerOrder.js` + `layerOrder.test.js` | `climatology-raster@250`, `climatology-vector@260`, `pointer-events: none`. Le test fige la liste. Allumage seulement dans le 7ᵉ mode. |
| C2. HTTP | `backend/app/routers/climatology.py` | `GET /api/climatology/meta` ; `GET /api/climatology/point?lat=&lon=&month=` ; `GET /api/climatology/{wind\|wave\|current\|cyclones}.geojson?month=`. Tout champ `kind: "climatology"`. `null` sur terre. |
| C3. Metadata | `app/core/export_meta.py` | `version`, `content_sha256`, `license`, `disclaimer` / `disclaimer_fr`, plus `period`, `month`, `source_ids`, `doi`. |
| C4. Panneau | `ClimatologyPanel.js` | Curseur 1–12, filtres Vent / Houle / Courant / Cyclones, légende, attribution. Éteints au premier affichage (sauf éventuellement le vent, à trancher à l’implémentation). |
| C5. Carte | `useClimatologyLayer.js` + branche `MapView.js` | Comme `useScienceLayer` : uniquement si `mode === "climatology"`. |
| C6. Règles | `run_rules.json` famille `climatology.*` | Voir §14. Loi = pas de prévision déguisée, pas de LLM. |
| C7. Snapshot | `backend/data/climatology/` + export snapshot | Généré **hors VPS** (Mac). Le serveur sert les fichiers. |
| C8. Review | — | **Pas** de Review / Gold / `RunSelector` en V1 (comme Science : moisson ou snapshot, pas un run Gold). |

Critère de sortie C : le 7ᵉ bouton change la carte et le panneau ; `meta` + `point`
renvoient `kind`, `month`, `period`, licence ; panes verts au test ; les six
autres modes n’affichent aucune rose.

### NAVIGUIDE — fusion de carte (même coquille)

| Tâche | Fichiers | Détail |
|-------|----------|--------|
| N1 | `climatology_query` côté `naviguide-api` ou lecture des snapshots BI | Point / crossings **sans** Source MapLibre climatologie |
| N2 | `MaritimeLayers.jsx`, `Sidebar.jsx` | Une carte ; retirer de l’UI les pastilles ZEE, WPI, climatologie (données toujours fetchables) |
| N3 | `isochrone.py`, `SimulationPanel` / `useLegContext` | Consomment le mois ; pas de calque atlas |
| N4 | `meteo_agent.py` | Chiffre IBTrACS, pas un texte de saison inventé |

---

## 10. Produit 1 — Vent 10 m et roses

### En une phrase

Pour chaque mois, une **rose** (8 secteurs, % du temps, kn moyen, % calme,
% gale) et deux résumés (MOST_LIKELY, AVERAGE).

### Source

Une moyenne mensuelle (ERA5 monthly CDS, ou
`WIND_GLO_PHY_CLIMATE_L4_MY_012_003`) ne donne **que des flèches**. OpenCPN
construit l’atlas depuis SeaWinds **6 h**.

On reste sur Copernicus (compte déjà dans `COPERNICUS_USERNAME`) :

| Produit | Dataset | Rôle |
|---------|---------|------|
| NRT (code actuel) | `cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H` | Clic « récemment observé » — hors ce produit |
| MY horaire | `cmems_obs-wind_glo_phy_my_l4_0.25deg_PT1H` | **Source des roses** (u/v 10 m, 1994 → mois-3) |
| Climatologie mensuelle | `WIND_GLO_PHY_CLIMATE_L4_MY_012_003` | Filet flèches AVERAGE seulement (V0) |

PUM : [CMEMS-WIND-PUM-012-004-006](https://documentation.marine.copernicus.eu/PUM/CMEMS-WIND-PUM-012-004-006.pdf).

Direction : `atan2(-u, -v)` (d’où vient le vent), déjà dans `getWind.py`.
Maille stockée : 0,5°. Période cible : `1994-01..2020-12`.

### Phases

**A — Pipeline hors ligne (Mac)**

| Tâche | Fichiers | Détail |
|-------|----------|--------|
| A1 | `scripts/climatology/gen_wind_atlas.py` | `copernicusmarine.subset` MY 0,25°, un mois calendaire × années 1994–2020, **sous-échantillon 6 h**. kn = m/s × 1,94384. |
| A2 | même script | 8 secteurs, calme/gale, option bins 10 kn. Secteur &lt; 2,5 % → 0. Cellule trop peu échantillonnée → `null`. |
| A3 | `backend/data/climatology/wind/wind-MM.npz` + `.atlas.json` | 12 fichiers documentés. Pas le binaire GPL. |
| A4 | `gen_wind_mean.py` (optionnel) | Flèches AVERAGE depuis le produit climate — V0 visible, pas le livrable rose. |

Critère A : 15°N, 25°W, mars : rose NE dominante ; calme/gale ∈ [0, 100] ;
`sample_count` &gt; 0 en mer ; `null` sur le Sahara.

**B — API** — `climatology_wind.py` : `atlas_at(lat, lon, month)`, interpolation
bilinéaire + entre mois. `point` remplit `wind_atlas`. GeoJSON : 1° au large,
0,5° si demandé.

**C — Carte BI** — `useClimatologyWind.js` : roses sur le pane vectoriel
(longueur = %, barbules = 5 kn, centre bleu/rouge). Popup : MOST_LIKELY **et**
AVERAGE, période, `sample_count`. Jamais « vent prévu ».

**D — NAVIGUIDE** — `wind_at` lit l’atlas (`most_likely` par défaut). Lookup
zones = repli. `isochrone.py` : `mode=most_likely\|average` consigné dans la route.

---

## 11. Produit 2 — Houle P50 / P90

### En une phrase

Deux champs mensuels Hs P50 et Hs P90 + période et direction : overlay du
mode, no-go des isochrones. OpenCPN ne l’a jamais livré.

### Source

[GLOBAL_MULTIYEAR_WAV_001_032](https://data.marine.copernicus.eu/product/GLOBAL_MULTIYEAR_WAV_001_032/description)
(WAVERYS / MFWAM, 0,2°). PUM : [CMEMS-GLO-PUM-001-032](https://documentation.marine.copernicus.eu/PUM/CMEMS-GLO-PUM-001-032.pdf).

| Dataset | Contenu | Suffit pour P90 ? |
|---------|---------|-------------------|
| `cmems_mod_glo_wav_my_0.2deg-climatology_P1M-m` | **Moyenne** 1993–04/2019 de `VHM0`, `VTM02` | Non |
| `cmems_mod_glo_wav_my_0.2deg_PT3H-i` | Instantané 3 h + partitions | **Oui** — percentiles hors ligne |

Variables : `VHM0`, `VTM02`, `VMDR`, `VHM0_SW1` / `VMDR_SW1` (mêmes noms que
`getWave.py`, autre produit). Interdit d’étiqueter une moyenne « P90 ».

### Phases

**A0** — `gen_wave_mean.py` : dataset climatology_P1M-m, overlay V0 `stat: mean`.
**A1** — `gen_wave_pct.py` : pour chaque mois, PT3H toutes années, `nanpercentile`
50 et 90, `circmedian` pour `VMDR`. Un mois à la fois, jamais le cube mondial en RAM.
**A2** — `wave-MM.npz` : `hs_p50`, `hs_p90`, `period`, `dir`, masque mer.

Critère A : 40°S en juillet, `hs_p90` &gt; `hs_p50` &gt; 0 ; Andes = null.

**B / C** — API + raster du mode (boutons P50 / P90). Popup : « 1 année sur 10,
Hs &gt; X m ce mois-ci (période 1993–2019) ».

**D** — `is_wave_hazard` si `hs_p90 > climatology.wave_nogo_m` (défaut 2,5 m,
déjà dans `overWave`). `getWave.py` inchangé (forecast de départ).

---

## 12. Produit 3 — Courant de surface

### En une phrase

Douze champs mensuels u/v de surface (moyenne 1993–2016), flèches vers où
ça porte, dérive au calme et correction d’isochrone.

### Source (la plus simple)

[GLOBAL_MULTIYEAR_PHY_001_030](https://data.marine.copernicus.eu/product/GLOBAL_MULTIYEAR_PHY_001_030/description)
(GLORYS12). PUM : [CMEMS-GLO-PUM-001-030](https://documentation.marine.copernicus.eu/PUM/CMEMS-GLO-PUM-001-030.pdf).

Dataset déjà climatologique :
`cmems_mod_glo_phy_my_0.083deg-climatology_P1M-m`

12 moyennes 1993–2016, `uo` / `vo` / `thetao`, premier niveau `depth ≈ 0,494 m`
(`minimum_depth=0.5`, `maximum_depth=1.0`, comme `getCurrent.py`).

Ne pas confondre avec `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m` (forecast clic).

Convention : `atan2(u, v)` — **vers où** ça porte. Seuil bas documenté
(`climatology.current_min_kn`) : en dessous, vecteur 0 **et** flag
`below_threshold`, pas un null silencieux.

### Phases

**A** — `gen_current.py` : un subset surface, 12 pas. Option : 0,25° pour la
carte, 1/12° pour le point.

Critère A : 26°N, 80°W (Gulf Stream, février) &gt; 1 kn vers le NE ; Sahara = null.

**B / C** — flèches sur le pane vectoriel du **mode** BI, cumulables avec les roses.

**D** — après `move_position` au vent, ajouter `current × time_step_h` dans
`isochrone.py`. `getCurrent.py` inchangé.

---

## 13. Produit 4 — Risque cyclone (IBTrACS)

### En une phrase

Pistes historiques **since 1980**, filtrées par mois, plus `crossings` pour
interdire une jambe d’isochrone. Saison **chiffrée**.

### Source

[IBTrACS v04r01](https://www.ncei.noaa.gov/products/international-best-track-archive),
CSV `ibtracs.since1980.list.v04r01.csv`.
[Colonnes](https://www.ncei.noaa.gov/sites/default/files/2025-09/IBTrACS_v04r01_column_documentation.pdf).
Licence : redistribution sans restriction (ERDDAP).

Colonnes : `SID`, `SEASON`, `BASIN` (NA, EP, WP, NI, SI, SP, SA), `ISO_TIME`,
`LAT`, `LON`, `TRACK_TYPE`, `USA_STATUS`, `USA_WIND` (kn, 1 min), `USA_PRES`,
`WMO_WIND` (10 min selon bassin — **documenter le mélange** : `USA_WIND` sinon
`WMO_WIND`, champ `wind_source`).

Filtre : `TRACK_TYPE == main` (pas `spur`). Antiméridien : couper les LineString
WP/SP qui franchissent 180°.

API routage (esprit OpenCPN) :

`crossings(lat1, lon1, lat2, lon2, month, dayrange) → { count, storms[] }`

### Phases

**A** — `gen_cyclones.py` : un GeoJSON + index `{month: [sid…]}`.
Critère A : septembre NA plein ; février NA vide ; SP janvier–mars plein.

**B / C** — traces dans le mode BI, couleur par `max_wind_kn`. Clic : SID, année,
kn max, lien NCEI.

**D** — isochrone : si `climatology.avoid_cyclone_tracks`, jeter le pas si
`crossings > 0`. Agent météo : entier du mois sur la jambe.

---

## 14. Règles (`run_rules`)

Un chiffre n’est pas une opinion (`docs/REGLES_PARAMETRES.md`). Famille
`climatology.*`.

| Id | Famille | Défaut | Intervalle | Phénomène |
|----|---------|--------|------------|-----------|
| `climatology.wind_calm_kn` | géométrie | 3 | 2–4 | Calme Beaufort 0–1 (OpenCPN) |
| `climatology.wind_gale_kn` | géométrie | 34 | 34–41 | Gale Beaufort 8 |
| `climatology.wind_sectors` | loi | 8 | — | Rose 45° |
| `climatology.wind_min_sector_pct` | géométrie | 2.5 | 1–5 | Bruit de secteur |
| `climatology.wind_grid_deg` | budget | 0.5 | 0.25–1 | Maille atlas |
| `climatology.wave_nogo_m` | géométrie | 2.5 | 2.0–4.0 | Seuil `overWave` |
| `climatology.wave_stat` | loi | P90 = no-go, P50 = « typique » | — | Interdit de labeller une moyenne P90 |
| `climatology.wave_period` | loi | `1993-2019` | — | Fenêtre WAVERYS climo ; A1 peut l’étendre si documenté |
| `climatology.current_min_kn` | géométrie | 0.15 | 0.05–0.30 | Bruit vs dérive utile |
| `climatology.current_depth_m` | loi | 0.5 | — | Premier niveau GLORYS |
| `climatology.current_period` | loi | `1993-2016` | — | Dataset climatology PUM |
| `climatology.cyclone_first_year` | loi | 1980 | — | Fichier since1980 |
| `climatology.cyclone_dayrange` | géométrie | 21 | 7–45 | Fenêtre autour du jour de route |
| `climatology.cyclone_radius_nm` | géométrie | 120 | 60–200 | Compteur popup « proche de la jambe » |
| `climatology.cyclone_min_kn` | géométrie | 34 | 34–64 | Afficher au moins tempête tropicale |
| `climatology.avoid_cyclone_tracks` | loi | true en simulation | — | Contrainte isochrone |

Loi non surchargeable : `kind` climatologie ≠ prévision ; pas de LLM pour un
vent / une Hs / un compteur cyclone.

---

## 15. Contrats JSON

### Point d’interrogation

```json
{
  "kind": "climatology",
  "month": 3,
  "period": "1991-2020",
  "provenance": {
    "wind": "CMEMS WIND MY L4 0.25°",
    "wave": "WAVERYS GLOBAL_MULTIYEAR_WAV_001_032",
    "current": "GLORYS12 GLOBAL_MULTIYEAR_PHY_001_030 climatology_P1M-m",
    "cyclone": "IBTrACS v04r01 since1980"
  },
  "coordinates": { "latitude": 15.24, "longitude": -42.85, "cell_selection": "sea" },
  "wind_atlas": {
    "sectors_deg": 45,
    "directions_from": [
      { "dir_deg": 45, "pct": 41, "speed_knots": 16.2 },
      { "dir_deg": 90, "pct": 22, "speed_knots": 14.0 }
    ],
    "calm_pct": 8,
    "gale_pct": 3,
    "most_likely": { "dir_deg": 45, "speed_knots": 16.2 },
    "vector_mean": { "dir_deg": 58, "speed_knots": 12.1 },
    "sample_count": 1840
  },
  "wave": {
    "hs_p50_m": 1.8,
    "hs_p90_m": 3.1,
    "period_s": 8.4,
    "dir_deg": 70
  },
  "current": {
    "speed_knots": 0.4,
    "direction_to_deg": 280
  },
  "cyclone": {
    "tracks_in_month": 12,
    "crossings_if_leg": null
  }
}
```

Sur terre : `wind_atlas`, `wave`, `current` à `null` (structure conservée).

`most_likely` et `vector_mean` restent **tous les deux** visibles : la moyenne
vectorielle est le piège des pilot charts.

### GeoJSON vent (grille du mode)

`FeatureCollection` + `metadata` (`export_meta`) : `model` / produit, `month`,
`period`, `grid_spacing_deg`, licence. Points : `wind_speed_knots` du
MOST_LIKELY, `wind_direction_from_deg`, `calm_pct`, `gale_pct`.

---

## 16. Ordre de chantier

```
C0–C8  7ᵉ mode + API vide + panes + panneau
   ├─ 4  Cyclones     (CSV, le plus court à voir sur la carte)
   ├─ 3  Courant      (12 NetCDF surface)
   ├─ 1  Vent roses   (subset 6 h × ~27 ans, Mac)
   └─ 2  Houle P90    (3 h WAVERYS, le plus lourd ; V0 = moyenne P1M en parallèle)
        └─ isochrones « OpenCPN-grade » quand 1+2+3+4 sont branchés
N1–N4  fusion carte NAVIGUIDE (peut avancer en parallèle dès que l’API point répond)
```

Tant que le produit 1 n’est pas là, on ne prétend pas remplacer `climatology.py`.

Prévision 0–10 j (déverrouiller l’échéance CMEMS ANFC, overlay GFS/IFS) :
**hors V1** de ce mode. Autre chantier, autre `kind: "forecast"`.

---

## 17. Fichiers touchés

### Blue Intelligence

- `frontend/src/App.js`, `Header.js`, `i18n.js`, `MapView.js`
- `frontend/src/components/ClimatologyPanel.js` (nouveau)
- `frontend/src/components/map/useClimatologyLayer.js` (nouveau, ou un hook par produit)
- `frontend/src/components/map/layerOrder.js` + `__tests__/layerOrder.test.js`
- `backend/app/routers/climatology.py` (nouveau)
- `backend/app/services/climatology_wind.py`, `_wave.py`, `_current.py`, `_cyclones.py`
- `backend/app/core/export_meta.py` (champs période / DOI)
- `backend/data/run_rules.json` + `docs/REGLES_PARAMETRES.md`
- `backend/data/climatology/` (snapshots git-lfs ou release `data-`, à trancher)
- `scripts/climatology/gen_*.py`
- `backend/tests/test_climatology_*.py`
- `README.md`, `docs/CONTRATS_MODES.md`

### NAVIGUIDE

- `naviguide/naviguide_workspace/naviguide_weather_routing/climatology.py`
- `naviguide/naviguide_workspace/naviguide_weather_routing/isochrone.py`
- `naviguide/naviguide-api/agents/meteo_agent.py`
- `naviguide/naviguide-app/src/components/MaritimeLayers.jsx`
- `naviguide/naviguide-app/src/components/Sidebar.jsx`
- `naviguide/naviguide-app/src/hooks/useLegContext.js` (mois de jambe)
- `getWind.py` / `getWave.py` / `getCurrent.py` : **pas** fusionnés avec l’atlas

---

## 18. Licences et attributions

| Source | Licence | Mention |
|--------|---------|---------|
| CMEMS vent / vague / courant | Licence de service Copernicus Marine | « Generated using E.U. Copernicus Marine Service Information » + DOI du produit |
| IBTrACS | Redistribution sans restriction | « IBTrACS v04r01, NOAA NCEI » |
| OpenCPN (idée seulement) | GPL v3 — on ne copie pas | Pas de fichier dérivé |

Footer du 7ᵉ mode + `metadata.disclaimer_fr` : mêmes phrases que `export_meta.py`
(ne convient pas à la navigation, pas un document SOLAS, veille METAREA / Navtex
inchangée).

---

## 19. Recette

### Blue Intelligence (mode Climatologie)

1. Le 7ᵉ bouton affiche le panneau et la carte atlas ; les six autres modes
   n’ont aucune rose.
2. Décembre, Atlantique 10–20°N : roses ENE/NE, pas l’unique 18 kn / 050° de
   `climatology.py`.
3. P90 allumé, P50 éteint : quarantièmes plus sombres, Méditerranée d’été calme.
4. Gulf Stream février : flèches &gt; 1 kn ; Sahara : pas de courant.
5. Curseur septembre, Caraïbes : pelote de traces ; mars : presque vide.
6. Clic terre : blocs vent / houle / courant à `null`.
7. Attribution CMEMS + IBTrACS + bandeau navigation visibles.

### NAVIGUIDE

1. Aucune couche « climatologie » / ZEE / WPI n’est requise à l’écran pour
   qu’une simulation donne un ETA qui **bouge** selon le mois.
2. Isochrone MOST_LIKELY ≠ AVERAGE sur un alizé.
3. Isochrone juillet 50°S plus nord dès que le P90 est branché.
4. `crossings` Martinique→Açores en septembre &gt; 0 ; en mars = 0.
5. L’agent météo cite un **entier** IBTrACS, pas seulement « saison des ouragans ».
6. Le clic Copernicus vent/vague/courant continue de parler NRT / ANFC
   (`kind` différent, horodatage du produit).

---

## 20. Risques

| Risque | Parade |
|--------|--------|
| Cube 3 h WAVERYS / vent MY sur le VPS 8 Go | Pipeline Mac uniquement ; VPS = fichiers finis |
| Confondre moyenne P1M et P90 | Champ `stat` obligatoire ; test `p90 >= p50` |
| Confondre NRT 48 h et atlas | Deux `kind`, deux endpoints |
| Convention vent `from` vs courant `to` | Tests `atan2` séparés ; légende du popup |
| Antiméridien (pistes WP, route) | Couper les LineString ; jamais interpoler à travers l’Afrique |
| Header trop dense (7 boutons) | Libellés courts ; icône seule sous viewport étroit (à traiter en UI) |
| GPL OpenCPN | Réécriture ; revue licence avant merge |
| El Niño / changement climatique | Période écrite à l’écran ; pas de « vérité 2027 » |
| `best_match` Open-Meteo | Hors V1 ; si un jour forecast, modèle **nommé** |

---

## 21. Hors périmètre (V1)

- Prévision GFS / IFS / ICON / AIFS et overlay « cette semaine ».
- Déverrouillage `valid_time` de `getWave.py` / `getCurrent.py` (chantier forecast
  à part).
- Auto-hébergement Open-Meteo, ingestion GRIB NOMADS.
- Review / Gold du mode Climatologie.
- Rayons R34 IBTrACS, années analogues El Niño, bins vent 40+ kn.
- Spectre directionnel complet, Stokes, courants de marée.
- Nuages, foudre, humidité, précipitations (OpenCPN les a ; ce n’est pas le skipper
  hauturier V1).
- 8ᵉ pastille climatologie dans NAVIGUIDE.

---

## 22. Documents et conversations dont ce plan hérite

- Décisions produit (sept. 2026) : climatologie d’abord pour les traversées ;
  7ᵉ mode BI ; NAVIGUIDE invisible + fusion de cartes ; quatre produits ouverts.
- Plugin OpenCPN `climatology_pi` (manuel, `gendata/`, `ClimatologyOverlayFactory.h`)
  et `weather_routing_pi` (MOST_LIKELY, crossings).
- `docs/REGLES_PARAMETRES.md`, `docs/CONTRATS_MODES.md`, `docs/PRD.md`.
- Code : `getWind.py`, `getWave.py`, `getCurrent.py`, `climatology.py`,
  `isochrone.py`, `useScienceWms.js`, `layerOrder.js`, `MaritimeLayers.jsx`,
  `export_meta.py`, `meteo_agent.py`.
- PUM CMEMS vent 012-004-006, vagues 001-032, physique 001-030 ;
  IBTrACS v04r01 ; ERA5 monthly (écarté comme source **seule** des roses).
