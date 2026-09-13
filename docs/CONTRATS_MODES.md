# Contrats des modes

**Ce que je cherche à faire.** Transformer le web maritime vivant en une base géospatiale fiable, posée sur une carte mondiale : sites d’action accessibles en bateau, ports d’entrée officiels, marinas, capitaineries, aires protégées — sans confondre un siège, une page institutionnelle ou un port commercial avec ce dont un plaisancier a besoin.

Les cinq modes ont été câblés séparément. Des jobs qui posent **la même question** n’utilisent pas les mêmes outils. Ce document recadre les pipelines sur **7 familles** (pas 5 : « qualification » ne doit pas devenir un fourre-tout), puis nomme les jumeaux à faire converger.

## Ce que chaque mode cherche

| Mode | Contrat |
| --- | --- |
| **Projets** | Trouver les projets de conservation marine financés par des fondations, extraire le **lieu d’action** (un GPS par page, pas le siège), n’en garder que ce qui est accessible en bateau, scorer (S_ocean), écrire un run isolé — sans vider la carte live. |
| **Ports d’entrée** | Pour **chaque polygone VLIZ** (`mrgid`, jamais un pays), retrouver la page ou le PDF d’État qui liste les ports d’entrée plaisance, et n’écrire un GPS que s’il tombe dans *ce* polygone. Top-down : polygone → liste. Bottom-up : lieu déjà connu → preuve, et catalogue entier si la page en est un. Noonsite, OSM et le WPI sont des signaux / contre-liste, pas une preuve. Publication carte = revue / Gold. |
| **Marinas** | Annuaire mondial `leisure=marina` (identité OSM stable), signal Google `/maps/place/` s’il existe vraiment, contacts et services **sans inventer**. Mouillages OSM à part, le long de la route. Runs isolés. |
| **Capitaineries** | Recenser les **bureaux** (le bâtiment, pas le plan d’eau ni la marina), en tirer téléphone et VHF, sans jamais les rattacher aux marinas. |
| **AMP** | Polygones ProtectedSeas sur une **façade** (pas le monde), et **deux URL distinctes** : gestionnaire (`manager_url`) vs visite / entrée / permis / mouillage (`visit_url`). La visite n’est jamais la homepage gestionnaire. |
| **Science** | Localiser les jeux de données océanographiques des catalogues officiels (Sextant/SISMER, ODATIS, EDMED SeaDataNet), les flotteurs Argo actifs et les tracés de campagnes CSR, chacun avec le **lien direct vers sa fiche portail**. Couches WMS EMODnet en fond (bathymétrie, substrat, câbles). Moisson par API structurées (JSON GeoNetwork, SPARQL, ERDDAP) — jamais de LLM ni de scraping. |
| **Climatologie** | Atlas mensuel sourcé (CMEMS + IBTrACS) : vent (roses), houle P50/P90, courant de surface, pistes cycloniques. Chaque objet porte `kind: climatology`. Pas de LLM ni de prévision déguisée. Pas de Review / Gold en V1. |

Légende des jobs web : **P** Projets swarm · **TD** PoE top-down · **BU** PoE bottom-up · **MM** Marinas Maps · **ME** Marinas enrich · **CE** Capitaineries enrich · **AV** AMP visit.

Les dumps OSM (marinas, capitaineries, mouillages), les polygones AMP et la moisson Science n’enchaînent pas les 7 familles. Ce n’est pas un trou : ce n’est pas le même objet.

---

## 1. Recherche — où est la page ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | Découvrir les URL de projets sur chaque listing | Crawler httpx + BeautifulSoup sur un **MasterSeed déjà connu** ; TinyFish **Agent** si 0 URL |
| TD | Chercher l’URL d’État qui porte la liste | SearXNG + Serper ; TinyFish Search selon variante ; OpenRouter `:online` en dernier |
| BU | Chercher la page d’État de ce nom | **`search_named`** : TinyFish Search paginé ; `serp_filter` ; DuckDuckGo si pas de clé |
| MM | Ouvrir le lien Maps et ramasser `/place/` | TinyFish **Fetch** d’une URL Maps **déjà construite** ; Search sauté |
| ME | Trouver un site s’il n’y a pas de tag OSM | **`search_named`** : TinyFish Search ; `serp_filter` ; DuckDuckGo si pas de clé |
| CE | Trouver des pages de contact | **`search_named`** (même outillage) ; ranking métier ensuite |
| AV | Chercher visite `site:` puis web ouvert | **`search_named`** ; DuckDuckGo si pas de clé ; pas SearXNG |

