"""Register the Imperial services as soft-loaded dispatcher tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from context_mcp import gateway
from context_mcp.imperial import auth, canvas, ed, http, labts, panopto, scientia
from context_mcp.imperial.util import FILES_DIR


def _files() -> list[dict[str, Any]]:
    if not FILES_DIR.exists():
        return []
    return [{"path": str(p.relative_to(FILES_DIR)), "bytes": p.stat().st_size}
            for p in sorted(FILES_DIR.rglob("*")) if p.is_file()]


def register(mcp: FastMCP) -> None:
    gateway.service(mcp, "scientia", "Scientia (DoC VLE)", {
        "modules": scientia.modules, "module": scientia.module, "exercises": scientia.exercises,
        "resources": scientia.resources, "resource_file": scientia.resource_file,
        "exercise_spec": scientia.exercise_spec, "past_papers": scientia.past_papers,
        "past_paper_file": scientia.past_paper_file, "results": scientia.results,
        "choices": scientia.choices, "tutorial_groups": scientia.tutorial_groups,
    })
    gateway.service(mcp, "canvas", "Canvas (Maths VLE)", {
        "courses": canvas.courses, "content": canvas.content, "page": canvas.page, "pages": canvas.pages,
        "panopto_folders": canvas.panopto_folders, "deadlines": canvas.deadlines,
        "announcements": canvas.announcements, "files": canvas.files, "file": canvas.file, "search": canvas.search,
    })
    gateway.service(mcp, "panopto", "Panopto lectures", {
        "folders": panopto.folders, "recordings": panopto.recordings,
        "transcript": panopto.transcript, "search": panopto.search,
    })
    gateway.service(mcp, "ed", "Ed Discussion", {
        "courses": ed.courses, "threads": ed.threads, "thread": ed.thread,
        "announcements": ed.announcements, "search": ed.search,
    })
    gateway.service(mcp, "labts", "LabTS submissions", {
        "exercises": labts.exercises, "repository": labts.repository,
    })
    gateway.service(mcp, "imperial", "Imperial auth and files", {
        "status": auth.status,
        "refresh": lambda providers=None: auth.refresh(providers),
        "files": _files,
        "clear_cache": lambda prefix="": {"deleted": http.clear_cache(prefix)},
    })
