import asyncio
import difflib
import os
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document as ReadabilityDoc

from ai import extract_project, gatekeeper_check, gemini_geocode, has_llm
from geo import geocode, haversine_km, is_ocean, ocean_fallback_coords, snap_to_ocean
from seeds import CRAWL_BLACKLIST, MASTER_SEEDS, TEST_SEED_COUNT, URL_PATTERNS
from tinyfish_client import (DISCOVERY_SCHEMA, discovery_goal, find_live_url,
                             tf_get_run, tf_run_async, tf_run_sse)

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
            "ts": now_iso(),
        })

    async def add_failed(self, url, source, funder, reason, stage):
        await self.db.failed.update_one(
            {"url": url},
            {"$set": {"url": url, "source": source, "funder": funder,
                      "reason": str(reason)[:300], "stage": stage, "ts": now_iso()},
             "$setOnInsert": {"_id": str(uuid.uuid4())}},
            upsert=True,
        )

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
        }

    def _tf_key(self):
        return (self.settings.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY") or "").strip()

    # ---------- lifecycle ----------
    async def deploy(self, mode: str, clear_db: bool, settings: dict):
        if self.running:
            raise ValueError("swarm already running")
        self.settings = settings
        self.mode = mode
        if clear_db:
            await self.db.projects.delete_many({})
            self.log("Database cleared before deployment", "warn")
        self.running = True
        self.logs.clear()
        self.log(f"Deploying TinyFish Swarm — mode: {mode.upper()}")
        self.log(f"TinyFish key: {'ACTIVE' if self._tf_key() else 'MISSING → fallback crawler'}",
                 "info" if self._tf_key() else "warn")
        self.log(f"Gemini pipeline: {'ACTIVE' if has_llm(settings) else 'MISSING → heuristic gatekeeper/extractor'}",
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
        try:
            seeds = MASTER_SEEDS[:TEST_SEED_COUNT] if self.mode == "test" else MASTER_SEEDS
            max_urls = int(self.settings.get("test_max_urls_per_seed", 6)) if self.mode == "test" \
                else int(self.settings.get("full_max_urls_per_seed", 20))
            self.queue = asyncio.Queue()
            self.recursive_tasks = []
            self.partner_domains = {urlparse(s["url"]).netloc.replace("www.", "") for s in MASTER_SEEDS}
            self.partner_count = 0
            concurrency = max(1, min(20, int(self.settings.get("extract_concurrency", 6))))
            self.workers = [asyncio.create_task(self._extract_worker(i)) for i in range(concurrency)]
            self.log(f"MasterSeeds loaded: {len(seeds)} portals | extraction concurrency: {concurrency}")

            if self.mode == "full":
                cached = await self.db.deeplink_pages.find({}).to_list(2000)
                if cached:
                    self.log(f"DeepLinkCache: injecting {len(cached)} cached project pages")
                    for c in cached:
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
            count = await self.db.projects.count_documents({})
            self.log(f"Pipeline complete — {count} projects mapped", "success")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log(f"Pipeline error: {e}", "error")
        finally:
            self.running = False

    # ---------- discovery ----------
    async def _discover(self, seed, max_urls, depth=0):
        key = self._tf_key()
        engine = "TinyFish" if key else "Crawler"
        aid = self.new_agent(engine, "discover", seed["url"], seed["name"])
        t0 = time.time()
        urls = []
        used_engine = engine
        tf_err = ""
        try:
            if key:
                self.agent_log(aid, f"TinyFish mission dispatched → {seed['url']}")
                try:
                    urls = await self._tinyfish_discover(aid, seed, key, max_urls)
                except Exception as e:
                    tf_err = str(e)[:120]
                    self.agent_log(aid, f"TinyFish failed: {tf_err}")
                    self.log(f"TinyFish discovery failed on {seed['name']}: {tf_err}", "error")
            if not urls:
                used_engine = "Crawler" if not key else "TinyFish+Crawler"
                self.set_agent(aid, status="RUNNING")
                self.agent_log(aid, "Fallback crawler engaged")
                urls = await self._crawl_discover(seed, max_urls)
            urls = urls[:max_urls]
            if urls:
                self.set_agent(aid, status="SUCCESS")
                self.agent_log(aid, f"{len(urls)} project URLs discovered")
                self.log(f"[{seed['name']}] {len(urls)} project pages found → DeepLinkCache + queue")
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
                detail = f"tinyfish: {tf_err}; crawler: 0 urls" if tf_err else "no urls found"
                await self.telemetry(seed["url"], used_engine, "FAILED", (time.time() - t0) * 1000, 0, detail)
                await self.add_failed(seed["url"], seed["url"], seed["name"], detail, "discover")
        except asyncio.CancelledError:
            self.set_agent(aid, status="CANCELLED")
            raise
        except Exception as e:
            self.set_agent(aid, status="FAILED")
            await self.telemetry(seed["url"], used_engine, "FAILED", (time.time() - t0) * 1000, 0, str(e))
            await self.add_failed(seed["url"], seed["url"], seed["name"], str(e), "discover")

    async def _tinyfish_discover(self, aid, seed, key, max_urls):
        """SSE streaming first (real-time agent events), polling fallback."""
        self.set_agent(aid, status="RUNNING")

        async def on_event(ev):
            et = ev.get("type")
            if et == "STARTED":
                self.agent_log(aid, f"SSE stream open — run {str(ev.get('run_id'))[:8]}…")
            elif et == "STREAMING_URL" and ev.get("streaming_url"):
                self.set_agent(aid, live_url=ev["streaming_url"])
            elif et == "PROGRESS" and ev.get("purpose"):
                self.agent_log(aid, str(ev["purpose"])[:110])

        try:
            result = await tf_run_sse(seed["url"], discovery_goal(seed["name"]), DISCOVERY_SCHEMA, key, on_event=on_event)
        except (httpx.HTTPError, TimeoutError) as e:
            self.agent_log(aid, f"SSE dropped ({str(e)[:60]}) → polling fallback")
            result = await self._tinyfish_discover_poll(aid, seed, key)
        projects = (result or {}).get("projects") or []
        self.agent_log(aid, f"agent finished: {len(projects)} candidates")
        urls, seen = [], set()
        for p in projects:
            u = (p.get("url") or "").strip()
            if u.startswith("http") and u not in seen:
                seen.add(u)
                urls.append(u)
        return urls[:max_urls]

    async def _tinyfish_discover_poll(self, aid, seed, key):
        body = await tf_run_async(seed["url"], discovery_goal(seed["name"]), DISCOVERY_SCHEMA, key)
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
        self.log(f"Follow the Money: new org '{name}' ({domain}) → recursive discovery", "success")
        seed = {"name": f"{name} (partner)", "url": purl}
        self.recursive_tasks.append(asyncio.create_task(self._discover(seed, 6, depth=1)))

    async def _process_url(self, item):
        url, funder, source = item["url"], item["funder"], item["source"]
        depth = item.get("depth", 0)
        if await self.db.projects.find_one({"url": url}):
            return
        aid = self.new_agent("Readability.js", "extract", url, source)
        t0 = time.time()
        try:
            self.set_agent(aid, status="RUNNING")
            self.agent_log(aid, "Fetching + Readability cleaning")
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=UA) as client:
                r = await client.get(url)
                html = r.text
            doc = ReadabilityDoc(html)
            page_title = (doc.short_title() or "").strip() or url
            summary_html = doc.summary()
            soup = BeautifulSoup(summary_html, "html.parser")
            text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
            full_soup = BeautifulSoup(html, "html.parser")
            if len(text) < 200:
                text = re.sub(r"\s+", " ", full_soup.get_text(" ")).strip()[:8000]
            meta = full_soup.find("meta", attrs={"name": "description"}) or \
                full_soup.find("meta", attrs={"property": "og:description"})
            meta_desc = meta.get("content", "").strip() if meta else ""
            og_img = full_soup.find("meta", attrs={"property": "og:image"})
            image = pick_image(full_soup, soup, url)
            base_host = urlparse(url).netloc
            ext_links, seen_d = [], set()
            for a in full_soup.find_all("a", href=True):
                href = urljoin(url, a["href"]).split("#")[0]
                d = urlparse(href).netloc
                name = re.sub(r"\s+", " ", a.get_text(" ")).strip()
                if href.startswith("http") and d and d != base_host and d not in seen_d and 3 < len(name) < 80:
                    seen_d.add(d)
                    ext_links.append({"name": name, "url": href})
                if len(ext_links) >= 15:
                    break

            self.agent_log(aid, "Gatekeeper Protocol (marine filter)")
            gk = await gatekeeper_check(page_title, text, self.settings)
            if not gk["accepted"]:
                self.set_agent(aid, status="REJECTED")
                self.agent_log(aid, f"REJECTED: {gk['reason'][:80]}")
                await self.telemetry(url, gk["engine"], "REJECTED", (time.time() - t0) * 1000, 0, gk["reason"])
                await self.add_failed(url, source, funder, gk["reason"], "gatekeeper")
                return

            self.agent_log(aid, f"Extraction + S_ocean scoring ({'Gemini' if has_llm(self.settings) else 'heuristic'})")
            proj = await extract_project(page_title, text, meta_desc, url, funder, self.settings, ext_links=ext_links)

            lat, lon = proj.get("latitude"), proj.get("longitude")
            geo_src = "extracted"
            if not self._valid_coords(lat, lon):
                lat = lon = None
                if proj.get("location"):
                    g = await geocode(proj["location"])
                    if g:
                        lat, lon = g
                        geo_src = "geocoded:location"
                if lat is None:
                    g = await gemini_geocode(proj.get("location") or "", proj["title"], self.settings)
                    if g:
                        lat, lon = g
                        geo_src = "gemini-geocoded"
                        self.agent_log(aid, "Smart geocoding: Gemini estimated site coordinates")
                if lat is None:
                    g = await geocode(proj["title"])
                    if g:
                        lat, lon = g
                        geo_src = "geocoded:title"
                if lat is None:
                    lat, lon = ocean_fallback_coords(proj["title"])
                    geo_src = "ocean-region-fallback"

            snapped = False
            if not is_ocean(lat, lon):
                max_km = float(self.settings.get("max_coast_km", 50))
                nlat, nlon, snapped = snap_to_ocean(lat, lon, max_km=max(500.0, max_km * 4))
                if snapped:
                    self.agent_log(aid, f"Point-in-Ocean failed → snapped to coast ({haversine_km(lat, lon, nlat, nlon):.0f} km)")
                    lat, lon = nlat, nlon

            merged = await self._dedup_merge(proj, url, funder, lat, lon)
            if merged:
                self.set_agent(aid, status="SUCCESS")
                self.agent_log(aid, "Merged with existing project (dedup <500m / similarity)")
                await self.telemetry(url, proj["engine"], "MERGED", (time.time() - t0) * 1000, 1)
                return

            await self.db.projects.insert_one({
                "_id": str(uuid.uuid4()), "title": proj["title"], "url": url,
                "description": proj["description"], "funder": funder, "funders": [funder],
                "location": proj.get("location"), "lat": float(lat), "lon": float(lon),
                "s_ocean": proj.get("s_ocean", 0.5), "snapped": snapped, "geo_source": geo_src,
                "image": image, "engine": proj["engine"], "created_at": now_iso(),
            })
            self.set_agent(aid, status="SUCCESS")
            self.agent_log(aid, f"Project mapped — S_ocean {proj.get('s_ocean')}")
            self.log(f"+ {proj['title'][:60]} ({funder})", "success")
            await self.telemetry(url, proj["engine"], "SUCCESS", (time.time() - t0) * 1000, 1)
            if depth == 0:
                for p in (proj.get("partners") or []):
                    if p.get("url"):
                        self._queue_partner(p["name"], p["url"])
        except asyncio.CancelledError:
            self.set_agent(aid, status="CANCELLED")
            raise
        except Exception as e:
            self.set_agent(aid, status="FAILED")
            self.agent_log(aid, f"FAILED: {str(e)[:80]}")
            await self.telemetry(url, "Readability.js", "FAILED", (time.time() - t0) * 1000, 0, str(e))
            await self.add_failed(url, source, funder, str(e), "extract")

    @staticmethod
    def _valid_coords(lat, lon):
        try:
            return lat is not None and lon is not None and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180 \
                and not (float(lat) == 0 and float(lon) == 0)
        except (TypeError, ValueError):
            return False

    async def _dedup_merge(self, proj, url, funder, lat, lon):
        candidates = await self.db.projects.find({}, {"title": 1, "lat": 1, "lon": 1, "funders": 1, "url": 1}).to_list(3000)
        for c in candidates:
            if c.get("url") == url:
                return True
            dist = haversine_km(lat, lon, c["lat"], c["lon"])
            sim = difflib.SequenceMatcher(None, proj["title"].lower(), c["title"].lower()).ratio()
            if (dist < 0.5 and sim > 0.6) or sim > 0.9:
                funders = list(set((c.get("funders") or []) + [funder]))
                await self.db.projects.update_one({"_id": c["_id"]}, {"$set": {"funders": funders}})
                return True
        return False
