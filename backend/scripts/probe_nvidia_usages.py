#!/usr/bin/env python3
"""Tests dirigés par usage Blue Intelligence (NIM hosted).

Usages : juge PoE, extract décret, JSON court, page marina/capitainerie.
Aucun Mongo. Clé NVIDIA_API_KEY.

  python scripts/probe_nvidia_usages.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
load_dotenv(BACKEND / ".env")

from app.core import nvidia  # noqa: E402
from app.core.llm import POE_EXTRACT_PROMPT, coerce_ports  # noqa: E402
from app.services.poe_seed_enrich import JUDGE_SYSTEM  # noqa: E402
import probe_nvidia_models as probe  # noqa: E402

USEFUL = (
    nvidia.PRIMARY_MODEL,
    nvidia.SECONDARY_MODEL,
    nvidia.GPT_OSS_MODEL,
    nvidia.FLASH_MODEL,
    nvidia.LEGAL_MODEL,
    "meta/llama-3.2-11b-vision-instruct",
    "poolside/laguna-xs-2.1",
)

MARINA_PAGE = (
    "Port des Minimes — La Rochelle. Capitainerie VHF canal 9. "
    "Téléphone 05 46 41 44 20. 320 places visiteurs. Tirant d'eau max 3,5 m. "
    "Services : eau, électricité, douches, wifi, carburant. Port bien abrité."
)
MARINA_PROMPT = (
    "Return STRICT JSON:\n"
    '{"canal_vhf": string|null, "places_visiteurs": integer|null, '
    '"tirant_eau_max_metres": number|null, "telephone_capitainerie": string|null, '
    '"services_disponibles": string[]|null}\n\n'
    f"Marina: Port des Minimes\nWebsite:\n{MARINA_PAGE}\n"
    "Set a field to null if absent. NEVER fabricate. JSON only."
)


def _score_marina(data: dict | None) -> dict:
    d = data or {}
    vhf = str(d.get("canal_vhf") or "")
    tel = str(d.get("telephone_capitainerie") or "")
    places = d.get("places_visiteurs")
    draft = d.get("tirant_eau_max_metres")
    vhf_ok = "9" in vhf
    tel_ok = "05" in tel.replace(" ", "") or "546" in tel.replace(" ", "")
    places_ok = isinstance(places, int) and 200 <= places <= 400
    draft_ok = isinstance(draft, (int, float)) and 3 <= float(draft) <= 4
    return {
        "vhf_ok": vhf_ok, "tel_ok": tel_ok, "places_ok": places_ok,
        "draft_ok": draft_ok,
        "ok": vhf_ok and tel_ok,
        "data": {k: d.get(k) for k in (
            "canal_vhf", "places_visiteurs", "tirant_eau_max_metres",
            "telephone_capitainerie", "services_disponibles")},
    }


async def one_task(client, key, model, system, user, max_tokens, json_object=None):
    payload = nvidia.chat_payload(
        model, system, user, max_tokens, json_object=json_object)
    return await probe.post_chat(client, key, payload, retries=1, require_json=True)


async def run_model(client, key, model) -> dict:
    row = {"model": model, "tasks": {}}
    t0 = time.perf_counter()
    for case in probe.JUDGE_CASES:
        r = await one_task(client, key, model, JUDGE_SYSTEM, case["prompt"], 800)
        scored = probe.score_judge(case, r.get("json") or {})
        scored["latency_s"] = r.get("latency_s")
        scored["http"] = r.get("status")
        scored["error"] = r.get("error")
        scored["json_object"] = r.get("json_object")
        row["tasks"][case["id"]] = scored
        print(f"  [{model.split('/')[-1]}] {case['id']}: "
              f"{'OK' if scored.get('ok') else 'FAIL'} {r.get('latency_s')}s "
              f"{r.get('error') or ''}"[:120], flush=True)
    prompt = POE_EXTRACT_PROMPT.format(
        name="France hexagone", sovereign="France", context=probe.EXTRACT_CONTEXT)
    r = await one_task(
        client, key, model, "Tu réponds uniquement en JSON strict.", prompt, 2500)
    ports = coerce_ports(r.get("json") or {}, context=probe.EXTRACT_CONTEXT)
    ex = probe.score_extract(ports)
    ex["latency_s"] = r.get("latency_s")
    ex["http"] = r.get("status")
    ex["error"] = r.get("error")
    row["tasks"]["extract"] = ex
    print(f"  [{model.split('/')[-1]}] extract: "
          f"{'OK' if ex.get('ok') else 'FAIL'} {r.get('latency_s')}s "
          f"{ex.get('ports') or r.get('error')}"[:140], flush=True)
    r = await one_task(
        client, key, model, "JSON strict.", MARINA_PROMPT, 400)
    marina = _score_marina(r.get("json") if r.get("ok") else None)
    marina["latency_s"] = r.get("latency_s")
    marina["http"] = r.get("status")
    marina["error"] = r.get("error")
    row["tasks"]["marina"] = marina
    print(f"  [{model.split('/')[-1]}] marina: "
          f"{'OK' if marina.get('ok') else 'FAIL'} {r.get('latency_s')}s "
          f"{marina.get('data') or r.get('error')}"[:140], flush=True)
    row["elapsed_s"] = round(time.perf_counter() - t0, 2)
    row["quality_ok"] = all(
        row["tasks"][k].get("ok") for k in ("fort_bay", "tiwai", "extract", "marina"))
    return row


async def main() -> None:
    key = probe._key()
    timeout = httpx.Timeout(120.0, connect=20.0)
    out = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in USEFUL:
            print(f"[usage] {model} …", flush=True)
            try:
                row = await run_model(client, key, model)
            except Exception as e:
                row = {"model": model, "error": f"{type(e).__name__}: {e}",
                       "quality_ok": False, "tasks": {}}
            out.append(row)
            print(f"[usage] {'OK' if row.get('quality_ok') else 'FAIL'} {model}",
                  flush=True)
            await asyncio.sleep(0.8)
    path = Path("/opt/cursor/artifacts/nvidia_usage_directed.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    lines = [f"{r['model']:<52} {'OK' if r.get('quality_ok') else 'FAIL':<6} "
             + " ".join(
                 f"{k}:{'✓' if (r.get('tasks') or {}).get(k, {}).get('ok') else '✗'}"
                 for k in ("fort_bay", "tiwai", "extract", "marina"))
             for r in out]
    txt = "\n".join(lines) + "\n"
    path.with_suffix(".txt").write_text(txt)
    print("\n" + txt)
    print(f"écrit {path}")


if __name__ == "__main__":
    asyncio.run(main())
