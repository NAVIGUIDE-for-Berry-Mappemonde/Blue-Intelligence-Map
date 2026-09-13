# Hackathon Nebius × NVIDIA — synthèse et orientations

**Projet cible :** Blue Intelligence + NAVIGUIDE
**Track visé :** Best Apps and Agents
**Nom de travail :** Expedition Clearance Copilot (Clearance Brief + copilote de route)
**Date de cette synthèse :** 13 septembre 2026
**Deadline soumission :** vendredi 30 octobre 2026, 10:00 PT
**Jugement :** 1–15 décembre 2026 · résultats vers le 11 janvier 2027

Ce document fige la discussion du 12–13 septembre 2026 : règles, recherches (Token Factory, Tavily, Nemotron, code), décision produit, contraintes réelles, et plan d’exécution. Mis à jour le 13 septembre (crédits reçus, RDV Toronto). Ce n’est pas une soumission Devpost — c’est le cahier interne.

---

## 1. Décision en une phrase

On soumet **un seul produit** (track Best Apps), pas la plateforme entière : un agent de formalités / notices sur une jambe de route, avec **Token Factory + Nemotron (Nano/Lightning + Ultra juge)** et **Tavily runtime**. L’esprit « Coding / Sandboxes » reste un stretch goal dans le même projet. On ne vise pas Personal AI ni Physical AI.

---

## 2. Le hackathon, ce qu’il faut retenir

- **Sponsor :** Nebius B.V. · **Admin :** Devpost
- **Page :** https://nebiusglobalaihackathon.devpost.com/
- **Inscriptions :** ~3 660 au 12 septembre 2026
- **Éligibilité :** majorité légale ; la France est OK (exclus : Brésil, Québec, Russie, Crimée, Cuba, Iran, Corée du Nord, sanctions OFAC).
- **Événement IRL :** Builders & Brews **Toronto, mardi 29 septembre 2026** (pas Paris). Crédits extra possibles + éligibilité City Winner 500 $.

### Obligation technique (étape 1, éliminatoire)

Le projet doit :

1. Faire un **appel runtime** à Token Factory **ou** tourner sur Nebius AI Cloud (Serverless Jobs, Endpoints ou DevPods).
   **NVIDIA NIM (`integrate.api.nvidia.com`) ne compte pas.**
2. Utiliser **au moins un modèle NVIDIA open source** (Nemotron, GR00T, Cosmos, Sonic).
3. Coller vraiment au track — pas un rebrand superficiel.

### Critères étape 2 (poids égal)

| Critère | Question |
|---|---|
| Technological Implementation | Le stack Nebius + NVIDIA est-il au cœur ? |
| Design | Produit fini, pas une preuve de concept |
| Potential Impact | Problème réel, public réel, preuve dans la démo |
| Quality of the Idea | Usage **non évident** de Token Factory / Nemotron |

Les juges **n’ont pas l’obligation de tester le code**. Vidéo + texte + images pèsent énormément.

**Update officielle :** « push past the obvious » — un wrapper ChatGPT / un chatbot Nemotron = perdu.

### Prix (un projet = Overall **ou** Track, plus **un** bonus)

| Prix | Montant | Note |
|---|---|---|
| Grand Prize / 2e / 3e | 20 000 $ / 10 000 $ / 6 000 $ | Objectif |
| Gagnant de track | Jetson Orin Nano | Consolation si pas Overall |
| Best Use of Tavily | 3 000 $ | Appel **runtime** Tavily |
| City Winner | 500 $ × 20 | Toronto 29 sept. — **un seul bonus** : Tavily **ou** City |
| Most Valuable Feedback | 100 $ + swag × 10 | Section feedback soignée |

On vise **Grand Prize + Tavily**. Le feedback se remplit quand même (peut ne pas stacker).

### Soumission Devpost (check-list)

- Un seul track
- Démo URL qui marche (login de test si besoin)
- Repo **public** + licence MIT / Apache / MPL visible dans About
- README **anglais** : setup, où est Nemotron, où Token Factory accélère, où est Tavily
- Vidéo YouTube **publique**, **≤ 3 min**, projet qui tourne, sans musique copyright
- Textes en anglais (ou traduction)
- Feedback Nebius / NVIDIA
- Si projet existant : paragraphe « what we significantly updated » pendant la période (26 août – 30 oct.)
- Testable jusqu’au **15 décembre 2026**

---

## 3. Orientations validées

### Combo produit : 1 + 2, esprit de 3 en stretch