## 2. Filtre de source — cette URL a-t-elle le droit d’être lue ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | Écarter contact / dons / news du listing | Liste noire de chemins **dans le crawler**, pas `serp_filter` |
| TD | Domaines d’État + jeter forums / OTA | Whitelist ISO2 + `serp_filter` + classifieur ML SERP |
| BU | Whitelist d’abord, puis sans si 0 hit | `include_domains` dans Search ; `url_allowed` ; **`serp_filter`** |
| MM | Une fiche marina proche, pas un resto | Nom / slug + 8 km |
| CE | Ignorer réseaux / OTA | **`serp_filter`** ; ranking `_url_rank` |
| AV | Homepage interdite ; hits Search jugés | `serp_filter` **puis** score local **puis** `ask_yes_no` |

## 3. Lecture — quel texte a-t-on ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P + TD | Extraire pages et PDF | **`read_url`** → `extract_cascade` : httpx, trafilatura ∥ Readability, PyMuPDF / Tesseract, Playwright, Jina ∥ TinyFish Fetch, Wayback |
| BU | Télécharger les hits whitelistés | **`read_url(prefer_fetch=True)`** : Fetch, cascade si texte inutilisable ; Agent si `bot_blocked` |
| ME | Lire le site officiel | **`read_url`** (cascade : PDF, HTML, Playwright) |
| CE | Télécharger les pages contact | **`read_url(prefer_fetch=True)`** : Fetch, cascade si vide |
| MM | Lire la page Maps rendue | TinyFish Fetch seulement (DOM JS Maps — hors cascade) |
| AV | Lire le `manager_url` | **`read_url(prefer_fetch=True, keep_if_links=True)`** ; scoring **sans** LLM |

P, TD, BU, ME, CE et AV passent par `read_url`. MM reste Fetch-only (fiche `/place/`).

## 4. Filtre de contenu / objet — est-ce le bon objet ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | Projet marin, puis accessible en bateau | Gatekeeper ML → `ask_yes_no` (rôle `json`, prompt marin) ; puis `site_publishable` |
| TD | L’objet « port » sort à l’extraction (le filtre fort est la source d’État) | Parseur catalogue / NER plus tard |
| BU | Juger seulement le résidu | `ask_yes_no` (rôle `judge`, prompt plaisance / cargo) |
| Dump marinas | Marina de plaisance | Overpass `leisure=marina` |
| Dump capitaineries | Bureau, pas plan d’eau | Overpass `office=harbour_master` (+ seamark / harbour) |
| Mouillages | Objet mouillage | Tags Overpass anchorage / baie nommée |
| AV (Fetch) | Lien visite dans le HTML | Score heuristique, pas de juge |
| AV (Search) | Bonne page visite | `ask_yes_no` (rôle `json`, prompt visite) ; URL parmi les candidates |

P, BU et AV (Search) passent par `ask_yes_no`. Le dump OSM et le juge LLM ne sont pas la même implémentation ; la **question** est la même.

## 5. Extraction structurée — quels champs ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | Nom, lieu, S_ocean, partenaires | NIM `extract` → OpenRouter → Claude ; heuristique |
| TD | Noms de ports (+ lat/lon dans le texte) | Parseur catalogue d’abord ; NIM `extract` / `legal` ∥ spaCy ; Claude en dernier |
| ME | VHF, places, tirant, services, tél | **`run_page_enrich`** : tags ; regex tél/VHF ; NIM `page` → OpenRouter ; Agent si site officiel |
| CE | Téléphone, canal VHF | **`run_page_enrich`** (même ordre) ; schéma contact seulement |
| AV | Pas des champs métier : une URL | Liens extraits du Fetch ; pas de schéma JSON page |

ME et CE sont le jumeau « JSON sur du texte de page » (`page`). P et TD sont le jumeau « JSON métier sur un corpus long » (`extract`).

