"""Provider dispatch and batch helpers shared by the mail tools."""

from __future__ import annotations

from typing import Any, Callable

import sys

from context_mcp.common import parallel_map, parse_date
from context_mcp.mail import gmail, outlook
from context_mcp.mail.outlook_auth import have_credentials

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

    def fetch(target: tuple[str, Any]) -> tuple[str, dict[str, Any] | Exception]:
        name, backend = target
        try:
            return name, backend.list_messages_page(folder=folder, query=query, unread_only=unread_only,
                                                    limit=limit, cursor=cursor if provider != "both" else "")
        except Exception as exc:
            return name, exc

    for name, page in parallel_map(fetch, targets(provider)):
        if isinstance(page, Exception):
            errors.append({"provider": name, "error": str(page)})
            continue
        messages.extend(page.get("messages", []))
        if page.get("next_cursor"):
            next_cursors[name] = str(page["next_cursor"])
        if page.get("result_size_estimate") is not None:
            estimates[name] = int(page["result_size_estimate"])
        if page.get("total_count") is not None:
            totals[name] = int(page["total_count"])
    return {"messages": _merge(messages), "returned": len(messages), "next_cursors": next_cursors,
            "result_size_estimates": estimates, "total_counts": totals, "errors": errors}


def batch(provider: str, action: str, ids: list[str], apply_one: Callable[[str], dict[str, Any]],
          apply_all: Callable[[list[str]], None] | None = None) -> dict[str, Any]:
    def run(mid: str) -> dict[str, Any]:
        try:
            return {"id": mid, "ok": True, "result": apply_one(mid)}
        except Exception as exc:
            return {"id": mid, "ok": False, "error": str(exc)}

    if apply_all is not None and len(ids) > 1:
        apply_all(ids)
        results = [{"id": mid, "ok": True} for mid in ids]
    else:
        results = parallel_map(run, ids)
    ok = sum(1 for r in results if r["ok"])
    return {"provider": provider, "action": action, "requested": len(ids),
            "succeeded": ok, "failed": len(ids) - ok, "results": results}


def is_reversible(entry: dict[str, Any]) -> bool:
    return entry.get("op") in {"move", "tag", "mark_read", "flag", "trash", "mark_spam", "untrash"}

def _warm_gmail() -> None:
    gmail.list_folders()
    gmail.list_messages_page(limit=1)


def prewarm() -> None:
    """Mint tokens and open the TLS connections before the first tool call needs them."""
    def warm(name: str, call: Callable[[], Any]) -> None:
        try:
            call()
        except Exception as exc:
            print(f"prewarm {name}: {exc}", file=sys.stderr)

    warm("gmail", _warm_gmail)
    if have_credentials():
        warm("outlook", outlook.list_folders)