1. **Clearance Brief** — agent de formalités / ports d’entrée / ZEE, sourcé, juge d’évidence Ultra.
2. **Copilote de route NAVIGUIDE** — Lightning en tool calls (Tavily, Copernicus, AMP, ZEE, polaires), **un** Ultra pour le go/no-go.
3. **Routing Lab / ConTree** — **pas** une 2ᵉ soumission Coding. Stretch : l’agent exécute des tests géospatiaux (point-in-polygon, AMP) dans un Sandbox ConTree, 3 branches visibles. Si le cœur n’est pas poli mi-octobre, on s’en passe.

**Tracks écartés**

- Personal AI (NemoClaw / Hermes) : Design faible vs notre carte ; compat Nemotron encore fragile.
- Physical AI : pas de robot ; vidéo 1 min hardware obligatoire.
- Coding seul : trop concurrentiel, dépend d’un moteur de routage encore prototype.

### Git : les deux, rôles distincts

Le dépôt `NAVIGUIDE-for-Berry-Mappemonde/Blue-Intelligence-Map` est **déjà public**, licence **MIT détectée** (PR #78, double MIT/Apache sur `origin/main`).

| Où | Rôle |
|---|---|
| Branche `hackathon/clearance-brief` dans ce monorepo | Développement (réutilise ZEE, geo, carte, pipelines) |
| Dossier autonome `clearance-brief/` | Facilite l’export |
| `main` | Production VPS — merge seulement ce qui doit être live (feature flag) |
| Dépôt public dédié, ex. `…/clearance-brief` | URL Devpost : README EN, historique 100 % période hackathon, pas de secrets |

Le dépôt dédié se crée à la main (l’agent GitHub est en lecture seule). Export plus tard (`git subtree split` ou copie propre).

---

## 4. Contraintes réelles (et comment on les retourne)

### 4.1 Ports d’Entrée peu reviewés (11 polygones Gold)

**Ce n’est pas bloquant.** La démo 3 min n’a besoin que des jambes qui traversent ces 11 zones.

**C’est un atout.** Les 11 zones Gold = vérité terrain pour évaluer « Tavily → Nano extrait → Ultra juge » (précision, ports hallucinés rejetés). Chiffre à mettre dans le README et la vidéo.

**Pitch produit :** la review manuelle est lente ; l’agent produit des dossiers sourcés qui **accélèrent** Review → Gold. On ne prétend pas que les données sont officielles. Le disclaimer « ne convient pas à la navigation » reste.

### 4.2 Crédits reçus (13 septembre 2026)

Comptes ouverts sur l’organisation **Berry-Mappemonde**. Inventaire lu dans les consoles :

| Service | État observé | Usage prévu |
|---|---|---|
| **Nebius Token Factory** | Solde **60 $** ; essai 29 j / 30 j encore à **1,00 $ / 1,00 $** | Inférence Nemotron (Nano/Lightning volume, Ultra juge). Variable d’env : `NEBIUS_API_KEY`. |
| **Tavily** (plan Researcher) | **0 / 10 000** crédits du plan mensuel ; add-on **0 / 3 125** (Builders) ; clé déjà créée | Search + Extract + Research mini runtime. Ne pas allumer « Pay as you go » tant que le quota suffît. |
| **Toloka** | Solde **50 $** (collecte / labélisation / fine-tune) | Hors cœur hackathon. Utile plus tard pour labéliser les 11 zones Gold vs sorties agent. |
| **Tendem** | Promo **50 $** (12 sept. 2026) | Hors cœur hackathon. Ne pas en dépendre pour la soumission. |

Discipline de dépense (inchangée) : Nano/Lightning = 0,06 $ / M tokens in — le volume est presque gratuit. Ultra (1 $ / 3 $ par M) : **un Ultra par action utilisateur visible**, jamais dans la boucle d’outils. Tavily : Research **mini** seulement, pas de `pro` au clic, pas de crawl sans `limit`.

La clé Token Factory n’est **pas** encore dans le code (et ne doit jamais aller dans le frontend ni dans git). Créer la clé dans Token Factory → API keys, la poser en env sur le Mac / le VPS.

Toronto (29 sept.) peut encore débloquer des crédits extra.

### 4.3 Moteur de routage NAVIGUIDE encore prototype

L’option 2 **lit** les sorties existantes (segments, anti-shipping, Copernicus, VMG) ; elle n’exige pas un moteur parfait, seulement une jambe de démo qui marche (déjà le cas en live).
C’est la raison de **ne pas** faire l’option 3 en soumission séparée.

---

## 5. État du code (12 septembre 2026)

Monorepo **2 apps** :

| | Blue Intelligence | NAVIGUIDE |
|---|---|---|
| Rôle | OSINT géospatial (6 modes + Console + Review) | Planificateur de route expédition |
| Prod | blueintelligence.online | www.naviguide.fr (et preview complete.dev) |
| LLM | `backend/app/core/nvidia.py` + `judge.py` + `llm.py` | `naviguide/llm_cascade.py` |

**Chaînes actuelles = NIM hosted, pas Token Factory, pas Nemotron.**

- BI : `NVIDIA_URL = https://integrate.api.nvidia.com/v1/chat/completions`
  Rôles `judge` / `extract` / `legal` / `json` / `page` / `text` : DeepSeek Pro, gpt-oss-20b, Muse, Flash, Kimi.
  `engine_label()` sait taguer `nvidia-nemotron` mais **`CHAINS` n’en contient aucun**.
- NAVIGUIDE : même NIM ; chaîne interactive gpt-oss → Pro → Muse → OpenRouter → Claude.
  LangGraph : Route → Risk → Briefing (~26 s) — le LLM **commente** en ~120–280 mots, il n’appelle pas d’outils web.

**Recherche web actuelle (pas Tavily) :** OpenRouter `:online`, SearXNG, Serper, TinyFish, DuckDuckGo HTML.

**Atouts déjà là (à réutiliser, pas à réécrire) :**

- `zee_crossings.py` — intersection route ∩ ZEE (VLIZ v12, shapely, 4 fallbacks)
- `extract_ports` / `ask_yes_no` / `complete_json_cascade` — extract + juge anti-hallucination
- `poe_pipeline.py` — workflow long (search → whitelist gov → extract → géocode → point-in-EEZ)
- Carte Leaflet / MapLibre, exports GeoJSON versionnés
- NAVIGUIDE : Copernicus, polaires, anti-shipping, couches ZEE/WPI

**À ne pas soumettre tel quel :** toute la plateforme (trop large, FR, « quoi de neuf ? »).
**Risque Stage 1 :** le README distant parle déjà Token Factory / Nemotron alors que le code pointe encore NIM — aligner le code avant le pitch.

---

## 6. Architecture cible

```
Skipper (carte BI / jambe NAVIGUIDE)
        │  GeoJSON route + ZEE + AMP
        ▼
FastAPI « clearance » (VPS ou Serverless Endpoint)
        │
        ├─ Lightning / Nano (eu-north1)     volume, JSON, tools
        ├─ Super (us-central1, optionnel)   briefing bilingue
        └─ Ultra (us-central1)              1× juge d’évidence OU go/no-go
                │
                ├─ Tavily Search / Extract / Research mini  (runtime, citations)
                ├─ Outils existants : point_in_eez, Overpass, VLIZ, polar, Copernicus
                └─ [stretch] ConTree : 3 branches de tests géo, rollback
                ▼
        Carte : pins validés / rejetés + HUD tokens Ultra vs Nano
```

**Règle d’or crédits :** ~7–15 % des appels en Ultra. Afficher le split dans l’UI (preuve qu’on a lu le brief du track).

**Deux `base_url` Token Factory :**

- Contrôle / Nano / Lightning : `https://api.tokenfactory.nebius.com/v1/`
- Super / Ultra : `https://api.tokenfactory.us-central1.nebius.com/v1/`
- Clé : `NEBIUS_API_KEY` (jamais dans le frontend)

**IDs à vérifier le jour J** via `GET /v1/models?verbose=true` (casse significative ; le cookbook ment parfois) :

| Rôle | ID (snapshot 12 sept. 2026) | Prix / M tok |
|---|---|---|
| Volume | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 0,06 / 0,24 |
| Agents rapides | `nvidia/Nemotron-3_5-Lightning` | 0,06 / 0,24 |
| Briefing | `nvidia/nemotron-3-super-120b-a12b` | 0,30 / 0,90 |
| Juge | `nvidia/Nemotron-3-Ultra-550b-a55b` | 1,00 / 3,00 |

Nemotron 3 : raisonnement **ON par défaut**. JSON / tools : `enable_thinking: false` ou `max_tokens` généreux + parser `reasoning_content` **et** `content`. Tag catalogue « JSON mode » : **aucun Nemotron live** — prompt + parseur existant (`parse_json_flexible`). Fine-tune Nemotron sur TF : **non disponible**.

**Tavily (bonus) — runtime essentiel, pas un 4ᵉ crawler.**

On **garde** SearXNG / TinyFish / trafilatura pour le volume. Tavily = vérité officielle live + citations :

1. Search `advanced` + allowlist .gouv / hydrographie + `time_range=week`
2. Extract `advanced` (pages JS / tableaux) — **pas** search+extract des mêmes URL
3. Map puis Crawl si le chemin « formalités » est inconnu
4. Research **mini** (pas pro) + `files=[leg.json]` + `output_schema` + streaming
5. **Ne pas** utiliser `include_answer` (ça court-circuite Nemotron)

Un run démo : ~30–80 crédits. Envelope réel (13 sept.) : **10 000** (plan Researcher) + **3 125** (add-on Builders) ≈ **13 000** crédits Tavily — largement suffisant si on reste en `mini` et on cache par jambe.
`include_domains_mode=filter` pour toute affirmation réglementaire.

---

## 7. Fichiers à toucher (quand on implémente)

**Nouveau**

- `backend/app/core/token_factory.py` (ou évolution de `nvidia.py`)
- `backend/app/core/tavily.py`
- `backend/app/services/clearance_brief.py`
- `backend/app/routers/clearance.py` — `POST /api/clearance/brief`
- `frontend/src/components/ClearanceBriefPanel.js`
- Tests mock Tavily / Token Factory
- `docs/hackathon-nebius-nvidia.md` (ce document)

**Léger**

- `backend/app/config.py`, `backend/.env.example`
- `naviguide/llm_cascade.py` (même bascule)
- `naviguide/.../nodes.py` — nœud tools (phase 2)
- `frontend` Header / carte — entrée démo
- README feature EN + paragraphe « significantly updated »

**Réemploi sans réécrire :** `zee_crossings.py`, `poe_pipeline.py`, `geo.py`, `extract.py`, `judge.py`, `llm.extract_ports`, couches carte NAVIGUIDE.

**Ne pas open-sourcer :** `.env`, dumps Mongo, PMTiles seamap, Review nominatif, clés (`NVIDIA_*`, `NEBIUS_*`, `TAVILY_*`, `TINYFISH_*`, `SERPER_*`).

---

## 8. Vidéo 3 min (structure)

Tout en **anglais**, YouTube public.

| Temps | Plan |
|---|---|
| 0:00–0:20 | Problème skipper : décret / ZEE / notices — **pas** un chatbot |
| 0:20–0:50 | Nano/Lightning extrait (HUD : ID, région, 1,8 s, 0,00X $) |
| 0:50–1:25 | Ultra **rejette** 2 ports sans citation (surlignage) |
| 1:25–2:10 | NAVIGUIDE : Lightning tool-calls Tavily + vent + AMP ; Ultra go/no-go |
| 2:10–2:40 | Token Factory : split ~92 % Lightning / 8 % Ultra |
| 2:40–3:00 | Carte : validés vs rejetés ; « Nebius Token Factory + Nemotron 3 » |

---

## 9. Plan jusqu’au 30 octobre

| Phase | Quoi | Qui |
|---|---|---|
| **Fait** | Comptes + crédits TF (60 $) + Tavily (10k + 3 125) | Humain |
| **Phase 1** | Adaptateur Token Factory + module Tavily (clés en env, pas dans git) | Agent |
| **Cœur** | Clearance Brief sur zones Gold + éval vs 11 polygones reviewés | Agent |
| **Phase 2** | Copilote route NAVIGUIDE (mêmes adaptateur / outils) | Agent |
| **Stretch** | ConTree 3 branches de vérif géo | Si le cœur est poli mi-octobre |
| **29 sept.** | Builders & Brews **Toronto** | Humain |
| **Fin octobre** | Gel, démo hébergée, README EN, vidéo, dépôt d’extraction, soumission | Les deux |

Un seul projet Devpost, un seul README, une seule vidéo.

---

## 10. Sources

- https://nebiusglobalaihackathon.devpost.com/ · /rules · /resources
- https://dev.nebius.com/ · https://dev.nebius.com/builders
- https://docs.tokenfactory.nebius.com/ · https://tokenfactory.nebius.com/api/public/models_info
- https://docs.tavily.com/
- https://developer.nvidia.com/topics/ai/nemotron
- Code : `backend/app/core/nvidia.py`, `judge.py`, `llm.py`, `zee_crossings.py`, `poe_pipeline.py`, `naviguide/llm_cascade.py`

---

## 11. Prochaine action

1. Humain : créer la clé Token Factory (`NEBIUS_API_KEY`) si ce n’est pas déjà fait ; la garder hors git. Aller à Toronto le 29 septembre.
2. Agent : adaptateur Token Factory + `tavily.py`, puis Clearance Brief (plus besoin de mocks pour les appels réels).
