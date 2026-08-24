"""
Formalities generation pipeline — Phase 4B.

Per-territory workflow:
    1. Pick 2-3 URLs from the curated territories.json ref_urls (territory.ref_url +
       ports_of_entry[].ref_url). Only whitelisted domains are ever kept.
    2. Fire TinyFish missions (real API, no mock) with a wide flat schema aimed at
       every formality field we know about. Poll every 4 s, 210 s budget/mission.
       Missions run SEQUENTIALLY inside a territory to preserve chronological logs
       and avoid burning credits when the first mission already returns most facts.
    3. Aggregate the mission payloads + a filtered `sources[]` (only URLs whose
       domain matches the territory whitelist survive — Noonsite/forums/blogs
       cannot possibly land here even if the LLM insists).
    4. LLM synthesis (OpenRouter gpt-4o-mini → EMERGENT_LLM_KEY/Gemini fallback):
       compile a strict JSON matching the formalities schema, in FRENCH. Never
       fabricate a field — null when unknown.
    5. Persist the doc directly (per-field write), flip status to `ia` or
       `ia_sans_source`, stamp `generated_at`, wipe `verified_at`.

Public entry points:
    - `generate_territory_formality(db, code, territories, log_fn)` -> dict
    - `generate_immigration_slot(db, code, nat, territories, log_fn)` -> dict
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx


NOW = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())  # noqa: E731

# --------------------------------------------------------------------------------
# TinyFish mission schema (flat, all optional strings — TinyFish rejects nullable /
# union types / descriptions, so we normalise empty values to null downstream).
# --------------------------------------------------------------------------------
MISSION_SCHEMA = {
    "type": "object",
    "properties": {
        # Entrée
        "entree_preavis": {"type": "string"},
        "entree_pavillon_q": {"type": "string"},
        "entree_demarches_arrivee": {"type": "string"},
        "entree_ou_s_amarrer": {"type": "string"},
        "entree_vhf": {"type": "string"},
        "entree_douanes_clearance": {"type": "string"},
        "entree_admission_temporaire": {"type": "string"},
        "entree_franchises": {"type": "string"},
        "entree_biosecurite": {"type": "string"},
        "entree_frais": {"type": "string"},
        "entree_horaires": {"type": "string"},
        # Sortie
        "sortie_clearance": {"type": "string"},
        "sortie_delais": {"type": "string"},
        "sortie_documents": {"type": "string"},
        "sortie_ou_obtenir": {"type": "string"},
        # Cas particuliers
        "cas_animaux": {"type": "string"},
        "cas_drones": {"type": "string"},
        "cas_armes": {"type": "string"},
        # Immigration FR (default nationality)
        "immigration_fr_visa": {"type": "string"},
        "immigration_fr_duree_sejour": {"type": "string"},
        "immigration_fr_equivalent_esta": {"type": "string"},
        "immigration_fr_notes": {"type": "string"},
        # Contacts
        "contact_vhf": {"type": "string"},
        "contact_tel": {"type": "string"},
        "contact_email": {"type": "string"},
        "contact_capitainerie": {"type": "string"},
        # Bookkeeping
        "urls_consulted": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

IMMIGRATION_SCHEMA = {
    "type": "object",
    "properties": {
        "visa": {"type": "string"},
        "duree_sejour": {"type": "string"},
        "equivalent_esta": {"type": "string"},
        "notes": {"type": "string"},
        "urls_consulted": {"type": "array", "items": {"type": "string"}},
    },
}


# --------------------------------------------------------------------------------
# Mission prompt builders — spec: pleasure yacht under FRENCH flag, French crew
# by default, sailing the tour des territoires français.
# --------------------------------------------------------------------------------
def mission_goal(territory: dict) -> str:
    name = territory.get("name_fr") or territory.get("code")
    regime = territory.get("regime")
    escales = ", ".join(territory.get("escale_names") or [])
    poe = ", ".join(p.get("name", "") for p in (territory.get("ports_of_entry") or []))
    regime_hint = {
        "metropole": "France métropolitaine, espace Schengen, territoire douanier UE.",
        "drom": "DROM — territoire de l'UE mais fiscalement tiers (octroi de mer).",
        "com": "COM — hors territoire douanier UE.",
        "taaf": "TAAF — accès uniquement sur autorisation préalable écrite du Préfet des TAAF. AUCUN port d'entrée ouvert au trafic maritime privé.",
        "sui_generis": "Statut sui generis (Nouvelle-Calédonie) — territoire douanier et fiscal autonome.",
    }.get(regime, "")
    return (
        "Tu es un agent d'enquête OSINT maritime pour un tour du monde en voilier sous PAVILLON FRANÇAIS, "
        "équipage majoritairement français, tour des territoires français d'outre-mer.\n\n"
        f"Territoire : {name} ({regime}).\n"
        f"Escales concernées : {escales}.\n"
        f"Ports d'entrée officiels connus : {poe or '(à déterminer / aucun)'}\n"
        f"Contexte réglementaire : {regime_hint}\n\n"
        "Sur ce site officiel, extrais TOUS les faits utiles à un plaisancier français pour préparer son entrée "
        "et sa sortie du territoire : préavis obligatoire (h ou min), pavillon Q à hisser, démarches d'arrivée, "
        "où s'amarrer, canal VHF, clearance douanière, admission temporaire du navire, franchises fiscales, "
        "règles biosécurité, frais, horaires du bureau de douane, clearance de sortie, délais et documents, "
        "où obtenir le certificat de sortie, règles animaux/drones/armes, contacts (VHF, téléphone, email, "
        "capitainerie), et pour un citoyen FRANÇAIS : visa nécessaire ou pas, durée de séjour, ESTA équivalent, "
        "notes particulières.\n\n"
        "Reporte AUSSI la liste EXACTE des URLs des pages officielles consultées (champ urls_consulted). "
        "Règle absolue : NE JAMAIS inventer. Chaque champ non trouvé reste vide (string vide '')."
    )


def immigration_goal(territory: dict, nat_label: str) -> str:
    name = territory.get("name_fr") or territory.get("code")
    return (
        f"Tu es un agent OSINT immigration. Territoire : {name}. Nationalité du plaisancier : {nat_label}.\n\n"
        "Sur ce site officiel, indique : le visa nécessaire (ou pas), la durée de séjour autorisée, "
        "un éventuel ESTA/AVE/eTA équivalent, et toute note particulière (autorisation préalable, préavis, "
        "restriction de circulation). Cite l'URL des pages consultées. Ne jamais inventer — string vide si absent."
    )


# --------------------------------------------------------------------------------
# URL helpers
# --------------------------------------------------------------------------------
def _norm_domain(url: str) -> str:
    try:
        d = urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def _url_is_whitelisted(url: str, whitelist: list[str]) -> bool:
    dom = _norm_domain(url)
    if not dom:
        return False
    return any(dom == w or dom.endswith("." + w) for w in whitelist)


def _select_source_urls(territory: dict, cap: int = 3) -> list[str]:
    """
    Pick up to `cap` unique URLs to run TinyFish against.
    Priority: territory.ref_url → ports_of_entry[i].ref_url. Deduped by URL.
    Only whitelisted URLs are kept.
    """
    whitelist = territory.get("official_domains") or []
    urls: list[str] = []
    seen = set()
    for src in [territory.get("ref_url")]:
        if src and src not in seen and _url_is_whitelisted(src, whitelist):
            urls.append(src)
            seen.add(src)
    for p in territory.get("ports_of_entry") or []:
        r = p.get("ref_url")
        if r and r not in seen and _url_is_whitelisted(r, whitelist):
            urls.append(r)
            seen.add(r)
        if len(urls) >= cap:
            break
    return urls[:cap]


# --------------------------------------------------------------------------------
# TinyFish mission execution — async + poll (real API, no mock)
# --------------------------------------------------------------------------------
async def _run_tinyfish_mission(
    url: str,
    goal: str,
    schema: dict,
    key: str,
    logger: Optional[Callable[[str], None]] = None,
    budget_s: float = 210.0,
) -> tuple[Optional[dict], list[str]]:
    """
    Fire ONE TinyFish run-async mission on `url`, poll every 4s, return (payload, urls_consulted).
    Returns (None, []) on failure/timeout.
    """
    from tinyfish_client import tf_get_run, tf_run_async

    try:
        if logger:
            logger(f"[tinyfish] mission → {url}")
        started = await tf_run_async(url, goal, schema, key)
    except Exception as e:
        detail = ""
        if hasattr(e, "response") and e.response is not None:
            try:
                detail = e.response.text[:180]
            except Exception:
                pass
        if logger:
            logger(f"[tinyfish] run-async error: {type(e).__name__}: {str(e)[:120]} {detail}")
        return None, []
    run_id = started.get("run_id") or started.get("id")
    if not run_id:
        if logger:
            logger(f"[tinyfish] no run_id: {str(started)[:150]}")
        return None, []
    if logger:
        logger(f"[tinyfish] run_id={run_id}, polling every 4s (budget {int(budget_s)}s)")
    deadline = asyncio.get_event_loop().time() + budget_s
    last_status = None
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(4)
        try:
            info = await tf_get_run(run_id, key)
        except Exception as e:
            if logger:
                logger(f"[tinyfish] poll error: {type(e).__name__}: {str(e)[:80]}")
            continue
        status = info.get("status")
        if status != last_status and logger:
            logger(f"[tinyfish] status={status}")
            last_status = status
        if status in ("COMPLETED", "SUCCESS", "SUCCEEDED"):
            payload: Any = info.get("result") or info.get("output") or info
            for pk in ("result", "output", "extraction", "data"):
                if isinstance(payload, dict) and pk in payload and isinstance(payload[pk], dict):
                    payload = payload[pk]
            if not isinstance(payload, dict):
                return None, []
            urls = payload.get("urls_consulted") or []
            if not isinstance(urls, list):
                urls = []
            filled = [k for k, v in payload.items() if isinstance(v, str) and v.strip()]
            if logger:
                logger(f"[tinyfish] COMPLETED · filled={len(filled)} fields · urls={len(urls)}")
            return payload, [str(u) for u in urls if isinstance(u, str)]
        if status in ("FAILED", "ERROR", "CANCELLED", "CANCELED"):
            err = str(info.get("error") or info.get("message"))[:180]
            if logger:
                logger(f"[tinyfish] {status}: {err}")
            return None, []
    if logger:
        logger(f"[tinyfish] TIMEOUT after {int(budget_s)}s (last status={last_status})")
    return None, []


# --------------------------------------------------------------------------------
# Fallback readable-fetch for gov.fr/service-public.pf pages that time out in TinyFish.
# The URL is ALWAYS a whitelisted one already picked by _select_source_urls, so the
# resulting fact-blob is trustworthy source-wise.
# --------------------------------------------------------------------------------
# Cached local PDFs mapped to their canonical URL — used when the site is hard to
# fetch live but a user-provided snapshot is available. The URL of the source[]
# entry is ALWAYS the canonical remote URL, never the local file path.
CACHED_PDF_MAP: dict[str, str] = {
    "https://www.reunion.gouv.fr/":
        "/app/backend/data/cached_pdfs/la_reunion_reunion_gouv_fr.pdf",
}


def _extract_pdf_text(pdf_bytes: bytes, max_chars: int = 12000) -> Optional[str]:
    """Extract readable text from a PDF byte-stream. Returns None on failure."""
    try:
        import pdfplumber, io
        text_parts = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:30]:   # cap at 30 pages
                t = page.extract_text() or ""
                if t.strip():
                    text_parts.append(t)
        text = "\n".join(text_parts)
        # Collapse blank runs
        lines = [ln for ln in text.split("\n") if ln.strip()]
        cleaned = "\n".join(lines)
        if len(cleaned) < 200:
            return None
        return cleaned[:max_chars]
    except Exception:
        return None


def _extract_local_pdf(path: str, max_chars: int = 12000) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return _extract_pdf_text(f.read(), max_chars=max_chars)
    except Exception:
        return None


async def _fetch_readable(url: str, logger: Optional[Callable[[str], None]] = None,
                          max_chars: int = 8000) -> Optional[str]:
    """
    Fetch url with httpx, extract readable text.
    - If a cached local PDF exists for that URL (CACHED_PDF_MAP), read it and parse
      via pdfplumber — the source URL remains the canonical one.
    - If the remote response is a PDF (Content-Type or .pdf extension), parse via
      pdfplumber into text.
    - Otherwise treat as HTML and BeautifulSoup-strip.
    """
    # ---- Cached local PDF override (whitelist-preserving) -----------------------
    if url in CACHED_PDF_MAP:
        local = CACHED_PDF_MAP[url]
        snippet = _extract_local_pdf(local, max_chars=max(max_chars, 12000))
        if snippet:
            if logger:
                logger(f"[fallback-fetch/pdf-cache] {url}: {len(snippet)} chars from local cache")
            return snippet
        elif logger:
            logger(f"[fallback-fetch/pdf-cache] local file empty/failed: {local}")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; BlueIntelligence/1.0; +blue-intelligence-map)",
            "Accept": "text/html,application/xhtml+xml,application/pdf",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
        }
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
        if r.status_code != 200 or not r.content:
            if logger:
                logger(f"[fallback-fetch] HTTP {r.status_code} on {url}")
            return None

        # ---- PDF branch -----------------------------------------------------------
        ct = (r.headers.get("content-type") or "").lower()
        is_pdf = "pdf" in ct or url.lower().endswith(".pdf") or r.content[:4] == b"%PDF"
        if is_pdf:
            snippet = _extract_pdf_text(r.content, max_chars=max(max_chars, 12000))
            if snippet:
                if logger:
                    logger(f"[fallback-fetch/pdf] {url}: {len(snippet)} chars extracted from PDF")
                return snippet
            if logger:
                logger(f"[fallback-fetch/pdf] {url}: PDF parsing yielded nothing usable")
            return None

        # ---- HTML branch ---------------------------------------------------------
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            if logger:
                logger("[fallback-fetch] bs4 not available")
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside", "form", "svg", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [ln for ln in text.split("\n") if ln.strip()]
        cleaned = "\n".join(lines)
        if len(cleaned) < 300:
            if logger:
                logger(f"[fallback-fetch] {url}: extracted {len(cleaned)} chars (too short)")
            return None
        cleaned = cleaned[:max_chars]
        if logger:
            logger(f"[fallback-fetch] {url}: {len(cleaned)} chars extracted")
        return cleaned
    except Exception as e:
        if logger:
            logger(f"[fallback-fetch] error on {url}: {type(e).__name__}: {str(e)[:120]}")
        return None


# --------------------------------------------------------------------------------
# LLM synthesis — OpenRouter (gpt-4o-mini JSON mode) → EMERGENT_LLM_KEY/Gemini fallback
# --------------------------------------------------------------------------------
FORMALITIES_SYNTHESIS_INSTRUCTIONS = """Tu es un synthétiseur multilingue au service d'un plaisancier français faisant un tour des territoires français d'outre-mer sur voilier sous PAVILLON FRANÇAIS.

