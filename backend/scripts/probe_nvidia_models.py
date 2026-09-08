#!/usr/bin/env python3
"""Sonde les modèles NVIDIA NIM du palier d'essai (build.nvidia.com).

Mesure, avec la même forme d'appel que l'adaptateur PoE :
  1. ping JSON strict
  2. juge Fort Bay (plaisance) vs Tiwai Point (cargo)
  3. extraction d'une liste officielle courte

Aucun écriture Mongo. Clé : NVIDIA_API_KEY.

  python scripts/probe_nvidia_models.py
  python scripts/probe_nvidia_models.py --only meta/muse-glimmer-30b,moonshotai/kimi-k3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

from app.core import nvidia  # noqa: E402
from app.core.llm import POE_EXTRACT_PROMPT, coerce_ports  # noqa: E402
from app.services.poe_seed_enrich import JUDGE_SYSTEM, parse_judge  # noqa: E402

NVIDIA_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"
NVIDIA_URL = nvidia.NVIDIA_URL

# Non-LLM ou hors chat JSON (ASR, embeddings, guard, bio, …).
_SKIP_RE = re.compile(
    r"embed|rerank|nvclip|arctic-embed|guard|safety|jailbreak|reward|"
    r"asr|tts|translate|ocr|parse|synthetic-video|ising-calibration|"
    r"fuyu|deplot|kosmos|paligemma|neva-22b|/vila$|starcoder2",
    re.I,
)

# Pile actuelle + candidats texte utiles pour le juge / l'extracteur.
CURATED = (
    nvidia.PRIMARY_MODEL,
    nvidia.LEGAL_MODEL,
    "poolside/laguna-xs-2.1",
    "moonshotai/kimi-k2.6",
    "google/gemma-4-31b-it",
    "google/gemma-3-12b-it",
    "google/gemma-3-4b-it",
    "google/diffusiongemma-26b-a4b-it",
    "mistralai/mistral-nemotron",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-nano-3-30b-a3b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "openai/gpt-oss-20b",
    "deepseek-ai/deepseek-v4-flash-0731",
    "deepseek-ai/deepseek-v4-pro-0813",
    "minimaxai/minimax-m3",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nv-mistralai/mistral-nemo-12b-instruct",
    "microsoft/phi-3.5-moe-instruct",
    "ibm/granite-3.0-8b-instruct",
    "mistralai/mistral-7b-instruct-v0.3",
    "mistralai/mistral-large-2-instruct",
)

PING_USER = 'Réponds uniquement avec {"ok": true}.'
EXTRACT_CONTEXT = (
    "Arrêté relatif aux points de passage frontaliers maritimes pour la "
    "plaisance. Sont habilités : Dunkerque, Calais, Saint-Malo, Brest, "
    "La Rochelle. Les formalités de police aux frontières s'y accomplissent."
)
EXPECTED_PORTS = ("dunkerque", "calais", "saint-malo", "brest", "la rochelle")

JUDGE_CASES = (
    {
        "id": "fort_bay",
        "expect": "accepted",
        "kinds": ("pleasure", "mixed"),
        "prompt": (
            "Candidat : Fort Bay\n"
            "Zone VLIZ : Saba (mrgid=21090, BQ)\n"
            "Juge uniquement CE lieu à partir des extraits. "
            "Ne liste aucun autre port.\n\n"
            "EXTRAITS:\n"
            "Fort Bay Harbour is the official port of entry for visiting "
            "yachts and pleasure craft on Saba. Clearance must be completed here."
        ),
    },
    {
        "id": "tiwai",
        "expect": "rejected",
        "kinds": ("cargo", "other", "unknown"),
        "prompt": (
            "Candidat : Tiwai Point\n"
            "Zone VLIZ : New Zealand (mrgid=8455, NZ)\n"
            "Juge uniquement CE lieu à partir des extraits. "
            "Ne liste aucun autre port.\n\n"
            "EXTRAITS:\n"
            "Tiwai Point is an industrial aluminium smelter wharf. "
            "Commercial cargo only. Not designated for pleasure craft clearance."
        ),
    },
)


def _key() -> str:
    key = nvidia.get_nvidia_key()
    if not key:
        raise SystemExit("NVIDIA_API_KEY manquante")
    return key


def _headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def is_chat_candidate(model_id: str) -> bool:
    return bool(model_id) and not _SKIP_RE.search(model_id)


def _payload(model: str, system: str, user: str, max_tokens: int,
              json_object: bool = True) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
        **nvidia.muse_generation_extras(model),
    }
    if json_object:
        body["response_format"] = {"type": "json_object"}
    return body


def _err_text(status: int, text: str, limit: int = 220) -> str:
    blob = (text or "").replace("\n", " ")
    return f"HTTP {status}: {blob[:limit]}"


def _retry_wait(response: httpx.Response, fallback: float = 8.0) -> float:
    return nvidia._retry_wait(response, fallback)


async def post_chat(client: httpx.AsyncClient, key: str, payload: dict,
                     *, retries: int = 1) -> dict:
    """Un POST chat/completions. 1 retry 429 ; retry sans json_object si 400."""
    used = dict(payload)
    last = {"ok": False, "status": 0, "error": "no response", "raw": "",
            "json": None, "latency_s": 0.0, "finish": None, "usage": {}}
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            r = await client.post(NVIDIA_URL, headers=_headers(key), json=used)
        except httpx.TimeoutException as e:
            last = {
                "ok": False, "status": 0,
                "error": f"timeout {type(e).__name__}",
                "raw": "", "json": None,
                "latency_s": round(time.perf_counter() - t0, 2),
                "finish": None, "usage": {},
            }
            continue
        except httpx.HTTPError as e:
            last = {
                "ok": False, "status": 0,
                "error": f"{type(e).__name__}: {e}",
                "raw": "", "json": None,
                "latency_s": round(time.perf_counter() - t0, 2),
                "finish": None, "usage": {},
            }
            continue
        latency = round(time.perf_counter() - t0, 2)
        body_txt = r.text or ""
        if r.status_code == 429 and attempt < retries:
            await asyncio.sleep(_retry_wait(r))
            continue
        if (r.status_code == 400 and used.get("response_format")
                and attempt < retries
                and re.search(r"response_format|json_object|structured",
                              body_txt, re.I)):
            used = {k: v for k, v in used.items() if k != "response_format"}
            last = {
                "ok": False, "status": r.status_code,
                "error": _err_text(r.status_code, body_txt),
                "raw": body_txt[:400], "json": None, "latency_s": latency,
                "finish": None, "usage": {}, "json_object_rejected": True,
            }
            continue
        parsed_body = {}
        try:
            parsed_body = r.json()
        except Exception:
            parsed_body = {}
        if r.status_code >= 400:
            return {
                "ok": False, "status": r.status_code,
                "error": _err_text(r.status_code, body_txt),
                "raw": body_txt[:400], "json": None, "latency_s": latency,
                "finish": None, "usage": parsed_body.get("usage") or {},
                "json_object": "response_format" in used,
            }
        choices = parsed_body.get("choices") or []
        msg = (choices[0].get("message") or {}) if choices else {}
        raw = nvidia._message_text(msg)
        data = nvidia.parse_json_strict(raw)
        if not isinstance(data, dict):
            # Filet : JSON noyé après une courte prose (hors adaptateur).
            data = None
            try:
                from app.core.llm import parse_json_flexible
                flex = parse_json_flexible(raw)
                if isinstance(flex, dict):
                    data = flex
            except Exception:
                pass
        finish = (choices[0].get("finish_reason") if choices else None)
        return {
            "ok": isinstance(data, dict),
            "status": r.status_code,
            "error": None if isinstance(data, dict) else "no JSON in output",
            "raw": (raw or "")[:500],
            "json": data if isinstance(data, dict) else None,
            "latency_s": latency,
            "finish": finish,
            "usage": parsed_body.get("usage") or {},
            "json_object": "response_format" in used,
        }
    return last


async def list_models(client: httpx.AsyncClient, key: str) -> list[str]:
    r = await client.get(NVIDIA_MODELS_URL, headers=_headers(key))
    r.raise_for_status()
    data = r.json().get("data") or []
    return [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def score_extract(ports: list[dict]) -> dict:
    names = [_norm(p.get("name") or "") for p in ports]
    found = [exp for exp in EXPECTED_PORTS if any(exp.replace("-", "") in n
                                                   or _norm(exp) in n
                                                   for n in names)]
    invented = [p.get("name") for p in ports
                if _norm(p.get("name") or "")
                and not any(_norm(exp) in _norm(p.get("name") or "")
                            or _norm(p.get("name") or "") in _norm(exp)
                            for exp in EXPECTED_PORTS)]
    return {
        "n": len(ports),
        "found": found,
        "missing": [e for e in EXPECTED_PORTS if e not in found],
        "invented": invented,
        "ok": len(found) >= 4 and not invented,
    }


def score_judge(case: dict, data: dict | None) -> dict:
    judged = parse_judge(data)
    kind_ok = judged["judge_kind"] in case["kinds"]
    status_ok = judged["judge_status"] == case["expect"]
    return {
        "ok": status_ok,
        "status": judged["judge_status"],
        "kind": judged["judge_kind"],
        "confidence": judged["judge_confidence"],
        "reason": judged["judge_reason"][:160],
        "kind_ok": kind_ok,
    }


async def ping_one(client: httpx.AsyncClient, key: str, model: str) -> dict:
    payload = _payload(model, "Tu réponds uniquement en JSON strict.",
                       PING_USER, 300)
    out = await post_chat(client, key, payload, retries=1)
    out["model"] = model
    out["task"] = "ping"
    return out


async def quality_one(client: httpx.AsyncClient, key: str, model: str) -> dict:
    row = {"model": model, "tasks": {}}
    for case in JUDGE_CASES:
        payload = _payload(model, JUDGE_SYSTEM, case["prompt"], 800)
        out = await post_chat(client, key, payload, retries=1)
        if out.get("ok") and out.get("json"):
            scored = score_judge(case, out["json"])
        else:
            scored = {"ok": False, "status": "error",
                      "error": out.get("error"), "raw": out.get("raw")}
        scored["latency_s"] = out.get("latency_s")
        scored["http"] = out.get("status")
        scored["json_object"] = out.get("json_object")
        row["tasks"][case["id"]] = scored

    extract_prompt = POE_EXTRACT_PROMPT.format(
        name="France", sovereign="France", context=EXTRACT_CONTEXT)
    payload = _payload(model, "Tu réponds uniquement en JSON strict.",
                       extract_prompt, 1200)
    out = await post_chat(client, key, payload, retries=1)
    if out.get("ok") and out.get("json"):
        ports = coerce_ports(out["json"], context=EXTRACT_CONTEXT)
        scored = score_extract(ports)
        scored["ports"] = [p.get("name") for p in ports]
    else:
        scored = {"ok": False, "error": out.get("error"), "raw": out.get("raw"),
                  "n": 0, "found": [], "missing": list(EXPECTED_PORTS),
                  "invented": []}
    scored["latency_s"] = out.get("latency_s")
    scored["http"] = out.get("status")
    row["tasks"]["extract"] = scored

    judges_ok = all(row["tasks"][c["id"]].get("ok") for c in JUDGE_CASES)
    row["quality_ok"] = bool(judges_ok and row["tasks"]["extract"].get("ok"))
    row["app_compatible"] = all(
        t.get("http") == 200 for t in row["tasks"].values())
    return row


def _summary_table(pings: list[dict], qualities: list[dict]) -> str:
    by_q = {q["model"]: q for q in qualities}
    lines = [
        f"{'modèle':<52} {'ping':<6} {'ms':>7} {'juge+extract':<14} détail",
        "-" * 110,
    ]
    for p in pings:
        q = by_q.get(p["model"])
        ping = "OK" if p.get("ok") else "FAIL"
        qflag = ""
        detail = (p.get("error") or "")[:40]
        if q:
            qflag = "OK" if q.get("quality_ok") else "FAIL"
            bits = []
            for name, task in q["tasks"].items():
                mark = "✓" if task.get("ok") else "✗"
                bits.append(f"{name}:{mark}")
            detail = " ".join(bits)
        elif not p.get("ok"):
            detail = (p.get("error") or "")[:50]
        ms = int((p.get("latency_s") or 0) * 1000)
        lines.append(f"{p['model']:<52} {ping:<6} {ms:7d} {qflag:<14} {detail}")
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/opt/cursor/artifacts/nvidia_probe.json")
    ap.add_argument("--only", default="",
                    help="Liste d'id séparés par des virgules")
    ap.add_argument("--all-catalog", action="store_true",
                    help="Ping tous les chat du catalogue, pas seulement CURATED")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--no-quality", action="store_true")
    args = ap.parse_args()

    key = _key()
    timeout = httpx.Timeout(90.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        catalog = await list_models(client, key)
        chat = [m for m in catalog if is_chat_candidate(m)]
        if args.only:
            wanted = [m.strip() for m in args.only.split(",") if m.strip()]
        elif args.all_catalog:
            wanted = chat
        else:
            wanted = [m for m in CURATED if m in catalog]
            for extra in (nvidia.PRIMARY_MODEL, nvidia.LEGAL_MODEL,
                          "poolside/laguna-xs-2.1"):
                if extra not in wanted:
                    wanted.append(extra)

        sem = asyncio.Semaphore(max(1, args.concurrency))

        async def ping_guarded(model: str) -> dict:
            async with sem:
                row = await ping_one(client, key, model)
                flag = "OK" if row.get("ok") else "FAIL"
                print(f"[ping] {flag:4} {model}  {row.get('latency_s')}s  "
                      f"{row.get('error') or (row.get('json') or {})}",
                      flush=True)
                await asyncio.sleep(0.4)
                return row

        pings = list(await asyncio.gather(*[ping_guarded(m) for m in wanted]))

        qualities: list[dict] = []
        if not args.no_quality:
            quality_ids = []
            for m in wanted:
                ping = next((p for p in pings if p["model"] == m), None)
                if m in (nvidia.PRIMARY_MODEL, nvidia.LEGAL_MODEL,
                           "poolside/laguna-xs-2.1"):
                    quality_ids.append(m)
                elif ping and ping.get("ok"):
                    quality_ids.append(m)
            # Un modèle à la fois : juge + extract ≈ 3 appels.
            for model in quality_ids:
                print(f"[quality] {model} …", flush=True)
                row = await quality_one(client, key, model)
                flag = "OK" if row.get("quality_ok") else "FAIL"
                print(f"[quality] {flag:4} {model}  {row['tasks']}", flush=True)
                qualities.append(row)

    report = {
        "catalog_n": len(catalog),
        "chat_candidates_n": len(chat),
        "catalog_chat": chat,
        "tested": wanted,
        "pings": pings,
        "quality": qualities,
        "current_defaults": {
            "primary": nvidia.PRIMARY_MODEL,
            "secondary": nvidia.SECONDARY_MODEL,
            "legal": nvidia.LEGAL_MODEL,
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    md = _summary_table(pings, qualities)
    md_path = out_path.with_suffix(".txt")
    md_path.write_text(md + "\n")
    print("\n" + md)
    print(f"\nécrit {out_path} et {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
