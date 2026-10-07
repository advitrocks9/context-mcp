"""Scientia reads: modules, exercises and deadlines, resources, files, marks."""

from __future__ import annotations

from typing import Any

from context_mcp.imperial import http
from context_mcp.imperial.auth import SCIENTIA_API as API
from context_mcp.imperial.util import TTL_DAY, TTL_HOUR, academic_year, download

P = "scientia"


def _personal(year: str) -> dict[str, Any]:
    rows = http.get_json(P, f"{API}/{year}/personal", ttl=TTL_DAY)
    return rows[0] if rows else {}


def login(year: str = "") -> str:
    return _personal(year or academic_year()).get("login", "")


def modules(year: str = "") -> list[dict[str, Any]]:
    year = year or academic_year()
    mods = _personal(year).get("modules", [])
    return [{"code": m.get("code"), "title": m.get("title"), "term": m.get("terms") or m.get("term"),
             "ects": m.get("ects")} for m in mods]


def module(code: str, year: str = "") -> dict[str, Any]:
    year = year or academic_year()
    rows = http.get_json(P, f"{API}/{year}/modules", ttl=TTL_DAY, params={"module_code": code})
    detail = rows[0] if rows else {}
    staff = [{"name": f"{s.get('firstname','')} {s.get('lastname','')}".strip(), "role": s.get("role_on_module"),
              "hours": s.get("timetabled_hours")} for s in detail.get("staff", [])]
    return {"code": detail.get("code"), "title": detail.get("title"), "ects": detail.get("ects"),
            "terms": detail.get("terms"), "staff": staff}


def _enrolled_codes(year: str) -> set[str]:
    return {m["code"] for m in modules(year)}


def exercises(module: str = "", year: str = "", include_done: bool = True) -> list[dict[str, Any]]:
    year = year or academic_year()
    rows = http.get_json(P, f"{API}/me/{year}/exercises", ttl=TTL_HOUR)
    codes = _enrolled_codes(year)
    out = []
    for e in rows:
        code = e.get("module_code")
        if code not in codes:
            continue
        if module and code != module:
            continue
        submitted = bool(e.get("submissions"))
        mark = (e.get("mark") or {}).get("mark")
        if not include_done and submitted and mark is not None:
            continue
        out.append({
            "module": code, "number": e.get("number"), "title": e.get("title"), "type": e.get("type"),
            "start": e.get("start"), "deadline": e.get("extended_end") or e.get("end"),
            "assessed": bool(e.get("maximum_mark")), "weight": e.get("weight"),
            "max_mark": e.get("maximum_mark"), "group": bool(e.get("requires_group")),
            "requires_submission": bool(e.get("requires_submission")),
            "submitted": submitted, "mark": mark,
            "has_spec": bool(e.get("spec")), "expected_hours": e.get("expected_hours"),
        })
    out.sort(key=lambda r: r.get("deadline") or "")
    return out


def resources(module: str, year: str = "") -> list[dict[str, Any]]:
    year = year or academic_year()
    rows = http.get_json(P, f"{API}/resources", ttl=TTL_HOUR * 6, params={"year": year, "course": module})
    out = []
    for r in rows or []:
        out.append({"id": r.get("id"), "title": r.get("title"), "category": r.get("category"),
                    "type": r.get("type"), "filename": r.get("filename") or r.get("path"),
                    "visible_after": r.get("visible_after"), "url": r.get("path") if r.get("type") == "link" else None})
    return out


def resource_file(resource_id: int, module: str = "", year: str = "", filename: str = "") -> dict[str, Any]:
    name = filename or f"resource_{resource_id}"
    return download(P, f"{API}/resources/{resource_id}/file", f"{module or 'scientia'}/resources", name)


def exercise_spec(module: str, number: int, year: str = "") -> dict[str, Any]:
    year = year or academic_year()
    return download(P, f"{API}/{year}/{module}/exercises/{number}/spec", f"{module}/specs", f"{module}_ex{number}_spec.pdf")


def past_papers(module: str, year: str = "") -> list[dict[str, Any]]:
    year = year or academic_year()
    rows = http.get_json(P, f"{API}/past-papers", ttl=TTL_DAY, params={"year": year, "module_code": module})
    return [{"id": r.get("id"), "module": r.get("module_code"), "year": r.get("year")} for r in rows or []]


def past_paper_file(paper_id: int, module: str = "", year: str = "") -> dict[str, Any]:
    return download(P, f"{API}/past-papers/{paper_id}/file", f"{module or 'scientia'}/past-papers", f"paper_{paper_id}.pdf")


def results(year: str = "") -> dict[str, Any]:
    year = year or academic_year()
    who = login(year)
    return http.get_json(P, f"{API}/{year}/students/{who}/results", ttl=TTL_DAY)


def choices(year: str = "") -> list[dict[str, Any]]:
    year = year or academic_year()
    return http.get_json(P, f"{API}/me/{year}/module-choices", ttl=TTL_DAY)


def tutorial_groups(module: str = "", year: str = "") -> list[dict[str, Any]]:
    year = year or academic_year()
    rows = http.get_json(P, f"{API}/{year}/tutorial-groups", ttl=TTL_DAY)
    who = login(year)
    out = []
    for g in rows or []:
        members = g.get("members") or []
        mine = any((m.get("username") or m.get("login")) == who for m in members)
        if module and g.get("module_code") != module:
            continue
        if not module and not mine:
            continue
        out.append({"module": g.get("module_code"), "type": g.get("type"), "name": g.get("name"),
                    "size": len(members), "mine": mine})
    return out
