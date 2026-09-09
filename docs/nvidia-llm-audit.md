# Audit des LLM NVIDIA pour Blue Intelligence

**Date :** 2026-09-09  
**Périmètre :** palier d’essai hosted NVIDIA NIM (`POST https://integrate.api.nvidia.com/v1/chat/completions`), clé Developer Program (`NVIDIA_API_KEY`).  
**Session source :** agent Cloud [Modèles NVIDIA gratuits](https://cursor.com/agents/bc-860e6e61-df5a-4b8d-9831-d3c444b11f22) (2026-09-08 06:16 UTC → 2026-09-09), branche `cursor/nvidia-free-models-1f22`, PR [#52](https://github.com/NAVIGUIDE-for-Berry-Mappemonde/Blue-Intelligence-Map/pull/52) fusionnée le 2026-09-09 07:01 UTC.  
**Règle de preuve :** aucun chiffre inventé. Les latences et codes HTTP viennent des sondes du 2026-09-08 (`backend/scripts/probe_nvidia_models.py` et artefacts de session). Les contrats d’API viennent des fiches infer NVIDIA relues le 2026-09-08 et revérifiées le 2026-09-09.

Ce document a deux couches, volontairement séparées :

1. **Fil du chat** — les cinq demandes, ce que l’agent a répondu à chaque tour, y compris les conclusions **fausses** du matin.  
2. **Verdict technique** — ce qui est vrai après correction de méthode, paramétrage infer, et l’état du code sur `main` au 2026-09-09.

---

## 1. Verdict (lire d’abord)

Le catalogue Build n’est pas un index d’inférence live. Trois sources se contredisent :

| Source | Taille observée | Ce qu’elle est |
|---|---|---|
| `GET /v1/models` | 81 ids (55 chat-like) | Index OpenAI **périmé** (yi-large, dbrx, granite… → 404 Function) |
| [llm-apis](https://docs.api.nvidia.com/nim/reference/llm-apis) | 56 ids (mixte chat / guard / NER / translate) | Contrats d’API ; **omet** Muse, Gemma 4, MiniMax M3, Laguna `2.1` |
| [models.md](https://build.nvidia.com/models.md) | « 100 of 102 shown » (page 1 lue ; 2 fiches page 2 non lues, challenge JS) | Fiches marketing **mélangées** : ~20 LLM/VLM, ~80 ASR/bio/image/OCR/CFD |

Sur le **hosted trial** du compte Blue Intelligence, un id catalogue peut être :

- **live** (HTTP 200) ;
- **410 Gone** (essai hosted EOL, fiche encore en ligne) ;
- **404 Function** (NVCF non provisionné — id catalogue mort) ;
- **404 page not found** (slug docs ≠ slug hosted) ;
- **timeout** parce que `response_format=json_object` est envoyé à un modèle **Structured Output: Not supported** ;
- **429 / 503 / 529** (quota ou saturation trial).

**Chaînes NIM en production** (`backend/app/core/nvidia.py`, après PR #52) :

| Usage Blue Intelligence | Chaîne | Pourquoi |
|---|---|---|
| Juge PoE | Pro-0813 → Muse → gpt-oss-20b → Flash-0731 | Pro 4/4 le plus stable ; Muse live **sans** `json_object` |
| Extract PoE | Pro-0813 → Muse → Kimi-K3 | Kimi tient les arrêtés ; 429 trial → pas un juge |
| Décret / gazette | Kimi-K3 → Pro-0813 → Muse | Long contexte / thinking always on |
| JSON générique (gatekeeper, projet, géocode) | Pro-0813 → Muse → gpt-oss-20b | Structured Output sur Pro et gpt-oss |
| Capitaineries (contacts) | Muse d’abord (`secondary_model`), puis OpenRouter | Ajout **après** ce chat (PR capitaineries, déjà sur `main`) |
| Recherche web | **OpenRouter `:online` seulement** | NIM n’a pas de plugin web |
| Marinas | **OpenRouter seulement** | Lecture de page, inchangé |

IDs :

- `deepseek-ai/deepseek-v4-pro-0813` — tête
- `meta/muse-glimmer-30b` — 2ᵉ (pas de `json_object`)
- `openai/gpt-oss-20b` — 3ᵉ JSON / 3ᵉ juge
- `deepseek-ai/deepseek-v4-flash-0731` — 4ᵉ juge
- `moonshotai/kimi-k3` — legal

Alias EOL dans le code : `deepseek-v4-flash` → `…-0731` ; `deepseek-v4-pro` → `…-0813` ; `laguna-xs-2-1` → `laguna-xs-2.1`.

Hors chaîne malgré des pings parfois OK : Laguna (503 capacité), MiniMax M3 (429 + licence carte non-commercial), Lightning (juge Tiwai **faux**), Gemma 4 (hang avec **et** sans `json_object`).

---

## 2. Fil du chat — demandes et réponses

Cinq messages utilisateur. Les tours 3 et 4 étaient déjà en file pendant le tour 2 : l’agent les a commencés avant que les bulles n’apparaissent. Un audit qui lirait seulement l’ordre des bulles sous-estimerait ce recouvrement.

### 2.1 Demande 1 — 2026-09-08 ~06:16 UTC

> teste les modèles NVIDIA disponibles gratuitement

**Ce que l’agent a fait.** Il a constaté un adaptateur NIM déjà présent, écrit `backend/scripts/probe_nvidia_models.py`, listé `GET /v1/models` (81 ids), pingé avec `response_format=json_object`, puis lancé un canari PoE (juge Fort Bay plaisance / Tiwai Point cargo / extract d’un arrêté FR à 5 ports).

**Ce qu’il a répondu (conclusion du matin, commit `abd9c01`).** Minorité d’ids JSON live. **Muse, « l’ancien lecteur principal, ne répond plus »** (timeout 180 s). Laguna saturé (503). Meilleur remplaçant : **DeepSeek-V4-Flash**. Muse et Laguna **remappés vers Flash**. Kimi-K3 conservé pour les gazettes. Environ 40 ids en 404 « Function not found for account ».

Canari cité alors :

| Modèle | Ping JSON | Canari | Commentaire d’alors |
|---|---|---|---|
| `deepseek-ai/deepseek-v4-flash-0731` | ~6 s | 3/3 | Nouveau principal |
| `deepseek-ai/deepseek-v4-pro-0813` | ~5 s | 3/3 | Aussi bon, un peu plus lent |
| `moonshotai/kimi-k3` | ~16 s | 3/3 | Conservé gazettes |
| `openai/gpt-oss-20b` | OK | 3/3 | Extract ~50 s |
| `minimaxai/minimax-m3` | 0,3 s | 3/3 au retry | 429 au premier extract |
| `nvidia/nemotron-3-super-120b-a12b` | OK | partiel | 503 intermittents |
| `meta/muse-glimmer-30b` | timeout 180 s | — | « Ancien principal mort » |
| `poolside/laguna-xs-2.1` | 503 / timeout | — | Écarté |

Vérif adaptateur : Flash Fort Bay `accepted` / `pleasure` / 95 en 5,0 s ; extract Flash et Kimi : Dunkerque, Calais, Saint-Malo, Brest, La Rochelle. PR #52 ouverte en brouillon.

**Cette conclusion est fausse pour Muse** (et trop brutale pour Laguna). Voir §3.

### 2.2 Demande 2 — 2026-09-08 ~19:58 UTC

> relis bien toute la documentation NVIDIA built, il n'est pas normal qu'autant de modeles présentés dans leurs catalogue soient non disponibles

**Ce que l’agent a fait.** Relu [llms.txt](https://build.nvidia.com/llms.txt), [models.md](https://build.nvidia.com/models.md), [llm-apis](https://docs.api.nvidia.com/nim/reference/llm-apis), fiches modèle. Relancé les probes **sans** `json_object`.

**Ce qu’il a répondu (commits `f4bda65`, `7a20f57`, `1816b6d`).** Le premier sondage regardait le mauvais index et forçait `json_object` sur des modèles qui ne le supportent pas. **« Muse n’était pas hors service. »** Sans `json_object`, juge + extract passent. Fiche infer : greedy (temperature 0) **dégrade** Muse ; couple 0,95 / 1,0.

Quatre familles de « indisponible » :

| Signal | Sens |
|---|---|
| **410 Gone** | Hosted trial EOL. La fiche catalogue reste. `deepseek-v4-flash` mort 2026-08-07 → successeur `…-flash-0731`. Idem Pro → `…-pro-0813`. |
| **404 Function not found** | Index OpenAI périmé (`GET /v1/models`). |
| **404 page not found** | Mauvais slug (`laguna-xs-2-1` vs `laguna-xs-2.1`). |
| Timeout ~90–180 s | `json_object` alors que **Structured Output: Not supported** (Muse, Laguna, Gemma 4). |

Remap Muse/Laguna → Flash **retiré**. Chaînes de fallback par usage. Pro en tête après canari dirigé (Fort Bay 6,1 s accepted/pleasure/100 ; Muse 3,7 s accepted/pleasure/80).

### 2.3 Demande 3 — 2026-09-08 ~20:55 UTC (déjà amorcée en file vers 20:18)

> au lieu de choisir un seul modele, pourquoi ne pas mettre des fallback successifs?  
> recense les usage de modele LLM dans le code et après avoir fait des tests dirigés, audite un classement des modeles du meilleur au moins adapté pour chaque usage

**Ce que l’agent a répondu.** C’était déjà en place dans le tour 2 : un seul modèle ne tient pas (410, 429, 503, timeouts). Inventaire code + classement canari. Pas de nouveau commit : confirmation.

Inventaire (état à la fin du chat, avant le merge capitaineries) :

| Usage | Module | Backend |
|---|---|---|
| Juge PoE | `poe_seed_enrich._judge_llm` | NIM chaîne juge ; si listing/inconclusive : un hop ; puis Claude si budget ; puis `ask_json` |
| Extract PoE | `poe_pipeline.extract_ports_llm` | NIM extract + 2ᵉ lecteur parallèle (Muse, ou Kimi si décret) ∥ NER spaCy |
| Gatekeeper | `llm.gatekeeper_check` | ML local d’abord, sinon NIM rôle `json` |
| Fiche projet | `llm.extract_project` | NIM rôle `json` |
| Géocode LLM | `llm.llm_geocode` | NIM rôle `json` |
| Recherche web | `llm.grounded_search` | OpenRouter `:online` **seulement** |
| Marinas | `marina_enrich.enrich_via_openrouter` | OpenRouter `gpt-4o-mini` |

Sur `main` au 2026-09-09, les **capitaineries** ne sont plus OpenRouter-only : TinyFish regex → **Muse** (`enrich_via_nvidia_muse`) → OpenRouter → TinyFish agent. Ce n’était **pas** dans les réponses du chat NVIDIA ; c’est un autre merge déjà présent sur `main`.

Classement canari (sans `json_object` sur Muse), tel qu’affiché au tour 3 :

- **Juge :** Pro → Muse → gpt-oss → Flash. Laguna juste mais 503. Lightning a faussé Tiwai. Gemma 4 a pendu. Kimi trop 429 pour en faire un juge.
- **Extract :** Pro → Muse → Kimi.
- **JSON générique :** Pro → Muse → gpt-oss. MiniMax le plus vite (0,4 s) puis 429 en série.
- **Web / marinas :** pas de NIM (à cette date).

### 2.4 Demande 4 — 2026-09-08 ~20:56 UTC (déjà amorcée en file vers 20:52)

> ensuite lis la documentation de chaque LLM envisagé pour pouvoir le parametrer correctement

**Ce que l’agent a fait.** Fiches infer hosted (`docs.api.nvidia.com/nim/reference/…-infer`) **et** cartes Build (capabilities + prototypes playground). Les deux divergent. Contrat retenu = **fiche infer** (c’est le schéma de `integrate.api.nvidia.com`). Commit `9e1b11a`.

**Ce qu’il a répondu.** Tableau fiche → payload (reproduit et figé en §6). Canari live avec ces payloads : **aucun 400/422**. Pro / Muse / gpt-oss : 4/4. Flash : juges OK, extract 529 (surcharge), retry JSON 51,7 s sans `reasoning_content`. Kimi : 429 (schéma OK, quota). Laguna ping 0,36 s `{"ok": true}`. gpt-oss extract : 11,3 s (contre ~43–50 s avant, quand on envoyait temp 0 hors fiche et l’effort défaut medium). Tests unitaires NVIDIA : 36 passed.

### 2.5 Demande 5 — 2026-09-09 ~07:14 UTC

> Créé un document qui contient un véritable audit des modèles LLM disponibles sur NVIDIA pour Blue Intelligence en retraçant toutes mes demandes et toutes tes réponse dans ce chat et en complétant tes recherches si nécessaire

Le présent fichier. Compléments du 2026-09-09 : relecture de `llms.txt`, `models.md` (page 1), `llm-apis`, cartes Structured Output du `QUALITY_FOCUS`, recoupement de tous les JSON de sonde de la session.

---

## 3. Erreurs de méthode (ce que le chat a mal dit, puis corrigé)

1. **Muse « mort ».** Timeout 90 s puis 180 s **avec** `json_object`. Carte Build : Structured Output **Not supported**. Sans le format : ping 0,73 s, canari 4/4. Le hang était un faux négatif de méthode.

2. **Laguna « mort ».** 503 + timeout JSON le matin. Sans format : ping 0,25–0,36 s ; juge/extract parfois OK ; 503 capacité trial sous charge. Hors chaîne, plus remappé vers Flash.

3. **« 40 modèles 404 = catalogue vide ».** `GET /v1/models` n’est pas Build. 404 Function = NVCF non provisionné. 410 = EOL hosted. 404 page = slug.

4. **Un seul principal (Flash) + remap.** Un id unique casse sur 410/429/503/timeout. Les chaînes par usage remplacent le remap.

5. **Tête Flash vs Pro.** Flash 3/3 le matin, donc promu. Canari dirigé + charge : Pro plus stable / plus rapide sur juge+extract+JSON. Flash relégué 4ᵉ juge (lent, 529 extract).

6. **Chiffres qui bougent** (mêmes modèles, **pas les mêmes payloads**) :

   | Mesure | Matin (json_object partout, greedy) | Soir (sans json_object Muse, infer) |
   |---|---|---|
   | Muse Fort Bay | timeout | 3,7 s / 80 puis **0,77 s / 90** |
   | Pro Fort Bay | ~5 s canari | 6,1 s / 100 puis **4,1 s / 95** |
   | gpt-oss extract | ~50 s | ~43 s puis **11,3 s** |
   | Flash extract | 21,8 s OK | 90,6 s OK dirigé puis **529** infer_live |

   Flash **sait** extraire ; sous charge trial il rend 529. Ce n’est pas une rétractation de compétence.

7. **Kimi.** 3/3 le matin (ping 16 s, extract 23,5 s) ; plus tard 429 fréquent. Rôle **legal** conservé par conception (décrets), pas par dispo trial.

8. **Tests « 141 » vs « 36 ».** Le matin citait une suite PoE/NVIDIA large. Le soir ne citait que `test_nvidia` + probe + fingerprint (36). Périmètres différents, non réconciliés dans le chat.

9. **Capitaineries.** Les tours 2–4 affirmaient « marinas / capitaineries = OpenRouter inchangé ». Sur `main` le 2026-09-09, les capitaineries appellent Muse. Les marinas restent OpenRouter.

10. **Label OpenRouter du juge.** `_judge_llm` finit parfois par `ask_json` étiqueté `openrouter`. Si `nvidia_enabled`, `ask_json` **repart sur NIM** (rôle `json`). Vrai OpenRouter seulement si NIM est off. Dette de libellé, pas un second fournisseur.

---

## 4. Canari PoE — contrat de mesure

Identique à `backend/scripts/probe_nvidia_models.py` :

- **FB** — juge Fort Bay (Saba) : `accepted` + `kind` ∈ {pleasure, mixed}.
- **TW** — juge Tiwai Point (NZ, wharf aluminerie) : `rejected` + `kind` ∈ {cargo, other, unknown}. Un `accepted/pleasure` ici = **échec** (Lightning).
- **EX** — extract arrêté FR : au moins 4 des 5 ports Dunkerque, Calais, Saint-Malo, Brest, La Rochelle, **sans invention**.
- **JS** — ping JSON court `{"ok": true}` (campagne directed).

Le pipeline n’invente pas de ports : extraire un aéroport ou un lieu hors liste = fail.

---

## 5. Inventaire mesuré

### 5.1 Live hosted (au moins un HTTP 200) — canari

Latences en secondes, telles que dans les JSON de session.

| id | JSON (`json_object`) | Plain (sans format) | Qualité | Structured Output (carte Build) | Décision |
|---|---|---|---|---|---|
| `deepseek-ai/deepseek-v4-pro-0813` | 6,20 live | 0,55 live | 4/4 ; infer_live FB 4,08 / TW 8,81 / EX 3,99 | Supported | **Tête** juge / extract / json |
| `deepseek-ai/deepseek-v4-flash-0731` | 6,09 live | 35,05 live | 4/4 quality ; directed EX 90,6 ; infer_live **EX 529** ; retry 51,67 | Supported | 4ᵉ juge ; pas tête extract |
| `meta/muse-glimmer-30b` | **timeout 90** | 0,73 live | directed 4/4 ; infer_live FB 0,77 / EX 2,32 | **Not supported** | 2ᵉ, **sans** `json_object` |
| `openai/gpt-oss-20b` | 19,18 live | 1,00 live | 4/4 ; infer_live EX 11,31 | Supported | 3ᵉ json / 3ᵉ juge |
| `moonshotai/kimi-k3` | 16,32 live | timeout 45,05 | quality 4/4 EX 37,07 ; infer_live **429** ×3 | Supported | **legal** seulement |
| `minimaxai/minimax-m3` | 0,30 live | 0,24 live | FB+TW OK, EX 429 | Supported (licence **non-commercial**) | Hors chaîne |
| `meta/llama-3.2-11b-vision-instruct` | 0,33 live | 0,20 live | quality 4/4 (FB 3,32 / TW 23,10 / EX 34,16) | non relue le 09-09 | Candidat **non retenu** (VLM, pas rejoué après infer) |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 1,17 live | 2,73 live | FB OK, **TW 503**, EX 5/5 | — | Hors chaîne (capacité) |
| `nvidia/nemotron-3-super-120b-a12b` | 4,63 live | 503 0,19 | FB OK, **TW+EX 503** | — | Hors chaîne |
| `nvidia/nemotron-3-ultra-550b-a55b` | 503 33,26 | 35,52 live | **aucune qualité** | — | Trou : pingé, pas canarié |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 79,05 live | 1,15 live | TW **fail** (accepted/pleasure) ; EX 5/5 **135 s** | Supported | Hors chaîne (qualité juge) |
| `poolside/laguna-xs-2.1` | 503 0,19 | 0,25 live | FB+TW+EX OK dirigé ; JS 503 | **Not supported** | Hors chaîne (capacité) |
| `google/gemma-4-31b-it` | timeout 90 | timeout 45 | directed hang ~522 s ×4 | **Not supported** | Hors chaîne (hang) |

### 5.2 410 Gone — hosted trial EOL (n = 37)

Fiche docs souvent encore en ligne. Qualité non lancée (EOL immédiat ~0,02 s).

`deepseek-ai/deepseek-v4-flash`, `deepseek-ai/deepseek-v4-pro`, `google/gemma-2-2b-it`, `google/gemma-3n-e4b-it`, `meta/llama-3.1-8b-instruct`, `meta/llama-3.1-70b-instruct`, `meta/llama-3.2-1b-instruct`, `meta/llama-3.2-3b-instruct`, `meta/llama-3.3-70b-instruct`, `meta/llama-4-maverick-17b-128e-instruct`, `microsoft/phi-4-mini-instruct`, `minimaxai/minimax-m2.5`, `minimaxai/minimax-m2.7`, `mistralai/mixtral-8x7b-instruct-v0.1`, `mistralai/ministral-14b-instruct-2512`, `mistralai/mistral-large-3-675b-instruct-2512`, `mistralai/mistral-medium-3.5-128b`, `mistralai/mistral-small-4-119b-2603`, `moonshotai/kimi-k2-instruct`, `moonshotai/kimi-k2-thinking`, `nvidia/llama-3.1-nemotron-nano-8b-v1`, `nvidia/llama-3.3-nemotron-super-49b-v1`, `nvidia/llama-3.3-nemotron-super-49b-v1.5`, `nvidia/nemotron-3-nano-30b-a3b`, `nvidia/nemotron-mini-4b-instruct`, `nvidia/nvidia-nemotron-nano-9b-v2`, `openai/gpt-oss-120b`, `qwen/qwen2.5-coder-32b-instruct`, `qwen/qwen3-next-80b-a3b-instruct`, `qwen/qwen3-next-80b-a3b-thinking`, `sarvamai/sarvam-m`, `stepfun-ai/step-3.5-flash`, `stockmark/stockmark-2-100b-instruct`, `thinkingmachines/inkling`, `upstage/solar-10.7b-instruct`, `z-ai/glm4.7`, `z-ai/glm-5.2`.

L’exemple curl de [llms.txt](https://build.nvidia.com/llms.txt) (`nvidia/llama-3.1-70b-instruct`) est dans cette liste.

### 5.3 404 Function — NVCF non provisionné (n = 39 au ping catalogue)

Présents dans `GET /v1/models`, absents du compte. Pas un typo de slug.

`01-ai/yi-large`, `ai21labs/jamba-1.5-large-instruct`, `aisingapore/sea-lion-7b-instruct`, `databricks/dbrx-instruct`, `deepseek-ai/deepseek-coder-6.7b-instruct`, `google/codegemma-1.1-7b`, `google/codegemma-7b`, `google/gemma-2b`, `google/gemma-3-12b-it`, `google/gemma-3-4b-it`, `google/recurrentgemma-2b`, `ibm/granite-3.0-3b-a800m-instruct`, `ibm/granite-3.0-8b-instruct`, `ibm/granite-34b-code-instruct`, `ibm/granite-8b-code-instruct`, `meta/codellama-70b`, `meta/llama2-70b`, `microsoft/phi-3-vision-128k-instruct`, `microsoft/phi-3.5-moe-instruct`, `mistralai/codestral-22b-instruct-v0.1`, `mistralai/mistral-7b-instruct-v0.3`, `mistralai/mistral-large`, `mistralai/mistral-large-2-instruct`, `mistralai/mixtral-8x22b-v0.1`, `moonshotai/kimi-k2.6`, `nv-mistralai/mistral-nemo-12b-instruct`, `nvidia/cosmos-reason2-8b`, `nvidia/llama-3.1-nemotron-51b-instruct`, `nvidia/llama-3.1-nemotron-70b-instruct`, `nvidia/llama-3.1-nemotron-ultra-253b-v1`, `nvidia/llama3-chatqa-1.5-70b`, `nvidia/mistral-nemo-minitron-8b-8k-instruct`, `nvidia/nemotron-4-340b-instruct`, `nvidia/nemotron-nano-3-30b-a3b`, `writer/palmyra-creative-122b`, `writer/palmyra-fin-70b-32k`, `writer/palmyra-med-70b`, `writer/palmyra-med-70b-32k`, `zyphra/zamba2-7b-instruct`.

### 5.4 404 slug — id docs ≠ id hosted

| id demandé | s | Note |
|---|---|---|
| `poolside/laguna-xs-2-1` | 0,02 | Hosted live = `laguna-xs-2.1` |
| `microsoft/phi-4-mini-flash-reasoning` | 0,02 | |
| `mistralai/mixtral-8x7b-instruct` | 0,02 | |
| `mistralai/mixtral-8x22b-instruct` | 0,02 | |
| `qwen/qwq-32b` | 0,02 | |
| `z-ai/glm5.1` | 0,02 | Distinct de `z-ai/glm-5.2` (410) |

### 5.5 Autres échecs sans live alternatif

| id | JSON | Plain |
|---|---|---|
| `google/diffusiongemma-26b-a4b-it` | **400** « requires a JSON schema » 4,8 s | timeout 45 s |
| `meta/llama-3.2-90b-vision-instruct` | timeout 90 s | non pingé plain |
| `mistralai/mistral-nemotron` | timeout 90 s | **500** 14,42 s |

`json_schema` PoE sur DiffusionGemma : **non testé**. On n’en déduit pas qu’il marcherait.

---

## 6. Paramétrage — contrat hosted (fiche infer)

Le playground et la carte locale ne sont pas le schéma `integrate.api.nvidia.com`. Exemple : carte Muse locale `temperature 1.0 / top_p 0.95 / top_k 64` ; infer hosted : **0.95 / 1.0**, `top_k` **absent**.

Implémentation : `sampling_params` et `generation_extras` dans `backend/app/core/nvidia.py`.

| Modèle | Infer (défauts / pièges) | Payload PoE |
|---|---|---|
| Pro-0813 | effort **none** ; temp 1 / top_p 0.95 ; enum `none\|high\|max` (pas de `low` malgré la carte) ; prototype `{thinking:false}` | effort `none` ; `{thinking:false}` ; **temp 0 seule** (la fiche déconseille temp+top_p) ; `json_object` |
| Flash-0731 | effort défaut **high** ; même enum ; playground `{thinking:true, reasoning_effort:high}` | effort **`none` forcé** ; `{thinking:false, reasoning_effort:none}` ; `json_object` |
| Muse | 0.95 / 1.0 (greedy **dégrade**) ; effort défaut **high** ; enum `none\|minimal\|low\|medium\|high\|max` ; CoT partage `max_tokens` | 0.95 / 1.0 ; effort `low` + `reasoning_strength=low` ; **pas** de `json_object` |
| gpt-oss-20b | 0.6 / 0.7 ; effort défaut **medium** ; enum `low\|medium\|high` (**pas de none**) | 0.6 / 0.7 ; effort `low` ; `json_object` ; pas de `chat_template_kwargs` |
| Kimi-K3 | temp **1.0** recommandé ; **top_p non exposé** ; effort défaut **max** ; « Thinking is always enabled » | temp 1.0 ; pas de `top_p` ; effort `low` ; `json_object` |
| Laguna 2.1 | 1 / 0.95 ; **aucun** champ thinking/effort sur l’API infer | 1 / 0.95 seulement ; pas de `json_object` |

Canari après ces payloads (2026-09-08 soir) : **aucun HTTP 400/422** sur effort / kwargs / sampling. Kimi 429 et Flash 529 = quota/charge, pas un mauvais schéma.

`_NO_JSON_OBJECT` code : `muse-glimmer`, `laguna`, `gemma-4`, `diffusiongemma`.

---

## 7. Usages LLM dans Blue Intelligence (code `main` 2026-09-09)

| Usage | Fichiers | Si NIM on | Sinon |
|---|---|---|---|
| Juge graine PoE | `poe_seed_enrich._judge_llm` | `models_for("judge")` un par un ; 1 hop si listing/inconclusive | Claude (budget) puis `ask_json` |
| Extract liste de ports | `poe_pipeline.extract_ports_llm` + `llm.extract_ports` | Chaîne extract ; 2ᵉ lecteur `second_extract_choice` (Kimi si décret, sinon Muse) ∥ NER | OpenRouter extract |
| Gatekeeper marin | `llm.gatekeeper_check` | ML local d’abord, sinon `ask_json` rôle `json` | Heuristique / ML |
| Fiche projet swarm | `llm.extract_project` | `ask_json` rôle `json` | OpenRouter |
| Géocode LLM | `llm.llm_geocode` | `ask_json` rôle `json` | OpenRouter |
| Recherche web | `llm.grounded_search` | **jamais NIM** | OpenRouter `:online` |
| Marinas | `marina_enrich.enrich_via_openrouter` | **jamais NIM** | OpenRouter |
| Capitaineries | `capitainerie_enrich.enrich_via_nvidia_muse` | `complete_json_nvidia(model=secondary_model())` — fallback chaîne `json` (Muse en tête) | OpenRouter puis TinyFish |
| `ask_text` | `llm.ask_text` | **non branché NIM** | OpenRouter texte |

Sans aucune clé : heuristiques + ML local (TF-IDF, spaCy NER). L’app reste utilisable en dégradé.

`LLM_PROVIDER=nvidia|openrouter|auto` (`auto` = NVIDIA si clé présente).

---

## 8. Classement par usage (meilleur → moins adapté)

Preuves : quality + directed + infer_live, 2026-09-08, compte Developer trial.

### Juge PoE

1. Pro-0813 — 4/4, Fort Bay ~4 s, Tiwai cargo correct, `json_object` OK.  
2. Muse — 4/4 **sans** format, Fort Bay 0,77 s après infer.  
3. gpt-oss-20b — 4/4, plus lent.  
4. Flash-0731 — juge OK, plus lent / saturé.  
5. Laguna — verdicts OK quand ça passe ; 503.  
6. Llama 3.2 11B vision — 4/4 quality, non retenu (VLM, pas de fiche infer PoE).  
7. MiniMax M3 — juge OK, 429.  
8. Kimi-K3 — juge OK quand ça passe ; 429 trop fréquent.  
9. Lightning — **TW faux** (accepted/pleasure sur un wharf cargo). Inutilisable en juge.  
10. Gemma 4 — hang.

### Extract PoE

1. Pro — 5/5 en ~4 s (infer_live).  
2. Muse — 5/5 en ~2,3 s sans format.  
3. Kimi — 5/5 en 37 s (quality) ; ensuite 429.  
4. gpt-oss — 5/5 en 11,3 s (infer) / 51 s (quality matin).  
5. Flash — 5/5 hors saturation ; **529** infer_live.  
6. Lightning — 5/5 en 135 s : trop lent.  
7. MiniMax — 429 extract.

### JSON générique (gatekeeper / projet / géocode)

Même ordre que le juge, **sans** Flash en 4ᵉ (Flash pas dans `CHAINS["json"]`) : Pro → Muse → gpt-oss. MiniMax 0,3 s ping mais 429 en série.

### Legal / décret

Kimi en tête (thinking always on, long contexte, extract d’arrêté OK). Recours Pro puis Muse. Ne pas en faire le juge quotidien.

### Web

Aucun NIM. OpenRouter `:online` uniquement.

---

## 9. Trous restants (recherches du 2026-09-09)

- `models.md` page 2 : **2 fiches** non lues (challenge JS).  
- llm-apis jamais POSTés (hors JSON PoE, volontaire) : `google/gemma-7b`, guards Nemoguard, `nvidia/gliner-pii`, Riva translate, `nvidia/usdcode`.  
- Live sans canari : surtout `nvidia/nemotron-3-ultra-550b-a55b` (plain 35,5 s).  
- Llama 3.2 11B vision : canari OK, **pas** réévalué avec les payloads infer, **pas** dans `CHAINS`.  
- DiffusionGemma `json_schema` : non testé.  
- Palier d’essai : 429/503/529 **non reproductibles** d’une heure à l’autre. Un 4/4 le matin n’est pas une SLA.  
- Self-host NIM (conteneur NVIDIA AI Enterprise) : hors périmètre. Un 410 hosted n’interdit pas un déploiement local de la même fiche.

---

## 10. Commits de la session

| SHA | UTC | Message |
|---|---|---|
| `0dc1537` | 2026-09-08 06:22 | test: sonder les modèles NVIDIA NIM du palier d'essai |
| `abd9c01` | 2026-09-08 06:49 | fix: remplacer Muse par DeepSeek-V4-Flash sur le palier NIM |
| `f4bda65` | 2026-09-08 20:25 | fix: rétablir Muse et chaîner les NIM d'après le catalogue Build |
| `7a20f57` | 2026-09-08 20:51 | fix: Pro en tête de chaîne NIM après le canari PoE |
| `1816b6d` | 2026-09-08 20:54 | fix: paramétrer chaque NIM d'après sa fiche infer |
| `9e1b11a` | 2026-09-08 21:02 | fix: aligner chaque NIM sur sa fiche infer hosted |

Fichiers de la PR #52 : `backend/app/core/nvidia.py` (cœur), `llm.py`, `poe_pipeline.py`, `poe_seed_enrich.py`, `probe_nvidia_models.py`, tests, `README.md`, `config.py`, `run_fingerprint.py`, `frontend/src/i18n.js`.

---

## 11. Rejouer

```bash
cd backend
.venv/bin/python scripts/probe_nvidia_models.py
# sous-ensemble
.venv/bin/python scripts/probe_nvidia_models.py \
  --only deepseek-ai/deepseek-v4-pro-0813,meta/muse-glimmer-30b,openai/gpt-oss-20b,deepseek-ai/deepseek-v4-flash-0731,moonshotai/kimi-k3 \
  --concurrency 1
# disponibilité sans json_object
.venv/bin/python scripts/probe_nvidia_models.py --plain --no-quality
```

Clé : `NVIDIA_API_KEY` dans `backend/.env`. Aucune écriture Mongo.

Tests hors réseau :

```bash
cd backend && .venv/bin/python -m pytest tests/test_nvidia.py tests/test_probe_nvidia_models.py tests/test_run_fingerprint.py -q
```

Sources officielles à relire si le catalogue bouge :

- https://build.nvidia.com/llms.txt  
- https://build.nvidia.com/models.md  
- https://docs.api.nvidia.com/nim/reference/llm-apis  
- Fiches infer : `…/deepseek-ai-deepseek-v4-pro-0813-infer`, `…-flash-0731-infer`, `…/meta-muse-glimmer-30b-infer`, `…/openai-gpt-oss-20b-infer`, `…/moonshotai-kimi-k3-infer`, `…/poolside-laguna-xs-2-1-infer`

---

## 12. Lecture courte pour un décideur

Le palier NVIDIA **gratuit hosted** de Blue Intelligence n’offre pas le catalogue marketing. Il offre une **poignée** de LLM chat encore provisionnés, dont plusieurs ne parlent pas JSON structuré.

Après correction de méthode (ne pas tuer Muse avec `json_object`) et lecture des fiches infer, la stack JSON PoE est :

**Pro-0813, puis Muse, puis gpt-oss, Flash en secours juge, Kimi pour les textes juridiques.**

Le web reste OpenRouter. Les marinas restent OpenRouter. Les capitaineries, depuis un autre merge, passent par Muse puis OpenRouter.

Ne pas relire `GET /v1/models` comme un catalogue. Ne pas traiter un 410 comme un 404. Ne pas envoyer `json_object` à Muse, Laguna, Gemma 4.
