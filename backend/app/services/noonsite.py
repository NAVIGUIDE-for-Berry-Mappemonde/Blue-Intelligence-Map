"""
Corroboration Noonsite — signal de fiabilité, PAS un Gold Dataset.

Sémantique (explicite) :
  * Un PoE nommé comme tel sur Noonsite → confiance élevée (signal positif).
  * L'absence sur Noonsite ne dit RIEN : on ne retire, ne dégrade, ni n'invalide
    un port existant.
  * On n'insère jamais un listing Noonsite comme Port d'Entrée officiel.
    Les noms sans correspondance restent des candidats à revue humaine.
  * On n'ajoute pas noonsite.com aux source_urls officielles du pipeline PoE.
  * Quota dur : 3 pays / mois civil (plafond du compte gratuit). On ne tente
    pas de débloquer un 4ᵉ pays, ni le contenu Premium.

Deux chemins d'entrée, même schéma JSON :
  1. Import console — l'opérateur est déjà connecté dans son navigateur.
  2. Agent TinyFish — Vault + Browser Context Profile (login sans mot de passe
     dans Blue Intelligence). Doc TinyFish :
     https://docs.tinyfish.ai/key-concepts/credentials
     https://docs.tinyfish.ai/key-concepts/browser-context-profiles
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone

from app.core.dedup import text_similarity
from app.core.tinyfish import automation_payload, tf_api_key, tf_run_and_wait
from app.core.tasks import TaskState
from app.services.poe_pipeline import now_iso

MONTHLY_COUNTRY_CAP = 3
NOONSITE_ORIGIN = "https://www.noonsite.com"
MATCH_THRESHOLD = 0.60
HARVEST_STATE = TaskState(max_logs=200)

# Schéma TinyFish : pas de description / additionalProperties / oneOf
# (validateur Agent API — docs.tinyfish.ai/key-concepts/structured-output).
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "country": {"type": "string"},
        "country_slug": {"type": "string"},
        "logged_in": {"type": "boolean"},
        "access_granted": {"type": "boolean"},
        "quota_blocked": {"type": "boolean"},
        "ports_of_entry": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "settlement": {"type": "string"},
                    "is_port_of_entry": {"type": "boolean"},
                    "page_url": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["name", "is_port_of_entry"],
            },
        },
    },
    "required": ["country", "logged_in", "access_granted", "quota_blocked",
                 "ports_of_entry"],
}

# Snippet à coller dans la console du pays déjà ouvert (session opérateur).
CONSOLE_SNIPPET = r"""(async () => {
  const text = document.body.innerText || "";
  const title = (document.querySelector("h1")?.innerText || document.title || "").trim();
  const slug = (location.pathname.match(/\/place\/([^/?#]+)/i) || [])[1] || "";
  const seen = new Set();
  const ports = [];
  const push = (name, url, evidence, isPoe) => {
    const n = (name || "").replace(/\s+/g, " ").trim();
    if (!n || n.length < 2 || n.length > 80) return;
    const key = n.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    ports.push({
      name: n,
      settlement: "",
      is_port_of_entry: !!isPoe,
      page_url: url || location.href,
      evidence: (evidence || "").replace(/\s+/g, " ").trim().slice(0, 120),
    });
  };
  document.querySelectorAll("a[href*='/place/']").forEach((a) => {
    const ctx = ((a.closest("p,li,div,article,section")?.innerText || "") + " " + a.innerText).replace(/\s+/g, " ");
    if (/port of entry|ports of entry|port d['’]entr/i.test(ctx)) {
      push(a.innerText, a.href, ctx, true);
    }
  });
  const faq = text.match(/Where can I enter\?\s*([\s\S]{0,400})/i);
  if (faq) {
    const chunk = faq[1].split(/\n{2,}|Are fees|What security/i)[0];
    const named = chunk.match(/(?:port of entry(?: is|, which is)?|ports of entry (?:are|include))\s+([^.]+)/i);
    if (named) {
      named[1].split(/\s*(?:,| and | \& )\s*/i).forEach((part) => {
        const clean = part.replace(/\(.*?\)/g, " ").replace(/See\s+.*$/i, "").trim();
        if (clean) push(clean, location.href, chunk.slice(0, 120), true);
      });
    }
  }
  const locked = /unlock this country|monthly (limit|allowance)|upgrade to (premium|plus)|membership required/i.test(text);
  const loginWall = /please (log in|sign in)|existing users please|new users please \[?register/i.test(text.slice(0, 2500));
  const payload = {
    country: title.replace(/\s*[–—-]\s*Noonsite.*$/i, "").trim(),
    country_slug: slug,
    logged_in: !loginWall,
    access_granted: !locked && !loginWall,
    quota_blocked: locked,
    ports_of_entry: ports,
  };
  const json = JSON.stringify(payload, null, 2);
  try { await navigator.clipboard.writeText(json); } catch (_) {}
  console.log("Blue Intelligence · Noonsite corroboration", payload);
  alert("JSON Noonsite : " + ports.length + " port(s) — copié si le presse-papiers est autorisé. Collez-le dans la Console Formalités.");
  return payload;
})();"""

DISCLAIMER = (
    "Noonsite est un signal de corroboration, pas un Gold Dataset. "
    "Un PoE nommé comme tel sur Noonsite augmente la confiance ; "
    "l'absence d'un port sur Noonsite ne le réfute pas. "
    "Le quota gratuit (3 pays / mois) n'est jamais dépassé."
)


def month_key(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


def normalize_slug(value: str) -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"^https?://([^/]+\.)?noonsite\.com/place/", "", s)
    s = s.split("?")[0].split("#")[0].strip("/")
    s = s.split("/")[0]
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9-]+", "-", s).strip("-")
    return s


def country_url(slug: str) -> str:
    return f"{NOONSITE_ORIGIN}/place/{normalize_slug(slug)}/"


def normalize_place(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    slug = normalize_slug(raw.get("slug") or raw.get("name") or "")
    if not slug:
        return None
    name = (raw.get("name") or slug.replace("-", " ").title()).strip()
    mrgid = raw.get("mrgid")
    try:
        mrgid = int(mrgid) if mrgid not in (None, "") else None
    except (TypeError, ValueError):
        mrgid = None
    out = {"slug": slug, "name": name, "mrgid": mrgid}
    iso2 = (raw.get("iso2") or raw.get("country_iso2") or "").strip().upper()
    if iso2:
        out["iso2"] = iso2[:2]
    return out


def sanitize_watchlist(items) -> list[dict]:
    out, seen = [], set()
    for raw in items or []:
        place = normalize_place(raw)
        if not place or place["slug"] in seen:
            continue
        seen.add(place["slug"])
        out.append(place)
    return out


def can_harvest(slug: str, consumed: list[str], cap: int = MONTHLY_COUNTRY_CAP) -> bool:
    slug = normalize_slug(slug)
    if not slug:
        return False
    used = {normalize_slug(s) for s in consumed if s}
    return slug in used or len(used) < cap


def remaining_slots(consumed: list[str], cap: int = MONTHLY_COUNTRY_CAP) -> int:
    used = {normalize_slug(s) for s in consumed if s}
    return max(0, cap - len(used))


def harvest_goal(place: dict) -> str:
    name = place.get("name") or place["slug"]
    slug = place["slug"]
    url = country_url(slug)
    return (
        f"You are using a personal Noonsite account whose FREE plan allows THREE "
        f"countries per calendar month. Stay on ONE country only: {name} "
        f"(slug `{slug}`). Start at {url}. "
        "If a login form appears, complete login with the vault credential for "
        "noonsite.com (never invent credentials). "
        "If the site asks to unlock a DIFFERENT country, or shows a paywall / "
        "upgrade / premium wall for another place, STOP immediately. "
        "Unlock this country only if it is the page you already opened and the "
        "unlock prompt is for this same country. "
        "Then open Formalities / Clearance and Main Ports for this country. "
        "Extract every place explicitly labelled Port of Entry, Port of Clearance, "
        "or designated entry port for foreign yachts (example: Saba lists Fort Bay). "
        "Also read the country FAQ 'Where can I enter?'. "
        "Do not invent ports. Do not copy long articles — only the port name, "
        "optional settlement, is_port_of_entry, a short evidence phrase "
        "(max 120 characters), and the page URL. "
        "If a harbour is explicitly NOT a port of entry, include it with "
        "is_port_of_entry=false. "
        "Set logged_in, access_granted, and quota_blocked from what you actually see. "
        "If you unlocked or opened Formalities for this country, access_granted=true "
        "even when the port list is empty."
    )


def parse_extract_result(raw) -> dict:
    empty = {
        "country": "", "country_slug": "", "logged_in": False,
        "access_granted": False, "quota_blocked": False, "ports": [],
    }
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return empty
    if not isinstance(raw, dict):
        return empty
    data = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    if not isinstance(data, dict):
        return empty
    ports = []
    seen = set()
    for item in data.get("ports_of_entry") or data.get("ports") or []:
        if not isinstance(item, dict):
            continue
        name = re.sub(r"\s+", " ", (item.get("name") or "")).strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        evidence = re.sub(r"\s+", " ", str(item.get("evidence") or "")).strip()[:120]
        url = (item.get("page_url") or item.get("url") or "").strip()
        ports.append({
            "name": name[:80],
            "settlement": re.sub(r"\s+", " ", str(item.get("settlement") or "")).strip()[:80],
            "is_port_of_entry": bool(item.get("is_port_of_entry")),
            "page_url": url if url.startswith("http") else "",
            "evidence": evidence,
        })
    slug = normalize_slug(data.get("country_slug") or data.get("slug") or "")
    return {
        "country": (data.get("country") or "").strip()[:80],
        "country_slug": slug,
        "logged_in": bool(data.get("logged_in")),
        "access_granted": bool(data.get("access_granted")),
        "quota_blocked": bool(data.get("quota_blocked")),
        "ports": ports,
    }


def best_port_match(name: str, ports: list[dict]) -> tuple[dict | None, float]:
    best, score = None, 0.0
    for port in ports or []:
        pname = port.get("name") or ""
        city = port.get("city") or ""
        sc = text_similarity(name, pname)
        if city:
            sc = max(sc, text_similarity(name, city),
                     text_similarity(name, f"{pname} {city}"))
        if sc > score:
            best, score = port, sc
    if best is not None and score >= MATCH_THRESHOLD:
        return best, round(score, 3)
    return None, round(score, 3)


def auth_kwargs(settings: dict | None) -> dict:
    s = settings or {}
    profile = (s.get("noonsite_browser_profile") or "stealth").strip() or "stealth"
    if profile not in ("lite", "stealth"):
        profile = "stealth"
    kw = {
        "browser_profile": profile,
        "use_vault": bool(s.get("noonsite_use_vault", True)),
        "use_profile": bool(s.get("noonsite_use_profile", True)),
        "profile_id": (s.get("noonsite_profile_id") or "").strip() or None,
        "credential_item_ids": list(s.get("noonsite_credential_item_ids") or []),
    }
    if s.get("noonsite_use_proxy"):
        kw["proxy_config"] = {"enabled": True}
    return kw


def planned_slugs(watchlist: list[dict], consumed: list[str],
                  requested: list[str] | None = None,
                  cap: int = MONTHLY_COUNTRY_CAP) -> list[str]:
    """Pays à récolter : d'abord ceux déjà débloqués ce mois, puis les suivants
    jusqu'au plafond. `requested` restreint à un sous-ensemble."""
    watch = [p["slug"] for p in sanitize_watchlist(watchlist)]
    want = [normalize_slug(s) for s in (requested or watch)]
    want = [s for s in want if s and s in set(watch)]
    used = [normalize_slug(s) for s in consumed if s]
    used_set = set(used)
    already = [s for s in want if s in used_set]
    fresh = [s for s in want if s not in used_set]
    room = max(0, cap - len(used_set))
    return already + fresh[:room]


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------
async def load_month(db, month: str | None = None) -> dict:
    key = month or month_key()
    rec = await db.noonsite_months.find_one({"_id": key})
    slugs = [normalize_slug(s) for s in (rec or {}).get("slugs") or [] if s]
    return {"_id": key, "slugs": slugs, "updated_at": (rec or {}).get("updated_at")}


async def reserve_country(db, slug: str, month: str | None = None,
                          cap: int = MONTHLY_COUNTRY_CAP) -> tuple[bool, list[str]]:
    """Enregistre le pays dans le quota du mois. Re-récolte = gratuit."""
    slug = normalize_slug(slug)
    key = month or month_key()
    rec = await load_month(db, key)
    slugs = list(rec["slugs"])
    if slug in slugs:
        return True, slugs
    if len(slugs) >= cap:
        return False, slugs
    slugs.append(slug)
    await db.noonsite_months.update_one(
        {"_id": key},
        {"$set": {"slugs": slugs, "updated_at": now_iso()}},
        upsert=True,
    )
    return True, slugs


async def _ports_for_place(db, place: dict) -> list[dict]:
    if place.get("mrgid") is not None:
        docs = await db.poe_ports.find({"mrgid": int(place["mrgid"])}).to_list(500)
        if docs:
            return docs
    clauses = []
    if place.get("iso2"):
        clauses.append({"country_iso2": place["iso2"]})
    name = place.get("name")
    if name:
        clauses.append({"zone_name": {"$regex": re.escape(name), "$options": "i"}})
    if not clauses:
        return []
    return await db.poe_ports.find({"$or": clauses}).to_list(500)


async def apply_corroboration(db, *, slug: str, place: dict, ports: list[dict],
                              harvest_id: str, month: str, engine: str) -> dict:
    existing = await _ports_for_place(db, place)
    confirmed = unmatched = not_poe = 0
    signals = []
    stamp = now_iso()
    for item in ports:
        match, score = None, 0.0
        if item.get("is_port_of_entry"):
            match, score = best_port_match(item["name"], existing)
            if match:
                kind = "confirmed"
                confirmed += 1
                await db.poe_ports.update_one(
                    {"_id": match["_id"]},
                    {"$set": {
                        "noonsite_confirmed": True,
                        "noonsite_url": item.get("page_url") or country_url(slug),
                        "noonsite_checked_at": stamp,
                        "noonsite_name": item["name"],
                        "noonsite_slug": slug,
                    }},
                )
            else:
                kind = "unmatched"
                unmatched += 1
        else:
            kind = "not_poe"
            not_poe += 1
        signals.append({
            "_id": str(uuid.uuid4()),
            "month": month,
            "harvest_id": harvest_id,
            "slug": slug,
            "name": item["name"],
            "settlement": item.get("settlement") or "",
            "is_port_of_entry": bool(item.get("is_port_of_entry")),
            "page_url": item.get("page_url") or "",
            "evidence": item.get("evidence") or "",
            "match_kind": kind,
            "match_port_id": match["_id"] if match else None,
            "match_score": score if match else None,
            "engine": engine,
            "created_at": stamp,
        })
    if signals:
        await db.noonsite_signals.insert_many(signals)
    return {"confirmed": confirmed, "unmatched": unmatched, "not_poe": not_poe}


def _place_from_watch(watchlist: list[dict], slug: str) -> dict:
    slug = normalize_slug(slug)
    for p in sanitize_watchlist(watchlist):
        if p["slug"] == slug:
            return p
    return {"slug": slug, "name": slug.replace("-", " ").title(), "mrgid": None}


async def import_payload(db, settings: dict, raw, *, slug: str | None = None,
                         name: str | None = None, mrgid: int | None = None,
                         log=None) -> dict:
    """Import du JSON console (même schéma que TinyFish). Compte dans le quota
    : l'opérateur a déjà ouvert le pays sur Noonsite."""
    log = log or (lambda m: None)
    parsed = parse_extract_result(raw)
    watch = sanitize_watchlist((settings or {}).get("noonsite_watchlist"))
    resolved = normalize_slug(slug or parsed.get("country_slug") or "")
    if not resolved:
        raise ValueError("slug pays manquant (URL /place/{slug}/ ou champ country_slug)")
    place = _place_from_watch(watch, resolved)
    if name:
        place["name"] = name.strip()
    if mrgid not in (None, ""):
        place["mrgid"] = int(mrgid)
    month = month_key()
    ok, consumed = await reserve_country(db, resolved, month)
    if not ok:
        raise ValueError(
            f"Quota Noonsite épuisé ce mois ({month}) : {consumed}. "
            "Ré-importez un pays déjà débloqué, ou attendez le mois suivant.")
    hid = str(uuid.uuid4())
    stats = await apply_corroboration(
        db, slug=resolved, place=place, ports=parsed["ports"],
        harvest_id=hid, month=month, engine="console")
    doc = {
        "_id": hid,
        "month": month,
        "slug": resolved,
        "name": place.get("name"),
        "mrgid": place.get("mrgid"),
        "status": "ok" if parsed["ports"] else "empty",
        "logged_in": parsed["logged_in"],
        "access_granted": parsed["access_granted"],
        "quota_blocked": parsed["quota_blocked"],
        "engine": "console",
        "port_count": len(parsed["ports"]),
        **stats,
        "started_at": now_iso(),
        "finished_at": now_iso(),
    }
    await db.noonsite_harvests.insert_one(doc)
    log(f"import console {resolved}: {stats['confirmed']} confirmé(s), "
        f"{stats['unmatched']} candidat(s)")
    return {k: v for k, v in doc.items() if k != "_id"} | {"harvest_id": hid}


async def harvest_place(db, settings: dict, place: dict, log=None) -> dict:
    """Une récolte TinyFish pour un pays de la watchlist."""
    log = log or (lambda m: None)
    place = normalize_place(place)
    if not place:
        raise ValueError("pays Noonsite invalide")
    slug = place["slug"]
    month = month_key()
    rec = await load_month(db, month)
    if not can_harvest(slug, rec["slugs"]):
        return {
            "status": "quota_exhausted", "slug": slug, "month": month,
            "consumed": rec["slugs"],
        }
    key = tf_api_key(settings)
    if not key:
        raise ValueError("Clé TinyFish manquante (Paramètres ou TINYFISH_API_KEY)")
    hid = str(uuid.uuid4())
    started = now_iso()
    log(f"TinyFish · {place.get('name')} ({slug}) — Vault+profil, stealth")
    raw = await tf_run_and_wait(
        country_url(slug),
        harvest_goal(place),
        EXTRACT_SCHEMA,
        key,
        timeout_s=360,
        poll_s=4.0,
        max_duration_s=300,
        log=log,
        **auth_kwargs(settings),
    )
    parsed = parse_extract_result(raw)
    if parsed["quota_blocked"] and not parsed["access_granted"] and not parsed["ports"]:
        status = "quota_blocked"
        reserved, consumed = True, rec["slugs"]
        stats = {"confirmed": 0, "unmatched": 0, "not_poe": 0}
        log(f"{slug}: mur de quota Noonsite — pays non consommé dans notre registre")
    else:
        consumed_now = parsed["access_granted"] or bool(parsed["ports"]) or parsed["logged_in"]
        if consumed_now:
            reserved, consumed = await reserve_country(db, slug, month)
            if not reserved:
                status = "quota_exhausted"
                stats = {"confirmed": 0, "unmatched": 0, "not_poe": 0}
            else:
                stats = await apply_corroboration(
                    db, slug=slug, place=place, ports=parsed["ports"],
                    harvest_id=hid, month=month, engine="tinyfish")
                status = "ok" if parsed["ports"] else "empty"
        else:
            reserved, consumed = True, rec["slugs"]
            stats = {"confirmed": 0, "unmatched": 0, "not_poe": 0}
            status = "login_failed" if not parsed["logged_in"] else "empty"
            log(f"{slug}: pas d'accès Formalités (login={parsed['logged_in']})")
    doc = {
        "_id": hid,
        "month": month,
        "slug": slug,
        "name": place.get("name"),
        "mrgid": place.get("mrgid"),
        "status": status,
        "logged_in": parsed["logged_in"],
        "access_granted": parsed["access_granted"],
        "quota_blocked": parsed["quota_blocked"],
        "engine": "tinyfish",
        "port_count": len(parsed["ports"]),
        **stats,
        "started_at": started,
        "finished_at": now_iso(),
        "consumed": consumed,
    }
    await db.noonsite_harvests.insert_one(doc)
    log(f"{slug}: {status} · {stats.get('confirmed', 0)} confirmé(s) · "
        f"{stats.get('unmatched', 0)} candidat(s)")
    return {k: v for k, v in doc.items() if k != "_id"} | {"harvest_id": hid}


async def harvest_watchlist(db, settings: dict, slugs: list[str] | None = None,
                            log=None) -> dict:
    log = log or HARVEST_STATE.log
    watch = sanitize_watchlist((settings or {}).get("noonsite_watchlist"))
    month = month_key()
    rec = await load_month(db, month)
    todo = planned_slugs(watch, rec["slugs"], slugs)
    if not todo:
        log("aucun pays éligible (watchlist vide ou quota 3/3 déjà utilisé)")
        return {"month": month, "harvested": [], "skipped": "none_eligible",
                "consumed": rec["slugs"]}
    results = []
    by_slug = {p["slug"]: p for p in watch}
    for slug in todo:
        if HARVEST_STATE.cancel:
            log("annulation demandée")
            break
        rec = await load_month(db, month)
        if not can_harvest(slug, rec["slugs"]):
            log(f"{slug}: quota mensuel atteint — stop")
            break
        try:
            results.append(await harvest_place(db, settings, by_slug.get(slug) or {"slug": slug}, log))
        except Exception as e:
            log(f"{slug}: ÉCHEC {type(e).__name__}: {e}")
            results.append({"slug": slug, "status": "error", "error": f"{type(e).__name__}: {e}"})
        await asyncio_sleep_brief()
    return {"month": month, "harvested": results, "consumed": (await load_month(db, month))["slugs"]}


async def asyncio_sleep_brief():
    import asyncio
    await asyncio.sleep(1.2)


async def maybe_monthly_harvest(db, log=None) -> dict | None:
    """Un pays par cycle si la corroboration auto est activée."""
    from app.db import get_settings
    settings = await get_settings()
    if not settings.get("noonsite_enabled"):
        return None
    if HARVEST_STATE.running:
        return None
    if not tf_api_key(settings):
        return None
    watch = sanitize_watchlist(settings.get("noonsite_watchlist"))
    rec = await load_month(db)
    pending = planned_slugs(watch, rec["slugs"])
    pending = [s for s in pending if s not in set(rec["slugs"])]
    if not pending:
        return None
    HARVEST_STATE.start()
    try:
        HARVEST_STATE.total = 1
        place = next((p for p in watch if p["slug"] == pending[0]), {"slug": pending[0]})
        result = await harvest_place(db, settings, place, log or HARVEST_STATE.log)
        HARVEST_STATE.progress = 1
        HARVEST_STATE.results = [result]
        HARVEST_STATE.summary = result
        return result
    except Exception as e:
        HARVEST_STATE.error = f"{type(e).__name__}: {e}"
        HARVEST_STATE.log(str(HARVEST_STATE.error))
        return None
    finally:
        HARVEST_STATE.finish()


async def start_harvest(db, settings: dict, slugs: list[str] | None = None) -> dict:
    if HARVEST_STATE.running:
        raise RuntimeError("Une récolte Noonsite est déjà en cours")
    HARVEST_STATE.start()

    async def _runner():
        try:
            summary = await harvest_watchlist(db, settings, slugs, HARVEST_STATE.log)
            HARVEST_STATE.summary = summary
            HARVEST_STATE.results = summary.get("harvested") or []
            HARVEST_STATE.progress = len(HARVEST_STATE.results)
            HARVEST_STATE.total = max(HARVEST_STATE.progress, 1)
        except Exception as e:
            HARVEST_STATE.error = f"{type(e).__name__}: {e}"
            HARVEST_STATE.log(f"FATAL: {HARVEST_STATE.error}")
        finally:
            HARVEST_STATE.finish()

    import asyncio
    asyncio.create_task(_runner())
    return {"started": True, "slugs": slugs or []}


async def status_payload(db, settings: dict) -> dict:
    month = month_key()
    rec = await load_month(db, month)
    watch = sanitize_watchlist((settings or {}).get("noonsite_watchlist"))
    harvests = await db.noonsite_harvests.find({"month": month}).sort("finished_at", -1).to_list(20)
    for h in harvests:
        h["harvest_id"] = h.pop("_id", None)
    unmatched = await db.noonsite_signals.find(
        {"month": month, "match_kind": "unmatched"}
    ).sort("created_at", -1).to_list(40)
    for s in unmatched:
        s["id"] = s.pop("_id", None)
    confirmed = await db.poe_ports.count_documents({"noonsite_confirmed": True})
    key = bool(tf_api_key(settings))
    return {
        "enabled": bool((settings or {}).get("noonsite_enabled")),
        "month": month,
        "quota": {
            "cap": MONTHLY_COUNTRY_CAP,
            "used": len(rec["slugs"]),
            "remaining": remaining_slots(rec["slugs"]),
            "slugs": rec["slugs"],
        },
        "watchlist": watch,
        "planned": planned_slugs(watch, rec["slugs"]),
        "harvest": HARVEST_STATE.status(),
        "last_harvests": harvests,
        "unmatched": unmatched,
        "confirmed_ports": confirmed,
        "console_snippet": CONSOLE_SNIPPET,
        "tinyfish": {
            "key": key,
            "use_vault": bool((settings or {}).get("noonsite_use_vault", True)),
            "use_profile": bool((settings or {}).get("noonsite_use_profile", True)),
            "profile_id_set": bool((settings or {}).get("noonsite_profile_id")),
            "browser_profile": (settings or {}).get("noonsite_browser_profile") or "stealth",
        },
        "disclaimer": DISCLAIMER,
    }


def preview_automation_payload(settings: dict, slug: str = "saba") -> dict:
    """Exposé aux tests : le corps Agent API n'embarque aucun secret."""
    place = {"slug": slug, "name": slug.replace("-", " ").title()}
    return automation_payload(
        country_url(slug),
        harvest_goal(place),
        EXTRACT_SCHEMA,
        max_duration_s=300,
        **auth_kwargs(settings),
    )
