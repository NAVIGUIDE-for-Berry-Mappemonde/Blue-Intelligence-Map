# Contrats des modes

**Ce que je cherche à faire.** Transformer le web maritime vivant en une base géospatiale fiable, posée sur une carte mondiale : sites d’action accessibles en bateau, ports d’entrée officiels, marinas, capitaineries, aires protégées — sans confondre un siège, une page institutionnelle ou un port commercial avec ce dont un plaisancier a besoin.

---

## Projets

Trouver les projets de conservation, restauration ou protection marine financés par des fondations, extraire le lieu d’action (un GPS par page, pas le siège), n’en garder que ce qui est assez précis et accessible en bateau, les scorer (S_ocean) et les enregistrer dans un run isolé — sans vider ni modifier la carte live.

| Étape | Outils |
| --- | --- |
| Ouvrir un run isolé, sans vider ni écrire la carte live | MongoDB (`project_runs`, `project_run_projects`, `project_run_events`) ; `clear_db` refusé |
| Partir des listings financeurs connus | MasterSeeds (21 portails ; 3 en mode test, tous en full) |
| Réutiliser ce qui a déjà été vu | TTL `discovery_state` (7 j.) ; cache `deeplink_pages` ; en full, les pages cachées absentes de `projects` sont remises en file |
| Découvrir les URL de projets sur chaque listing | Crawler HTML (httpx, BeautifulSoup) ; si 0 URL et clé présente : TinyFish Agent |
| Si l’URL est déjà sur la carte live, la tracer sans recrawler | Lecture seule de `projects` |
| Extraire le texte des pages et des PDF | httpx ; trafilatura ∥ Readability ; PyMuPDF (+ Tesseract si scan) ; si trop court ou challenge souple : Playwright / Chromium ; puis miroir Jina ∥ TinyFish Fetch, sinon Wayback |
| Décider si c’est bien un projet marin | Classifieur local TF-IDF + régression logistique ; sinon NVIDIA NIM (Pro → gpt-oss → Muse) → OpenRouter → Claude (si budget) ; sinon heuristique mots-clés |
| Isoler les passages utiles des pages trop longues | RAG local au-delà de 6 000 caractères (sentence-transformers, sinon TF-IDF) |
| Extraire le nom, le lieu, S_ocean, la catégorie et les partenaires | NVIDIA NIM → OpenRouter → Claude ; sinon heuristique ; au plus 3 partenaires |
| Trouver le GPS du lieu d’action | Coordonnées déjà dans la page ; Nominatim puis GeoNames ; géocodage LLM (NIM / OpenRouter / Claude) ; Nominatim / GeoNames sur le titre |
| Ne retenir que ce qui est accessible en bateau | `site_publishable` + masque terrestre : mer, ou havre ≤ 15 km ; pas de snap océan |
| Dédupliquer, dans le run puis contre la v1 | Même URL ; Haversine < 500 m et similarité de noms ≥ 60 %, ou similarité ≥ 90 % ; lecture seule de `projects` |
| Suivre l’argent vers les organisations partenaires | Même découverte (crawler, puis Agent si vide), plafond 5 partenaires |
| S’arrêter quand ça ne trouve plus rien de nouveau | Seuil de saturation (défaut 50 extractions d’affilée sans nouveau site unique) |

---

## Ports d’entrée

Pour chaque polygone VLIZ (`mrgid`, jamais un agrégat pays : l’hexagone et Mayotte sont deux fiches), retrouver la page ou le PDF d’État qui liste les ports d’entrée, et les noms de ces ports utilisables par un yacht étranger, puis n’écrire un GPS que s’il tombe dans *ce* polygone. Deux bras distincts alimentent la même fiche ZEE : le Top-Down part du polygone ; le Bottom-Up part d’un lieu déjà connu et, si la page ouverte est un catalogue, moissonne toute la liste. Noonsite, OSM et le WPI sont des signaux / contre-liste, pas une preuve. Un run écrit `poe_run_*` ; la publication carte passe par la revue / Gold.

### Top-down (un polygone → la liste)

