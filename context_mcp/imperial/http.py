"""GET-only HTTP for Imperial providers with an on-disk response cache.

Every call is a GET; there is no path that writes. Responses are cached in
SQLite by url and served while fresh, so repeated reads never re-hit a provider.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

import httpx

from context_mcp.common import CONFIG_DIR
from context_mcp.imperial import auth

DB_PATH = CONFIG_DIR / "imperial-cache.sqlite"
_local = threading.local()
_client = httpx.Client(timeout=45, follow_redirects=False,
                       limits=httpx.Limits(max_connections=16, max_keepalive_connections=8))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, fetched REAL NOT NULL, body BLOB NOT NULL, ctype TEXT);
"""


class AuthError(RuntimeError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider} session expired or signed out")
        self.provider = provider


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        _local.conn = conn
    return conn


def _cache_get(key: str, ttl: float) -> bytes | None:
    if ttl <= 0:
        return None
    row = _conn().execute("SELECT fetched, body FROM cache WHERE key = ?", (key,)).fetchone()
    if row and time.time() - row[0] < ttl:
        return row[1]
    return None


MAX_CACHE_BYTES = 262144
MAX_CACHE_AGE = 7 * 86400


def _cache_put(key: str, body: bytes, ctype: str) -> None:
    if len(body) > MAX_CACHE_BYTES:
        return
    conn = _conn()
    with conn:
        conn.execute("INSERT OR REPLACE INTO cache (key, fetched, body, ctype) VALUES (?, ?, ?, ?)",
                     (key, time.time(), body, ctype))
        conn.execute("DELETE FROM cache WHERE fetched < ?", (time.time() - MAX_CACHE_AGE,))


def clear_cache(prefix: str = "") -> int:
    conn = _conn()
    with conn:
        cur = conn.execute("DELETE FROM cache WHERE key LIKE ?", (f"{prefix}%",))
    return cur.rowcount


def _is_login(provider: str, response: httpx.Response) -> bool:
    if response.status_code in (401, 403):
        return True
    if response.is_redirect:
        loc = response.headers.get("location", "")
        return any(m in loc for m in auth.LOGIN_MARKERS)
    return False


def _raw(provider: str, url: str, follow: bool, params: dict[str, Any] | None) -> httpx.Response:
    auth.ensure(provider)
    hdrs = auth.headers(provider)
    if not (hdrs.get("Cookie") or hdrs.get("x-token")):
        raise AuthError(provider)
    response = _client.get(url, headers=hdrs, params=params, follow_redirects=follow)
    if _is_login(provider, response):
        raise AuthError(provider)
    return response


def get_bytes(provider: str, url: str, ttl: float = 0, params: dict[str, Any] | None = None,
              follow: bool = True) -> tuple[bytes, str]:
    key = f"{provider}:{url}:{json.dumps(params, sort_keys=True) if params else ''}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        row = _conn().execute("SELECT ctype FROM cache WHERE key = ?", (key,)).fetchone()
        return cached, (row[0] if row else "")
    response = _raw(provider, url, follow, params)
    if response.is_error:
        raise RuntimeError(f"{provider} HTTP {response.status_code} {url.split('?')[0]} :: {response.text[:300]}")
    body, ctype = response.content, response.headers.get("content-type", "")
    if ttl > 0:
        _cache_put(key, body, ctype)
    return body, ctype


def get_json(provider: str, url: str, ttl: float = 0, params: dict[str, Any] | None = None) -> Any:
    body, _ = get_bytes(provider, url, ttl=ttl, params=params, follow=False)
    text = body.decode("utf-8", "replace").lstrip()
    text = text.removeprefix("while(1);")
    return json.loads(text) if text else None


def get_text(provider: str, url: str, ttl: float = 0, params: dict[str, Any] | None = None,
             follow: bool = True) -> str:
    body, _ = get_bytes(provider, url, ttl=ttl, params=params, follow=follow)
    return body.decode("utf-8", "replace")


def get_paged_json(provider: str, url: str, ttl: float = 0, params: dict[str, Any] | None = None,
                   cap: int = 20) -> list[Any]:
    out: list[Any] = []
    page = params or {}
    for _ in range(cap):
        body, _ctype = get_bytes(provider, url, ttl=ttl, params=page, follow=False)
        text = body.decode("utf-8", "replace").lstrip()
        text = text.removeprefix("while(1);")
        batch = json.loads(text) if text else []
        if isinstance(batch, dict):
            return batch
        out.extend(batch)
        if len(batch) < int(page.get("per_page", 100)):
            break
        page = dict(page)
        page["page"] = int(page.get("page", 1)) + 1
    return out
