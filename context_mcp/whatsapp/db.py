"""Read-only readers and a guarded raw-SQL entry point over the local WhatsApp store."""

from __future__ import annotations

import pathlib
import re
import sqlite3
from typing import Any

from context_mcp.common import coredata_to_iso

DB_PATH = (pathlib.Path.home()
           / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite")

_SELECT_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def guard_sql(sql: str) -> str:
    stripped = _COMMENT.sub(" ", sql or "").strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("Empty query.")
    if ";" in stripped:
        raise ValueError("Only one statement is allowed.")
    if not _SELECT_START.match(stripped):
        raise ValueError("Only read-only SELECT/WITH queries are allowed.")
    return stripped


def _connect(path: pathlib.Path = DB_PATH) -> sqlite3.Connection:
    if not pathlib.Path(path).exists():
        raise RuntimeError(f"WhatsApp store not found at {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=1")
    return conn


def query(sql: str, params: tuple[Any, ...] = (), limit: int = 200,
          path: pathlib.Path = DB_PATH) -> list[dict[str, Any]]:
    safe = guard_sql(sql)
    conn = _connect(path)
    try:
        rows = conn.execute(safe, params).fetchmany(int(limit))
        return [dict(r) for r in rows]
    finally:
        conn.close()


def schema(path: pathlib.Path = DB_PATH) -> dict[str, list[str]]:
    conn = _connect(path)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ZWA%' ORDER BY name")]
        out: dict[str, list[str]] = {}
        for table in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            out[table] = cols
        return out
    finally:
        conn.close()


def _chat_kind(session_type: int | None) -> str:
    return {0: "direct", 1: "group", 3: "status"}.get(session_type or 0, "other")


def list_chats(limit: int = 30, query: str = "", kind: str = "",
               path: pathlib.Path = DB_PATH) -> list[dict[str, Any]]:
    clauses = ["s.ZREMOVED = 0"]
    params: list[Any] = []
    if query:
        clauses.append("(s.ZPARTNERNAME LIKE ? OR s.ZCONTACTJID LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    if kind:
        code = {"direct": 0, "group": 1, "status": 3}.get(kind.lower())
        if code is not None:
            clauses.append("s.ZSESSIONTYPE = ?")
            params.append(code)
    params.append(int(limit))
    conn = _connect(path)
    try:
        rows = conn.execute(
            f"""SELECT s.ZPARTNERNAME name, s.ZCONTACTJID jid, s.ZSESSIONTYPE stype,
                       s.ZUNREADCOUNT unread, s.ZMESSAGECOUNTER messages,
                       lm.ZMESSAGEDATE last, s.ZLASTMESSAGETEXT last_text
                FROM ZWACHATSESSION s LEFT JOIN ZWAMESSAGE lm ON s.ZLASTMESSAGE = lm.Z_PK
                WHERE {' AND '.join(clauses)}
                ORDER BY lm.ZMESSAGEDATE DESC LIMIT ?""", params).fetchall()
        return [{"name": r["name"], "jid": r["jid"], "kind": _chat_kind(r["stype"]),
                 "unread": r["unread"], "messages": r["messages"],
                 "last_message": coredata_to_iso(r["last"]), "last_text": r["last_text"]}
                for r in rows]
    finally:
        conn.close()


def list_contacts(query: str = "", limit: int = 50,
                  path: pathlib.Path = DB_PATH) -> list[dict[str, Any]]:
    clauses = ["ZSESSIONTYPE = 0", "ZREMOVED = 0"]
    params: list[Any] = []
    if query:
        clauses.append("(ZPARTNERNAME LIKE ? OR ZCONTACTJID LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    params.append(int(limit))
    conn = _connect(path)
    try:
        rows = conn.execute(
            f"""SELECT ZPARTNERNAME name, ZCONTACTJID jid, ZMESSAGECOUNTER messages
                FROM ZWACHATSESSION WHERE {' AND '.join(clauses)}
                ORDER BY ZMESSAGECOUNTER DESC LIMIT ?""", params).fetchall()
        return [{"name": r["name"], "jid": r["jid"], "messages": r["messages"]} for r in rows]
    finally:
        conn.close()


def _resolve_session(conn: sqlite3.Connection, name_or_jid: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT Z_PK, ZPARTNERNAME, ZCONTACTJID FROM ZWACHATSESSION
           WHERE ZCONTACTJID = ? OR ZPARTNERNAME = ?
           ORDER BY ZMESSAGECOUNTER DESC LIMIT 1""",
        (name_or_jid, name_or_jid)).fetchone() or conn.execute(
        """SELECT Z_PK, ZPARTNERNAME, ZCONTACTJID FROM ZWACHATSESSION
           WHERE ZPARTNERNAME LIKE ? OR ZCONTACTJID LIKE ?
           ORDER BY ZMESSAGECOUNTER DESC LIMIT 1""",
        (f"%{name_or_jid}%", f"%{name_or_jid}%")).fetchone()


def _message_row(r: sqlite3.Row) -> dict[str, Any]:
    return {"from_me": bool(r["ZISFROMME"]), "sender": r["sender"],
            "text": r["ZTEXT"], "date": coredata_to_iso(r["ZMESSAGEDATE"]),
            "type": r["ZMESSAGETYPE"], "starred": bool(r["ZSTARRED"])}


def get_chat(name_or_jid: str, limit: int = 50,
             path: pathlib.Path = DB_PATH) -> dict[str, Any]:
    conn = _connect(path)
    try:
        session = _resolve_session(conn, name_or_jid)
        if not session:
            return {"error": f"No chat matching '{name_or_jid}'.", "messages": []}
        rows = conn.execute(
            """SELECT m.ZISFROMME, m.ZTEXT, m.ZMESSAGEDATE, m.ZMESSAGETYPE, m.ZSTARRED,
                      COALESCE(gm.ZCONTACTNAME, gm.ZFIRSTNAME, m.ZPUSHNAME) sender
               FROM ZWAMESSAGE m LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
               WHERE m.ZCHATSESSION = ?
               ORDER BY m.ZSORT DESC LIMIT ?""",
            (session["Z_PK"], int(limit))).fetchall()
        messages = [_message_row(r) for r in reversed(rows)]
        return {"chat": session["ZPARTNERNAME"], "jid": session["ZCONTACTJID"],
                "returned": len(messages), "messages": messages}
    finally:
        conn.close()


def search_messages(text: str, contact: str = "", limit: int = 50,
                    path: pathlib.Path = DB_PATH) -> list[dict[str, Any]]:
    clauses = ["m.ZTEXT LIKE ?"]
    params: list[Any] = [f"%{text}%"]
    if contact:
        clauses.append("(s.ZPARTNERNAME LIKE ? OR s.ZCONTACTJID LIKE ?)")
        params += [f"%{contact}%", f"%{contact}%"]
    params.append(int(limit))
    conn = _connect(path)
    try:
        rows = conn.execute(
            f"""SELECT m.ZISFROMME, m.ZTEXT, m.ZMESSAGEDATE, m.ZMESSAGETYPE, m.ZSTARRED,
                       s.ZPARTNERNAME sender
                FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON m.ZCHATSESSION = s.Z_PK
                WHERE {' AND '.join(clauses)}
                ORDER BY m.ZMESSAGEDATE DESC LIMIT ?""", params).fetchall()
        return [{"chat": r["sender"], **_message_row(r)} for r in rows]
    finally:
        conn.close()


def person_stats(name_or_jid: str, path: pathlib.Path = DB_PATH) -> dict[str, Any]:
    conn = _connect(path)
    try:
        session = _resolve_session(conn, name_or_jid)
        if not session:
            return {"error": f"No chat matching '{name_or_jid}'.", "total": 0}
        row = conn.execute(
            """SELECT COUNT(*) total, SUM(ZISFROMME) sent,
                      MIN(ZMESSAGEDATE) first, MAX(ZMESSAGEDATE) last
               FROM ZWAMESSAGE WHERE ZCHATSESSION = ?""",
            (session["Z_PK"],)).fetchone()
        total = row["total"] or 0
        sent = row["sent"] or 0
        return {"chat": session["ZPARTNERNAME"], "jid": session["ZCONTACTJID"],
                "total": total, "sent": sent, "received": total - sent,
                "first_message": coredata_to_iso(row["first"]),
                "last_message": coredata_to_iso(row["last"])}
    finally:
        conn.close()