| Étape | Outils |
| --- | --- |
| Prendre **ce** polygone VLIZ (nom, ISO2, souverain, géométrie) | VLIZ Marine Regions WFS → MongoDB `eez_zones` |
| Lister les domaines d’État autorisés | Whitelist ISO2 du polygone + du souverain + exceptions disque |
| Chercher l’URL d’État qui porte la liste, avec le nom du polygone | **v1** : SearXNG (EN, puis localisé si vide) + Serper. **v2** : SearXNG EN ∥ local + Serper, sans TinyFish. **tinyfish** (défaut) : SearXNG ∥ TinyFish Search + Serper ; filet TinyFish `include_domains` ; 2ᵉ round « leçons » ; SearXNG `site:` PDF/pages. OpenRouter `:online` seulement si rien n’a été trouvé |
| Écarter forums, OTA, dictionnaires ; garder les domaines d’État | Filtre SERP + classifieur ML + gatekeeper whitelist |
| Télécharger et lire la page / le PDF | httpx → trafilatura ∥ Readability ; PDF PyMuPDF (+ Tesseract si scan) ; Playwright / Chromium si JS ; miroir Jina ∥ TinyFish Fetch (variante tinyfish seulement) puis Wayback |
| Extraire les noms (et les lat/lon déjà écrits dans le texte) | Parseur catalogue d’abord (saute le LLM si la table suffit) ; sinon NVIDIA NIM en parallèle spaCy NER ; second lecteur NIM ; Claude Haiku en dernier ; RAG si texte long |
| Coller chaque port dans **ce** polygone | Nominatim ∥ GeoNames ; si désaccord : NIM → OpenRouter → Claude. Point gardé seulement in-EEZ / bord terrestre ≤ 15 km / exception rivière ≤ 400 km |
| Noter la confiance (signal, pas vérité) | Score 0–100 (source d’État, lecture, carte, listing Noonsite + OSM) |
| Écrire l’étape, sans toucher la carte v1 | MongoDB `poe_run_ports` / `poe_run_zones` / `poe_run_events` |
| Qualifier une ZEE **sans** port physique | Règles UNCLOS (île vide, revendication, régime conjoint, Antarctique, entrée via l’État souverain) — hors boucle d’extraction |

### Bottom-up (un lieu déjà connu → la preuve, et parfois la liste)

| Étape | Outils |
| --- | --- |
| (Optionnel) Rafraîchir l’inventaire OSM | Overpass → cache `osm_port_seeds` ; Taginfo |
| Unionner les lieux déjà connus | v1 `poe_ports` ∪ runs ∪ OSM ∪ listing Noonsite. WPI = contre-liste commerce, jamais une preuve ni une nouvelle graine |
| Trier ce qu’il reste à faire | `confirmed` / `probable` / `unverified` / `name_only` |
| Géocoder les noms sans point | Nominatim ∥ GeoNames ; même filtre polygone. Pas de SearXNG / TinyFish ici |
| Chercher la page d’État **de ce nom** | TinyFish Search (whitelist d’abord). Pas SearXNG, pas Serper, pas Playwright, pas `:online` |
| Télécharger les hits whitelistés | TinyFish Fetch ; si `bot_blocked` : TinyFish Agent sur une URL officielle déjà vue |
| Si la page est un catalogue : prendre **toute** la liste | Parseur catalogue → `sources_bu` ; les noms déjà sur la liste : juge sauté |
| Juger seulement le **résidu** | NVIDIA NIM ; sinon OpenRouter ; Claude Haiku → Sonnet si listing ou inconclusive. `kind=cargo` → rejeté. N’écrit jamais `poe_ports` |
| Relire les URLs déjà payées, sans nouvelle recherche | TinyFish Fetch seulement, puis juge du résidu |
| (À part) Recoller OSM sur la carte v1, sans bouger nom/GPS | Overpass autour du point → `osm_confidence` |
| (À part) File de revue vs listing Noonsite | Listing control (le listing n’est pas Gold) |

---

## Marinas

