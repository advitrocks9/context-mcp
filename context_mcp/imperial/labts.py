"""LabTS reads: individual assignments and their submission and test state.

GET-only and path-restricted. The commit-request and late-submit links on these
pages trigger actions, so they are never followed.
"""

from __future__ import annotations

import html
import re
from typing import Any

from context_mcp.imperial import http
from context_mcp.imperial.util import TTL_SHORT, academic_year

P = "labts"
BASE = "https://teaching.doc.ic.ac.uk/labts"
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_HREF = re.compile(r'href="(/labts/lab_exercises/[^"]+)"')


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def exercises(year: str = "") -> list[dict[str, Any]]:
    year = year or academic_year()
    page = http.get_text(P, f"{BASE}/home/index/{year}", ttl=TTL_SHORT, follow=False)
    out = []
    for row in _ROW.findall(page):
        cells = [_text(c) for c in _CELL.findall(row)]
        if len(cells) < 4:
            continue
        link = _HREF.search(row)
        out.append({"exercise": cells[0], "milestone": cells[1], "latest_test": cells[2],
                    "submission": cells[3], "result": cells[4] if len(cells) > 4 else "",
                    "repo": link.group(1) if link else None})
    return out


def repository(path: str) -> dict[str, Any]:
    if not path.startswith("/labts/lab_exercises/") or re.search(r"late|request|submit|delete", path):
        return {"error": "only repository view paths are allowed"}
    page = http.get_text(P, f"https://teaching.doc.ic.ac.uk{path}", ttl=TTL_SHORT, follow=False)
    commits = []
    for row in _ROW.findall(page):
        cells = [_text(c) for c in _CELL.findall(row)]
        if len(cells) >= 4 and re.match(r"^[0-9a-f]{6,}$", cells[1] or ""):
            commits.append({"status": cells[0], "hash": cells[1], "message": cells[2],
                            "date": cells[3], "test": cells[4] if len(cells) > 4 else ""})
    clone = re.findall(r"git clone (https://gitlab[^\s<\"]+)", page)
    return {"commits": commits, "clone": clone[0] if clone else None}