## 6. Géocodage — ce point est-il dans le bon espace ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P | GPS du lieu d’action | **`geocode_name`** Nominatim **∥** GeoNames ; départage LLM si désaccord ; havre ≤ 15 km (`site_publishable`) |
| TD | Coller le port dans **ce** polygone | **`geocode_port_dual`** (même appel parallèle) ; départage LLM ; si les deux annuaires sont muets : **`llm_geocode_port`** puis in-EEZ / 15 km / rivière 400 km |
| BU | Géocoder les noms sans point | **Le même** `geocode_port_dual` + `llm_geocode_port` si muets + filtre polygone |
| MM / dumps / AMP | — | GPS déjà dans OSM / SHOM / NOAA / ProtectedSeas |

P et PoE partagent `geocode_dual` (Nominatim ∥ GeoNames). Les tests d’espace restent distincts : havre (`site_publishable`) vs polygone VLIZ (`classify_poe_point`).

## 7. Identité / doublon — est-ce déjà là ?

| Job | Phrase | Outils aujourd’hui |
| --- | --- | --- |
| P + TD | Fusionner deux fiches du même lieu | `same_site` (`app.core.dedup`) : 500 m + similarité 60 % / 90 % |
| BU catalogue | Noms déjà sur la liste : juge sauté | Identité **de nom dans un catalogue**, pas un merge GPS |
| Dump marinas | Upsert | `osm_id` |
| Dump capitaineries | Coller SHOM / NOAA sur OSM | `find_building` : 0,25 km, distance seule, pas de nom |
| Mouillages | Doublons de corridor | nom + geohash6 |
| AMP carte | Ne pas retélécharger | Cache tuile 30 j. (pas un merge d’entités) |

---

## Jumeaux réels (à faire converger)

Un jumeau, dans ce document, n’est pas « deux modes qu’il faudrait fusionner ». C’est deux morceaux de code qui se posent **la même question** — où est la page, quel texte a-t-on, est-ce le bon objet — et qui, parce qu’ils ont été écrits à des semaines d’écart, ont chacun réinventé leurs outils. Les faire converger, c’est partager la brique technique. Ce n’est pas mélanger les contrats produit : une marina n’est toujours pas un port d’entrée, une aire marine protégée n’est toujours pas un projet de conservation.

Chacun des six points ci-dessous est un projet de modification. Il raconte d’abord ce que le code fait aujourd’hui, ensuite pourquoi c’est un vrai problème (et pas seulement du code moche), ensuite ce qu’on changerait, et pourquoi ce changement est justifié — y compris ce qu’on refuse de coller ensemble.

### 1. Lire une URL : une seule porte d’entrée, pas cinq lecteurs

Dès qu’on a une adresse web, on a besoin du **texte** de la page (ou du PDF). C’est la même question partout. Pourtant le chemin n’est pas le même selon le mode.

Le swarm Projets et le bras top-down des ports d’entrée passent par une cascade d’extraction (`extract_cascade`). On télécharge d’abord simplement. Si c’est du HTML, on en tire le texte. Si c’est un PDF, y compris un scan, on l’ouvre (et on le lit à l’OCR si besoin). Si la page n’est que du JavaScript, on ouvre un vrai navigateur. Si le site bloque, on essaie un miroir. Le bras bottom-up des ports d’entrée, l’enrichissement des capitaineries, la recherche de page de visite des AMP, et le job Google Maps des marinas, eux, appellent surtout TinyFish Fetch : un seul coup, le texte rendu, et c’est tout. L’enrichissement marina est encore plus mince : un téléchargement HTTP plus un extracteur de lisibilité, sans PDF ni navigateur.

Le problème se voit concrètement. Un décret d’État en PDF, ouvert par le top-down, est lu. Le même décret, ouvert par le bottom-up, peut revenir vide, parce que Fetch n’est pas une cascade PDF. Un site de marina tout en JavaScript passe au swarm (le navigateur local s’en occupe) et échoue à l’enrichissement marina. On paie donc plus cher d’un côté, ou on rate l’information de l’autre, pour une question identique : « donne-moi le texte de cette URL ».

