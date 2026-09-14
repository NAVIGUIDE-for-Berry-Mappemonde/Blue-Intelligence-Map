# Vague 4 — Guide Mac, pas à pas (Sentinel)

À faire **sur votre Mac**, pas sur le serveur. Une étape après l’autre.
Si une commande affiche une erreur, arrêtez-vous et relisez le cadre
« Si ça bloque » de l’étape.

Les images sont lourdes (~1 Go pièce). On commence par **une** scène.

---

## Avant de commencer (une seule fois)

1. Ouvrez **Terminal** (Spotlight : tapez `Terminal`, Entrée).
2. Allez dans le dossier du projet. Adaptez le chemin si le vôtre est ailleurs :

```bash
cd ~/Documents/Blue-Intelligence-Map
```

3. Créez le fichier secret (s’il n’existe pas encore) :

```bash
cp scripts/satellite/.env.example scripts/satellite/.env
```

4. Ouvrez-le :

```bash
open -e scripts/satellite/.env
```

5. Remplissez, **mot de passe entre quotes** :

```
CDSE_USERNAME=votre.email@exemple.com
CDSE_PASSWORD='votre-mot-de-passe'
```

Enregistrez. Ce fichier n’est **pas** envoyé dans Git.

6. Vérifiez le login :

```bash
python3 scripts/satellite/check_login.py
```

Vous devez lire `CDSE : connexion OK`. Sinon le mot de passe ou le compte
n’est pas le bon (CDSE = dataspace.copernicus.eu, pas CMEMS).

---

## Étape 1 — Télécharger **une** photo L1C (S1)

ACOLITE a besoin du **L1C** (image brute). Le **L2A** (déjà corrigé par
l’ESA) est refusé : *Level-2A data not supported*.

**Pourquoi ne pas utiliser le L2A ESA, plus « prêt » ?** L’ESA corrige
surtout pour la terre (champs, forêts). Sur l’eau, cette correction
est souvent mauvaise. ACOLITE part du L1C et corrige pour le littoral.
On ne saute donc pas ACOLITE : ce n’est pas plus long pour rien.
Le zip L2A déjà téléchargé peut rester sur le Bureau ; on ne le
pointe pas dans ACOLITE.

D’abord rafraîchir la liste (scènes `MSIL1C`) :

```bash
python3 scripts/satellite/search_stac.py --limit 2 --out scripts/satellite/scenes_la_rochelle.json
```

Les `id` doivent contenir `MSIL1C`, pas `MSIL2A`.

Ensuite télécharger **une** scène. Cela peut prendre 10 à 40 minutes
selon votre box.

```bash
python3 scripts/satellite/download_scenes.py --limit 1
```

Le zip arrive sur le Bureau : `~/Desktop/sentinel-pilot/`.
Un fichier `download_receipt.json` donne le `sha256` (preuve S1).

Pour voir seulement si le catalogue répond, sans télécharger :

```bash
python3 scripts/satellite/download_scenes.py --limit 1 --dry-run
```

**Si ça bloque.** Espace disque : il faut ~2 Go libres (un zip +
décompression). Menu Pomme → Réglages → Général → Stockage.

Décompressez ensuite le zip (double-clic). Vous obtenez un dossier
`.SAFE`.

---

## Étape 2 — Nettoyer le ciel et la brume (S2, ACOLITE)

ACOLITE est un logiciel **à part**. Il ne tourne pas dans Blue Intelligence.

