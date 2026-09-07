import asyncio
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
from app.core.dedup import is_duplicate, merge_docs
from app.core.extract import extract_cascade
from app.core.project_geocode import resolve_sites
from app.core.rag import select_context
from app.static_data.seeds import (CRAWL_BLACKLIST, TEST_SEED_COUNT, URL_PATTERNS,
                                   load_master_seeds)
from app.core.tinyfish import (DISCOVERY_SCHEMA, PROJECT_PURPOSE, discovery_goal,
                             find_live_url, tf_fetch, tf_get_run, tf_run_async,
                             tf_run_sse, tf_search)

MASTER_SEEDS = load_master_seeds()

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
        self.logs = deque(maxlen=300)
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
        self.no_new_streak = 0
        self.saturated = False
        self.run_id = None
        self.recorder = None
        self.force_rescan = False
        self.wrote_projects = False

    # ---------- state helpers ----------
    def log(self, msg, level="info"):
        self.logs.append({"ts": now_iso(), "msg": msg, "level": level})

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

    async def _runtime_seeds(self) -> list[dict]:
        """Fichier ~861 + partenaires Follow the Money déjà vus (Mongo)."""
        base = list(MASTER_SEEDS) if MASTER_SEEDS else load_master_seeds()
        seen = {(s.get("name") or "").lower() for s in base}
        try:
            extra = await self.db.master_seeds.find({}).to_list(2000)
        except Exception:
            extra = []
        for s in extra:
            key = (s.get("name") or "").lower()
            if key and key not in seen and s.get("url"):
                seen.add(key)
                base.append(s)
        return base

    @staticmethod
    def _seed_key(seed: dict) -> str:
        return (seed.get("url") or "").strip() or f"name:{(seed.get('name') or '').strip()}"

    async def _persist_partner_seed(self, name: str, url: str):
        if not name or not (url or "").startswith("http"):
            return
        try:
            await self.db.master_seeds.update_one(
                {"name": name},
                {"$set": {"name": name, "url": url, "priority": 2,
                          "listing_kind": "follow_the_money", "updated_at": now_iso()},
                 "$setOnInsert": {"_id": str(uuid.uuid4())}},
                upsert=True,
            )
        except Exception:
            pass

    async def _emit(self, step: str, **payload):
        rec = self.recorder
        if rec is not None:
            try:
                await rec.event(step, **payload)
            except Exception:
                pass

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
            "logs": list(self.logs)[-100:],
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
        try:
            all_seeds = await self._runtime_seeds()
            seeds = all_seeds[:TEST_SEED_COUNT] if self.mode == "test" else all_seeds
            max_urls = int(self.settings.get("test_max_urls_per_seed", 6)) if self.mode == "test" \
                else int(self.settings.get("full_max_urls_per_seed", 20))
            self.queue = asyncio.Queue()
            self.recursive_tasks = []
            self.partner_domains = {
                urlparse(s["url"]).netloc.replace("www.", "")
                for s in all_seeds if s.get("url")
            }
            self.partner_count = 0
            concurrency = max(1, min(20, int(self.settings.get("extract_concurrency", 6))))
            self.workers = [asyncio.create_task(self._extract_worker(i)) for i in range(concurrency)]
            self.log(f"MasterSeeds loaded: {len(seeds)} portals | extraction concurrency: {concurrency}")

            if self.mode == "full":
                cached = await self.db.deeplink_pages.find({}).to_list(5000)
                if cached:
                    existing = {p["url"] for p in await self.db.projects.find({}, {"url": 1}).to_list(30000)}
                    fresh = [c for c in cached if c["url"] not in existing]
                    self.log(f"DeepLinkCache: {len(cached)} pages cached, {len(fresh)} not yet extracted → queued")
                    for c in fresh:
                        self.queued_count += 1
                        await self.queue.put({"url": c["url"], "funder": c.get("funder", ""), "source": c.get("source", "cache")})

            tf_agents = max(1, min(2, int(self.settings.get("tinyfish_agents", 2))))
            sem = asyncio.Semaphore(tf_agents)

            async def guarded(seed):
                async with sem:
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
            self.running = False

    # ---------- discovery (cascade : N1 crawler gratuit → N3 TinyFish dernier recours) ----------
    async def _discover(self, seed, max_urls, depth=0):
        # Incremental discovery: skip seeds scanned recently (TTL), unless force_rescan
        seed_key = self._seed_key(seed)
        known_urls = []
        if depth == 0:
            state = await self.db.discovery_state.find_one({"seed_url": seed_key})
            rescan_days = float(self.settings.get("rescan_after_days", 7))
            if state and state.get("last_scan") and not getattr(self, "force_rescan", False):
                try:
                    last = datetime.fromisoformat(state["last_scan"])
                    age_days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
                    if age_days < rescan_days:
                        self.log(f"[{seed['name']}] discovery skipped — scanned {age_days:.1f}d ago (TTL {rescan_days:g}d, cache reused)")
                        return
                except ValueError:
                    pass
            cached = await self.db.deeplink_pages.find({"source": seed_key}, {"url": 1}).to_list(300)
            known_urls = [c["url"] for c in cached]
            if known_urls:
                self.log(f"[{seed['name']}] delta scan — {len(known_urls)} known URLs excluded from mission")
        key = self._tf_key()
        aid = self.new_agent("Crawler N1", "discover", seed.get("url") or seed["name"], seed["name"])
        t0 = time.time()
        urls = []
        used_engine = "none"
        notes = []
        try:
            self.set_agent(aid, status="RUNNING")
            if seed.get("url"):
                self.agent_log(aid, "N1: crawler httpx (gratuit)")
                try:
                    urls = await self._crawl_discover(seed, max_urls)
                    if urls:
                        used_engine = "Crawler"
                except Exception as e:
                    notes.append(f"crawler: {type(e).__name__}: {str(e)[:80]}")
                    self.agent_log(aid, f"N1 crawler échec: {notes[-1]}")
            if not urls and key:
                self.set_agent(aid, engine="TinyFish Search")
                self.agent_log(aid, "N2: TinyFish Search (quota, pas Agent)")
                try:
                    urls = await self._tinyfish_search_discover(seed, key, max_urls, known_urls)
                    if urls:
                        used_engine = "TinyFish Search"
                except Exception as e:
                    notes.append(f"search: {str(e)[:80]}")
                    self.agent_log(aid, f"Search échec: {notes[-1]}")
            if not urls and key and seed.get("url"):
                self.set_agent(aid, engine="TinyFish Fetch")
                self.agent_log(aid, "N2b: TinyFish Fetch listing (quota)")
                try:
                    urls = await self._tinyfish_fetch_discover(seed, key, max_urls)
                    if urls:
                        used_engine = "TinyFish Fetch"
                except Exception as e:
                    notes.append(f"fetch: {str(e)[:80]}")
                    self.agent_log(aid, f"Fetch échec: {notes[-1]}")
            if not urls and key and seed.get("url") and self.settings.get("allow_tinyfish_agent", True):
                self.set_agent(aid, engine="TinyFish N3")
                self.agent_log(aid, "N3: TinyFish Agent (dernier recours)")
                self.log(f"[{seed['name']}] Search/Fetch/crawler vides → Agent")
                try:
                    urls = await self._tinyfish_discover(aid, seed, key, max_urls, known_urls)
                    if urls:
                        used_engine = "TinyFish Agent"
                except Exception as e:
                    notes.append(f"agent: {str(e)[:80]}")
                    self.agent_log(aid, f"TinyFish Agent failed: {notes[-1]}")
                    self.log(f"TinyFish Agent failed on {seed['name']}: {notes[-1]}", "error")
            urls = urls[:max_urls]
            if depth == 0 and (urls or known_urls):
                new_count = len([u for u in urls if u not in set(known_urls)])
                await self.db.discovery_state.update_one(
                    {"seed_url": seed_key},
                    {"$set": {"seed_url": seed_key, "name": seed["name"], "last_scan": now_iso(),
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
                        {"url": u}, {"$set": {"url": u, "funder": seed["name"], "source": seed_key, "ts": now_iso()},
                                     "$setOnInsert": {"_id": str(uuid.uuid4())}}, upsert=True)
                    self.queued_count += 1
                    await self.queue.put({"url": u, "funder": seed["name"], "source": seed_key, "depth": depth})
                await self.telemetry(seed_key, used_engine, "SUCCESS", (time.time() - t0) * 1000, len(urls))
            else:
                self.set_agent(aid, status="FAILED")
                self.log(f"[{seed['name']}] discovery returned 0 URLs", "warn")
                detail = "; ".join(notes) or "0 urls (crawler/search/fetch/agent)"
                await self.telemetry(seed_key, used_engine, "FAILED", (time.time() - t0) * 1000, 0, detail)
                await self.add_failed(seed_key, seed_key, seed["name"], detail, "discover")
        except asyncio.CancelledError:
            self.set_agent(aid, status="CANCELLED")
            raise
        except Exception as e:
            self.set_agent(aid, status="FAILED")
            await self.telemetry(seed_key, used_engine, "FAILED", (time.time() - t0) * 1000, 0, str(e))
            await self.add_failed(seed_key, seed_key, seed["name"], str(e), "discover")

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

    async def _tinyfish_search_discover(self, seed, key, max_urls, known_urls=None):
        """Search API, scoped au domaine du listing si connu."""
        known = set(known_urls or [])
        domain = ""
        if seed.get("url"):
            domain = urlparse(seed["url"]).netloc.replace("www.", "")
        query = f'"{seed["name"]}" marine project OR conservation OR "hope spot"'
        hits = await tf_search(
            query, key,
            include_domains=[domain] if domain else None,
            purpose=PROJECT_PURPOSE,
            log=lambda m: self.log(m),
        )
        urls, seen = [], set()
        for h in hits:
            u = (h.get("url") or "").strip().split("#")[0]
            if not u.startswith("http") or u in known or u in seen:
                continue
            path = urlparse(u).path
            if domain and any(p in path for p in URL_PATTERNS):
                seen.add(u)
                urls.append(u)
            elif not domain:
                seen.add(u)
                urls.append(u)
            if len(urls) >= max_urls:
                break
        if not urls:
            for h in hits:
                u = (h.get("url") or "").strip().split("#")[0]
                if u.startswith("http") and u not in known and u not in seen:
                    seen.add(u)
                    urls.append(u)
                if len(urls) >= max_urls:
                    break
        return urls[:max_urls]

    async def _tinyfish_fetch_discover(self, seed, key, max_urls):
        """Fetch du listing : extraire les liens projet (même host)."""
        url = seed.get("url")
        if not (url or "").startswith("http"):
            return []
        recs = await tf_fetch([url], key, links=True, purpose=PROJECT_PURPOSE,
                              log=lambda m: self.log(m))
        rec = recs.get(url) or {}
        if rec.get("blocked"):
            return []
        base_host = urlparse(url).netloc
        urls, seen = [], set()
        for link in rec.get("links") or []:
            href = link if isinstance(link, str) else (link.get("url") or link.get("href") or "")
            href = urljoin(url, href).split("#")[0].split("?")[0]
            if not href.startswith("http") or href in seen:
                continue
            if urlparse(href).netloc != base_host:
                continue
            path = urlparse(href).path
            if any(p in path for p in URL_PATTERNS) and len(path.strip("/").split("/")) >= 2:
                seen.add(href)
                urls.append(href)
            if len(urls) >= max_urls:
                break
        return urls[:max_urls]

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
        try:
            domain = urlparse(purl).netloc.replace("www.", "")
        except Exception:
            return
        if not domain or domain in self.partner_domains:
            return
        if self.partner_count >= int(self.settings.get("max_partner_orgs", 5)):
            return
        self.partner_domains.add(domain)
        self.partner_count += 1
        self.log(f"Follow the Money: new org '{name}' ({domain}) → master_seeds + recursive discovery", "success")
        asyncio.create_task(self._persist_partner_seed(name, purl))
        seed = {"name": name, "url": purl, "priority": 2, "listing_kind": "follow_the_money"}
        self.recursive_tasks.append(asyncio.create_task(self._discover(seed, 6, depth=1)))

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

            self.agent_log(aid, f"Extraction sites[] + juge de lieu ({'LLM cascade' if has_llm(self.settings) else 'heuristic'})")
            proj = await extract_project(page_title, llm_text, meta_desc, url, funder, self.settings, ext_links=ext_links)
            resolved = await resolve_sites(
                proj, funder, self.settings,
                log=lambda m: self.agent_log(aid, m))
            ok_sites = resolved.get("ok") or []
            if resolved.get("verdict") != "site" or not ok_sites:
                reason = resolved.get("reason") or "unlocated"
                self.set_agent(aid, status="FAILED")
                self.agent_log(aid, f"UNLOCATED ({reason}): no visitable action site")
                await self._write_verdict(
                    item, "unlocated", title=proj.get("title") or page_title,
                    location=proj.get("location"),
                    sites=resolved.get("rejected") or [],
                    geo_source=None, geo_kind=reason, engine=proj.get("engine"),
                    reason=f"unlocated:{reason}")
                await self.telemetry(url, proj["engine"], "UNLOCATED", (time.time() - t0) * 1000, 0, reason)
                await self.add_failed(url, source, funder, f"unlocated:{reason}", "unlocated")
                self._bump_saturation(False)
                return {"status": "unlocated", "url": url, "kind": reason}

            first = ok_sites[0]
            lat, lon = first.get("lat"), first.get("lon")
            geo_src = first.get("geo_source") or "extracted"
            kind = first.get("geo_kind") or "ocean"
            snapped = False
            self.agent_log(aid, f"{len(ok_sites)} site(s) publishable ({kind})")

            funders = list(dict.fromkeys(
                [funder] + list(proj.get("funders") or []) + [s.get("funder") for s in ok_sites if s.get("funder")]
            ))
            funders = [f for f in funders if f]

            merged = await self._dedup_merge(proj, url, funder, lat, lon, sites=ok_sites)
            if merged:
                self.set_agent(aid, status="SUCCESS")
                self.agent_log(aid, f"Merged ({merged}) — dedup_core + merge_docs")
                await self.telemetry(url, proj["engine"], "MERGED", (time.time() - t0) * 1000, 1)
                self._bump_saturation(False)
                return {"status": merged, "url": url}

            category = proj.get("category")
            await self._write_verdict(
                item, "site",
                title=proj["title"],
                description=proj.get("description"),
                location=first.get("location") or proj.get("location"),
                lat=float(lat), lon=float(lon),
                s_ocean=proj.get("s_ocean", 0.5),
                snapped=snapped,
                geo_source=geo_src,
                geo_kind=kind,
                sites=ok_sites,
                funders=funders,
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
            if depth == 0:
                for p in (proj.get("partners") or []):
                    if p.get("url"):
                        self._queue_partner(p["name"], p["url"])
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

    @staticmethod
    def _valid_coords(lat, lon):
        try:
            return lat is not None and lon is not None and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180 \
                and not (float(lat) == 0 and float(lon) == 0)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _merge_site_lists(existing, incoming):
        out = [dict(s) for s in (existing or []) if isinstance(s, dict)]
        for s in incoming or []:
            if not isinstance(s, dict):
                continue
            cand = {"title": s.get("name") or s.get("location"), "lat": s.get("lat"), "lon": s.get("lon")}
            if any(is_duplicate(cand, {"title": t.get("name") or t.get("location"),
                                       "lat": t.get("lat"), "lon": t.get("lon")})
                   for t in out):
                continue
            out.append(s)
        return out

    async def _dedup_merge(self, proj, url, funder, lat, lon, sites=None):
        """Dédup dans le run, puis lecture seule de v1. Fusion `merge_docs`."""
        from app.services.project_runs import write_run_project
        candidate = {"title": proj["title"], "lat": lat, "lon": lon}
        incoming = {
            "title": proj.get("title"),
            "description": proj.get("description"),
            "location": proj.get("location"),
            "lat": lat,
            "lon": lon,
            "sites": list(sites or []),
            "category": proj.get("category"),
        }
        run_docs = await self.db.project_run_projects.find(
            {"run_id": self.run_id, "verdict": "site"},
            {"title": 1, "lat": 1, "lon": 1, "funders": 1, "url": 1,
             "funder": 1, "location": 1, "description": 1, "sites": 1,
             "category": 1},
        ).to_list(20000)
        for c in run_docs:
            if c.get("url") == url:
                return "merged_run"
            if is_duplicate(candidate, c):
                updates = merge_docs(c, incoming)
                funders = list(set((c.get("funders") or []) + [funder]
                                   + list(proj.get("funders") or [])))
                merged_sites = self._merge_site_lists(c.get("sites"), sites)
                if merged_sites:
                    updates["sites"] = merged_sites
                payload = {
                    "url": c["url"],
                    "title": updates.get("title") or c.get("title"),
                    "funder": c.get("funder"),
                    "funders": funders,
                    "lat": updates.get("lat", c.get("lat")),
                    "lon": updates.get("lon", c.get("lon")),
                    "location": updates.get("location", c.get("location")),
                    "description": updates.get("description", c.get("description")),
                    "sites": updates.get("sites", c.get("sites") or []),
                    "verdict": "site",
                }
                await write_run_project(self.db, self.run_id, payload)
                await self._write_verdict(
                    {"url": url, "funder": funder}, "merged_run",
                    title=proj["title"], lat=lat, lon=lon,
                    location=proj.get("location"),
                    sites=sites or [],
                    merged_into_url=c.get("url"),
                )
                return "merged_run"

        v1_docs = await self.db.projects.find(
            {}, {"title": 1, "lat": 1, "lon": 1, "url": 1},
        ).to_list(30000)
        for c in v1_docs:
            if c.get("url") == url:
                await self._write_verdict(
                    {"url": url, "funder": funder}, "seen_v1",
                    title=proj["title"], lat=lat, lon=lon,
                    location=proj.get("location"), v1_id=c.get("_id"),
                    sites=sites or [],
                )
                return "seen_v1"
            if is_duplicate(candidate, c):
                await self._write_verdict(
                    {"url": url, "funder": funder}, "merged_v1",
                    title=proj["title"], lat=lat, lon=lon,
                    location=proj.get("location"),
                    v1_url=c.get("url"), v1_id=c.get("_id"),
                    sites=sites or [],
                )
                return "merged_v1"
        return None