Le changement proposé est donc une seule porte d’entrée pour lire une URL. Dès que TinyFish Fetch ne rend pas un texte utilisable — surtout un PDF ou un site JavaScript — le bottom-up, les marinas et les capitaineries rentreraient dans la même cascade que les Projets et le top-down. On ne supprime pas Fetch : il reste le bon outil quand on a besoin du DOM après JavaScript, typiquement la fiche Google Maps `/place/`, que la cascade n’a pas vocation à parser comme un décret. On n’allume pas non plus le navigateur local à chaque Fetch réussi : il ne sert que si le HTML simple et Fetch ont déjà échoué. Sinon le coût explose, et on n’a rien gagné.

**Fait.** Porte `app.core.extract.read_url` / `read_urls`. Fetch d’abord pour BU, CE, AV. Cascade dès que Fetch est vide. Chromium seulement après HTML simple et Fetch. Maps : Fetch seulement. `extract_cascade` : magie `%PDF-`, Content-Type / Content-Disposition ; un HTML d’erreur sous une URL `.pdf` n’est plus un PDF.

### 2. Chercher « la page officielle de ce nom » : même outillage, questions métier distinctes

Quatre jobs cherchent la page officielle d’un **lieu déjà nommé** : un port, une capitainerie, une aire protégée, une marina sans site dans OpenStreetMap. C’est la même question humaine. Chacun a pourtant sa recette.

Le bottom-up n’a que TinyFish Search, filtré par une liste de domaines d’État. S’il n’y a pas de clé TinyFish, il n’y a pas de recherche du tout. Les capitaineries font TinyFish Search, puis DuckDuckGo si ça revient vide, et jettent Facebook ou Tripadvisor avec une petite liste maison, au lieu du filtre de résultats de recherche déjà partagé ailleurs. Les AMP font TinyFish Search, passent les résultats dans ce filtre commun (`serp_filter`), puis un score, mais n’ont pas de filet DuckDuckGo. L’enrichissement marina, s’il n’a pas de tag site, tape DuckDuckGo et ignore TinyFish Search.

Ce n’est pas la question du bras top-down des ports d’entrée. Celui-là ne cherche pas « la page de *ce* port ». Il cherche une **liste réglementaire pour tout un polygone de zone économique exclusive**. Il a donc besoin de SearXNG, de Serper, parfois d’un modèle avec accès web. Coller SearXNG sur une marina ou une AMP serait le mauvais outil : on n’y cherche pas un décret de ports d’entrée.

Le changement proposé n’aligne que les recherches **nommées**. On commencerait par TinyFish Search, on passerait les résultats dans le même filtre déjà utilisé par le top-down et les AMP pour écarter forums et sites d’annonces, et on garderait DuckDuckGo uniquement comme filet quand la clé TinyFish manque — exactement ce que les capitaineries font déjà, et que le bottom-up et les AMP n’ont pas. Les requêtes et les listes de domaines resteraient propres à chaque mode : un port d’entrée n’est pas une page de permis d’aire protégée. On changerait l’outillage, pas la question métier. On n’installerait pas SearXNG sur l’enrichissement marina, capitainerie ou AMP.

**Fait.** Porte `app.core.search.search_named`. TinyFish Search d’abord (paginé si le caller le demande), puis `serp_filter`. DuckDuckGo HTML seulement si la clé TinyFish manque — pas un second avis après un TinyFish vide. Requêtes, `include_domains` / `exclude_domains` et ranking restent propres à BU / CE / AV / ME. Pas de SearXNG sur ces jobs. Filet DDG : opérateur `site:` + filtre d’hôte pour que la whitelist survive sans API TinyFish.

### 3. Enrichir une marina ou une capitainerie : le même ordre des étapes, pas le même formulaire

Les deux jobs d’enrichissement font le travail le plus proche du dépôt : extraire un téléphone, un canal VHF, parfois des services, **sans jamais inventer** un champ. Ils partagent déjà le même modèle NVIDIA pour lire une page, OpenRouter avec un contrôle de crédit, DuckDuckGo, et la petite fonction de lecture HTML. L’Agent TinyFish est le dernier recours des deux.

Ils ne font pourtant pas les étapes dans le même ordre, et ce n’est pas justifié par le métier. Les capitaineries cherchent le web tout de suite, parce qu’elles n’ont souvent pas d’adresse dans OpenStreetMap. Les marinas lisent d’abord le tag site, ce qui est plus économique quand le tag existe. Les capitaineries sortent un numéro de téléphone par une règle simple *avant* d’appeler un modèle de langage. Les marinas appellent le modèle d’abord et ne regardent les tags OpenStreetMap qu’à la fin. L’Agent marina peut partir d’une URL trouvée sur DuckDuckGo, donc parfois un Tripadvisor. L’Agent capitainerie n’accepte qu’un site officiel — et c’est cette seconde règle qui est la bonne : un Agent lancé sur une page d’avis invente ou copie n’importe quoi.

