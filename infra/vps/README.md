# Déploiement VPS OVH — blueintelligence.online

Production auto-hébergée sur le VPS OVH `vps-52ba6d62.vps.ovh.net` (135.125.226.16,
Ubuntu, 4 vCores / 8 Go / 75 Go) : **MongoDB 8.0 Community local** (fin du
throttling Atlas M0), backend FastAPI + frontend React servis par **uvicorn**
derrière le **nginx** du serveur, domaine derrière **Cloudflare**.

```
Internet → Cloudflare → nginx (443, certificat Let's Encrypt)
                          └→ uvicorn 127.0.0.1:8001 (SERVE_FRONTEND=1 : UI + /api/*)
                               └→ MongoDB 8.0 (127.0.0.1:27017, authentification activée)
```

## Emplacements sur le VPS

| Quoi | Où |
|------|-----|
| Code de l'application | `~/blue-intelligence-map/` |
| Secrets MongoDB local (comptes `admin` et `blue`) | `~/.config/blue-intelligence/mongo.env` (chmod 600) |
| Chaîne Atlas (pour resynchronisation) | `~/.config/blue-intelligence/atlas.env` (chmod 600) |
| Clés API applicatives | `~/blue-intelligence-map/backend/.env` (chmod 600) |
| Sauvegardes quotidiennes (04:00, rotation 14 j) | `~/backups/mongodb/` + `/etc/cron.d/blue-intelligence-backup` |
| Service applicatif | `/etc/systemd/system/blue-intelligence.service` |
| Reverse proxy | `/etc/nginx/sites-available/blue-intelligence` (TLS géré par certbot) |

## Première installation (déjà effectuée le 2026-09-09)

```bash
# 1. MongoDB 8 sécurisé (idempotent — crée les comptes au premier passage)
bash infra/vps/install-mongodb.sh

# 2. Données depuis Atlas (ÉCRASE la base locale)
bash infra/vps/sync-from-atlas.sh

# 3. Application (venv Python 3.12 via uv, build frontend, systemd, cron)
bash infra/vps/deploy-app.sh
```

Le `proxy_pass` nginx doit viser `127.0.0.1:8001` (voir
`nginx-blue-intelligence.conf`, copie de référence).

## Redéployer après une mise à jour du code

```bash
cd ~/blue-intelligence-map
# code à jour (rsync depuis un poste, ou git pull si un remote est configuré)
bash infra/vps/deploy-app.sh
```

## Resynchroniser les données depuis Atlas

À faire une dernière fois **juste avant la bascule DNS Cloudflare** (tant
qu'Atlas reste la base « vivante »), puis plus jamais :

```bash
bash infra/vps/sync-from-atlas.sh
sudo systemctl restart blue-intelligence
```

## Sauvegardes

- Automatique : cron quotidien à 04:00, archives `blue-AAAA-MM-JJ.archive.gz`,
  rotation 14 jours. Penser à copier régulièrement une archive **hors du VPS**.
- Restaurer une archive :

```bash
. ~/.config/blue-intelligence/mongo.env
mongorestore --uri "$MONGO_URL_LOCAL" --gzip \
  --archive=$HOME/backups/mongodb/blue-AAAA-MM-JJ.archive.gz --drop
```

## Bascule Cloudflare (dernière étape)

1. Dashboard Cloudflare → zone `blueintelligence.online` → **DNS**.
2. Éditer l'enregistrement du domaine racine (et `www`) pour pointer vers
   **135.125.226.16** (A), nuage orange (proxy) conservé.
3. SSL/TLS → mode **Full (strict)** (le certificat Let's Encrypt du VPS est
   valide).
4. Vérifier `https://blueintelligence.online/api/` → `"mongo": "local"`.
5. Retour arrière : remettre l'ancienne cible DNS (propagation quasi immédiate,
   Atlas n'est pas touché).

Après bascule, vérifier le renouvellement du certificat : `sudo certbot renew
--dry-run` (le challenge HTTP passe par Cloudflare ; si « Always Use HTTPS »
bloque `/.well-known/acme-challenge/`, créer une exception ou utiliser un
certificat Origin Cloudflare).

## Sécurité / accès

- MongoDB n'écoute que sur 127.0.0.1, authentification obligatoire — jamais
  exposé sur Internet, aucun port à ouvrir.
- Révoquer l'accès de l'agent Cursor : supprimer la ligne
  `cursor-agent-blue-intelligence` de `~/.ssh/authorized_keys` sur le VPS.
- Journaux applicatifs : `sudo journalctl -u blue-intelligence -f` ;
  MongoDB : `/var/log/mongodb/mongod.log`.

## NAVIGUIDE — www.naviguide.fr (même VPS)

NAVIGUIDE (`naviguide/` du monorepo) est publié sur le même VPS, sous le
domaine **www.naviguide.fr** (DNS A → 135.125.226.16, sans Cloudflare).
Voir `infra/vps/naviguide/`.

```
Internet → nginx (443, Let's Encrypt)
   www.naviguide.fr        → dist/ statique (React + MapLibre)
   /route /wind /wave …    → uvicorn 127.0.0.1:9000  (naviguide-api)
   /api/v1/polar/*         → uvicorn 127.0.0.1:9004  (polar-api)
   /api/v1/*               → uvicorn 127.0.0.1:9008  (orchestrateur LangGraph)
   /bi/*                   → uvicorn 127.0.0.1:8001  (Blue Intelligence /api/*)
```

| Quoi | Où |
|------|-----|
| Code | `~/blue-intelligence-map/naviguide/` (venv partagé `.venv/`) |
| Secrets (Anthropic, Copernicus, StormGlass) | `~/.config/naviguide/naviguide.env` (chmod 600) |
| Services | `naviguide-api`, `naviguide-orchestrator`, `naviguide-polar` (systemd) |
| Reverse proxy | `/etc/nginx/sites-available/naviguide` (TLS certbot) |

```bash
# (Re)déploiement — build frontend + venv + systemd + nginx
bash infra/vps/naviguide/deploy-naviguide.sh
# Premier déploiement seulement : secrets puis TLS
vim ~/.config/naviguide/naviguide.env && sudo systemctl restart naviguide-api naviguide-orchestrator naviguide-polar
sudo certbot --nginx -d www.naviguide.fr -d naviguide.fr
```

Les couches « Blue Intelligence » de la carte NAVIGUIDE consomment les exports
GeoJSON du backend Blue Intelligence local via la route nginx `/bi/*` — aucun
CORS, aucun appel réseau externe. Journaux : `sudo journalctl -u naviguide-api -f`
(idem `-orchestrator`, `-polar`). Ports 9000/9004/9008 réservés à NAVIGUIDE
(8001 = Blue Intelligence). `naviguide-weather-routing` (3010) n'est pas
déployé : le frontend ne l'appelle pas.
