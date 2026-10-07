"""Panopto reads: lecture folders, recordings, transcripts, cross-lecture search."""

from __future__ import annotations

import re
from typing import Any

import httpx

from context_mcp.imperial import auth, http
from context_mcp.imperial.util import TTL_DAY, TTL_HOUR, academic_year, save_file, target

P = "panopto"
BASE = "https://imperial.cloud.panopto.eu/Panopto"
API = f"{BASE}/api/v1"


def _term_tag(year: str) -> str:
    start = 2000 + int(year[:2])
    return f"{start}-{start + 1}"


def _query(module: str) -> str:
    module = module.upper()
    return module if module.startswith("MATH") else "COMP" + module.split(".")[0]


def _refresh_csrf() -> None:
    cred = auth.credential(P)
    cookie = cred.get("cookie", "")
    if not cookie:
        return
    resp = httpx.get(f"{BASE}/Pages/Home.aspx", headers={"Cookie": cookie}, timeout=30, follow_redirects=True)
    for raw in resp.headers.get_list("set-cookie"):
        pair = raw.split(";", 1)[0]
        if pair.startswith("csrfToken="):
            jar = auth._cookie_dict(cookie)
            jar["csrfToken"] = pair.split("=", 1)[1]
            with auth._lock:
                state = auth._load()
                entry = state.get(P, {})
                entry["cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
                entry["csrf"] = jar["csrfToken"]
                state[P] = entry
                auth._save(state)
            return


def _get(url: str, ttl: float, params: dict[str, Any] | None = None) -> Any:
    try:
        return http.get_json(P, url, ttl=ttl, params=params)
    except http.AuthError:
        _refresh_csrf()
        return http.get_json(P, url, ttl=ttl, params=params)


def folders(query: str = "", year: str = "") -> list[dict[str, Any]]:
    year = year or academic_year()
    tag = _term_tag(year)
    if not query:
        from context_mcp.imperial import scientia
        queries = [_query(m["code"]) for m in scientia.modules(year)]
    else:
        queries = [query]
    seen: dict[str, dict[str, Any]] = {}
    for q in queries:
        data = _get(f"{API}/folders/search", TTL_DAY, {"searchQuery": q}) or {}
        for r in data.get("Results", []):
            name = r.get("Name", "")
            seen[r.get("Id")] = {"id": r.get("Id"), "name": name, "sessions": r.get("SessionCount"),
                                 "current_term": tag in name}
    return [f for f in seen.values() if not query and f["current_term"]] or list(seen.values())


def _resolve_folder(module: str, year: str) -> dict[str, Any] | None:
    hits = folders(_query(module), year)
    current = [h for h in hits if h["current_term"]]
    return (current or hits or [None])[0]


def recordings(module: str, year: str = "") -> list[dict[str, Any]]:
    year = year or academic_year()
    folder = _resolve_folder(module, year)
    if not folder:
        return []
    data = _get(f"{API}/folders/{folder['id']}/sessions", TTL_HOUR,
                {"sortField": "CreatedDate", "sortOrder": "Desc"}) or {}
    out = []
    for s in data.get("Results", []):
        urls = s.get("Urls") or {}
        out.append({"id": s.get("Id"), "name": s.get("Name"), "date": s.get("StartTime"),
                    "minutes": round((s.get("Duration") or 0) / 60, 1), "viewer": urls.get("ViewerUrl"),
                    "captions": urls.get("CaptionDownloadUrl")})
    return out


def _srt_to_text(srt: str) -> str:
    lines = []
    for line in srt.splitlines():
        line = line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        line = re.sub(r"\[Auto-generated transcript.*?\]", "", line).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return " ".join(lines)


def transcript(session_id: str, module: str = "", full: bool = False) -> dict[str, Any]:
    txt_path = target(f"{module or 'panopto'}/transcripts", f"{session_id}.txt")
    if txt_path.exists() and txt_path.stat().st_size > 0:
        text = txt_path.read_text()
    else:
        srt = http.get_text(P, f"{BASE}/Pages/Transcription/GenerateSRT.ashx?id={session_id}&language=English_GBR",
                            ttl=0, follow=True)
        if len(srt.strip()) < 40:
            return {"error": "no transcript available"}
        save_file(f"{module or 'panopto'}/transcripts", f"{session_id}.srt", srt.encode())
        text = _srt_to_text(srt)
        txt_path.write_text(text)
    result = {"path": str(txt_path), "chars": len(text), "words": len(text.split())}
    if full:
        result["text"] = text
    return result


def search(query: str, year: str = "") -> list[dict[str, Any]]:
    data = _get(f"{API}/sessions/search", TTL_HOUR, {"searchQuery": query}) or {}
    out = []
    for s in data.get("Results", []):
        urls = s.get("Urls") or {}
        out.append({"id": s.get("Id"), "name": s.get("Name"), "folder": s.get("FolderName"),
                    "date": s.get("StartTime"), "viewer": urls.get("ViewerUrl")})
    return out