On ne fusionnerait pas les deux schémas de données : une marina a des places visiteurs et un tirant d’eau, une capitainerie n’a besoin que du téléphone et du VHF. Ce qu’on partagerait, c’est **l’ordre** des étapes. On partirait des tags déjà là. On ne chercherait le web que s’il manque une URL. On lirait la page. On extrairait par une règle simple ce qui est trivial (un numéro, un canal). On n’appellerait NVIDIA puis OpenRouter que s’il reste un trou. On n’appellerait l’Agent que si l’URL est vraiment officielle. On éviterait ainsi de payer un modèle pour relire un téléphone déjà dans OpenStreetMap, et d’envoyer l’Agent sur un résultat de moteur.

**Fait.** Porte `app.core.enrich.run_page_enrich`. Ordre commun : tags → URL déjà là (`search_named` seulement s’il en manque) → lecture → regex téléphone/VHF → NVIDIA `page` puis OpenRouter s’il reste un trou → Agent TinyFish seulement si l’URL est officielle (`serp_filter`, jamais un hit moteur). Schémas distincts : marina = places visiteurs, tirant, services ; capitainerie = téléphone + VHF. Un champ déjà rempli n’est pas écrasé.

### 4. Dire oui ou non : un même branchement, trois prompts différents

Trois jobs disent « j’accepte » ou « je refuse » après avoir vu du texte ou des résultats de recherche. Chacun a son propre prompt et son propre rôle NVIDIA. Le gatekeeper des Projets demande si la page est un projet marin. Le juge bottom-up demande si *ce lieu* est un port d’entrée plaisance, ou du cargo. Le juge AMP demande, parmi une **liste d’URL déjà trouvées**, laquelle est une page de visite — et il n’a pas le droit d’en inventer une. Cette dernière contrainte est précieuse : c’est elle qui empêche d’halluciner une adresse de visite.

Le problème n’est pas que les questions métier soient différentes. Elles doivent le rester. Le problème, c’est que chaque mode a recâblé l’appel au modèle, les replis OpenRouter et Claude, et le format de la réponse. Quand on corrige un bug d’appel — un délai trop court, un JSON cassé, le filet Claude — on le corrige trois fois, ou une seule.

Le changement proposé est un adaptateur commun, pas un juge unique. On enverrait un prompt, et on recevrait un objet du type « j’accepte ou je refuse, éventuellement cette URL parmi les candidates, voici pourquoi ». Les trois textes de prompt resteraient trois textes. On n’écrirait pas un juge « projet ou port ou aire protégée » : ce serait plus faible que chaque spécialiste, et ça mélangerait des objets que le produit refuse de confondre.

**Fait.** Porte `app.core.judge.ask_yes_no`. NVIDIA → OpenRouter → Claude. Réponse `YesNo` (accepté / refusé / URL parmi les candidates / raison). Trois prompts inchangés. Rôles NVIDIA distincts : `json` (gatekeeper, AMP, sans Flash) et `judge` (bottom-up, Flash en dernier). Une URL hors liste ou égale au `manager_url` est un refus — c’est le filet anti-hallucination des AMP, désormais dans l’adaptateur. `bool("false")` n’est plus un oui. Pas un juge unique « projet ou port ou AMP ».

### 5. Deux points proches : ce n’est pas toujours « le même objet »

Les dumps marinas, capitaineries et mouillages partagent déjà Overpass et la grille mondiale. Il n’y a pas de projet d’unification Overpass : c’est déjà le cas. Le piège serait d’y coller la déduplication des projets et des ports d’entrée (cinq cents mètres et un nom proche).

Quand on fusionne deux projets à moins de cinq cents mètres, on dit : c’est **le même site d’action**, on enrichit une seule fiche. Quand on colle un point du SHOM ou de la NOAA sur un objet OpenStreetMap à deux cent cinquante mètres, on dit : deux cartes officielles parlent du **même bâtiment**, on superpose un calque. Ce n’est pas la même décision. Réutiliser la déduplication des projets pour les capitaineries collerait des bureaux trop loin, ou refuserait un calque légitime.