Constituer l’annuaire mondial des marinas de plaisance (identité OSM `type/id` stable, pas de purge, pas de mélange PoE), y coller un signal de fiche Google `/maps/place/` s’il existe vraiment, puis remplir contacts et services sans inventer ; à part, lister les mouillages OSM le long de la route Berry-Mappemonde. Les jobs écrivent dans un run isolé, pas dans la carte live.

### Dump mondial

| Étape | Outils |
| --- | --- |
| Balayer la planète par tuiles, reprendre celles déjà faites, sans vider les fiches | Grille `WORLD_TILES` ; curseur MongoDB ; collection isolée |
| Ne garder que les marinas de plaisance OSM | Overpass `leisure=marina` — pas `harbour=yes` ni seamark commercial |
| Casser les tuiles trop vastes ou trop lourdes | Split si côté > 40° ; pause 3 s |
| Identifier et mettre à jour sans casser l’enrichissement ni la fiche Google | Upsert MongoDB par `osm_id` |
| Recopier le site OSM tel quel, sans le vérifier | Tags `website` / `contact:website` / `url` |
| Offrir un lien Maps de recherche, pas une vérité Places | URL déterministe `google.com/maps/search/?api=1&query=` (nom + coords) |
| Si le tag OSM est déjà une URL Google `/maps/place/` | Copie dans `maps_place_url`, source `osm_tag` — sans TinyFish |

### Signal fiche Google

| Étape | Outils |
| --- | --- |
| Savoir si une marina nommée a une vraie page Google `/maps/place/`, sans API Places | Job séparé, reprenable |
| Réutiliser d’abord un lien `/place/` déjà dans OSM | `website`, tags OSM, `contact:google` |
| Ouvrir le lien de recherche Maps et ramasser un lien `/place/` | TinyFish Fetch (lots de 10) ; TinyFish Search est sauté (n’indexe pas `/place/`) |
| Ne retenir qu’une fiche marina, proche, pas un resto / hôtel / pin de commune | Filtre nom + slug marina/port ; écart max 8 km ; sans nom → ignoré |

### Enrichissement contacts / services

| Étape | Outils |
| --- | --- |
| Extraire VHF, places visiteurs, tirant, abri, services, téléphone — null si inconnu, jamais inventé | Schéma JSON (canal VHF, places, tirant, protection, services, téléphone, résumé d’avis) |
| Lire le site officiel (ou un premier résultat web s’il n’y a pas d’URL OSM) | httpx + Readability ; DuckDuckGo HTML seulement pour NIM / OpenRouter si pas de tag site |
| Premier extracteur, le moins cher | NVIDIA NIM rôle `page` : DeepSeek-V4 Pro → gpt-oss-20b → Muse |
| Si NIM off ou vide | OpenRouter ; garde-fou crédit |
| Dernier recours payant, uniquement si un site OSM officiel existe | TinyFish Agent — pas Claude |
| Sinon ce qu’OSM sait déjà | Tags `vhf`, `capacity`, `depth` / `draught`, `phone`, shower/toilets/eau/élec/fuel/wifi |

### Mouillages

| Étape | Outils |
| --- | --- |
| Trouver les mouillages naturels et postes le long de la route officielle, pas un dump mondial | GeoJSON Berry-Mappemonde ; Overpass seulement |
| Couvrir les approches d’escale | Overpass `around:` par waypoint, rayon 10 NM |
| Couvrir la bande maritime | Points tous les 25 NM ; bboxes ±25 NM |
| Ne garder que les objets mouillage OSM | `seamark:type=anchorage` ; `anchor_berth` ; baie nommée ; `leisure=anchorage` |
| Fusionner les doublons et classer par proximité d’escale | Nom normalisé + geohash ; priorité vs escales / waypoints |

---

## Capitaineries

Recenser les **bureaux** de capitainerie (le bâtiment, pas le plan d’eau ni la marina) dans le monde, pour en tirer téléphone et canal VHF utilisables par un skipper, sans jamais les rattacher aux marinas.

### Dump mondial

