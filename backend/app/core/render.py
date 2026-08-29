"""
render_core — Rendu navigateur local (Playwright + Chromium headless).

Remplaçant gratuit et open source de TinyFish pour le besoin réel du pipeline
PoE : rendre les pages JavaScript (et passer les challenges anti-bot « soft »)
avant parsing. Aucun quota — le coût est du CPU/RAM local, l'usage peut donc
être intensif (fin du rationnement « 1 appel max par zone »).

Dégradation propre : si playwright ou son navigateur n'est pas installé,
render_html retourne None et la cascade continue sans rendu.
Installation : pip install playwright && playwright install chromium
"""
import asyncio

UA_BROWSER = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_pw = None
_browser = None
_lock = asyncio.Lock()
_sem = asyncio.Semaphore(2)  # pages rendues simultanément (RAM ~200 Mo/contexte)
_unavailable = False


async def _get_browser(log):
    """Navigateur partagé, relancé s'il a crashé. None si Playwright absent."""
    global _pw, _browser, _unavailable
    if _unavailable:
        return None
    async with _lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        try:
            from playwright.async_api import async_playwright
            if _pw is None:
                _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            return _browser
        except Exception as e:
            _unavailable = True
            log(f"render: Playwright indisponible ({type(e).__name__}: {str(e)[:80]}) — rendu désactivé")
            return None


async def render_html(url: str, timeout_s: int = 45, settle_ms: int = 2500, log=None) -> str | None:
    """HTML rendu par Chromium (DOM après exécution du JavaScript), ou None."""
    log = log or (lambda m: None)
    browser = await _get_browser(log)
    if browser is None:
        return None
    async with _sem:
        context = None
        try:
            context = await browser.new_context(
                user_agent=UA_BROWSER, viewport={"width": 1366, "height": 900},
                locale="en-US")
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                await page.wait_for_timeout(settle_ms)
            return await page.content()
        except Exception as e:
            log(f"render {url[:70]}: échec ({type(e).__name__}: {str(e)[:60]})")
            return None
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass


async def shutdown_render():
    """Fermeture propre (appelée au shutdown de l'app)."""
    global _pw, _browser
    try:
        if _browser is not None:
            await _browser.close()
        if _pw is not None:
            await _pw.stop()
    except Exception:
        pass
    _browser = None
    _pw = None