1. Installez Python 3 si besoin : [python.org/downloads](https://www.python.org/downloads/).
2. Dans Terminal :

```bash
cd ~
git clone https://github.com/acolite/acolite
cd acolite
python3 -m pip install -r requirements.txt
python3 launch_acolite.py
```

3. Dans ACOLITE :
   - **Input** : le dossier `.SAFE` **L1C** de l’étape 1
     (le nom contient `MSIL1C`). Pas le dossier `MSIL2A`.
   - Output : par ex. `~/Desktop/sentinel-pilot/acolite`
   - Laissez l’algorithme **DSF**. ACOLITE écrit le L2R tout seul.
   - Lancez. Attendez la fin (souvent 15–40 min). Le premier run
     peut télécharger des tables (LUT).

**Si le log dit** `Level-2A data not supported` : vous avez pointé
un `.SAFE` L2A. Relancez l’étape 1 (recherche L1C + téléchargement)
et changez l’Input.

Vous devez voir des fichiers GeoTIFF ou NetCDF dans le dossier de sortie
ACOLITE, avec des bandes vertes et SWIR (ex. `rhos_561`, `rhos_1614`).
Un dossier qui ne contient que `*_log_file.txt` et `*_settings_user.txt`
signifie que le calcul n’a pas tourné.

---

## Étape 3 — Trait de côte (S3, MNDWI)

L’eau est plus sombre en SWIR qu’en vert. On calcule :

`MNDWI = (vert − SWIR) / (vert + SWIR)`

Puis on garde le **bord** eau / terre.

**Chemin simple (Terminal, environnement ACOLITE)**

```bash
conda activate acolite
cd ~/Blue-Intelligence-Map/scripts/satellite
python3 mndwi_coastline.py
```

Le fichier arrive sur le Bureau :
`~/Desktop/sentinel-pilot/coastline-raw.geojson`.
Aucune profondeur n’est inventée.

**Autre chemin (QGIS)**

1. Installez [QGIS](https://qgis.org) (Mac).
2. Ouvrez les deux bandes ACOLITE (vert et SWIR).
3. Raster → Calculatrice raster :

```
("vert" - "swir") / ("vert" + "swir")
```

4. Extraction → Contour, seuil `0`.
5. Exportez en GeoJSON sur le Bureau, par ex.  
   `~/Desktop/sentinel-pilot/coastline-raw.geojson`.

Une seule ligne (ou quelques lignes) suffit. Ce n’est **pas** une carte
marine.

---

## Étape 4 — Profondeur seulement si ICESat-2 (S4)

```bash
cd ~/Documents/Blue-Intelligence-Map
python3 scripts/satellite/check_icesat2.py
```

- Message *« on n’invente pas de profondeur »* : **sautez S4**.
  Pas de `seamark:type=depth_area`. Passez à l’étape 5 avec le seul
  trait de côte.
- Message *« S4 est possible »* (c’est le cas autour de La Rochelle) :
  des traces ICESat-2 **existent**. On ne calcule la profondeur **que**
  quand le fichier ATL24/ATL03 est téléchargé et calé. En attendant :
  trait de côte seulement, pas de sondage inventé.

---

## Étape 5 — Comparer à EMODnet (S5)

```bash
python3 scripts/satellite/compare_emodnet.py \
  --in ~/Desktop/sentinel-pilot/coastline-raw.geojson \
  --out ~/Desktop/sentinel-pilot/coastline-emodnet.geojson
```

Le script interroge le DTM EMODnet. S’il n’y a **pas** de profondeur
estimée (cas normal sans S4), il note EMODnet et **n’invente pas**
un sondage.

---

## Étape 6 — Tamponner le fichier (S6)

```bash
python3 scripts/satellite/export_pilot.py \
  --in ~/Desktop/sentinel-pilot/coastline-emodnet.geojson \
  --out backend/data/satellite/coastline.geojson \
  --dataset sentinel-coastline
```

Le fichier reçoit `natural=coastline`, `source=sentinel-pilot`,
une version et un avertissement « pas pour la navigation ».

S’il existait une zone de profondeur (S4 seulement) :

```bash
python3 scripts/satellite/export_pilot.py \
  --in ~/Desktop/sentinel-pilot/depth-raw.geojson \
  --out backend/data/satellite/depth_areas.geojson \
  --dataset sentinel-depth
```

---

## Étape 7 — Voir dans Blue Intelligence (S7)

1. Lancez le site en local (comme d’habitude).
2. Entrez (modale d’avertissement).
3. Mode **Science**.
4. Roue dentée → **Importer GeoJSON** (compte admin).
5. Choisissez `backend/data/satellite/coastline.geojson`.
6. Filtre **Satellite (pilote)**.

La Review reste **éteinte** pour ce jeu. Ce n’est pas Gold.
Ce n’est **pas** mélangé à la moisson Sextant / Argo.

En ligne de commande (si le backend tourne déjà) :

```bash
curl -s -X POST http://127.0.0.1:8001/api/import/science.geojson \
  -H 'Content-Type: application/json' \
  --data-binary @backend/data/satellite/coastline.geojson
```

---

## Ce qu’on ne fait jamais

- Recaler l’image avec un VLM ou `geo.py`.
- Inventer une profondeur sans ICESat-2.
- Présenter ce trait comme une carte de navigation.
- Faire tourner ACOLITE ou le téléchargement **sur le VPS**.

---

## Déjà fait ici (pas à refaire)

- Compte CDSE vérifié (S0).
- Ancienne liste L2A dans `scenes_la_rochelle.json` : **à régénérer**
  avec `search_stac.py` (L1C) avant ACOLITE.
- Filtre Science `sentinel-pilot` dans l’app.