| Étape | Outils |
| --- | --- |
| Balayer le monde tuile par tuile, reprisable, sans vider la base | Overpass ; grille `WORLD_TILES` ; curseur `world_harbour_master` |
| Ne garder que les objets bureau de capitainerie | `office=harbour_master` ; `seamark:building:function=harbour_master` ; `harbour=harbour_master` |
| Lire téléphone et VHF déjà écrits (jamais inventés) | Tags `phone` / `contact:phone` ; `vhf` / `comcha` / canal seamark ; regex sur descriptions |
| Superposer les bureaux SHOM (France + outre-mer seulement) | WFS SHOM : `buisgl_point` FUNCTN=2, `smcfac_point` CATSCF=6 |
| Coller un SHOM sur un OSM proche, sinon le garder orphelin | Fusion ≤ 0,25 km |
| Superposer les bureaux NOAA (cartes ENC US) | NOAA ENC Direct : FUNCTN=2 sur points et centroïdes d’aires |
| Coller un NOAA sur un bureau déjà en base, sinon orphelin | Fusion ≤ 0,25 km sur OSM ou SHOM déjà présents |

### Enrichissement téléphone / VHF

| Étape | Outils |
| --- | --- |
| Reprendre tags OSM / SHOM / NOAA ; s’arrêter si téléphone **et** VHF sont déjà là | Tags uniquement |
| Ne chercher sur le web que s’il y a un site officiel, un nom distinct, ou un GPS | Site OSM ; nom hors libellés génériques ; lat, lon |
| Trouver des pages de contact (URL officielle d’abord) | TinyFish Search ; si vide ou sans clé → DuckDuckGo HTML |
| Télécharger les pages et extraire tél / VHF ; s’arrêter dès que les deux champs sont remplis | TinyFish Fetch ; si bloqué → Readability + BeautifulSoup ; regex |
| S’il reste un trou **et** du texte de page | NVIDIA NIM chaîne `page` : DeepSeek-V4-Pro → gpt-oss-20b → Muse |
| S’il reste un trou | OpenRouter — pas de Claude |
| Dernier recours, uniquement s’il existe un site officiel | TinyFish Agent sur cette URL seulement |

---

## Aires marines protégées

Afficher les polygones d’AMP sur la carte (façade, pas le monde) et, pour chaque site, coller **deux pages distinctes** : le site institutionnel du gestionnaire (`manager_url`) et les procédures de visite / entrée / permis / mouillage (`visit_url`). La page de visite n’est jamais la homepage gestionnaire (même hôte autorisé, autre chemin).

| Étape | Outils |
| --- | --- |
| Ne charger la couche qu’une fois zoomé sur une façade, pas un continent | Zoom ≥ 5 ; bbox trop large → rien |
| Servir d’abord les polygones déjà en cache si la tuile est encore bonne | MongoDB `amp_sites` + `amp_tiles` (TTL 30 j.) |
| Sinon télécharger les polygones ProtectedSeas dans la bbox | ArcGIS FeatureServer Navigator ; upsert `amp_sites` |
| Coller l’URL du gestionnaire | Champ ProtectedSeas `url` (Website) |
| Voir si ProtectedSeas a déjà écrit une page visite | Heuristique : `other_helpful_links`, extras Website / purpose ; jamais égal à `manager_url` |
| Avant le web, recharger les fiches attributs (sans polygone) | ArcGIS sans géométrie (`SITE_ID`, `url`, `other_helpful_links`, `purpose`) |
| Relancer l’heuristique extras / labels Website | Choix local, sans TinyFish |
| Lire le site du gestionnaire pour extraire une sous-page visite | TinyFish Fetch sur `manager_url` ; scoring sans juge LLM ; sauté si pas de clé TinyFish |
| Si Fetch n’a rien, chercher d’abord sur le site, puis sur le web ouvert | TinyFish Search : `site:{hôte}`, puis requête ouverte ; jamais la homepage |
| Faire choisir l’URL parmi les hits Search (pas après Fetch) | NVIDIA NIM (JSON) → OpenRouter → Claude Haiku en dernier ; l’URL doit déjà être dans la liste |
