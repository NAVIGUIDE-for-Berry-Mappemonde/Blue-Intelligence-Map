# Snapshots climatologie — générés sur le Mac, seulement servis sur le VPS

Ces scripts **ne doivent pas** tourner sur le VPS (4 vCores / 8 Go, ~35 Go
libres). Ils écrivent `backend/data/climatology/` :

| Script | Produit | Sortie |
|--------|---------|--------|
| `gen_cyclones.py` | IBTrACS v04r01 since1980 | `cyclones/ibtracs_since1980.json` |
| `gen_current.py` | GLORYS12 climatology_P1M-m | `current/current-MM.npz` |
| `gen_wind_mean.py` | CMEMS wind climate P1M 1994–2020 | `wind/wind-MM.npz` (`stat: average`) |
| `gen_wind_atlas.py` | CMEMS wind MY L4 0,25° 6 h | `wind/wind-MM.npz` + roses |
| `gen_wave_mean.py` | WAVERYS climatology_P1M-m | `wave/wave-MM.npz` (`stat: mean`) |
| `gen_wave_pct.py` | WAVERYS PT3H, un mois à la fois | `wave/wave-MM.npz` (`hs_p50` / `hs_p90`) |

Prérequis Mac : compte Copernicus dans `backend/.env`
(`COPERNICUS_USERNAME` / `COPERNICUS_PASSWORD`), `numpy`, `netCDF4` /
`xarray`, assez de disque pour **un mois** à la fois — jamais le cube
mondial en RAM. Ne pas lancer ça sur le VPS.

### Roses — une commande sur le Mac

Dans Terminal (remplace le chemin si ton dossier n'est pas là) :

```bash
cd ~/Blue-Intelligence-Map
source backend/.venv/bin/activate
pip install copernicusmarine xarray netCDF4 numpy python-dotenv
bash scripts/climatology/gen_wind_atlas_mac.sh
```

Si le Mac n'a pas encore de venv :

```bash
cd ~/Blue-Intelligence-Map
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install copernicusmarine xarray netCDF4 numpy python-dotenv
bash scripts/climatology/gen_wind_atlas_mac.sh
```

Les 12 mois prennent souvent **plusieurs heures**. `caffeinate` empêche
le Mac de s'endormir. Si ça s'arrête, relance **la même commande** : le
mois en cours reprend à l'année suivante. Un mois déjà en rose est sauté.
Si Copernicus reste figé, le script tue l'année au bout de 40 minutes
et la relance tout seul.

Le vent horaire CMEMS est en deux jeux du même produit : 0,25° jusqu'en
octobre 2009, puis 0,125° jusqu'en 2020. Le script les enchaîne et
stocke une maille 0,5°. Janvier–mai 1994 n'existent pas : ils sont
sautés, ce n'est pas une erreur.

```bash
# Cyclones (CSV libre, le plus court)
python3 scripts/climatology/gen_cyclones.py

# Courant (12 NetCDF surface — le plus simple CMEMS)
python3 scripts/climatology/gen_current.py

# Vent AVERAGE (climatologie mensuelle — V0 visible, pas une rose)
python3 scripts/climatology/gen_wind_mean.py

# Vent roses — 12 mois, sur le Mac (pas le VPS)
# Empêche la veille, reprend si le réseau coupe.
bash scripts/climatology/gen_wind_atlas_mac.sh

# Un seul mois (ex. mars, pour vérifier les alizés)
python3 scripts/climatology/gen_wind_atlas.py --month 3

# Houle : moyenne P1M d'abord (V0, ne pas l'étiqueter P90), puis percentiles
python3 scripts/climatology/gen_wave_mean.py --month 7
python3 scripts/climatology/gen_wave_pct.py --month 7
```