Ce point n’est donc pas un chantier d’unification. C’est un **garde-fou**. Même famille « identité » dans la taxonomie, deux règles, deux codes. On ne les mélange pas.

**Fait.** Portes `app.core.identity.same_site` et `app.core.identity.find_building`. `same_site` reste `app.core.dedup` (500 m + similarité 60 % / 90 %) — fusion de fiches Projets / PoE. `find_building` est le calque 250 m, distance seule, premier plus proche (plus de last-wins), préfiltre degré, rayon lu dans `capitaineries.merge_km`. Un nom différent n’empêche pas le calque. Un nom proche à 400 m ne colle pas deux bureaux. Pas de `is_duplicate` sur les capitaineries.

### 6. Géocoder un nom : un même appel aux deux annuaires, deux tests d’espace ensuite

Les Projets et les ports d’entrée demandent tous les deux à Nominatim et à GeoNames où se trouve un nom. Les Projets les appellent l’un après l’autre, puis un modèle de langage si besoin, puis vérifient qu’on est en mer ou dans un havre à moins de quinze kilomètres. Les ports d’entrée les appellent en parallèle, départagent au modèle s’ils ne sont pas d’accord, puis exigent que le point tombe dans **ce** polygone de zone économique exclusive — pas « en France », *ce* polygone VLIZ.

Les fournisseurs sont les mêmes, et le désaccord Nominatim / GeoNames est le même : c’est pour cela qu’un seul appel « demande aux deux, départage s’il le faut » est justifié. Ce qui ne doit pas fusionner, c’est le **test d’espace** ensuite. Un projet n’a pas à entrer dans un polygone VLIZ. Un port d’entrée n’a pas le droit d’être collé sur Mayotte alors qu’on fiche l’hexagone. On unifierait l’outil de géocodage, pas la géographie du produit.

**Fait.** Porte `app.core.geo.geocode_name` / `geocode_dual`. Nominatim ∥ GeoNames, départage `arbitrate_geocode` si désaccord, aucune troisième coordonnée. `geocode_port_dual` réutilise `pack_geocode_dual`. Projets : `site_publishable` (havre ≤ 15 km) dans `apply_havre` ; `llm_geocode` (site de conservation) seulement si les deux annuaires sont muets. PoE : polygone VLIZ inchangé ; si les deux annuaires sont muets, `llm_geocode_port` (prompt port d’entrée, pas récif/AMP) puis le même test VLIZ. Un GPS inventé hors de *ce* polygone n’est pas écrit. Pas de `classify_poe_point` sur un projet. Pas de `llm_geocode` Projet sur un port.

### Dans quel ordre, et pourquoi

On commence par la **lecture** (jumeau n°1 : **fait**), parce que c’est là que bottom-up, marinas et capitaineries perdent aujourd’hui des PDF et des pages JavaScript, et parce que tout le reste — enrichissement, juge — s’appuie sur un texte déjà là. Ensuite la **recherche nommée** (jumeau n°2 : **fait**), pour que capitaineries, AMP, marinas sans site et bottom-up cessent de réinventer le filet (TinyFish, le filtre de résultats, DuckDuckGo si la clé manque). Ensuite l’**ordre d’enrichissement** marina / capitainerie (jumeau n°3 : **fait**), qui devient simple une fois lecture et recherche stables. Le **juge** commun (jumeau n°4 : **fait**) : un branchement `ask_yes_no`, trois prompts. Le **garde-fou identité** (jumeau n°5 : **fait**) : `same_site` n’est pas `find_building`. Le **géocode** (jumeau n°6 : **fait**) : les Projets réutilisent l’appel parallèle des ports d’entrée, sans toucher à la règle du havre.

On ne met pas SearXNG dans l’enrichissement marina ou capitainerie : ce n’est pas une liste d’État par zone économique. On ne remplace pas Overpass par une recherche web pour les dumps. On ne traite pas le cache de tuiles AMP comme une fusion de fiches. On ne lance pas le navigateur local sur chaque TinyFish Fetch qui a déjà renvoyé du HTML.

