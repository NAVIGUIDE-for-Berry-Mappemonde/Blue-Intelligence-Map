# Snapshots climatologie — générés sur le Mac, seulement servis sur le VPS

Ces scripts **ne doivent pas** tourner sur le VPS (4 vCores / 8 Go, ~35 Go
libres). Ils écrivent `backend/data/climatology/` :

| Script | Produit | Sortie |
|--------|---------|--------|
| `gen_cyclones.py` | IBTrACS v04r01 since1980 | `cyclones/ibtracs_since1980.json` |
| `gen_current.py` | GLORYS12 climatology_P1M-m | `current/current-MM.npz` |
| `gen_wind_atlas.py` | CMEMS wind MY L4 0,25° 6 h | `wind/wind-MM.npz` + `.atlas.json` |
| `gen_wave_mean.py` | WAVERYS climatology_P1M-m | `wave/wave-MM.npz` (`stat: mean`) |
| `gen_wave_pct.py` | WAVERYS PT3H, un mois à la fois | `wave/wave-MM.npz` (`hs_p50` / `hs_p90`) |

Prérequis Mac : compte Copernicus (`copernicusmarine login`), `numpy`,
`netCDF4` / `xarray`, assez de disque pour **un mois** à la fois — jamais le
cube mondial en RAM.

```bash
# Cyclones (CSV libre, le plus court)
python3 scripts/climatology/gen_cyclones.py

# Courant (12 NetCDF surface — le plus simple CMEMS)
python3 scripts/climatology/gen_current.py

# Vent roses (subset 6 h × 1994–2020, un mois calendaire à la fois)
python3 scripts/climatology/gen_wind_atlas.py --month 3

# Houle : moyenne P1M d'abord (V0, ne pas l'étiqueter P90), puis percentiles
python3 scripts/climatology/gen_wave_mean.py --month 7
python3 scripts/climatology/gen_wave_pct.py --month 7
```
