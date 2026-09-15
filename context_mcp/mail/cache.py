"""Local mirror of Gmail message metadata, kept current with users.history.

Headers never change once a message exists, so they are stored forever. Label
sets do change, so a row serves a read only while its labels are known good;
a history gap blanks every label set and the next read re-fetches.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Iterable

from context_mcp.common import CONFIG_DIR

DB_PATH = CONFIG_DIR / "gmail-cache.sqlite"
_local = threading.local()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, headers TEXT NOT NULL, labels TEXT);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        _local.conn = conn
    return conn


def _row(headers: str, labels: str) -> dict[str, Any]:
    message = json.loads(headers)
    ids = json.loads(labels)
    message["folders"] = ids
    message["unread"] = "UNREAD" in ids
    message["importance"] = "important" if "IMPORTANT" in ids else ""
    return message


def get(ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    wanted = list(ids)
    if not wanted:
        return {}
    conn = _conn()
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        rows = conn.execute(
            f"SELECT id, headers, labels FROM messages WHERE labels IS NOT NULL "
            f"AND id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
        out.update({r[0]: _row(r[1], r[2]) for r in rows})
    return out


def put(messages: Iterable[dict[str, Any]]) -> None:
    rows = []
    for message in messages:
        headers = {k: v for k, v in message.items() if k not in ("folders", "unread", "importance")}
        rows.append((message["id"], json.dumps(headers), json.dumps(message.get("folders") or [])))
    if not rows:
        return
    conn = _conn()
    with conn:
        conn.executemany("INSERT OR REPLACE INTO messages (id, headers, labels) VALUES (?, ?, ?)", rows)


def labels_of(mid: str) -> list[str] | None:
    row = _conn().execute("SELECT labels FROM messages WHERE id = ? AND labels IS NOT NULL", (mid,)).fetchone()
    return json.loads(row[0]) if row else None


def forget(ids: Iterable[str]) -> None:
    chunk = list(ids)
    if not chunk:
        return
    conn = _conn()
    with conn:
        conn.execute(f"UPDATE messages SET labels = NULL WHERE id IN ({','.join('?' * len(chunk))})", chunk)


def forget_all() -> None:
    conn = _conn()
    with conn:
        conn.execute("UPDATE messages SET labels = NULL")


def apply_history(records: list[dict[str, Any]]) -> None:
    conn = _conn()
    with conn:
        for record in records:
            for added in record.get("messagesAdded", []):
                mid = (added.get("message") or {}).get("id")
                if mid:
                    conn.execute("UPDATE messages SET labels = NULL WHERE id = ?", (mid,))
            for deleted in record.get("messagesDeleted", []):
                mid = (deleted.get("message") or {}).get("id")
                if mid:
                    conn.execute("DELETE FROM messages WHERE id = ?", (mid,))
            for change, op in (("labelsAdded", "add"), ("labelsRemoved", "remove")):
                for entry in record.get(change, []):
                    mid = (entry.get("message") or {}).get("id")
                    if not mid:
                        continue
                    row = conn.execute("SELECT labels FROM messages WHERE id = ? AND labels IS NOT NULL",
                                       (mid,)).fetchone()
                    if not row:
                        continue
                    current = set(json.loads(row[0]))
                    touched = set(entry.get("labelIds") or [])
                    updated = current | touched if op == "add" else current - touched
                    conn.execute("UPDATE messages SET labels = ? WHERE id = ?",
                                 (json.dumps(sorted(updated)), mid))


def history_id() -> str | None:
    row = _conn().execute("SELECT value FROM state WHERE key = 'history_id'").fetchone()
    return row[0] if row else None


def set_history_id(value: str) -> None:
    conn = _conn()
    with conn:
        conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('history_id', ?)", (str(value),))
