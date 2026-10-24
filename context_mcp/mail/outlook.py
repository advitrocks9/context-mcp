"""Outlook mail surface over the OWA REST API; tokens come from outlook_auth."""

from __future__ import annotations

import base64
import mimetypes
import urllib.parse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from context_mcp.common import HTTPError, audit, http
from context_mcp.mail.outlook_auth import drop_access, get_token

BASE = "https://outlook.office.com/api/v2.0"

batch_move = batch_tag = batch_flag = batch_mark_read = batch_mark_spam = None


def api(
    method: str, url: str, data: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None
) -> dict[str, Any]:
    token = get_token()
    try:
        return http(method, url, _headers(token, headers), data)
    except HTTPError as exc:
        if exc.status != 401:
            raise
    drop_access(token)
    return http(method, url, _headers(get_token(), headers), data)


def _headers(token: str, extra: Mapping[str, str] | None) -> dict[str, str]:
    return {"Authorization": "Bearer " + token, "Accept": "application/json", **(extra or {})}


def _recipients(rows: list[dict[str, Any]] | None) -> str:
    return ", ".join((row.get("EmailAddress") or {}).get("Address", "") for row in rows or [])


def _norm(m: dict[str, Any]) -> dict[str, Any]:
    frm = (m.get("From") or {}).get("EmailAddress") or {}
    flag = m.get("Flag") or {}
    return {
        "provider": "outlook",
        "id": m.get("Id"),
        "thread_id": m.get("ConversationId"),
        "from": f"{frm.get('Name', '')} <{frm.get('Address', '')}>".strip(),
        "to": _recipients(m.get("ToRecipients")),
        "cc": _recipients(m.get("CcRecipients")),
        "subject": m.get("Subject"),
        "date": m.get("ReceivedDateTime"),
        "unread": not m.get("IsRead", True),
        "has_attachment": bool(m.get("HasAttachments")),
        "importance": m.get("Importance") or "",
        "flag_status": flag.get("FlagStatus", ""),
        "categories": m.get("Categories") or [],
        "snippet": str(m.get("BodyPreview") or "")[:200],
        "folders": [m.get("ParentFolderId")] if m.get("ParentFolderId") else [],
    }


_WELL_KNOWN = {
    "inbox": "inbox",
    "drafts": "drafts",
    "draft": "drafts",
    "sent": "sentitems",
    "sentitems": "sentitems",
    "trash": "deleteditems",
    "deleted": "deleteditems",
    "deleteditems": "deleteditems",
    "junk": "junkemail",
    "spam": "junkemail",
    "junkemail": "junkemail",
    "archive": "archive",
}


def _folder_id(name: str) -> str:
    if not name:
        return "inbox"
    key = name.lower().replace(" ", "")
    if key in _WELL_KNOWN:
        return _WELL_KNOWN[key]
    for f in list_folders():
        if (f["name"] or "").lower() == name.lower():
            return f["id"]
    return name


def list_folders() -> list[dict[str, Any]]:
    data = api("GET", BASE + "/me/mailfolders?$top=100&$select=Id,DisplayName,UnreadItemCount,TotalItemCount")
    return [
        {
            "id": f["Id"],
            "name": f.get("DisplayName"),
            "unread": f.get("UnreadItemCount"),
            "total": f.get("TotalItemCount"),
        }
        for f in data.get("value", [])
    ]


def create_folder(name: str) -> dict[str, Any]:
    for f in list_folders():
        if (f["name"] or "").lower() == name.lower():
            return {"ok": True, "id": f["id"], "name": name, "created": False}
    r = api("POST", BASE + "/me/mailfolders", {"DisplayName": name})
    return {"ok": True, "id": r.get("Id"), "name": r.get("DisplayName"), "created": True}


def list_messages_page(
    folder: str = "inbox",
    query: str = "",
    unread_only: bool = False,
    limit: int = 15,
    cursor: str = "",
) -> dict[str, Any]:
    if cursor:
        data = api("GET", cursor)
        return {
            "provider": "outlook",
            "messages": [_norm(m) for m in data.get("value", [])],
            "next_cursor": data.get("@odata.nextLink", ""),
            "total_count": data.get("@odata.count"),
        }

    sel = "$select=Id,Subject,From,ToRecipients,CcRecipients,ReceivedDateTime,IsRead,BodyPreview,ParentFolderId,Categories,HasAttachments,Importance,ConversationId,Flag"
    top = f"$top={int(limit)}"
    if folder and folder.lower() in ("all", "allitems"):
        path = f"{BASE}/me/messages"
    else:
        path = f"{BASE}/me/mailfolders/{_folder_id(folder)}/messages"
    if query:
        qs = f"{top}&{sel}&$count=true&$search=" + urllib.parse.quote('"' + query + '"')
    else:
        parts = [top, sel, "$count=true", "$orderby=ReceivedDateTime%20desc"]
        if unread_only:
            parts.append("$filter=" + urllib.parse.quote("IsRead eq false"))
        qs = "&".join(parts)
    data = api("GET", f"{path}?{qs}")
    return {
        "provider": "outlook",
        "messages": [_norm(m) for m in data.get("value", [])],
        "next_cursor": data.get("@odata.nextLink", ""),
        "total_count": data.get("@odata.count"),
    }


