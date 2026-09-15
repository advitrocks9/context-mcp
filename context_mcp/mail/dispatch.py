"""Provider dispatch and batch helpers shared by the mail tools."""

from __future__ import annotations

from typing import Any, Callable

from context_mcp.common import parse_date
from context_mcp.mail import gmail, outlook

PROVIDERS = {"gmail": gmail, "outlook": outlook}


def targets(provider: str) -> list[tuple[str, Any]]:
    normalized = (provider or "both").lower()
    if normalized == "both":
        return [("gmail", gmail), ("outlook", outlook)]
    if normalized in PROVIDERS:
        return [(normalized, PROVIDERS[normalized])]
    raise ValueError("provider must be 'gmail', 'outlook', or 'both'")


def one(provider: str) -> Any:
    normalized = (provider or "").lower()
    if normalized not in PROVIDERS:
        raise ValueError("This action needs a specific provider: 'gmail' or 'outlook'.")
    return PROVIDERS[normalized]


def _merge(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(key=lambda m: parse_date(m.get("date", "")) if "error" not in m else 0, reverse=True)
    return rows


def message_page(provider: str, folder: str = "inbox", query: str = "",
                 unread_only: bool = False, limit: int = 15, cursor: str = "") -> dict[str, Any]:
    if cursor and provider == "both":
        raise ValueError("Use provider='gmail' or provider='outlook' when passing a cursor.")
    messages: list[dict[str, Any]] = []
    next_cursors: dict[str, str] = {}
    estimates: dict[str, int] = {}
    totals: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    for name, backend in targets(provider):
        try:
            page = backend.list_messages_page(folder=folder, query=query, unread_only=unread_only,
                                              limit=limit, cursor=cursor if provider != "both" else "")
            messages.extend(page.get("messages", []))
            if page.get("next_cursor"):
                next_cursors[name] = str(page["next_cursor"])
            if page.get("result_size_estimate") is not None:
                estimates[name] = int(page["result_size_estimate"])
            if page.get("total_count") is not None:
                totals[name] = int(page["total_count"])
        except Exception as exc:
            errors.append({"provider": name, "error": str(exc)})
    return {"messages": _merge(messages), "returned": len(messages), "next_cursors": next_cursors,
            "result_size_estimates": estimates, "total_counts": totals, "errors": errors}


def batch(provider: str, action: str, ids: list[str], apply_one: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for mid in ids:
        try:
            results.append({"id": mid, "ok": True, "result": apply_one(mid)})
        except Exception as exc:
            results.append({"id": mid, "ok": False, "error": str(exc)})
    ok = sum(1 for r in results if r["ok"])
    return {"provider": provider, "action": action, "requested": len(ids),
            "succeeded": ok, "failed": len(ids) - ok, "results": results}


def is_reversible(entry: dict[str, Any]) -> bool:
    return entry.get("op") in {"move", "tag", "mark_read", "flag", "trash", "mark_spam", "untrash"}
