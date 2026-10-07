"""Ed Discussion reads: courses, threads, thread detail, announcements, search."""

from __future__ import annotations

from typing import Any

from context_mcp.imperial import http
from context_mcp.imperial.auth import ED_API as API
from context_mcp.imperial.util import TTL_DAY, TTL_SHORT

P = "ed"


def courses() -> list[dict[str, Any]]:
    user = http.get_json(P, f"{API}/user", ttl=TTL_DAY) or {}
    out = []
    for row in user.get("courses", []):
        c = row.get("course") or {}
        if c.get("status") != "active":
            continue
        cats = [x.get("name") for x in ((c.get("settings") or {}).get("discussion") or {}).get("categories", [])]
        out.append({"id": c.get("id"), "code": c.get("code"), "name": c.get("name"),
                    "year": c.get("year"), "session": c.get("session"), "categories": cats})
    return out


def _threads(course: int, limit: int, filt: str = "", category: str = "") -> list[dict[str, Any]]:
    params: dict[str, Any] = {"sort": "new", "limit": limit, "offset": 0}
    if filt:
        params["filter"] = filt
    if category:
        params["category"] = category
    data = http.get_json(P, f"{API}/courses/{course}/threads", ttl=TTL_SHORT, params=params) or {}
    return data.get("threads", [])


def _slim(t: dict[str, Any]) -> dict[str, Any]:
    return {"id": t.get("id"), "number": t.get("number"), "type": t.get("type"), "title": t.get("title"),
            "category": t.get("category"), "subcategory": t.get("subcategory"), "pinned": t.get("is_pinned"),
            "answered": t.get("is_answered"), "reply_count": t.get("reply_count"),
            "created": t.get("created_at"), "updated": t.get("updated_at"), "user": (t.get("user") or {}).get("name")}


def threads(course: int, limit: int = 40, filter: str = "", category: str = "") -> list[dict[str, Any]]:
    return [_slim(t) for t in _threads(course, limit, filter, category)]


def announcements(course: int, limit: int = 40) -> list[dict[str, Any]]:
    return [_slim(t) for t in _threads(course, limit) if t.get("type") == "announcement"]


def thread(thread_id: int) -> dict[str, Any]:
    data = http.get_json(P, f"{API}/threads/{thread_id}", ttl=TTL_SHORT) or {}
    t = data.get("thread") or {}

    def node(n: dict[str, Any]) -> dict[str, Any]:
        return {"user": (n.get("user") or {}).get("name"), "role": (n.get("user") or {}).get("course_role"),
                "endorsed": n.get("is_endorsed"), "text": n.get("document"),
                "comments": [node(c) for c in n.get("comments", [])]}

    return {"id": t.get("id"), "number": t.get("number"), "type": t.get("type"), "title": t.get("title"),
            "category": t.get("category"), "text": t.get("document"),
            "answers": [node(a) for a in t.get("answers", [])],
            "comments": [node(c) for c in t.get("comments", [])]}


def search(course: int, query: str, limit: int = 15) -> list[dict[str, Any]]:
    data = http.get_json(P, f"{API}/courses/{course}/threads/search", ttl=TTL_SHORT,
                         params={"query": query, "limit": limit, "offset": 0}) or {}
    return [_slim(t) | {"snippet": " ".join(t.get("highlights", []))[:200] if t.get("highlights") else ""}
            for t in data.get("threads", [])]
