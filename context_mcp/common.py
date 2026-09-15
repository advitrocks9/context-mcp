"""Shared configuration, HTTP, audit logging, and time helpers."""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
import pathlib
import threading
import urllib.parse
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping, TypeVar

import httpx

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = pathlib.Path.home() / ".config" / "context-mcp"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG = CONFIG_DIR / "actions.log"
HTTP_TIMEOUT_SECONDS = 30
COREDATA_EPOCH = 978307200
MAX_PARALLEL = 16

T = TypeVar("T")
R = TypeVar("R")

_client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True,
                       limits=httpx.Limits(max_connections=MAX_PARALLEL * 2,
                                           max_keepalive_connections=MAX_PARALLEL))
_audit_lock = threading.Lock()


def parallel_map(fn: Callable[[T], R], items: Iterable[T], workers: int = MAX_PARALLEL) -> list[R]:
    rows = list(items)
    if len(rows) < 2:
        return [fn(row) for row in rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(rows))) as pool:
        return list(pool.map(fn, rows))


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_file = REPO_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    for key in list(env):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def http(method: str, url: str, headers: Mapping[str, str] | None = None,
         data: Mapping[str, Any] | None = None, form: bool = False) -> dict[str, Any]:
    headers = dict(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = json.dumps(data).encode()
            headers.setdefault("Content-Type", "application/json")
    response = _client.request(method, url, headers=headers, content=body)
    if response.is_error:
        detail = response.text[:600]
        raise RuntimeError(f"HTTP {response.status_code} {method} {url.split('?')[0]} :: {detail}")
    return response.json() if response.content else {}


def audit(entry: Mapping[str, Any]) -> None:
    entry = dict(entry)
    entry["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    with _audit_lock, AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def read_audit() -> list[dict[str, Any]]:
    if not AUDIT_LOG.exists():
        return []
    return [json.loads(line) for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_date(value: object) -> float:
    if not value:
        return 0.0
    text = str(value)
    try:
        if "T" in text:
            return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        return parsedate_to_datetime(text).timestamp()
    except Exception:
        return 0.0


def coredata_to_iso(value: float | None) -> str:
    if not value or value <= 0 or value > 4_000_000_000:
        return ""
    return datetime.datetime.fromtimestamp(value + COREDATA_EPOCH).isoformat(timespec="minutes")
