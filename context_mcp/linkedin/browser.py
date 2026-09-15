"""Stealth browser engine for LinkedIn.

LinkedIn binds the web session to a browser fingerprint, so injecting a cookie
from another browser gets blocked as session-hijacking. Instead we keep a
persistent Patchright (stealth Chromium) profile and log in interactively once;
after that, reads run against that profile (headless by default).

The context is launched once and reused across calls (closed after an idle
window), and every navigation is paced server-side: a global lock serialises
callers, and min-interval + per-minute + per-session limits cap throughput so
even a parallel workflow cannot burst the account. Tuning via env:
LINKEDIN_MIN_INTERVAL, LINKEDIN_MAX_PER_MIN, LINKEDIN_MAX_PER_SESSION,
LINKEDIN_IDLE_TTL, LINKEDIN_HEADLESS.
"""

from __future__ import annotations

import asyncio
import collections
import os
import pathlib
import random
import re
import time
from typing import Any
from urllib.parse import quote

from patchright.async_api import async_playwright

from context_mcp.linkedin import extract

CONFIG_DIR = pathlib.Path.home() / ".config" / "context-mcp" / "linkedin"
USER_DATA_DIR = CONFIG_DIR / "profile"
BASE = "https://www.linkedin.com"

MIN_INTERVAL = float(os.getenv("LINKEDIN_MIN_INTERVAL", "2.5"))
MAX_PER_MIN = int(os.getenv("LINKEDIN_MAX_PER_MIN", "12"))
MAX_PER_SESSION = int(os.getenv("LINKEDIN_MAX_PER_SESSION", "150"))
IDLE_TTL = float(os.getenv("LINKEDIN_IDLE_TTL", "180"))
HEADLESS = os.getenv("LINKEDIN_HEADLESS", "1") != "0"

_SECTION_PATHS = {
    "experience": "details/experience/",
    "education": "details/education/",
    "skills": "details/skills/",
    "projects": "details/projects/",
    "certifications": "details/certifications/",
    "courses": "details/courses/",
    "honors": "details/honors/",
    "volunteering": "details/volunteering-experiences/",
    "languages": "details/languages/",
}

_lock = asyncio.Lock()
_pw: Any = None
_ctx: Any = None
_last_used = 0.0
_reaper: asyncio.Task | None = None
_recent: collections.deque[float] = collections.deque()
_session_calls = 0
_last_call = 0.0


def _blocked(url: str) -> bool:
    return any(s in url for s in ("/login", "/checkpoint", "/authwall", "/uas/login"))


def _status(final_url: str, text: str) -> str:
    low = final_url.lower()
    if any(s in low for s in ("/login", "/uas/login", "/authwall")):
        return "needs_login"
    if "/checkpoint" in low:
        return "checkpoint"
    if not text or len(text.strip()) < 40:
        return "empty"
    return "ok"


_NAV_LINES = {
    "skip to search", "skip to main content", "skip to primary content", "skip to aside",
    "skip to footer", "skip to sidebar", "home", "my network", "jobs", "messaging",
    "notifications", "me", "for business", "learning", "keyboard shortcuts",
    "close jump menu", "new feed updates notifications", "status is online",
    "status is reachable", "0 notifications", "0 notifications total",
    "search by title, skill, or company", "jump to active conversation details",
    "jump to active job details", "jump to active search result",
}
_FOOTER_MARKERS = ("Select language", "\nAbout\nAccessibility")


def _clean(text: str) -> str:
    if not text:
        return ""
    cut = len(text)
    for marker in _FOOTER_MARKERS:
        i = text.find(marker)
        if i != -1:
            cut = min(cut, i)
    out: list[str] = []
    for raw in text[:cut].split("\n"):
        s = raw.strip()
        if not s or s.lower() in _NAV_LINES:
            continue
        if out and out[-1] == s:
            continue
        out.append(s)
    return "\n".join(out)


async def _pace() -> None:
    global _last_call, _session_calls
    if _session_calls >= MAX_PER_SESSION:
        raise RuntimeError(
            f"LinkedIn per-session call budget ({MAX_PER_SESSION}) exhausted. "
            "Restart the MCP to reset. This guard protects the recruiting account."
        )
    now = time.monotonic()
    while _recent and now - _recent[0] > 60:
        _recent.popleft()
    if len(_recent) >= MAX_PER_MIN:
        await asyncio.sleep(max(0.0, 60 - (now - _recent[0])))
        now = time.monotonic()
        while _recent and now - _recent[0] > 60:
            _recent.popleft()
    gap = now - _last_call
    delay = MIN_INTERVAL + random.uniform(0, 1.5)
    if gap < delay:
        await asyncio.sleep(delay - gap)
    _last_call = time.monotonic()
    _recent.append(_last_call)
    _session_calls += 1


async def _reaper_loop() -> None:
    while True:
        await asyncio.sleep(30)
        async with _lock:
            if _ctx is not None and time.monotonic() - _last_used > IDLE_TTL:
                await _shutdown()


def _ensure_reaper() -> None:
    global _reaper
    if _reaper is None or _reaper.done():
        _reaper = asyncio.ensure_future(_reaper_loop())


async def _shutdown() -> None:
    global _pw, _ctx
    if _ctx is not None:
        try:
            await _ctx.close()
        except Exception:
            pass
        _ctx = None
    if _pw is not None:
        try:
            await _pw.stop()
        except Exception:
            pass
        _pw = None


