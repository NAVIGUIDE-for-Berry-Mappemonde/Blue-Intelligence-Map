# Miroir auto-hébergé de la carte marine (Open Waters: Seamap)

Le fond « Carte marine » de Blue Intelligence consomme par défaut le service
communautaire `tiles.openwaters.io` — sans garantie de disponibilité. Ce
dossier installe un **miroir sur le VPS OVH** : l'archive PMTiles datée
(~26 Go), le style et les sprites sont servis par nginx depuis
`https://blueintelligence.online/tiles/seamap/`.

Licences : tuiles/style/sprites **CC-BY 4.0** (« © Open Waters: Seamap ») sur
données **© OpenStreetMap contributors (ODbL)** — le miroir conserve ces
attributions (déjà affichées par le frontend). Aucun code GPL du dépôt seamap
n'est utilisé.

Budget disque : ~26 Go par archive, 2 archives conservées (`KEEP=2`) →
**prévoir ~55 Go libres** sur les 75 Go du VPS. Si c'est trop juste, mettre
`KEEP=1` (~30 Go).

## Installation (une fois)

Depuis le Terminal de votre Mac, connectez-vous au VPS :

```bash
ssh ubuntu@vps-52ba6d62.vps.ovh.net
```

Puis, sur le VPS :

```bash
# 1. Dossier de destination (archive immuable + partie servie par nginx)
sudo mkdir -p /srv/tiles/seamap/public
sudo chown -R ubuntu:ubuntu /srv/tiles

# 2. Script de synchronisation
cp ~/blue-intelligence-map/infra/vps/seamap/sync-seamap.sh /srv/tiles/seamap/
chmod +x /srv/tiles/seamap/sync-seamap.sh

# 3. Test sans téléchargement : découvre la version amont (ETag daté)
/srv/tiles/seamap/sync-seamap.sh --check

# 4. Test léger : style + sprites seulement (quelques Ko)
/srv/tiles/seamap/sync-seamap.sh --assets-only

# 5. Synchronisation complète (~26 Go — plusieurs dizaines de minutes,
#    reprise automatique si coupure : relancer la même commande)
/srv/tiles/seamap/sync-seamap.sh
```

### nginx

Ouvrez la configuration du site :

```bash
sudo nano /etc/nginx/sites-available/blue-intelligence
```

Dans le bloc `server { … }` HTTPS (celui qui contient `location / {`), ajoutez
le contenu de `nginx-tiles.conf` (le bloc `location /tiles/seamap/ { … }`),
puis :

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -sI https://blueintelligence.online/tiles/seamap/style.json | head -5
```

> Cloudflare : le fichier `current.pmtiles` (~26 Go) est lu par petites plages
> d'octets (en-têtes `Range`), ce que Cloudflare laisse passer sans le mettre
> en cache. Si vous constatez des lenteurs, créez un sous-domaine « DNS only »
> (nuage gris) `tiles.blueintelligence.online` et utilisez-le dans
> `PUBLIC_BASE_URL`.

### Cron hebdomadaire

```bash
sudo cp ~/blue-intelligence-map/infra/vps/seamap/seamap-sync.cron /etc/cron.d/seamap-sync
```

Le lundi 06:30 UTC (l'amont reconstruit sa carte le lundi 03:00 UTC), le miroir
récupère la nouvelle archive datée, bascule `current.pmtiles` atomiquement et
élague les archives au-delà de `KEEP`.

## Basculer le frontend sur le miroir

`deploy-app.sh` détecte le miroir automatiquement : si
`/srv/tiles/seamap/public/style.json` existe au moment du build, il écrit
`REACT_APP_SEAMAP_STYLE_URL=https://blueintelligence.online/tiles/seamap/style.json`
dans `frontend/.env`. Il suffit donc de redéployer après la première
synchronisation :

```bash
cd ~/blue-intelligence-map && bash infra/vps/deploy-app.sh
```

Sans miroir, le frontend garde le style public `tiles.openwaters.io` — le mode
« Carte marine » fonctionne dans les deux cas.

## Ce qui reste sur les CDN d'origine

Le miroir couvre ce que seamap construit : la couche seamark (PMTiles), le
style et les sprites nautiques. Les fonds VersaTiles, la bathymétrie Seascape
et les polices restent sur leurs CDN (plusieurs dizaines de Go, hors budget du
VPS). Conséquence assumée : sans réseau vers ces CDN, la carte marine affiche
le balisage sur fond neutre.