def get_message(mid: str, body: bool = True) -> dict[str, Any]:
    sel = "Id,Subject,From,ToRecipients,ReceivedDateTime,IsRead,BodyPreview,ParentFolderId,Categories"
    if body:
        sel += ",Body"
    m = api("GET", f"{BASE}/me/messages/{mid}?$select={sel}")
    d = _norm(m)
    d["to"] = _recipients(m.get("ToRecipients"))
    d["categories"] = m.get("Categories") or []
    if body:
        b = m.get("Body") or {}
        d["body"] = b.get("Content", "")
        d["body_type"] = b.get("ContentType", "")
    return d


def _message_state(mid: str) -> dict[str, Any] | None:
    try:
        return api("GET", f"{BASE}/me/messages/{mid}?$select=ParentFolderId,IsRead,Categories,Flag")
    except HTTPError:
        return None


def _current_folder(mid: str) -> str | None:
    try:
        return api("GET", f"{BASE}/me/messages/{mid}?$select=ParentFolderId").get("ParentFolderId")
    except HTTPError:
        return None


def move_message(mid: str, to_folder: str) -> dict[str, Any]:
    before = _current_folder(mid)
    r = api("POST", f"{BASE}/me/messages/{mid}/move", {"DestinationId": _folder_id(to_folder)})
    audit(
        {"provider": "outlook", "op": "move", "id": mid, "new_id": r.get("Id"), "to": to_folder, "from_folder": before}
    )
    return {"ok": True, "new_id": r.get("Id"), "moved_to": to_folder}


def tag_message(mid: str, labels: list[str] | str, mode: str = "add") -> dict[str, Any]:
    if mode not in {"add", "remove", "set"}:
        raise ValueError("mode must be 'add', 'remove', or 'set'.")
    cats = labels if isinstance(labels, list) else [labels]
    m = api("GET", f"{BASE}/me/messages/{mid}?$select=Categories")
    cur = set(m.get("Categories") or [])
    if mode == "remove":
        new = cur - set(cats)
    elif mode == "set":
        new = set(cats)
    else:
        new = cur | set(cats)
    api("PATCH", f"{BASE}/me/messages/{mid}", {"Categories": sorted(new)})
    audit({"provider": "outlook", "op": "tag", "id": mid, "before": sorted(cur), "after": sorted(new)})
    return {"ok": True, "categories": sorted(new)}


def mark_read(mid: str, read: bool = True) -> dict[str, Any]:
    before = _message_state(mid)
    api("PATCH", f"{BASE}/me/messages/{mid}", {"IsRead": bool(read)})
    audit(
        {
            "provider": "outlook",
            "op": "mark_read",
            "id": mid,
            "read": bool(read),
            "before_is_read": before.get("IsRead") if before else None,
        }
    )
    return {"ok": True, "read": bool(read)}


def flag_message(mid: str, on: bool = True) -> dict[str, Any]:
    before = _message_state(mid)
    api("PATCH", f"{BASE}/me/messages/{mid}", {"Flag": {"FlagStatus": "Flagged" if on else "NotFlagged"}})
    before_flag = (before.get("Flag") or {}).get("FlagStatus") if before else None
    audit({"provider": "outlook", "op": "flag", "id": mid, "on": bool(on), "before_flag_status": before_flag})
    return {"ok": True, "flagged": bool(on)}


def trash_message(mid: str) -> dict[str, Any]:
    before = _current_folder(mid)
    r = api("POST", f"{BASE}/me/messages/{mid}/move", {"DestinationId": "deleteditems"})
    audit({"provider": "outlook", "op": "trash", "id": mid, "new_id": r.get("Id"), "from_folder": before})
    return {"ok": True, "new_id": r.get("Id"), "trashed": True}


def mark_spam(mid: str, spam: bool = True) -> dict[str, Any]:
    before = _current_folder(mid)
    dest = "junkemail" if spam else "inbox"
    r = api("POST", f"{BASE}/me/messages/{mid}/move", {"DestinationId": dest})
    audit(
        {
            "provider": "outlook",
            "op": "mark_spam",
            "id": mid,
            "new_id": r.get("Id"),
            "spam": bool(spam),
            "from_folder": before,
        }
    )
    return {"ok": True, "new_id": r.get("Id"), "spam": bool(spam)}


def untrash_message(mid: str) -> dict[str, Any]:
    before = _current_folder(mid)
    r = api("POST", f"{BASE}/me/messages/{mid}/move", {"DestinationId": "inbox"})
    audit({"provider": "outlook", "op": "untrash", "id": mid, "new_id": r.get("Id"), "from_folder": before})
    return {"ok": True, "new_id": r.get("Id"), "untrashed": True}


