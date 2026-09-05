# Outil latéral Noonsite

Hors du code principal Blue Intelligence (`backend/`, `frontend/` inchangés).
Lit le panneau **Main Ports** (badge orange `Port of Entry`) et renvoie
deux listes par pays, **selon Noonsite** :

| Liste | Règle |
|---|---|
| `ports_of_entry` | ligne Main Ports avec badge orange **Port of Entry** |
| `other_ports` | ligne Main Ports **sans** badge |

Ce n’est **pas** un Gold Dataset. Le badge est un signal positif ;
l’absence d’un port sur Noonsite ne le réfute pas. Les baies citées
dans le texte *Facts* (ex. Cove Bay à Saba) ne sont pas des ports
Noonsite si elles n’apparaissent pas dans Main Ports.

Plafond : **3 pays** par invocation (quota du compte gratuit).

## Anatomie des pages (PDF FireShot)

Les imprimés Saba montrent trois surfaces, pas trois pays :

1. **Facts** — FAQ *Where can I enter?* (ex. « one Port of Entry… Fort Bay »).
2. **Formalities** — menu Clearance / Immigration / Customs (login).
3. **Main Ports** — overlay gauche : badge orange = PoE.

Niue et Saba étaient déjà débloqués sur le compte (2/3 du mois).

## Usage

```bash
cd tools/noonsite
python3 -m pip install -r requirements.txt
python3 harvest.py niue saba
```

Le HTML de la page pays contient déjà Main Ports. Le login n’est
nécessaire que pour Formalities / Clearance :

```bash
cp .env.example .env   # renseigner, ne jamais committer
python3 harvest.py niue saba --login
```

Sortie : résumé stdout + `output/latest.json`.

## Résultat Niue + Saba (live)

| Pays | PoE | non-PoE |
|---|---|---|
| Niue | Alofi | — |
| Saba | Fort Bay (Fort Baai) | Well's and Ladder Bays |

## Identifiants

Ne jamais coller le mot de passe dans le chat, un ticket ou git.
Le changer s’il a déjà circulé. Fichier `.env` gitignoré.
