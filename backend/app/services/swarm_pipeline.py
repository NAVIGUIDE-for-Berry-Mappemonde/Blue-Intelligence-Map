import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.llm import extract_project, gatekeeper_check, has_llm
from app.static_data.categories import normalize_category
from app.core.dedup import is_duplicate
from app.core.extract import extract_cascade
from app.core.project_geo import geocode_project_site, site_publishable, valid_coords
from app.core.rag import select_context
from app.static_data.seeds import (
    CRAWL_BLACKLIST, CURATED_SEEDS, MASTER_SEEDS, TEST_SEED_COUNT, URL_PATTERNS,
)
from app.services.master_seeds import (
    domain_of, is_known_funder, listing_url_for_name, seeds_for_run,
)
from app.core.tinyfish import (DISCOVERY_SCHEMA, discovery_goal, find_live_url,
                             tf_get_run, tf_run_async, tf_run_sse)
from app.core.events import RUNS_DIR, HeartbeatWatch

logger = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def pick_image(full_soup, content_soup, base_url):
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}, {"property": "twitter:image"}):
        m = full_soup.find("meta", attrs=attrs)
        if m and m.get("content", "").strip():
            return urljoin(base_url, m["content"].strip())
    for img in content_soup.find_all("img", src=True):
        src = img["src"].strip()
        low = src.lower()
        if src.startswith("data:") or low.endswith(".svg"):
            continue
        if any(b in low for b in ("logo", "icon", "sprite", "avatar", "placeholder", "pixel")):
            continue
        return urljoin(base_url, src)
    return None


