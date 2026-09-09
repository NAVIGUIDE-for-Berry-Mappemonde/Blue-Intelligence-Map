# Audit NVIDIA NIM — verdict et plan

**Date de ce verdict :** 2026-09-09  
**Compte :** palier d’essai hosted (`POST https://integrate.api.nvidia.com/v1/chat/completions`, `NVIDIA_API_KEY`).  
**Canari dirigé :** 2026-09-09 08:08–08:19 UTC, `backend/scripts/probe_nvidia_usages.py`.  
**Code :** branche `cursor/nvidia-llm-audit-1f22` — cascade **NIM → OpenRouter → Claude en dernier**.

Règle de preuve : aucun chiffre inventé. Latences et HTTP = sondes live. Contrats d’API = fiches infer relues le 2026-09-09.

---

## 1. Verdict technique

Blue Intelligence n’a **pas** le catalogue marketing NVIDIA. Il a une poignée de LLM chat encore provisionnés sur le trial, dont plusieurs ne parlent pas JSON structuré.

Trois index se contredisent (relu le 2026-09-09) :

| Source | Ce qu’elle est |
|---|---|
| `GET /v1/models` (81 ids, 55 chat-like) | Index OpenAI **périmé** (`yi-large`, `dbrx`, `granite`… → 404 Function) |
| [llm-apis](https://docs.api.nvidia.com/nim/reference/llm-apis) | Contrats d’API. **Omet** Muse, Gemma 4, MiniMax M3, Llama 3.2 vision, Laguna `2.1` (slug docs = `laguna-xs-2-1`) |
| [models.md](https://build.nvidia.com/models.md) | ~100 fiches **mélangées** (ASR, bio, CFD, image, OCR, quelques LLM) |

[llms.txt](https://build.nvidia.com/llms.txt) donne le bon endpoint et le bon auth. L’exemple curl (`nvidia/llama-3.1-70b-instruct`) est **410 Gone** sur ce compte.

Un id catalogue peut être : **200 live**, **410 Gone** (EOL hosted, fiche encore en ligne), **404 Function** (NVCF non provisionné), **404 page** (slug), **timeout** (`json_object` sur Structured Output: Not supported), **429 / 503 / 529** (quota / capacité trial).

**Décision de stack :**

1. Toute complétion JSON ou texte passe **d’abord** par NVIDIA NIM (chaîne du rôle).  
2. Si la chaîne NIM est épuisée → **OpenRouter**.  
3. **Claude uniquement en dernier fallback** (budget + clé).  
4. La recherche web reste **OpenRouter `:online`**. NIM n’a pas de plugin web.  
5. Les marinas **n’appellent pas Claude** (contrat `claude.py`). Chaîne : NIM → OpenRouter → TinyFish → tags OSM.

Modèles **dans les chaînes** (IDs hosted) :

- `deepseek-ai/deepseek-v4-pro-0813` — tête  
- `meta/muse-glimmer-30b` — 2ᵉ (pas de `json_object`)  
- `openai/gpt-oss-20b` — 3ᵉ JSON / extract / juge  
- `deepseek-ai/deepseek-v4-flash-0731` — 4ᵉ juge  
- `moonshotai/kimi-k3` — legal / 4ᵉ extract  

Hors chaîne : Laguna (503 capacité), MiniMax M3 (429 + licence carte non-commercial), Lightning (juge Tiwai faux), Gemma 4 (hang), Llama 3.2 11B vision (juge cargo 500, marina sans JSON).

Alias EOL dans le code : `deepseek-v4-flash` → `…-0731` ; `deepseek-v4-pro` → `…-0813` ; `laguna-xs-2-1` → `laguna-xs-2.1`.

---

## 2. Canari dirigé du 2026-09-09 (08:08 UTC)

Contrat identique au pipeline : juge Fort Bay (plaisance) / Tiwai Point (cargo), extract arrêté FR (5 ports, 0 invention), page marina Minimes (VHF 9, tél, 320 places, 3,5 m). Payloads = fiches infer.

| id | FB | TW | Extract | Marina | Décision |
|---|---|---|---|---|---|
| **Pro-0813** | 4,78 s accepted/pleasure/100 | 1,01 s rejected/cargo/95 | 5,97 s 5/5 | 2,32 s complet | **Tête partout** |
| **Muse** | 56,6 s accepted/pleasure/95 | 50,9 s rejected/cargo/95 | 101,7 s 5/5 | 19,1 s complet | 2ᵉ qualité ; lent sous charge trial |
| **gpt-oss-20b** | 10,0 s accepted/pleasure/80 | 7,33 s rejected/cargo/80 | **8,14 s 5/5** | 14,0 s complet | 3ᵉ ; extract plus rapide que Muse aujourd’hui |
| **Flash-0731** | **529** 7,7 s | 6,99 s OK | 11,7 s 5/5 | 8,24 s complet | 4ᵉ juge ; sait extraire ; 529 = charge |
| **Kimi-K3** | timeout 120 s | 429 | 429 | 429 | **legal seulement** |
| Llama 3.2 11B vision | 9,1 s OK | HTTP 500 | 28,1 s 5/5 | 200 sans JSON | hors chaîne |
| Laguna 2.1 | 503 0,21 s | 503 | 503 | 503 | hors chaîne (capacité) |

Les 4 champs marina (VHF, tél, places, tirant) sont **corrects** dès que le modèle répond en JSON (Pro, Muse, gpt-oss, Flash). Llama a répondu 200 sans objet JSON.

Latences trial **non reproductibles** d’une heure à l’autre. Muse a fait Fort Bay en 0,77 s la veille et 56 s ce matin, **même payload**. Un 4/4 n’est pas une SLA. D’où les chaînes, pas un modèle unique.

---

## 3. Usages LLM dans le code — cascade réelle

| Usage | Fichiers | NIM | Puis | Claude |
|---|---|---|---|---|
| Juge graine PoE | `poe_seed_enrich._judge_llm` | `models_for("judge")` un par un, 1 hop listing | OpenRouter | Haiku → Sonnet **si NIM+OR échouent ou inconclusive** |
| Extract listes de ports | `llm.extract_ports` + `poe_pipeline.extract_ports_llm` | chaîne `extract` ; 2ᵉ lecteur Muse (Kimi si décret) | OpenRouter | Haiku si les deux lecteurs vides |
| Départage Nominatim/GeoNames | `llm.arbitrate_geocode` | rôle `json` | OpenRouter | Haiku |
| Gatekeeper / fiche projet / géocode | `llm.ask_json` | rôle `json` | OpenRouter | Haiku |
| AMP visit_url | `amp_visit.llm_judge_visit` | rôle `json` (engine = modèle **servi**) | OpenRouter | Haiku |
| Marinas | `marina_enrich.enrich_marina` | rôle `page` | OpenRouter → TinyFish → OSM | **jamais** |
| Capitaineries | `capitainerie_enrich` | rôle `page` (Pro → Muse → gpt-oss) | OpenRouter → TinyFish | **jamais** |
| Texte libre | `llm.ask_text` | chaîne `text` (Muse en tête) | OpenRouter | jamais (adaptateur JSON) |
| Recherche web | `llm.grounded_search` | **jamais** | `:online` | jamais |

Sans aucune clé : heuristiques + ML local. `LLM_PROVIDER=nvidia|openrouter|auto`.

Libellés persistés : `NVIDIA Gatekeeper` / `NVIDIA Extractor` quand NIM répond (plus le faux « OpenRouter » d’avant).

---

## 4. Classement par usage (meilleur → moins adapté)

Preuve : canari §2 + campagnes 2026-09-08 (quality / directed / infer_live).

### Juge PoE

1. **Pro-0813** — 4/4, ~5 s, confiance 100/95, `json_object`.  
2. **Muse** — 4/4 **sans** format ; rapide à vide, lent sous charge.  
3. **gpt-oss-20b** — 4/4, ~10 s, confiance 80.  
4. **Flash-0731** — juge correct hors 529.  
5. Llama 3.2 11B — FB OK, TW 500 ce matin.  
6. Laguna — verdicts OK historiquement ; 503 aujourd’hui.  
7. Kimi — juge OK historiquement ; timeout/429 trop fréquent.  
8. Lightning — **TW faux** (accepted/pleasure sur un wharf cargo). Inutilisable.  
9. Gemma 4 — hang.

Chaîne code : Pro → Muse → gpt-oss → Flash.

### Extract PoE

1. **Pro** — 5/5 en ~6 s.  
2. **gpt-oss** — 5/5 en ~8 s (ce matin ; ~11 s infer_live la veille).  
3. **Muse** — 5/5 ; 2–4 s à vide, 102 s sous charge.  
4. **Flash** — 5/5 hors 529.  
5. Llama 3.2 — 5/5 en 28 s.  
6. **Kimi** — 5/5 hors 429 (rôle décret).  
7. Lightning — 5/5 en 135 s.  
8. MiniMax — 429 extract.

Chaîne code : Pro → Muse → gpt-oss → Kimi.

### Page marina / capitainerie

1. **Pro** — 2,32 s, 4/4 champs.  
2. **Flash** — 8,24 s, 4/4 (quand pas 529).  
3. **gpt-oss** — 14 s, 4/4.  
4. **Muse** — 19 s, 4/4 (sans `json_object`).  
5. Llama — 200 sans JSON.  
6. Kimi / Laguna — 429 / 503.

Chaîne code `page` : Pro → Muse → gpt-oss. **Marinas et capitaineries** partagent cette chaîne. Le pin Muse (`secondary_model()`) sur les capitaineries était historique (Muse = NIM principal au moment du feature) ; le canari page l’a invalidé.

### JSON générique (gatekeeper, projet, géocode, AMP, tiebreak)

Même ordre que le juge **sans** Flash (529 trop cher en tête de file) : Pro → Muse → gpt-oss.

### Legal / décret / gazette

**Kimi** en tête (thinking always on, long contexte, `top_p` non exposé). Recours Pro puis Muse. Ne pas en faire le juge quotidien.

### Texte libre (`ask_text`)

Muse → Pro → gpt-oss. Pas de `json_object`. Pas Claude.

### Web

Aucun NIM. OpenRouter `:online` uniquement.

---

## 5. Paramétrage — contrat hosted (fiche infer du 2026-09-09)

Le playground et la carte locale **ne sont pas** le schéma `integrate.api.nvidia.com`. Exemple Muse : carte locale `1.0 / 0.95 / top_k 64` ; infer hosted **0,95 / 1,0**, `top_k` absent.

Implémentation : `sampling_params` + `generation_extras(model, role=)` dans `backend/app/core/nvidia.py`.

| Modèle | Fiche infer | Payload Blue Intelligence |
|---|---|---|
| Pro-0813 | effort défaut **none** ; temp 1 / top_p 0,95 ; enum `none\|high\|max` ; « ne pas toucher temp et top_p ensemble » | effort `none` ; `{thinking:false}` ; **temp 0 seule** ; `json_object` |
| Flash-0731 | effort défaut **high** (à forcer) ; même enum | effort **`none` forcé** ; `{thinking:false, reasoning_effort:none}` ; `json_object` |
| Muse | 0,95 / 1,0 (greedy **dégrade**) ; effort défaut **high** ; CoT partage `max_tokens` ; Structured Output **Not supported** | 0,95 / 1,0 ; effort `low` + `reasoning_strength=low` ; **pas** de `json_object` |
| gpt-oss-20b | 0,6 / 0,7 ; effort défaut **medium** ; enum `low\|medium\|high` (**pas de none**) | 0,6 / 0,7 ; effort `low` ; `json_object` |
| Kimi-K3 | temp **1,0** recommandé ; **top_p non exposé** ; effort défaut **max** | temp 1,0 ; pas de `top_p` ; effort `low` (JSON) / **`high` si `role=legal`** ; `json_object` |
| Laguna 2.1 | 1 / 0,95 ; **aucun** thinking/effort | 1 / 0,95 ; pas de `json_object` ; **hors chaîne** |

`_NO_JSON_OBJECT` : `muse-glimmer`, `laguna`, `gemma-4`, `diffusiongemma`.

Canari après ces payloads : **aucun HTTP 400/422** sur effort / kwargs / sampling. Kimi 429, Flash 529, Laguna 503 = quota/charge, pas un mauvais schéma.

---

## 6. Plan d’implémentation

### Fait (cette PR)

- Chaînes par rôle dans `CHAINS` + `models_for`.  
- `ask_json` / `ask_json_tracked` : NIM → OR → Claude.  
- `extract_ports` : idem. Second lecteur extract = NIM seulement ; Claude après échec des deux.  
- Juge PoE : NIM d’abord, OR, Claude last (listing n’escalade plus vers Sonnet si OR a déjà tranché).  
- AMP : NIM tracked (libellé = modèle servi) → OR → Claude.  
- Marinas : `enrich_via_nvidia` en tête.  
- Capitaineries : même chaîne `page` que les marinas (Pro en tête ; le pin Muse est retiré).  
- Départage GPS : `llm.arbitrate_geocode` (NIM → OR → Claude).  
- `ask_text` : chaîne `text`.  
- Libellés gatekeeper/extracteur honnêtes.  
- `has_llm` inclut Claude (Claude-only ne tombe plus sur l’heuristique).  
- Script `probe_nvidia_usages.py`.  
- Tests unitaires cascade (197 passed hors Mongo).

### Volontairement inchangé

| Sujet | Pourquoi |
|---|---|
| `grounded_search` = OpenRouter `:online` | NIM n’expose pas de recherche web |
| Marinas / capitaineries sans Claude | `claude.py` : « Ne pas importer depuis … les marinas » |
| Llama / Laguna / MiniMax / Lightning / Gemma hors `CHAINS` | 500, 503, 429, TW faux, hang |
| Self-host NIM (conteneur AI Enterprise) | hors périmètre trial ; un 410 hosted n’interdit pas un déploiement local |

### Fallbacks à l’exécution

```
complétion JSON :  NIM(chaîne rôle) → OpenRouter → Claude (si clé+budget)
extract PoE     :  NIM extract (+ 2ᵉ NIM) → OpenRouter → Claude → catalogue → NER
juge PoE        :  NIM judge → OpenRouter → Haiku → Sonnet
page marina / capitainerie :  NIM page (Pro → Muse → gpt-oss) → OpenRouter → TinyFish
web             :  OpenRouter :online uniquement
```

HTTP 410/404 : modèle suivant **immédiat**. 429/503 : retry puis suivant. 529 Flash : suivant (non retenté, code ≥ 400 hors 429/5xx listés). Timeout 120 s : suivant (ne pas 3×120 s — Gemma pend).

### Suivi

- Rejouer `probe_nvidia_usages.py` si NVIDIA EOL un id (successeur daté, comme Flash/Pro).  
- Si Kimi redevient stable (plus de 429), il peut remonter en 3ᵉ extract.  
- Si Laguna cesse les 503, candidat `page` (pas de `json_object`).  
- Ne pas relire `GET /v1/models` comme catalogue.

---

## 7. Méthode — ce qu’il ne faut plus faire

1. **`json_object` sur Muse / Laguna / Gemma 4** → hang 90–180 s. Faux « Muse est mort » du 2026-09-08 matin.  
2. **Croire `GET /v1/models`.** 404 Function = NVCF, pas une typo.  
3. **Traiter un 410 comme un 404.** EOL hosted, fiche docs encore là.  
4. **Un seul modèle principal.** 410/429/503/529 cassent un id unique.  
5. **Confondre playground et infer.** `top_k`, temp+top_p, effort défaut Flash=`high`.  
6. **Mettre Claude au milieu** de la chaîne (ancien juge : NIM → Claude → `ask_json` qui rebouclait sur NIM).

---

## 8. Rejouer

```bash
cd backend
.venv/bin/python scripts/probe_nvidia_usages.py
.venv/bin/python scripts/probe_nvidia_models.py \
  --only deepseek-ai/deepseek-v4-pro-0813,meta/muse-glimmer-30b,openai/gpt-oss-20b,deepseek-ai/deepseek-v4-flash-0731,moonshotai/kimi-k3 \
  --concurrency 1
.venv/bin/python -m pytest tests/test_nvidia.py tests/test_probe_nvidia_models.py \
  tests/test_run_fingerprint.py tests/test_poe_seed_enrich.py -q
```

Fiches à relire si le catalogue bouge :

- https://build.nvidia.com/llms.txt  
- https://build.nvidia.com/models.md  
- https://docs.api.nvidia.com/nim/reference/llm-apis  
- infer : `deepseek-ai-deepseek-v4-pro-0813-infer`, `…-flash-0731-infer`, `meta-muse-glimmer-30b-infer`, `openai-gpt-oss-20b-infer`, `moonshotai-kimi-k3-infer`, `poolside-laguna-xs-2-1-infer`
