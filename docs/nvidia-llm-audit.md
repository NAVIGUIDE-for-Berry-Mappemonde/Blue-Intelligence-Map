# Fallbacks NIM par usage — verdict et plan

Fournisseur (prix, inchangé) : **toute la chaîne NIM du rôle**, puis OpenRouter, puis Claude.  
Ce document ne traite que l’ordre **des modèles NVIDIA à l’intérieur de NIM**.

**Canari :** 2026-09-09 08:08 UTC, `backend/scripts/probe_nvidia_usages.py`.  
**Source unique dans le code :** `CHAINS` dans `backend/app/core/nvidia.py`. `models_for(role)` ne réordonne plus Muse en 2ᵉ.

---

## 1. Verdict

Cinq ids hosted tiennent un JSON PoE / page. Un seul modèle ne suffit pas (410, 429, 503, 529, timeout).

| id | Rôle dans NIM |
|---|---|
| `deepseek-ai/deepseek-v4-pro-0813` | Tête de toutes les chaînes sauf `legal` |
| `openai/gpt-oss-20b` | 2ᵉ (qualité égale, plus rapide que Muse sous charge) |
| `meta/muse-glimmer-30b` | 3ᵉ (4/4, pas de `json_object`, lent sous charge) |
| `deepseek-ai/deepseek-v4-flash-0731` | Dernier du **juge seulement** (529 fréquent) |
| `moonshotai/kimi-k3` | Tête de **`legal` seulement** (timeout / 429 en juge quotidien) |

Hors `CHAINS` : Laguna (503), MiniMax (429 + licence), Lightning (Tiwai faux), Gemma 4 (hang), Llama 3.2 11B (TW 500, marina sans JSON).

Pin historique retiré : Muse n’est plus « le modèle capitaineries » ni le 2ᵉ implicite de `models_for`. Capitaineries = même chaîne `page` que les marinas.

---

## 2. Plan d’implémentation — une chaîne NIM par usage

Règle d’exécution dans `_complete_one` / `complete_json_nvidia_tracked` :

- 410 / 404 → modèle suivant **immédiat**
- 429 / 503 → retry puis suivant
- 529 → suivant (Flash, pas dans la liste retry)
- timeout 120 s → suivant (ne pas 3×120 s)

Surcharge opérateur : `NVIDIA_MODEL_CHAIN_{ROLE}` (liste complète). `NVIDIA_MODEL` ne fait que **préfixer** s’il est posé, il n’écrase pas le reste de la chaîne.

### Table

| Usage | `role` | Chaîne NIM | Call site | Pourquoi cet ordre |
|---|---|---|---|---|
| Juge PoE (graine) | `judge` | **Pro → gpt-oss → Muse → Flash** | `poe_seed_enrich._judge_llm` | Pro 4/4 ~5 s conf 100. gpt-oss 4/4 ~10 s. Muse 4/4 mais 57 s sous charge. Flash last : 529 sur Fort Bay. Listing = hop vers le **suivant de cette liste**, plus vers Muse par nom. |
| Extract listes de ports | `extract` | **Pro → gpt-oss → Muse** | `extract_ports_nvidia` ; 2ᵉ lecteur = 1ᵉ id ≠ tête | Pro 5/5 en 6 s, gpt-oss 8 s, Muse 102 s sous charge. Kimi **sorti** de cette chaîne (429). |
| Décret / gazette | `legal` | **Kimi → Pro → Muse** | `second_extract_choice` si `looks_like_legal_text` | Thinking always on, extract d’arrêté OK hors 429. Pas un juge quotidien. |
| JSON générique | `json` | **Pro → gpt-oss → Muse** | gatekeeper, `extract_project`, `llm_geocode`, AMP `llm_judge_visit`, `arbitrate_geocode` | Même ranking que le juge **sans** Flash (529 trop cher en tête de file JSON). |
| Page marina **et** capitainerie | `page` | **Pro → gpt-oss → Muse** | `marina_enrich.enrich_via_nvidia`, `capitainerie_enrich.enrich_via_nvidia` | Canari marina : Pro 2,3 s 4/4 ; gpt-oss 14 s ; Muse 19 s. Flash 8 s mais 529 ailleurs → pas en 2ᵉ page. **Une seule chaîne** pour les deux modes. |
| Texte libre | `text` | **Pro → gpt-oss → Muse** | `ask_text` / `complete_text_nvidia` (`json_object=false`) | Même ordre ; Muse n’a plus la tête (pas de canari texte-only qui le justifie). |
| Recherche web | — | **aucun NIM** | `grounded_search` | Pas de plugin `:online` sur `integrate.api.nvidia.com`. |

Après épuisement de la colonne « Chaîne NIM » : OpenRouter, puis Claude (sauf marinas / capitaineries / `ask_text` / web — voir contrats existants).

### Second lecteur extract

Plus « Muse parallèle par héritage ». C’est le 2ᵉ id de la chaîne du rôle :

- page non juridique → **gpt-oss**
- `looks_like_legal_text` → **Kimi** (chaîne `legal`)

### Capitaineries

Pas de modèle dédié. Regex TinyFish d’abord (tél + VHF → stop). Sinon `role="page"` sans `model=`. Le libellé persisté est `engine_label(modèle servi)` (`nvidia-deepseek` si Pro répond).

---

## 3. Preuve canari (08:08 UTC)

| id | FB | TW | Extract | Marina |
|---|---|---|---|---|
| Pro-0813 | 4,78 s accepted/100 | 1,01 s cargo/95 | 5,97 s 5/5 | 2,32 s 4/4 |
| gpt-oss-20b | 10,0 s accepted/80 | 7,33 s cargo/80 | 8,14 s 5/5 | 14,0 s 4/4 |
| Muse | 56,6 s accepted/95 | 50,9 s cargo/95 | 101,7 s 5/5 | 19,1 s 4/4 |
| Flash-0731 | **529** | 6,99 s OK | 11,7 s 5/5 | 8,24 s 4/4 |
| Kimi-K3 | timeout 120 s | 429 | 429 | 429 |
| Llama 3.2 11B | 9,1 s OK | **500** | 28 s 5/5 | 200 sans JSON |
| Laguna 2.1 | 503 | 503 | 503 | 503 |

Flash **sait** extraire et lire une page ; le 529 est de la charge trial, pas une incompétence. D’où la queue, pas la tête.

Muse 4/4 à vide (~1 s la veille) et 57 s le lendemain, même payload. D’où 3ᵉ, pas 2ᵉ.

---

## 4. Paramètres (fiche infer, pas le playground)

| Modèle | Payload |
|---|---|
| Pro | effort `none` ; `{thinking:false}` ; temp **0 seule** ; `json_object` |
| Flash | effort **`none` forcé** (défaut infer = high) ; `json_object` |
| gpt-oss | 0,6 / 0,7 ; effort `low` (défaut medium ; pas de `none`) ; `json_object` |
| Muse | 0,95 / 1,0 ; effort `low` ; **pas** de `json_object` |
| Kimi | temp 1,0 ; **pas de top_p** ; effort `low` / `high` si `role=legal` ; `json_object` |

---

## 5. Fait / pas fait

**Fait :** `CHAINS` = table §2 ; `models_for` ne préfixe plus Muse ; juge / extract / json / page / text alignés ; capitaineries sur `page` ; Kimi hors extract quotidien.

**Pas NIM :** `grounded_search` (`:online`). Marinas / capitaineries sans Claude. Self-host NIM hors périmètre.

**Rejouer :** `backend/scripts/probe_nvidia_usages.py` si NVIDIA EOL un id (successeur daté).
