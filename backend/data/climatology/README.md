# Snapshots climatologie

Générés **hors VPS** (voir `scripts/climatology/`). Le serveur ne fait que
les lire. Tant qu'un produit manque, l'API renvoie `null` / une
FeatureCollection vide — elle n'invente pas de champ.

| Dossier | Fichiers | Source |
|---------|----------|--------|
| `cyclones/` | `ibtracs_since1980.json` | IBTrACS v04r01 |
| `wind/` | `wind-MM.npz` + `.atlas.json` | CMEMS WIND MY L4 |
| `wave/` | `wave-MM.npz` | WAVERYS |
| `current/` | `current-MM.npz` | GLORYS12 climatology_P1M-m |

`kind: "climatology"` partout. Ne convient pas à la navigation.
