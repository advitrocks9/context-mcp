"""Canvas reads: courses, module content, pages, deadlines, announcements, files."""

from __future__ import annotations

import re
from typing import Any

from context_mcp.imperial import http
from context_mcp.imperial.util import TTL_DAY, TTL_HOUR, download

P = "canvas"
API = "https://canvas.imperial.ac.uk/api/v1"
_CODE = re.compile(r"\b(?:COMP|MATH)\d{5}\b")
_PANOPTO = re.compile(r"folderID=([0-9a-f-]{36})", re.I)


def courses() -> list[dict[str, Any]]:
    rows = http.get_paged_json(P, f"{API}/courses", ttl=TTL_HOUR * 6,
                               params={"enrollment_state": "active", "include[]": "term", "per_page": 50})
    out = []
    for c in rows:
        if "id" not in c:
            continue
        text = f"{c.get('name','')} {c.get('course_code','')}"
        out.append({"id": c["id"], "name": c.get("name"), "code": c.get("course_code"),
                    "modules": sorted(set(_CODE.findall(text))),
                    "term": (c.get("term") or {}).get("name")})
    return out


def content(course: int) -> list[dict[str, Any]]:
    mods = http.get_paged_json(P, f"{API}/courses/{course}/modules", ttl=TTL_HOUR,
                               params={"include[]": "items", "per_page": 50})
    out = []
    for m in mods:
        items = [{"title": i.get("title"), "type": i.get("type"), "page_url": i.get("page_url"),
                  "url": i.get("external_url") or i.get("html_url"), "content_id": i.get("content_id")}
                 for i in m.get("items", [])]
        out.append({"module": m.get("name"), "items": items})
    return out


def panopto_folders(course: int) -> list[str]:
    found: set[str] = set()
    for m in content(course):
        for i in m["items"]:
            if i.get("url"):
                found.update(_PANOPTO.findall(i["url"]))
    for page in pages(course):
        found.update(_PANOPTO.findall(page.get("body", "")))
    return sorted(found)


def pages(course: int) -> list[dict[str, Any]]:
    out = []
    for m in content(course):
        for i in m["items"]:
            if i.get("type") == "Page" and i.get("page_url"):
                out.append(page(course, i["page_url"]))
    return out


def page(course: int, url: str) -> dict[str, Any]:
    body = http.get_json(P, f"{API}/courses/{course}/pages/{url}", ttl=TTL_HOUR)
    html = body.get("body") or ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return {"title": body.get("title"), "url": url, "body": html, "text": text, "updated_at": body.get("updated_at")}


def deadlines(ahead_days: int = 120) -> list[dict[str, Any]]:
    import datetime
    start = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    end = (datetime.date.today() + datetime.timedelta(days=ahead_days)).isoformat()
    items = http.get_paged_json(P, f"{API}/planner/items", ttl=TTL_HOUR,
                                params={"start_date": start, "end_date": end, "per_page": 50})
    out = []
    for it in items:
        if it.get("plannable_type") in ("announcement", "calendar_event"):
            continue
        pl = it.get("plannable") or {}
        due = pl.get("due_at") or it.get("plannable_date")
        if not due:
            continue
        sub = it.get("submissions") or {}
        out.append({"course_id": it.get("course_id"), "title": pl.get("title") or pl.get("name"),
                    "type": it.get("plannable_type"), "due": due, "points": pl.get("points_possible"),
                    "submitted": bool(sub.get("submitted")) if isinstance(sub, dict) else False})
    out.sort(key=lambda r: r.get("due") or "")
    return out


def announcements(days: int = 60) -> list[dict[str, Any]]:
    import datetime
    active = courses()
    if not active:
        return []
    params: list[tuple[str, Any]] = [("context_codes[]", f"course_{c['id']}") for c in active]
    start = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    params += [("start_date", start), ("per_page", 50)]
    url = f"{API}/announcements?" + "&".join(f"{k}={v}" for k, v in params)
    rows = http.get_json(P, url, ttl=TTL_HOUR)
    return [{"title": a.get("title"), "posted": a.get("posted_at") or a.get("created_at"),
             "course_id": re.sub(r"\D", "", str(a.get("context_code", ""))),
             "message": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", a.get("message") or "")).strip()[:500]}
            for a in (rows or [])]


def files(course: int) -> list[dict[str, Any]]:
    rows = http.get_paged_json(P, f"{API}/courses/{course}/files", ttl=TTL_HOUR * 6, params={"per_page": 50})
    if isinstance(rows, dict):
        return [{"error": rows.get("status") or "not accessible"}]
    return [{"id": f.get("id"), "name": f.get("display_name"), "size": f.get("size"),
             "type": f.get("content-type"), "updated": f.get("updated_at")} for f in rows]


def file(file_id: int, course: str = "") -> dict[str, Any]:
    meta = http.get_json(P, f"{API}/files/{file_id}", ttl=TTL_DAY)
    pub = http.get_json(P, f"{API}/files/{file_id}/public_url", ttl=0)
    name = meta.get("display_name") or f"canvas_{file_id}"
    return download(P, pub["public_url"], f"canvas/{course or meta.get('folder_id','files')}", name)


def search(course: int, query: str) -> list[dict[str, Any]]:
    rows = http.get_json(P, f"{API}/courses/{course}/smartsearch", ttl=TTL_HOUR,
                         params={"q": query, "per_page": 15})
    results = (rows or {}).get("results", []) if isinstance(rows, dict) else []
    return [{"title": r.get("title"), "type": r.get("content_type"), "url": r.get("html_url"),
             "distance": r.get("distance")} for r in results]