def _category_id(name: str) -> str | None:
    for cat in api("GET", f"{BASE}/me/MasterCategories").get("value", []):
        if (cat.get("DisplayName") or "").lower() == name.lower():
            return cat["Id"]
    return None


def create_label(name: str, color: str = "Preset0") -> dict[str, Any]:
    if _category_id(name):
        return {"ok": True, "name": name, "created": False}
    created = api("POST", f"{BASE}/me/MasterCategories", {"DisplayName": name, "Color": color})
    return {"ok": True, "id": created.get("Id"), "name": name, "created": True}


def delete_label(name: str) -> dict[str, Any]:
    cid = _category_id(name)
    if not cid:
        raise ValueError(f"No category named '{name}'.")
    api("DELETE", f"{BASE}/me/MasterCategories/{cid}")
    return {"ok": True, "deleted": name}


def rename_label(name: str, new_name: str) -> dict[str, Any]:
    for cat in api("GET", f"{BASE}/me/MasterCategories").get("value", []):
        if (cat.get("DisplayName") or "").lower() == name.lower():
            api("DELETE", f"{BASE}/me/MasterCategories/{cat['Id']}")
            api(
                "POST", f"{BASE}/me/MasterCategories", {"DisplayName": new_name, "Color": cat.get("Color") or "Preset0"}
            )
            return {"ok": True, "renamed": new_name}
    raise ValueError(f"No category named '{name}'.")


def list_filters() -> list[dict[str, Any]]:
    rules = api("GET", f"{BASE}/me/MailFolders/inbox/MessageRules").get("value", [])
    return [
        {
            "id": r.get("Id"),
            "name": r.get("DisplayName"),
            "enabled": r.get("IsEnabled"),
            "conditions": r.get("Conditions"),
            "actions": r.get("Actions"),
        }
        for r in rules
    ]


def create_filter(
    display_name: str, conditions: dict[str, Any], exceptions: dict[str, Any], actions: dict[str, Any]
) -> dict[str, Any]:
    rules = api("GET", f"{BASE}/me/MailFolders/inbox/MessageRules").get("value", [])
    sequence = max((r.get("Sequence") or 0 for r in rules), default=0) + 1
    body = {
        "DisplayName": display_name,
        "Sequence": sequence,
        "IsEnabled": True,
        "Conditions": conditions,
        "Actions": actions,
    }
    if exceptions:
        body["Exceptions"] = exceptions
    created = api("POST", f"{BASE}/me/MailFolders/inbox/MessageRules", body)
    audit({"provider": "outlook", "op": "create_filter", "id": created.get("Id")})
    return {"ok": True, "id": created.get("Id"), "name": display_name}


def delete_filter(filter_id: str) -> dict[str, Any]:
    api("DELETE", f"{BASE}/me/MailFolders/inbox/MessageRules/{filter_id}")
    return {"ok": True, "deleted": filter_id}


def create_draft(
    to: str, subject: str, body: str, cc: str = "", attachments: list[str] | None = None
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "Subject": subject,
        "Body": {"ContentType": "Text", "Content": body},
        "ToRecipients": [{"EmailAddress": {"Address": a.strip()}} for a in to.split(",") if a.strip()],
    }
    if cc:
        msg["CcRecipients"] = [{"EmailAddress": {"Address": a.strip()}} for a in cc.split(",") if a.strip()]
    names: list[str] = []
    atts: list[dict[str, Any]] = []
    for path in attachments or []:
        p = Path(path).expanduser()
        ctype, _ = mimetypes.guess_type(p.name)
        atts.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "Name": p.name,
                "ContentType": ctype or "application/octet-stream",
                "ContentBytes": base64.b64encode(p.read_bytes()).decode(),
            }
        )
        names.append(p.name)
    if atts:
        msg["Attachments"] = atts
    r = api("POST", f"{BASE}/me/messages", msg)
    audit({"provider": "outlook", "op": "create_draft", "id": r.get("Id"), "subject": subject, "attachments": names})
    return {"ok": True, "draft_id": r.get("Id"), "attachments": names}


def undo(e: dict[str, Any]) -> bool:
    op = e.get("op")
    if op in ("move", "trash", "mark_spam", "untrash"):
        nid = e.get("new_id") or e.get("id")
        api("POST", f"{BASE}/me/messages/{nid}/move", {"DestinationId": e.get("from_folder") or "inbox"})
        return True
    if op == "tag":
        api("PATCH", f"{BASE}/me/messages/{e['id']}", {"Categories": e.get("before", [])})
        return True
    if op == "flag":
        api(
            "PATCH",
            f"{BASE}/me/messages/{e['id']}",
            {"Flag": {"FlagStatus": e.get("before_flag_status") or ("NotFlagged" if e.get("on") else "Flagged")}},
        )
        return True
    if op == "mark_read":
        before_is_read = e.get("before_is_read")
        api(
            "PATCH",
            f"{BASE}/me/messages/{e['id']}",
            {"IsRead": before_is_read if isinstance(before_is_read, bool) else not e.get("read")},
        )
        return True
    return False