Sur la base des extraits ci-dessous (issus de missions d'agents web sur les sites officiels du territoire), compile un JSON strict conforme au schéma suivant :

{
  "entree": {
    "preavis": string|null,
    "pavillon_q": string|null,
    "demarches_arrivee": string|null,
    "ou_s_amarrer": string|null,
    "vhf": string|null,
    "douanes_clearance": string|null,
    "admission_temporaire": string|null,
    "franchises": string|null,
    "biosecurite": string|null,
    "frais": string|null,
    "horaires": string|null
  },
  "sortie": {
    "clearance": string|null,
    "delais": string|null,
    "documents": string|null,
    "ou_obtenir": string|null
  },
  "cas_particuliers": {
    "animaux": string|null,
    "drones": string|null,
    "armes": string|null
  },
  "immigration_fr": {
    "visa": string|null,
    "duree_sejour": string|null,
    "equivalent_esta": string|null,
    "notes": string|null
  },
  "contacts": [{"type": string, "label": string, "value": string}],
  "liens_officiels": [{"label": string, "url": string}]
}

RÈGLES ABSOLUES :
- TOUT en FRANÇAIS.
- NE JAMAIS INVENTER. Si une info n'est pas dans les extraits, mets null. Aucune supposition, aucune extrapolation, aucun conseil général issu de ta connaissance.
- Reformule brièvement (2-3 phrases max par champ), mais fidèlement.
- N'inclus dans "liens_officiels" QUE les URLs qui apparaissent dans les extraits.
- Retourne UNIQUEMENT le JSON, pas de commentaire, pas de markdown.
"""


async def _synthesize_llm(
    territory: dict,
    tf_facts: list[dict],
    openrouter_key: Optional[str],
    emergent_key: Optional[str],
    logger: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    """
    Feed the aggregated TinyFish payloads to a JSON-mode LLM.
    Prefer OpenRouter gpt-4o-mini; fall back to Gemini via emergentintegrations.
    Returns the parsed dict, or None on both failures.
    """
    # ---- Territory-specific system rule (conditional, avoids cross-contamination) ----
    special_rule = ""
    if territory.get("regime") == "taaf":
        special_rule = (
            "RÈGLE SPÉCIFIQUE : ce territoire est TAAF (Îles Éparses). Il n'y a AUCUN port d'entrée "
            "ouvert au trafic maritime privé. Dans entree.demarches_arrivee, indique explicitement "
            "'Aucun accès sans autorisation préalable écrite du Préfet des TAAF'. Laisse null pour "
            "les champs incompatibles (VHF, quai, franchises, etc.) sauf si un fait concret existe "
            "dans les extraits pour un mouillage encadré."
        )
    instructions = FORMALITIES_SYNTHESIS_INSTRUCTIONS
    if special_rule:
        instructions = instructions + "\n\n" + special_rule
    ctx = {
        "territoire": {
            "code": territory.get("code"),
            "nom_fr": territory.get("name_fr"),
            "regime": territory.get("regime"),
            "ports_of_entry": [
                {"name": p.get("name"), "note": p.get("note")}
                for p in (territory.get("ports_of_entry") or [])
            ],
            "notes": territory.get("notes"),
        },
        "extraits_missions": tf_facts,
    }
    user_content = instructions + "\n\nContexte:\n" + json.dumps(ctx, ensure_ascii=False)

    # --- Attempt 1: OpenRouter gpt-4o-mini ---
    if openrouter_key:
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://anchorages-50nm.preview.emergentagent.com",
                        "X-Title": "Blue Intelligence - Formalities Synthesis",
                    },
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": [{"role": "user", "content": user_content}],
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "max_tokens": 2500,
                    },
                )
                if r.status_code != 200:
                    if logger:
                        logger(f"[llm/openrouter] HTTP {r.status_code}: {r.text[:200]}")
                else:
                    body = r.json()
                    content = body["choices"][0]["message"]["content"]
                    usage = body.get("usage") or {}
                    parsed = json.loads(content)
                    if logger:
                        logger(
                            f"[llm/openrouter] OK model=gpt-4o-mini in={usage.get('prompt_tokens')} "
                            f"out={usage.get('completion_tokens')} cost≈${(usage.get('total_cost') or 0):.6f}"
                        )
                    return parsed
        except Exception as e:
            if logger:
                logger(f"[llm/openrouter] error: {type(e).__name__}: {str(e)[:180]}")

    # --- Attempt 2: EMERGENT_LLM_KEY via emergentintegrations (Gemini) ---
    if emergent_key:
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = (
                LlmChat(api_key=emergent_key, session_id=f"formalities-{territory.get('code')}-{int(time.time())}",
                        system_message="You are a JSON-only assistant. Respond with valid JSON only.")
                .with_model("gemini", "gemini-2.5-flash")
            )
            reply = await chat.send_message(UserMessage(text=user_content))
            reply = reply.strip()
            # Strip markdown fences if any
            if reply.startswith("```"):
                reply = re.sub(r"^```(?:json)?\s*", "", reply)
                reply = re.sub(r"\s*```$", "", reply)
            parsed = json.loads(reply)
            if logger:
                logger("[llm/gemini] OK model=gemini-2.5-flash (via EMERGENT_LLM_KEY)")
            return parsed
        except Exception as e:
            if logger:
                logger(f"[llm/gemini] error: {type(e).__name__}: {str(e)[:180]}")

    if logger:
        logger("[llm] ALL PATHS FAILED — synthesis skipped")
    return None


async def _synthesize_immigration_llm(
    territory: dict,
    nat_label: str,
    tf_payload: Optional[dict],
    openrouter_key: Optional[str],
    emergent_key: Optional[str],
    logger: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    """
    Ask the LLM for the immigration slot for the given nationality.
    Returns {visa, duree_sejour, equivalent_esta, notes} or None.
    """
    prompt = (
        f"Territoire : {territory.get('name_fr')} ({territory.get('regime')}). "
        f"Nationalité du plaisancier : {nat_label}.\n\n"
        f"À partir de l'extrait de mission ci-dessous, compile UNIQUEMENT le JSON suivant :\n"
        '{ "visa": string|null, "duree_sejour": string|null, "equivalent_esta": string|null, "notes": string|null }\n'
        "Règles : tout en français, jamais d'invention (null si non présent dans l'extrait), "
        "réponse strictement JSON sans markdown ni commentaire.\n\n"
        f"Extrait mission : {json.dumps(tf_payload or {}, ensure_ascii=False)[:6000]}"
    )
    # ---- OpenRouter first
    if openrouter_key:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"},
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "max_tokens": 600,
                    },
                )
                if r.status_code == 200:
                    body = r.json()
                    content = body["choices"][0]["message"]["content"]
                    if logger:
                        logger(f"[llm/openrouter/immigration] OK")
                    return json.loads(content)
                if logger:
                    logger(f"[llm/openrouter/immigration] HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            if logger:
                logger(f"[llm/openrouter/immigration] error: {type(e).__name__}: {str(e)[:150]}")
    # ---- Gemini fallback
    if emergent_key:
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = (
                LlmChat(api_key=emergent_key, session_id=f"immigration-{territory.get('code')}-{nat_label}-{int(time.time())}",
                        system_message="Respond with valid JSON only.")
                .with_model("gemini", "gemini-2.5-flash")
            )
            reply = await chat.send_message(UserMessage(text=prompt))
            reply = reply.strip()
            if reply.startswith("```"):
                reply = re.sub(r"^```(?:json)?\s*", "", reply)
                reply = re.sub(r"\s*```$", "", reply)
            if logger:
                logger("[llm/gemini/immigration] OK")
            return json.loads(reply)
        except Exception as e:
            if logger:
                logger(f"[llm/gemini/immigration] error: {type(e).__name__}: {str(e)[:150]}")
    return None


# --------------------------------------------------------------------------------
# Public orchestrator — territory-level
# --------------------------------------------------------------------------------
async def generate_territory_formality(
    db,
    code: str,
    territories: dict,
    logger: Optional[Callable[[str], None]] = None,
    tinyfish_key: Optional[str] = None,
    openrouter_key: Optional[str] = None,
    emergent_key: Optional[str] = None,
    max_missions: int = 2,
) -> Optional[dict]:
    """
    Generate the formality doc for `code`. Persists a partial update into Mongo
    IMMEDIATELY (never leaves the DB stale), then flips status to `ia` or
    `ia_sans_source`.
    Returns the freshly-read doc, or None if the territory is unknown.
    """
    if logger:
        logger(f"=== generate {code} ===")
    territory = next(
        (t for t in territories.get("territories", []) if t.get("code") == code),
        None,
    )
    if not territory:
        if logger:
            logger(f"[abort] territory not found: {code}")
        return None

    whitelist = territory.get("official_domains") or []
    seed_urls = _select_source_urls(territory, cap=max_missions)
    if logger:
        logger(f"[select] {len(seed_urls)} seed URL(s) to visit: {seed_urls}")

    tf_facts: list[dict] = []
    tf_urls_consulted: list[str] = []

    # ---------- TinyFish missions (sequential, safe with per-territory 210s budget × N missions) ----------
    if tinyfish_key and seed_urls:
        goal = mission_goal(territory)
        for url in seed_urls:
            payload, urls = await _run_tinyfish_mission(
                url, goal, MISSION_SCHEMA, tinyfish_key,
                logger=logger, budget_s=210,
            )
            if payload:
                tf_facts.append(payload)
                tf_urls_consulted.extend(urls or [])
                tf_urls_consulted.append(url)
            else:
                # Explicitly note failure so we can trace the ia_sans_source verdict.
                if logger:
                    logger(f"[tinyfish] mission on {url} returned no usable payload")
    elif logger:
        logger("[tinyfish] no key or no seed URLs — skipping missions")

    # ---------- Fallback fetch (READONLY, official whitelisted URLs) if TinyFish returned nothing.
    #     Rationale: some gov.fr / service-public.pf pages are JS-heavy and time out inside
    #     the TinyFish agent budget (210s). Rather than falling straight to ia_sans_source
    #     for whole territories, we fetch the raw HTML with httpx, extract the readable body
    #     (BeautifulSoup), and hand it to the LLM as ONE "fact-blob" — the URL is still
    #     whitelisted, so sources[] remains trustworthy. This is a graceful degradation,
    #     NOT a mock: the payload comes from the same official URL TinyFish was pointed at.
    if not tf_facts and seed_urls:
        if logger:
            logger("[fallback-fetch] TinyFish returned no facts, trying httpx+readability on whitelisted URLs")
        for url in seed_urls:
            snippet = await _fetch_readable(url, logger=logger)
            if snippet:
                tf_facts.append({"_source_url": url, "_page_extract": snippet})
                tf_urls_consulted.append(url)

    # ---------- Whitelist filter on sources ----------
    dedup_seen = set()
    sources: list[dict] = []
    for u in tf_urls_consulted:
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        if u in dedup_seen:
            continue
        if not _url_is_whitelisted(u, whitelist):
            if logger:
                logger(f"[whitelist] REJECTED (out of scope): {u}")
            continue
        dedup_seen.add(u)
        sources.append({
            "url": u,
            "domain": _norm_domain(u),
            "collected_at": NOW(),
        })
    if logger:
        logger(f"[sources] {len(sources)} whitelisted URL(s) kept")

    # ---------- LLM synthesis (only if we have facts) ----------
    synth: dict | None = None
    if tf_facts:
        synth = await _synthesize_llm(
            territory, tf_facts, openrouter_key, emergent_key, logger=logger,
        )
    elif logger:
        logger("[llm] no TinyFish facts — skipping synthesis")

    # ---------- Fill the doc ----------
    def _clean_str(v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s and s.lower() not in ("null", "none", "n/a") else None
        return None

    entree_out = {k: None for k in (
        "preavis", "pavillon_q", "demarches_arrivee", "ou_s_amarrer", "vhf",
        "douanes_clearance", "admission_temporaire", "franchises",
        "biosecurite", "frais", "horaires",
    )}
    sortie_out = {k: None for k in ("clearance", "delais", "documents", "ou_obtenir")}
    cas_out = {k: None for k in ("animaux", "drones", "armes")}
    imm_fr = {"visa": None, "duree_sejour": None, "equivalent_esta": None, "notes": None}
    contacts_out: list[dict] = []
    liens_out: list[dict] = []

    if isinstance(synth, dict):
        for k in entree_out:
            entree_out[k] = _clean_str((synth.get("entree") or {}).get(k))
        for k in sortie_out:
            sortie_out[k] = _clean_str((synth.get("sortie") or {}).get(k))
        for k in cas_out:
            cas_out[k] = _clean_str((synth.get("cas_particuliers") or {}).get(k))
        imm_synth = synth.get("immigration_fr") or {}
        for k in imm_fr:
            imm_fr[k] = _clean_str(imm_synth.get(k))
        for c in synth.get("contacts") or []:
            if isinstance(c, dict) and c.get("value"):
                contacts_out.append({
                    "type": _clean_str(c.get("type")) or "",
                    "label": _clean_str(c.get("label")) or "",
                    "value": _clean_str(c.get("value")) or "",
                })
        for l in synth.get("liens_officiels") or []:
            if isinstance(l, dict) and l.get("url") and _url_is_whitelisted(l.get("url"), whitelist):
                liens_out.append({
                    "label": _clean_str(l.get("label")) or "",
                    "url": l.get("url"),
                })

    # ---------- Status decision ----------
    generated_at = NOW()
    status = "ia" if len(sources) >= 1 else "ia_sans_source"
    if logger:
        logger(f"[status] → {status} (sources={len(sources)})")

    # ---------- Preserve nationalities other than FR (Phase 4A immigration.ca/us/gb slots) ----------
    existing = await db.formalities.find_one({"territory_code": code})
    existing_imm = (existing or {}).get("immigration") or {}
    new_immigration = {
        "fr": imm_fr if any(v for v in imm_fr.values()) else None,
        "ca": existing_imm.get("ca"),
        "us": existing_imm.get("us"),
        "gb": existing_imm.get("gb"),
    }

    update = {
        "status": status,
        "entree": entree_out,
        "sortie": sortie_out,
        "cas_particuliers": cas_out,
        "contacts": contacts_out,
        "liens_officiels": liens_out,
        "immigration": new_immigration,
        "sources": sources,
        "generated_at": generated_at,
        "verified_at": None,  # regeneration always drops the human verification
        "stale": False,
    }
    await db.formalities.update_one({"territory_code": code}, {"$set": update})
    if logger:
        logger(f"[persist] doc for '{code}' saved · status={status}")
    return await db.formalities.find_one({"territory_code": code})


# --------------------------------------------------------------------------------
# Public orchestrator — per-nationality immigration slot
# --------------------------------------------------------------------------------
NAT_LABEL = {
    "fr": "Française",
    "ca": "Canadienne",
    "us": "Américaine",
    "gb": "Britannique",
}

# For non-FR nationalities we try to bootstrap on a public diplomatic portal +
# the territory's official page — no invention allowed. If the mission returns
# nothing useful we still let the LLM answer using ONLY the whitelisted urls
# already visited during the main run.
def _immigration_seed_urls(territory: dict) -> list[str]:
    """
    Pick 1 URL for an immigration mission. We reuse the territory ref_url as a
    starting point — the LLM will explicitly note if the info is missing there.
    """
    return _select_source_urls(territory, cap=1)


async def generate_immigration_slot(
    db,
    code: str,
    nat: str,
    territories: dict,
    logger: Optional[Callable[[str], None]] = None,
    tinyfish_key: Optional[str] = None,
    openrouter_key: Optional[str] = None,
    emergent_key: Optional[str] = None,
) -> Optional[dict]:
    """
    Generate immigration.{nat} on-demand. Does NOT touch any other field and
    does NOT flip the status.
    """
    if nat not in ("ca", "us", "gb"):
        if logger:
            logger(f"[immigration] rejected nationality '{nat}' (only ca/us/gb accepted)")
        return None
    territory = next(
        (t for t in territories.get("territories", []) if t.get("code") == code),
        None,
    )
    if not territory:
        if logger:
            logger(f"[immigration] territory not found: {code}")
        return None
    nat_label = NAT_LABEL[nat]
    if logger:
        logger(f"=== immigration.{nat} ({nat_label}) for {code} ===")
    seed_urls = _immigration_seed_urls(territory)
    tf_payload = None
    if tinyfish_key and seed_urls:
        payload, urls = await _run_tinyfish_mission(
            seed_urls[0], immigration_goal(territory, nat_label),
            IMMIGRATION_SCHEMA, tinyfish_key, logger=logger, budget_s=120,
        )
        if payload:
            tf_payload = payload
        if logger:
            logger(f"[immigration] TinyFish payload: {'yes' if payload else 'no'}")
    synth = await _synthesize_immigration_llm(
        territory, nat_label, tf_payload,
        openrouter_key, emergent_key, logger=logger,
    )
    if not isinstance(synth, dict):
        synth = {"visa": None, "duree_sejour": None, "equivalent_esta": None, "notes": None}
    else:
        # Trim
        synth = {
            "visa": synth.get("visa") or None,
            "duree_sejour": synth.get("duree_sejour") or None,
            "equivalent_esta": synth.get("equivalent_esta") or None,
            "notes": synth.get("notes") or None,
        }
    await db.formalities.update_one(
        {"territory_code": code},
        {"$set": {f"immigration.{nat}": synth}},
    )
    if logger:
        logger(f"[immigration.{nat}] persisted for {code}")
    return await db.formalities.find_one({"territory_code": code})