async def _context() -> Any:
    global _pw, _ctx, _last_used
    if _ctx is None:
        if not USER_DATA_DIR.exists():
            raise RuntimeError("LinkedIn profile not set up. Run: uv run python -m linkedin_mcp.login")
        _pw = await async_playwright().start()
        _ctx = await _pw.chromium.launch_persistent_context(str(USER_DATA_DIR), headless=HEADLESS, no_viewport=True)
    _last_used = time.monotonic()
    _ensure_reaper()
    return _ctx


async def _auto_scroll(page: Any, max_scrolls: int) -> None:
    prev, stable = 0, 0
    for _ in range(max(0, max_scrolls)):
        await page.mouse.wheel(0, 4200)
        await page.wait_for_timeout(1100)
        height = await page.evaluate("() => document.body ? document.body.scrollHeight : 0")
        if height <= prev:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        prev = height


async def _nav(page: Any, url: str, settle_ms: int, scroll: bool, max_scrolls: int) -> None:
    await _pace()
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(settle_ms)
    if scroll:
        await _auto_scroll(page, max_scrolls)


async def _page() -> Any:
    ctx = await _context()
    return ctx.pages[0] if ctx.pages else await ctx.new_page()


async def read_page(
    path: str, extract_js: str | None = None, settle_ms: int = 3000,
    max_scrolls: int = 8, scroll: bool = True,
) -> dict[str, Any]:
    """Navigate to one LinkedIn URL; return {status, authenticated, items?, text}."""
    async with _lock:
        page = await _page()
        url = path if path.startswith("http") else BASE + path
        await _nav(page, url, settle_ms, scroll, max_scrolls)
        global _last_used
        _last_used = time.monotonic()
        raw = await page.evaluate("() => document.body ? document.body.innerText : ''")
        status = _status(page.url, raw)
        result: dict[str, Any] = {
            "requested_url": url, "final_url": page.url, "title": await page.title(),
            "status": status, "authenticated": status not in ("needs_login", "checkpoint"),
        }
        if extract_js and status == "ok":
            try:
                result["items"] = await page.evaluate(extract_js)
            except Exception as exc:
                result["items"] = []
                result["extract_error"] = str(exc)[:200]
        result["text"] = _clean(raw)[:12000]
        return result


async def read_profile(username: str | None, sections: list[str], settle_ms: int = 3000) -> dict[str, Any]:
    """Read a profile via the /details/ subpages, which render full lists even for self
    (the /in/me/ landing page collapses them). Pass username=None for own profile."""
    async with _lock:
        page = await _page()
        if not username or username.strip("/") == "me":
            await _nav(page, f"{BASE}/in/me/", settle_ms, True, 3)
            match = re.search(r"/in/([^/?]+)", page.url)
            vanity = match.group(1) if match else "me"
        else:
            vanity = quote(username.strip("/"))
            await _nav(page, f"{BASE}/in/{vanity}/", settle_ms, True, 3)
        overview = await page.evaluate(extract.MAIN_JS)
        status = _status(page.url, overview)
        out: dict[str, Any] = {
            "username": vanity, "final_url": page.url, "status": status,
            "authenticated": status not in ("needs_login", "checkpoint"),
            "overview": _clean(overview)[:3000], "sections": {},
        }
        if status != "ok":
            return out
        for name in sections:
            sub = _SECTION_PATHS.get(name)
            if not sub:
                continue
            await _nav(page, f"{BASE}/in/{vanity}/{sub}", 2500, True, 6)
            out["sections"][name] = _clean(await page.evaluate(extract.MAIN_JS))[:6000]
        global _last_used
        _last_used = time.monotonic()
        return out


async def read_conversation(name: str, max_scrolls: int = 6) -> dict[str, Any]:
    """Open the conversation whose row matches `name` and return its messages.

    Note: opening a thread is navigation, not sending, but it may register a read
    receipt with the sender. Not a passive read."""
    async with _lock:
        page = await _page()
        await _nav(page, f"{BASE}/messaging/", 4000, False, 0)
        row = page.locator('li[class*="msg-conversation"]').filter(has_text=name).first
        try:
            if await row.count() == 0:
                raise LookupError
            await row.click(timeout=8000)
        except Exception:
            return {
                "status": "not_found", "authenticated": True,
                "message": f"No conversation matching '{name}'. See `conversations` for valid names.",
                "conversations": await page.evaluate(extract.MESSAGES_JS),
            }
        await page.wait_for_timeout(3000)
        for _ in range(max(0, max_scrolls)):
            await page.evaluate(extract.THREAD_SCROLL_JS)
            await page.wait_for_timeout(900)
        thread = await page.evaluate(extract.THREAD_JS)
        global _last_used
        _last_used = time.monotonic()
        return {
            "status": "ok", "authenticated": True, "participant": name,
            "thread_url": page.url, "text": _clean(thread)[:10000],
        }


async def login(timeout_s: int = 360) -> dict[str, Any]:
    """Open a visible browser for a one-time interactive login; persist the profile.
    Runs its own throwaway context so it does not touch the shared read context."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    marker = (
        "!!document.querySelector("
        "'img.global-nav__me-photo, .global-nav__me, [data-control-name=identity_welcome_message], "
        "button.global-nav__primary-link-me-menu-trigger')"
    )
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(str(USER_DATA_DIR), headless=False, no_viewport=True)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(f"{BASE}/feed/", wait_until="domcontentloaded", timeout=45000)
        waited = 0
        while waited < timeout_s:
            await page.wait_for_timeout(2000)
            waited += 2
            try:
                if _blocked(page.url):
                    continue
                if await page.evaluate(marker):
                    await ctx.close()
                    return {"ok": True, "message": f"Logged in (url {page.url}); profile persisted."}
            except Exception:
                continue
        url = page.url
        await ctx.close()
        return {"ok": False, "message": f"Login not detected within {timeout_s}s (last url {url})."}
