"""Shared helpers: academic-year code and the local files directory."""

from __future__ import annotations

import datetime
import os
import pathlib
import re

FILES_DIR = pathlib.Path(os.environ.get("IMPERIAL_DIR", str(pathlib.Path.home() / "Projects" / "imperial" / "files")))

TTL_SHORT = 900
TTL_HOUR = 3600
TTL_DAY = 86400
TTL_WEEK = 604800


def academic_year(when: datetime.date | None = None) -> str:
    today = when or datetime.date.today()
    start = today.year if today.month >= 9 else today.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def target(subdir: str, name: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "file"
    out = FILES_DIR / subdir
    out.mkdir(parents=True, exist_ok=True)
    return out / safe


def save_file(subdir: str, name: str, body: bytes) -> dict[str, object]:
    path = target(subdir, name)
    path.write_bytes(body)
    return {"path": str(path), "bytes": len(body)}


def download(provider: str, url: str, subdir: str, name: str, follow: bool = True) -> dict[str, object]:
    from context_mcp.imperial import http
    path = target(subdir, name)
    if path.exists() and path.stat().st_size > 0:
        return {"path": str(path), "bytes": path.stat().st_size, "cached": True}
    body, ctype = http.get_bytes(provider, url, ttl=0, follow=follow)
    if path.suffix == "" and "pdf" in ctype:
        path = path.with_suffix(".pdf")
    path.write_bytes(body)
    return {"path": str(path), "bytes": len(body), "content_type": ctype}
