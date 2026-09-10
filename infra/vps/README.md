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

## Bascule Cloudflare (effectuée le 2026-09-10)

Le domaine (registrar OVH) pointait vers le Cloudflare de l'ancienne
plateforme ; il a été rapatrié dans le compte Cloudflare du propriétaire :

1. Cloudflare → **Connect a domain** → `blueintelligence.online`, plan Free.
   Zone importée depuis OVH puis corrigée : **A `@` → 135.125.226.16**
   (proxied), CNAME `www` → racine (proxied), MX/TXT conservés tels quels.
2. OVH (manager → Web Cloud → Noms de domaine → onglet Serveurs DNS) :
   serveurs remplacés par `coby.ns.cloudflare.com` / `eve.ns.cloudflare.com`.
   **DNSSEC désactivé** au préalable (indispensable), protection contre le
   transfert laissée activée.
3. Certificat edge « Universal SSL » émis à l'activation ; SSL/TLS en mode
   **Full (strict)** (le certificat Let's Encrypt du VPS couvre racine + www).
4. Vérifié : `https://blueintelligence.online/api/` → `"mongo": "local"`,
   HTTP 200 via edge Cloudflare, garde admin 401/200, marinas 15 Mo en ~3 s.
5. Retour arrière : chez OVH, remettre les serveurs `ns14.ovh.net` /
   `dns14.ovh.net` (la zone OVH d'origine, intacte, redevient autoritaire et
   re-pointe vers l'ancienne plateforme).

Après bascule, vérifier le renouvellement du certificat : `sudo certbot renew
--dry-run` (le challenge HTTP passe par Cloudflare ; si « Always Use HTTPS »
bloque `/.well-known/acme-challenge/`, créer une exception ou utiliser un
certificat Origin Cloudflare).

## Accès admin (Console / Review)

Les onglets Console et Review, ainsi que toutes les écritures de l'API
(`POST/PUT/PATCH/DELETE /api/*`, sauf le signalement public de projets) sont
protégés par une clé admin :

- La clé vit dans `~/blue-intelligence-map/backend/.env` sur le VPS
  (`ADMIN_KEY=...`). Sans cette variable (dev local), tout reste ouvert.
- Pour débloquer l'interface : ouvrir une fois
  `https://blueintelligence.online/?admin=<clé>`. La clé est mémorisée dans le
  navigateur (localStorage) et envoyée ensuite via le header `X-Admin-Key`.
- Pour verrouiller un navigateur : `https://blueintelligence.online/?admin=off`.
- Régénérer la clé : `openssl rand -hex 24`, remplacer la valeur dans
  `backend/.env`, puis `sudo systemctl restart blue-intelligence` (les anciens
  navigateurs admin devront re-saisir la nouvelle clé).

## Sécurité / accès

- MongoDB n'écoute que sur 127.0.0.1, authentification obligatoire — jamais
  exposé sur Internet, aucun port à ouvrir.
- Révoquer l'accès de l'agent Cursor : supprimer la ligne
  `cursor-agent-blue-intelligence` de `~/.ssh/authorized_keys` sur le VPS.
- Journaux applicatifs : `sudo journalctl -u blue-intelligence -f` ;
  MongoDB : `/var/log/mongodb/mongod.log`.