class Swarm:
    def __init__(self, db):
        self.db = db
        self.running = False
        self.mode = "test"
        self.logs = deque(maxlen=4000)
        self.agents = {}
        self.agent_seq = 0
        self.queue = None
        self.main_task = None
        self.workers = []
        self.settings = {}
        self.queued_count = 0
        self.recursive_tasks = []
        self.partner_domains = set()
        self.partner_count = 0
        self.new_partner_count = 0
        self.master_seeds = []
        self._tf_sem = None
        self.no_new_streak = 0
        self.saturated = False
        self.run_id = None
        self.recorder = None
        self.force_rescan = False
        self.wrote_projects = False

    # ---------- state helpers ----------
    def log(self, msg, level="info"):
        entry = {"ts": now_iso(), "msg": msg, "level": level}
        self.logs.append(entry)
        rid = self.run_id
        if rid:
            try:
                RUNS_DIR.mkdir(parents=True, exist_ok=True)
                path = RUNS_DIR / f"{rid}.swarm.jsonl"
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as exc:
                logger.warning("swarm JSONL append failed run_id=%s: %s", rid, exc)

    def new_agent(self, engine, mode, url, source=""):
        self.agent_seq += 1
        aid = f"A{self.agent_seq:03d}"
        self.agents[aid] = {
            "id": aid, "engine": engine, "mode": mode, "url": url, "source": source,
            "status": "PENDING", "live_url": None, "logs": [], "ts": now_iso(),
        }
        done = [k for k, a in self.agents.items() if a["status"] not in ("PENDING", "RUNNING")]
        while len(self.agents) > 40 and done:
            del self.agents[done.pop(0)]
        return aid

    def agent_log(self, aid, msg):
        a = self.agents.get(aid)
        if a:
            a["logs"].append(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")
            a["logs"] = a["logs"][-8:]

    def set_agent(self, aid, **kw):
        a = self.agents.get(aid)
        if a:
            a.update(kw)

    async def telemetry(self, url, engine, status, duration_ms, results=0, detail=""):
        await self.db.telemetry.insert_one({
            "_id": str(uuid.uuid4()), "url": url, "engine": engine, "status": status,
            "duration_ms": int(duration_ms), "results": results, "detail": str(detail)[:500],
            "ts": now_iso(), "dataset": "projects", "run_id": self.run_id,
        })

    async def add_failed(self, url, source, funder, reason, stage):
        await self.db.failed.update_one(
            {"url": url},
            {"$set": {"url": url, "source": source, "funder": funder,
                      "reason": str(reason)[:300], "stage": stage, "ts": now_iso(),
                      "dataset": "projects", "run_id": self.run_id},
             "$setOnInsert": {"_id": str(uuid.uuid4())}},
            upsert=True,
        )

    async def _emit(self, step: str, **payload):
        rec = self.recorder
        if rec is not None:
            try:
                await rec.event(step, **payload)
            except Exception as exc:
                logger.warning("swarm recorder.event failed step=%s: %s", step, exc)

    async def _bump_run(self, key: str):
        if not self.run_id:
            return
        from app.services.project_runs import bump_counter
        try:
            await bump_counter(self.db, self.run_id, key)
        except Exception:
            pass

    async def _ensure_isolated_run(self, *, mode: str, settings: dict | None = None,
                                   force_rescan: bool = False, label: str = ""):
        """Ouvre un run project_run_* si aucun n'est déjà attaché. N'écrit pas `projects`."""
        if self.run_id:
            return self.run_id
        from app.services.project_runs import open_run
        opened = await open_run(
            self.db, mode=mode, label=label or f"projects-{mode}",
            settings=settings or self.settings, force_rescan=force_rescan)
        self.run_id = opened["run_id"]
        self.recorder = opened["recorder"]
        self.wrote_projects = False
        return self.run_id

    async def _write_verdict(self, item: dict, verdict: str, **fields):
        """Persiste une ligne de run. Interdit toute écriture dans `projects`."""
        if not self.run_id:
            raise RuntimeError("isolated run required — no write to projects")
        from app.services.project_runs import COUNTER_FOR_VERDICT, write_run_project
        url = item["url"]
        funder = item.get("funder") or fields.get("funder") or ""
        doc = {
            "url": url,
            "title": fields.pop("title", None) or url,
            "funder": funder,
            "funders": fields.pop("funders", None) or ([funder] if funder else []),
            "verdict": verdict,
            **fields,
        }
        await write_run_project(self.db, self.run_id, doc)
        key = COUNTER_FOR_VERDICT.get(verdict)
        if key:
            await self._bump_run(key)
        await self._emit("project_verdict", url=url, verdict=verdict, title=doc.get("title"))
        return doc

    def status(self):
        agents = list(self.agents.values())[::-1][:20]
        return {
            "running": self.running,
            "mode": self.mode,
            "llm": has_llm(self.settings),
            "tinyfish": bool(self._tf_key()),
            "active": sum(1 for a in self.agents.values() if a["status"] in ("PENDING", "RUNNING")),
            "queued": self.queued_count,
            "agents": agents,
            "logs": list(self.logs)[-200:],
            "run_id": self.run_id,
            "wrote_projects": False,
        }

    def _tf_key(self):
        return (self.settings.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY") or "").strip()

    # ---------- lifecycle ----------
    def _bump_saturation(self, new_project: bool):
        if new_project:
            self.no_new_streak = 0
            return
        self.no_new_streak += 1
        limit = int(self.settings.get("saturation_limit", 50))
        if limit > 0 and self.no_new_streak >= limit and self.running and not self.saturated:
            self.saturated = True
            self.log(f"Auto-Stop: {self.no_new_streak} consecutive extractions without a new unique project — graceful shutdown to save credits", "warn")
            asyncio.create_task(self.stop())

    async def deploy(self, mode: str, clear_db: bool, settings: dict, force_rescan: bool = False,
                     run_id: str | None = None, recorder=None):
        if self.running:
            raise ValueError("swarm already running")
        self.settings = settings
        self.mode = mode
        self.force_rescan = force_rescan
        if clear_db:
            raise ValueError("clear_db is disabled")
        if run_id:
            self.run_id = run_id
            self.recorder = recorder
        else:
            await self._ensure_isolated_run(
                mode=mode, settings=settings, force_rescan=force_rescan)
        self.wrote_projects = False
        self.running = True
        self.logs.clear()
        self.no_new_streak = 0
        self.saturated = False
        self.log(f"Isolated run {self.run_id} — writes project_run_* only (wrote_projects: false)")
        self.log(f"Deploying Swarm — mode: {mode.upper()} | cascade N1 (gratuit) → N2 → N3 TinyFish (dernier recours)")
        self.log(f"Auto-Stop armed: shutdown after {int(settings.get('saturation_limit', 50))} extractions without new project")
        self.log(f"TinyFish key: {'ACTIVE (N3 last-resort only)' if self._tf_key() else 'MISSING → N1/N2 only'}",
                 "info")
        self.log(f"LLM pipeline: {'ACTIVE' if has_llm(settings) else 'MISSING → heuristic gatekeeper/extractor'}",
                 "info" if has_llm(settings) else "warn")
        self.main_task = asyncio.create_task(self._run())

    async def stop(self):
        self.log("Stop requested — cancelling agents and flushing queue", "warn")
        if self.main_task:
            self.main_task.cancel()
        for w in self.workers:
            w.cancel()
        self.workers = []
        if self.queue:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except asyncio.QueueEmpty:
                    break
        self.queued_count = 0
        for a in self.agents.values():
            if a["status"] in ("PENDING", "RUNNING"):
                a["status"] = "CANCELLED"
        self.running = False
        self.log("Swarm stopped")

    async def _run(self):
        cancelled = False
        error = None
        hb = HeartbeatWatch(self.recorder).start(lambda: {
            "progress": self.queued_count,
            "active": sum(1 for a in self.agents.values()
                          if a["status"] in ("PENDING", "RUNNING")),
            "last_item": next(
                (a.get("url") for a in reversed(list(self.agents.values()))
                 if a.get("status") == "RUNNING"),
                None,
            ),
        })
        try:
            extras = []
            try:
                extras = await self.db.master_seeds.find({}).to_list(2000)
            except Exception:
                extras = []
            self.master_seeds = list(MASTER_SEEDS) + [
                e for e in extras
                if (e.get("url") or e.get("name"))
                and not is_known_funder(MASTER_SEEDS, e.get("name"), e.get("url"))
            ]
            if self.mode == "test":
                seeds = list(CURATED_SEEDS[:TEST_SEED_COUNT])
            else:
                seeds = seeds_for_run(self.master_seeds)
            max_urls = int(self.settings.get("test_max_urls_per_seed", 6)) if self.mode == "test" \
                else int(self.settings.get("full_max_urls_per_seed", 20))
            self.queue = asyncio.Queue()
            self.recursive_tasks = []
            self.partner_domains = {domain_of(s.get("url")) for s in seeds if s.get("url")}
            self.partner_domains.discard("")
            self.partner_count = 0
            self.new_partner_count = 0
            concurrency = max(1, min(20, int(self.settings.get("extract_concurrency", 6))))
            discover_n = max(1, min(12, int(self.settings.get("discover_concurrency", 8))))
            self.workers = [asyncio.create_task(self._extract_worker(i)) for i in range(concurrency)]
            self.log(
                f"MasterSeeds loaded: {len(seeds)} portals in queue "
                f"(catalog={len(self.master_seeds)}, "
                f"discover_concurrency={discover_n}, extract_concurrency={concurrency})"
            )

            if self.mode == "full":
                cached = await self.db.deeplink_pages.find({}).to_list(5000)
                if cached:
                    existing = {p["url"] for p in await self.db.projects.find({}, {"url": 1}).to_list(30000)}
                    fresh = [c for c in cached if c["url"] not in existing]
                    self.log(f"DeepLinkCache: {len(cached)} pages cached, {len(fresh)} not yet extracted → queued")
                    for c in fresh:
                        self.queued_count += 1
                        await self.queue.put({"url": c["url"], "funder": c.get("funder", ""), "source": c.get("source", "cache")})

            from app.core.run_rules import get_rule
            tf_agents = max(1, min(2, int(get_rule(
                "projects.tinyfish_agents",
                self.settings.get("tinyfish_agents", 2)))))
            self._tf_sem = asyncio.Semaphore(tf_agents)
            discover_sem = asyncio.Semaphore(discover_n)

            async def guarded(seed):
                async with discover_sem:
                    await self._discover(seed, max_urls)

            await asyncio.gather(*[guarded(s) for s in seeds], return_exceptions=True)
            self.log("Discovery phase complete — waiting for extraction queue to drain")
            while True:
                await self.queue.join()
                pending = [t for t in self.recursive_tasks if not t.done()]
                if not pending:
                    break
                self.log(f"Follow the Money: waiting on {len(pending)} recursive discovery agent(s)")
                await asyncio.gather(*pending, return_exceptions=True)
            for w in self.workers:
                w.cancel()
            self.workers = []
            n_sites = 0
            if self.run_id:
                n_sites = await self.db.project_run_projects.count_documents(
                    {"run_id": self.run_id, "verdict": "site"})
            self.log(
                f"Pipeline complete — {n_sites} sites in run {self.run_id} "
                f"(wrote_projects: false)",
                "success",
            )
        except asyncio.CancelledError:
            cancelled = True
        except Exception as e:
            error = str(e)
            self.log(f"Pipeline error: {e}", "error")
        finally:
            from app.services.project_runs import finalize_run
            try:
                await finalize_run(
                    self.db, self.run_id, cancelled=cancelled, error=error)
            except Exception:
                pass
            await hb.aclose()
            self.running = False

    # ---------- discovery (cascade : N1 crawler gratuit → N3 TinyFish dernier recours) ----------
    async def _discover(self, seed, max_urls, depth=0):
        # Incremental discovery: skip seeds scanned recently (TTL), unless force_rescan
        listing = (seed.get("url") or "").strip()
        if not listing:
            self.log(f"[{seed.get('name')}] skipped — no listing URL", "warn")
            return
        await self._emit("discover_seed", seed=seed.get("name"), url=listing,
                         depth=depth)
        known_urls = []
        force = bool(getattr(self, "force_rescan", False))
        if depth == 0:
            state = await self.db.discovery_state.find_one({"seed_url": seed["url"]})
            rescan_days = float(self.settings.get("rescan_after_days", 7))
            if state and state.get("last_scan") and not force:
                try:
                    last = datetime.fromisoformat(state["last_scan"])
                    age_days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
                    if age_days < rescan_days:
                        self.log(f"[{seed['name']}] discovery skipped — scanned {age_days:.1f}d ago (TTL {rescan_days:g}d, cache reused)")
                        return
                except ValueError:
                    pass
            if not force:
                cached = await self.db.deeplink_pages.find({"source": seed["url"]}, {"url": 1}).to_list(300)
                known_urls = [c["url"] for c in cached]
                if known_urls:
                    self.log(f"[{seed['name']}] delta scan — {len(known_urls)} known URLs excluded from mission")
            else:
                self.log(f"[{seed['name']}] from scratch — TTL et URLs déjà connues non sautés")
        key = self._tf_key()
        aid = self.new_agent("Crawler N1", "discover", seed["url"], seed["name"])
        t0 = time.time()
        urls = []
        used_engine = "Crawler"
        crawl_err = tf_err = ""
        try:
            # --- N1 : crawler httpx gratuit en PREMIÈRE intention ---
            self.set_agent(aid, status="RUNNING")
            self.agent_log(aid, "N1: crawler httpx (gratuit, économie TinyFish)")
            try:
                urls = await self._crawl_discover(seed, max_urls)
            except Exception as e:
                crawl_err = f"{type(e).__name__}: {str(e)[:80]}"
                self.agent_log(aid, f"N1 crawler échec: {crawl_err}")
            # --- N3 : TinyFish uniquement si le crawler ne trouve rien ---
            if not urls and key and self.settings.get("allow_tinyfish_agent", True):
                used_engine = "TinyFish"
                self.set_agent(aid, engine="TinyFish N3")
                self.agent_log(aid, "N1 vide → TinyFish (N3, dernier recours payant)")
                self.log(f"[{seed['name']}] crawler N1 vide → mission TinyFish (JS/pagination complexe présumée)")
                try:
                    sem = self._tf_sem or asyncio.Semaphore(1)
                    async with sem:
                        urls = await self._tinyfish_discover(aid, seed, key, max_urls, known_urls)
                except Exception as e:
                    tf_err = str(e)[:120]
                    self.agent_log(aid, f"TinyFish failed: {tf_err}")
                    self.log(f"TinyFish discovery failed on {seed['name']}: {tf_err}", "error")
            urls = urls[:max_urls]
            engine_code = "N3" if used_engine == "TinyFish" else "N1"
            await self._emit(
                "discover_urls", seed=seed.get("name"), n=len(urls),
                engine=engine_code, depth=depth,
            )
            if depth == 0 and (urls or known_urls):
                new_count = len([u for u in urls if u not in set(known_urls)])
                await self.db.discovery_state.update_one(
                    {"seed_url": seed["url"]},
                    {"$set": {"seed_url": seed["url"], "name": seed["name"], "last_scan": now_iso(),
                              "urls_found": len(urls), "new_urls": new_count},
                     "$setOnInsert": {"_id": str(uuid.uuid4())}},
                    upsert=True,
                )
            if urls:
                self.set_agent(aid, status="SUCCESS")
                self.agent_log(aid, f"{len(urls)} project URLs discovered ({used_engine})")
                self.log(f"[{seed['name']}] {len(urls)} project pages found via {used_engine} → DeepLinkCache + queue")
                for u in urls:
                    await self.db.deeplink_pages.update_one(
                        {"url": u}, {"$set": {"url": u, "funder": seed["name"], "source": seed["url"], "ts": now_iso()},
                                     "$setOnInsert": {"_id": str(uuid.uuid4())}}, upsert=True)
                    self.queued_count += 1
                    await self.queue.put({"url": u, "funder": seed["name"], "source": seed["url"], "depth": depth})
                await self.telemetry(seed["url"], used_engine, "SUCCESS", (time.time() - t0) * 1000, len(urls))
            else:
                self.set_agent(aid, status="FAILED")
                self.log(f"[{seed['name']}] discovery returned 0 URLs", "warn")
                detail = f"crawler: {crawl_err or '0 urls'}; tinyfish: {tf_err or 'not attempted'}"
                await self.telemetry(seed["url"], used_engine, "FAILED", (time.time() - t0) * 1000, 0, detail)
                await self.add_failed(seed["url"], seed["url"], seed["name"], detail, "discover")
        except asyncio.CancelledError:
            self.set_agent(aid, status="CANCELLED")
            raise
        except Exception as e:
            self.set_agent(aid, status="FAILED")
            await self.telemetry(seed["url"], used_engine, "FAILED", (time.time() - t0) * 1000, 0, str(e))
            await self.add_failed(seed["url"], seed["url"], seed["name"], str(e), "discover")

    async def _tinyfish_discover(self, aid, seed, key, max_urls, known_urls=None):
        """SSE streaming first (real-time agent events), polling fallback."""
        self.set_agent(aid, status="RUNNING")
        goal = discovery_goal(seed["name"], known_urls)

        async def on_event(ev):
            et = ev.get("type")
            if et == "STARTED":
                self.agent_log(aid, f"SSE stream open — run {str(ev.get('run_id'))[:8]}…")
            elif et == "STREAMING_URL" and ev.get("streaming_url"):
                self.set_agent(aid, live_url=ev["streaming_url"])
            elif et == "PROGRESS" and ev.get("purpose"):
                self.agent_log(aid, str(ev["purpose"])[:110])

        try:
            result = await tf_run_sse(seed["url"], goal, DISCOVERY_SCHEMA, key, on_event=on_event)
        except (httpx.HTTPError, TimeoutError) as e:
            self.agent_log(aid, f"SSE dropped ({str(e)[:60]}) → polling fallback")
            result = await self._tinyfish_discover_poll(aid, seed, key, goal)
        projects = (result or {}).get("projects") or []
        self.agent_log(aid, f"agent finished: {len(projects)} candidates")
        urls, seen = [], set()
        for p in projects:
            u = (p.get("url") or "").strip()
            if u.startswith("http") and u not in seen:
                seen.add(u)
                urls.append(u)
        return urls[:max_urls]

    async def _tinyfish_discover_poll(self, aid, seed, key, goal=None):
        body = await tf_run_async(seed["url"], goal or discovery_goal(seed["name"]), DISCOVERY_SCHEMA, key)
        run_id = body.get("run_id")
        if not run_id:
            raise ValueError(body.get("error", "no run_id"))
        live = find_live_url(body)
        if live:
            self.set_agent(aid, live_url=live)
        self.agent_log(aid, f"run_id {run_id[:12]}… agent navigating")
        for i in range(120):
            await asyncio.sleep(3)
            run = await tf_get_run(run_id, key)
            st = run.get("status", "")
            if not self.agents.get(aid) or self.agents[aid]["status"] == "CANCELLED":
                return {}
            live2 = find_live_url(run)
            if live2:
                self.set_agent(aid, live_url=live2)
            if st in ("COMPLETED", "FAILED", "CANCELLED"):
                if st != "COMPLETED":
                    raise ValueError(f"run {st}: {str(run.get('error'))[:100]}")
                return run.get("result") or {}
            if i % 5 == 0:
                self.agent_log(aid, f"status {st or 'PENDING'} — navigating pagination/forms")
        raise TimeoutError("TinyFish run timed out (360s)")

    async def _crawl_discover(self, seed, max_urls):
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=UA) as client:
            r = await client.get(seed["url"])
            soup = BeautifulSoup(r.text, "html.parser")
        base_host = urlparse(seed["url"]).netloc
        urls, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = urljoin(seed["url"], a["href"]).split("#")[0].split("?")[0]
            if urlparse(href).netloc != base_host or href.rstrip("/") == seed["url"].rstrip("/"):
                continue
            path = urlparse(href).path
            if any(p in path for p in URL_PATTERNS) and len(path.strip("/").split("/")) >= 2:
                if href not in seen:
                    seen.add(href)
                    urls.append(href)
            if len(urls) >= max_urls * 2:
                break
        if not urls:
            for a in soup.find_all("a", href=True):
                href = urljoin(seed["url"], a["href"]).split("#")[0].split("?")[0]
                if urlparse(href).netloc != base_host or href.rstrip("/") == seed["url"].rstrip("/"):
                    continue
                path = urlparse(href).path.strip("/")
                if not path or any(b in path.lower() for b in CRAWL_BLACKLIST):
                    continue
                if href not in seen:
                    seen.add(href)
                    urls.append(href)
                if len(urls) >= min(8, max_urls):
                    break
        return urls[:max_urls]

    # ---------- extraction ----------
    async def _extract_worker(self, idx):
        while True:
            item = await self.queue.get()
            self.queued_count = max(0, self.queued_count - 1)
            try:
                await self._process_url(item)
            except asyncio.CancelledError:
                self.queue.task_done()
                raise
            except Exception as e:
                self.log(f"Extractor error on {item['url'][:60]}: {str(e)[:100]}", "error")
            finally:
                try:
                    self.queue.task_done()
                except ValueError:
                    pass

    def _queue_partner(self, name: str, purl: str):
        if not self.running or not self.settings.get("follow_the_money", True):
            return
        domain = domain_of(purl)
        if not domain:
            return
        if domain in self.partner_domains:
            return
        seeds = self.master_seeds or MASTER_SEEDS
        known_seed = next((s for s in seeds if is_known_funder([s], name, purl)), None)
        known = known_seed is not None
        cap = int(self.settings.get("max_partner_orgs", 5))
        if not known:
            if self.new_partner_count >= cap:
                return
            self.new_partner_count += 1
            self.master_seeds.append({
                "name": name, "url": purl,
                "listing_kind": "homepage", "source": "follow_the_money",
                "project_count": 0,
            })
            try:
                asyncio.create_task(self.db.master_seeds.update_one(
                    {"domain": domain},
                    {"$set": {
                        "name": name, "url": purl, "domain": domain,
                        "source": "follow_the_money",
                        "ts": now_iso(),
                    },
                     "$setOnInsert": {"_id": str(uuid.uuid4())}},
                    upsert=True))
            except Exception:
                pass
            kind = f"new org ({self.new_partner_count}/{cap})"
        else:
            kind = "known v1 — queued (cap does not apply)"
        self.partner_domains.add(domain)
        self.partner_count = len(self.partner_domains)
        self.log(f"Follow the Money: {kind} '{name}' ({domain}) → recursive discovery", "success")
        label = known_seed["name"] if known_seed else f"{name} (partner)"
        seed = {"name": label, "url": purl}
        self.recursive_tasks.append(asyncio.create_task(self._discover(seed, 6, depth=1)))

    def _follow_the_money(self, proj: dict, depth: int):
        if depth != 0:
            return
        seeds = self.master_seeds or MASTER_SEEDS
        for p in (proj.get("partners") or []):
            if not isinstance(p, dict) or not p.get("name"):
                continue
            purl = (p.get("url") or "").strip() or listing_url_for_name(seeds, p["name"]) or ""
            if purl:
                self._queue_partner(p["name"], purl)

    async def _process_url(self, item):
        if not self.run_id:
            raise RuntimeError("isolated run required — no write to projects")
        url, funder, source = item["url"], item["funder"], item["source"]
        depth = item.get("depth", 0)
        force = bool(item.get("force") or getattr(self, "force_rescan", False))

        existing_run = await self.db.project_run_projects.find_one(
            {"run_id": self.run_id, "url": url})
        if existing_run and not force:
            return existing_run

        if not force:
            v1 = await self.db.projects.find_one({"url": url})
            if v1:
                # Skip crawl (crédits) mais trace dans le run — ne compte pas pour l'Auto-Stop
                await self._write_verdict(
                    item, "seen_v1",
                    title=v1.get("title") or url,
                    lat=v1.get("lat"), lon=v1.get("lon"),
                    location=v1.get("location"),
                    geo_source="v1",
                    v1_id=v1.get("_id"),
                )
                return {"status": "seen_v1", "url": url}

        aid = self.new_agent("Cascade N1→N2", "extract", url, source)
        t0 = time.time()
        await self._emit("extract_start", url=url, funder=funder, source=source)
        try:
            self.set_agent(aid, status="RUNNING")
            self.agent_log(aid, "Cascade hybride: N1 trafilatura/PyMuPDF → N2 Readability")
            page = await extract_cascade(url, min_chars=200,
                                         log=lambda m: self.agent_log(aid, m))
            if not page["text"]:
                raise ValueError(f"cascade N1/N2 sans texte exploitable ({page['level']})")
            page_title = (page["title"] or "").strip() or url
            text = page["text"]
            meta_desc = page["meta_desc"]
            image = page["image"]
            ext_links = page["ext_links"]
            self.agent_log(aid, f"texte extrait via {page['level']} ({len(text)} chars)")

            self.agent_log(aid, "Gatekeeper Protocol (ML local → LLM cascade)")
            gk = await gatekeeper_check(page_title, text, self.settings)
            await self._emit("gatekeeper", url=url, accepted=gk["accepted"],
                             reason=str(gk.get("reason") or "")[:200])
            if not gk["accepted"]:
                self.set_agent(aid, status="REJECTED")
                self.agent_log(aid, f"REJECTED: {gk['reason'][:80]}")
                await self._write_verdict(item, "rejected", title=page_title,
                                          reason=gk["reason"], engine=gk.get("engine"))
                await self._emit("rejected", url=url, reason=gk["reason"],
                                 engine=gk.get("engine"))
                await self.telemetry(url, gk["engine"], "REJECTED", (time.time() - t0) * 1000, 0, gk["reason"])
                await self.add_failed(url, source, funder, gk["reason"], "gatekeeper")
                self._bump_saturation(False)
                return {"status": "rejected", "url": url}

            # RAG local : sur les pages longues, seuls les chunks pertinents partent au LLM
            llm_text = text
            if len(text) > 6000:
                llm_text = select_context(f"marine ocean coastal conservation project {page_title}",
                                          text, max_chars=5000)
                self.agent_log(aid, f"RAG: {len(text)} → {len(llm_text)} chars (chunks pertinents)")

            self.agent_log(aid, f"Extraction + S_ocean scoring ({'LLM cascade' if has_llm(self.settings) else 'heuristic'})")
            proj = await extract_project(page_title, llm_text, meta_desc, url, funder, self.settings, ext_links=ext_links)

            lat, lon = proj.get("latitude"), proj.get("longitude")
            geo_src = "extracted"
            if not valid_coords(lat, lon):
                lat = lon = None
            elif not site_publishable(lat, lon, self.settings)[0]:
                # Siège / ville intérieure extraits : tenter le toponyme avant unlocated.
                lat = lon = None
            if lat is None:
                geo = await geocode_project_site(
                    proj.get("location") or "",
                    proj.get("title") or "",
                    self.settings,
                    log=lambda m: self.agent_log(aid, m),
                )
                if geo.get("lat") is not None:
                    lat, lon = geo["lat"], geo["lon"]
                    geo_src = geo.get("source") or geo.get("geo_source") or "geocoded:location"
                await self._emit(
                    "geocode", url=url,
                    source=geo_src if lat is not None else (geo.get("source") or "none"),
                    kind=geo.get("geo_kind") or "havre",
                    lat=lat, lon=lon,
                )
            else:
                await self._emit(
                    "geocode", url=url, source=geo_src, kind="extracted",
                    lat=lat, lon=lon,
                )

            ok, kind = site_publishable(lat, lon, self.settings)
            if not ok:
                self.set_agent(aid, status="FAILED")
                self.agent_log(aid, f"UNLOCATED ({kind}): no boat-accessible site — not published")
                self._follow_the_money(proj, depth)
                await self._write_verdict(
                    item, "unlocated", title=proj.get("title") or page_title,
                    location=proj.get("location"), lat=lat, lon=lon,
                    geo_source=geo_src, geo_kind=kind, engine=proj.get("engine"),
                    reason=f"unlocated:{kind}")
                await self._emit("unlocated", url=url, reason=f"unlocated:{kind}",
                                 kind=kind, lat=lat, lon=lon)
                await self.telemetry(url, proj["engine"], "UNLOCATED", (time.time() - t0) * 1000, 0, kind)
                await self.add_failed(url, source, funder, f"unlocated:{kind}", "unlocated")
                self._bump_saturation(False)
                return {"status": "unlocated", "url": url, "kind": kind}
            snapped = False
            self.agent_log(aid, f"site publishable ({kind})")

            merged = await self._dedup_merge(proj, url, funder, lat, lon)
            if merged:
                self.set_agent(aid, status="SUCCESS")
                self.agent_log(aid, f"Merged ({merged}) — dedup_core: <500m / similarity")
                await self.telemetry(url, proj["engine"], "MERGED", (time.time() - t0) * 1000, 1)
                self._bump_saturation(False)
                return {"status": merged, "url": url}

            category = proj.get("category")
            await self._write_verdict(
                item, "site",
                title=proj["title"],
                description=proj.get("description"),
                location=proj.get("location"),
                lat=float(lat), lon=float(lon),
                s_ocean=proj.get("s_ocean", 0.5),
                snapped=snapped,
                geo_source=geo_src,
                geo_kind=kind,
                category=category,
                category_group=normalize_category(category),
                image=image,
                engine=proj["engine"],
                extract_level=page["level"],
            )
            self._bump_saturation(True)
            self.set_agent(aid, status="SUCCESS")
            self.agent_log(aid, f"Site recorded in run — S_ocean {proj.get('s_ocean')}")
            self.log(f"+ {proj['title'][:60]} ({funder}) → run {self.run_id}", "success")
            await self.telemetry(url, proj["engine"], "SUCCESS", (time.time() - t0) * 1000, 1)
            self._follow_the_money(proj, depth)
            return {"status": "site", "url": url}
        except asyncio.CancelledError:
            self.set_agent(aid, status="CANCELLED")
            raise
        except Exception as e:
            self.set_agent(aid, status="FAILED")
            self.agent_log(aid, f"FAILED: {str(e)[:80]}")
            try:
                await self._write_verdict(item, "failed", title=url, reason=str(e)[:300])
            except Exception:
                pass
            await self.telemetry(url, "Cascade N1→N2", "FAILED", (time.time() - t0) * 1000, 0, str(e))
            await self.add_failed(url, source, funder, str(e), "extract")
            self._bump_saturation(False)
            return {"status": "failed", "url": url}

    async def _dedup_merge(self, proj, url, funder, lat, lon):
        """Dédup dans le run, puis lecture seule de v1. N'écrit jamais `projects`."""
        from app.services.project_runs import write_run_project
        candidate = {"title": proj["title"], "lat": lat, "lon": lon}
        run_docs = await self.db.project_run_projects.find(
            {"run_id": self.run_id, "verdict": "site"},
            {"title": 1, "lat": 1, "lon": 1, "funders": 1, "url": 1,
             "funder": 1, "location": 1, "description": 1},
        ).to_list(20000)
        for c in run_docs:
            if c.get("url") == url:
                return "merged_run"
            if is_duplicate(candidate, c):
                funders = list(set((c.get("funders") or []) + [funder]))
                await write_run_project(self.db, self.run_id, {
                    "url": c["url"],
                    "title": c.get("title"),
                    "funder": c.get("funder"),
                    "funders": funders,
                    "lat": c.get("lat"),
                    "lon": c.get("lon"),
                    "location": c.get("location"),
                    "description": c.get("description"),
                    "verdict": "site",
                })
                await self._write_verdict(
                    {"url": url, "funder": funder}, "merged_run",
                    title=proj["title"], lat=lat, lon=lon,
                    location=proj.get("location"),
                    merged_into_url=c.get("url"),
                )
                await self._emit("dedup", url=url, into=c.get("url"), how="merged_run")
                return "merged_run"

        # From scratch : on ré-extrait dans le run, même si la fiche existe en v1.
        if getattr(self, "force_rescan", False):
            return None
        v1_docs = await self.db.projects.find(
            {}, {"title": 1, "lat": 1, "lon": 1, "url": 1},
        ).to_list(30000)
        for c in v1_docs:
            if c.get("url") == url:
                await self._write_verdict(
                    {"url": url, "funder": funder}, "seen_v1",
                    title=proj["title"], lat=lat, lon=lon,
                    location=proj.get("location"), v1_id=c.get("_id"),
                )
                return "seen_v1"
            if is_duplicate(candidate, c):
                await self._write_verdict(
                    {"url": url, "funder": funder}, "merged_v1",
                    title=proj["title"], lat=lat, lon=lon,
                    location=proj.get("location"),
                    v1_url=c.get("url"), v1_id=c.get("_id"),
                )
                await self._emit("dedup", url=url, into=c.get("url"), how="merged_v1")
                return "merged_v1"
        return None
