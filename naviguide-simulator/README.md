# NAVIGUIDE simulator

Sous-dossier **hors production** : le cockpit de l’expédition Berry-Mappemonde <!-- pragma: allowlist secret -->
(carte Leaflet, boutons de couches, bateau qui avance, searoute, polaires).

`www.naviguide.fr` et `blueintelligence.online` ne sont **pas** le même
site. Publication prévue : **https://simulator.naviguide.fr** (sous-domaine
gratuit, même VPS, nginx à part).

Plan : [`docs/PLAN_IMPLEMENTATION_NAVIGUIDE_SIMULATOR_ETAPE1.md`](../docs/PLAN_IMPLEMENTATION_NAVIGUIDE_SIMULATOR_ETAPE1.md) (v3.0)

## Lancer (macOS, Terminal)

Deux onglets. Depuis ce dossier :

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
uvicorn server.main:app --host 127.0.0.1 --port 8010 --reload
```

Autre onglet :

```bash
cd naviguide-simulator
npm install
npm run dev
```

Ouvrir `http://localhost:5174`.

## Publier sur le VPS

Quand le DNS `simulator.naviguide.fr` pointe déjà vers `135.125.226.16`
(depuis le Mac, ou toute machine avec Node + SSH) :

```bash
cd /chemin/vers/Blue-Intelligence-Map
bash infra/vps/naviguide/publish-simulator-from-mac.sh
```

Ça construit le site sur le Mac, copie uniquement ce dossier et les
fichiers infra simulateur, puis sur le VPS : venv Python, service `:8010`, nginx **séparé**,
certificat Let's Encrypt étendu (gratuit). `www.naviguide.fr` n'est pas
redéployé. Détail : `infra/vps/README.md` (section simulator).

| Ça marche | Ça n’existe pas encore |
|---|---|
| Film NAVIGUIDE (2 sidebars, Berry, simulation, briefing) | 4 chats Ports / Sécurité / Météo / Cruisers |
| Searoute + draw your own route | Chat polar |
| Polar upload + tableau VMG (Leopard 46) | Import / export GeoJSON ou KML |
| Pastilles de couches (Sextant, Argo, ODATIS, EDMED, CSR, bathymétrie, fonds, câbles + Climat stub) | `ici()` rempli (ZEE, PoE Gold, Tavily) |
| Clic route → vent / vague / courant | Nemotron / Token Factory |

**Ne convient pas à la navigation.**
