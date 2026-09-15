"""Gmail backend over the OAuth refresh-token flow, scoped to gmail.modify."""

from __future__ import annotations

import base64
import mimetypes
import threading
import time
import urllib.parse
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from context_mcp.common import audit, http, load_env, parallel_map
from context_mcp.mail import cache

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
_cache: dict[str, str | float | None] = {"token": None, "exp": 0.0}
_cache_lock = threading.Lock()


def _creds() -> tuple[str, str, str]:
    env = load_env()
    client_id = env.get("GMAIL_CLIENT_ID")
    client_secret = env.get("GMAIL_CLIENT_SECRET")
    refresh_token = env.get("GMAIL_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Gmail is not configured: set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, "
            "and GMAIL_REFRESH_TOKEN in .env."
        )
    return client_id, client_secret, refresh_token


def _cached_token() -> str | None:
    token = _cache["token"]
    expires_at = float(_cache["exp"] or 0)
    return token if isinstance(token, str) and expires_at - time.time() > 120 else None


def get_token() -> str:
    token = _cached_token()
    if token:
        return token
    with _cache_lock:
        token = _cached_token()
        if token:
            return token
        client_id, client_secret, refresh_token = _creds()
        response = http(
            "POST",
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            form=True,
        )
        _cache["token"] = str(response["access_token"])
        _cache["exp"] = time.time() + float(response.get("expires_in", 3600))
        return str(_cache["token"])


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer " + get_token()}


_FOLDER_LABEL: dict[str, str | None] = {
    "inbox": "INBOX",
    "sent": "SENT",
    "drafts": "DRAFT",
    "draft": "DRAFT",
    "trash": "TRASH",
    "deleted": "TRASH",
    "spam": "SPAM",
    "junk": "SPAM",
    "archive": None,
    "starred": "STARRED",
    "important": "IMPORTANT",
    "unread": "UNREAD",
    "all": None,
    "allitems": None,
}


_label_memo: list[dict[str, Any]] | None = None


def _labels() -> list[dict[str, Any]]:
    global _label_memo
    if _label_memo is None:
        _label_memo = http("GET", API + "/labels", _auth()).get("labels", [])
    return _label_memo


def _labels_changed() -> None:
    global _label_memo
    _label_memo = None


def create_folder(name: str) -> dict[str, Any]:
    for label in _labels():
        if str(label.get("name") or "").lower() == name.lower():
            return {"ok": True, "id": label["id"], "name": name, "created": False}
    created = http("POST", API + "/labels", _auth(),
                   {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"})
    _labels_changed()
    return {"ok": True, "id": created.get("id"), "name": created.get("name"), "created": True}


def create_label(name: str) -> dict[str, Any]:
    return create_folder(name)


def _label_id(name: str | None) -> str | None:
    if not name:
        return None
    key = name.lower()
    if key in _FOLDER_LABEL:
        return _FOLDER_LABEL[key]
    for label in _labels():
        if str(label.get("name") or "").lower() == name.lower():
            return str(label["id"])
    return name


def _hdr(headers: list[dict[str, Any]], name: str) -> str:
    for header in headers:
        if str(header.get("name", "")).lower() == name.lower():
            return str(header.get("value", ""))
    return ""


def _has_attachment(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    if payload.get("filename") or (payload.get("body") or {}).get("attachmentId"):
        return True
    return any(_has_attachment(part) for part in payload.get("parts", []) or [])


def _norm(message: dict[str, Any]) -> dict[str, Any]:
    headers = (message.get("payload") or {}).get("headers", [])
    labels = message.get("labelIds", []) or []
    list_unsubscribe = _hdr(headers, "List-Unsubscribe")
    return {
        "provider": "gmail",
        "id": message["id"],
        "thread_id": message.get("threadId"),
        "from": _hdr(headers, "From"),
        "to": _hdr(headers, "To"),
        "cc": _hdr(headers, "Cc"),
        "subject": _hdr(headers, "Subject"),
        "date": _hdr(headers, "Date"),
        "unread": "UNREAD" in labels,
        "has_attachment": _has_attachment(message.get("payload")),
        "importance": "important" if "IMPORTANT" in labels else "",
        "list_unsubscribe": list_unsubscribe,
        "list_unsubscribe_post": _hdr(headers, "List-Unsubscribe-Post") if list_unsubscribe else "",
        "snippet": str(message.get("snippet") or "")[:200],
        "folders": labels,
    }


def list_folders() -> list[dict[str, Any]]:
    return [{"id": label["id"], "name": label.get("name")} for label in _labels()]


_METADATA = ("?format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Cc"
             "&metadataHeaders=Subject&metadataHeaders=Date"
             "&metadataHeaders=List-Unsubscribe&metadataHeaders=List-Unsubscribe-Post")


def _metadata(mid: str) -> dict[str, Any]:
    return _norm(http("GET", f"{API}/messages/{mid}{_METADATA}", _auth()))


def _hydrate(ids: list[str]) -> dict[str, dict[str, Any]]:
    cached = cache.get(ids)
    fetched = {m["id"]: m for m in parallel_map(_metadata, [i for i in ids if i not in cached])}
    cache.put(fetched.values())
    return {**fetched, **cached}


def _profile_history_id() -> str:
    return str(http("GET", API + "/profile", _auth())["historyId"])


def _sync() -> None:
    start = cache.history_id()
    if not start:
        cache.set_history_id(_profile_history_id())
        return
    records: list[dict[str, Any]] = []
    page = ""
    try:
        while True:
            params: dict[str, Any] = {"startHistoryId": start, "maxResults": 500}
            if page:
                params["pageToken"] = page
            data = http("GET", f"{API}/history?{urllib.parse.urlencode(params)}", _auth())
            records += data.get("history") or []
            page = data.get("nextPageToken", "")
            if not page:
                cache.apply_history(records)
                cache.set_history_id(data["historyId"])
                return
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
    cache.forget_all()
    cache.set_history_id(_profile_history_id())


def list_messages_page(
    folder: str = "inbox",
    query: str = "",
    unread_only: bool = False,
    limit: int = 15,
    cursor: str = "",
) -> dict[str, Any]:
    params = {"maxResults": int(limit)}
    gmail_query = query or ""
    if unread_only:
        gmail_query = (gmail_query + " is:unread").strip()
    if folder and folder.lower() == "archive":
        gmail_query = (gmail_query + " -in:inbox -in:sent -in:drafts -in:trash -in:spam").strip()
    if gmail_query:
        params["q"] = gmail_query
    label_id = _label_id(folder)
    if label_id:
        params["labelIds"] = label_id
    if cursor:
        params["pageToken"] = cursor

    listed, _ = parallel_map(lambda call: call(), [
        lambda: http("GET", f"{API}/messages?{urllib.parse.urlencode(params)}", _auth()),
        _sync,
    ])
    ids = [item["id"] for item in (listed.get("messages") or [])[: int(limit)]]
    known = _hydrate(ids)
    return {
        "provider": "gmail",
        "messages": [known[i] for i in ids],
        "next_cursor": listed.get("nextPageToken", ""),
        "result_size_estimate": listed.get("resultSizeEstimate", len(ids)),
    }


def _extract_body(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    if str(payload.get("mimeType", "")).startswith("text/plain"):
        data = (payload.get("body") or {}).get("data")
        if data:
            return base64.urlsafe_b64decode(str(data) + "==").decode("utf-8", "ignore")
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""


def get_message(mid: str, body: bool = True) -> dict[str, Any]:
    message = http("GET", f"{API}/messages/{mid}?format={'full' if body else 'metadata'}", _auth())
    headers = (message.get("payload") or {}).get("headers", [])
    result = _norm(message)
    result["to"] = _hdr(headers, "To")
    if body:
        result["body"] = _extract_body(message.get("payload"))
    return result


def _current_labels(mid: str) -> list[str]:
    known = cache.labels_of(mid)
    if known is not None:
        return known
    labels = http("GET", f"{API}/messages/{mid}?format=minimal", _auth()).get("labelIds", []) or []
    return [str(label) for label in labels]


def _modify(mid: str, add: list[str] | None = None, remove: list[str] | None = None) -> dict[str, Any]:
    done = http("POST", f"{API}/messages/{mid}/modify", _auth(),
                {"addLabelIds": add or [], "removeLabelIds": remove or []})
    cache.forget([mid])
    return done



def _before_labels(ids: list[str]) -> dict[str, list[str]]:
    known = _hydrate(ids)
    return {mid: (known[mid].get("folders") or []) for mid in ids}


def batch_modify(ids: list[str], add: list[str] | None = None, remove: list[str] | None = None) -> None:
    if not (add or remove):
        raise ValueError("batch_modify needs at least one label to add or remove.")
    for start in range(0, len(ids), 1000):
        http("POST", API + "/messages/batchModify", _auth(),
             {"ids": ids[start:start + 1000], "addLabelIds": add or [], "removeLabelIds": remove or []})
    cache.forget(ids)


def batch_move(ids: list[str], to_folder: str) -> None:
    dest = _label_id(to_folder)
    before = _before_labels(ids)
    batch_modify(ids, add=[dest] if dest else None, remove=["INBOX"])
    for mid in ids:
        audit({"provider": "gmail", "op": "move", "id": mid, "to": to_folder, "dest": dest,
               "before_labels": before[mid]})


def batch_tag(ids: list[str], labels: list[str] | str, mode: str = "add") -> None:
    if mode not in {"add", "remove"}:
        raise ValueError("mode must be 'add' or 'remove'.")
    names = labels if isinstance(labels, list) else [labels]
    resolved = [label_id for label_id in (_label_id(name) for name in names) if label_id]
    before = _before_labels(ids)
    batch_modify(ids, add=resolved if mode == "add" else None,
                 remove=None if mode == "add" else resolved)
    for mid in ids:
        audit({"provider": "gmail", "op": "tag", "id": mid, "mode": mode, "labels": resolved,
               "before_labels": before[mid]})


def batch_flag(ids: list[str], on: bool = True) -> None:
    before = _before_labels(ids)
    batch_modify(ids, add=["STARRED"] if on else None, remove=None if on else ["STARRED"])
    for mid in ids:
        audit({"provider": "gmail", "op": "flag", "id": mid, "on": bool(on),
               "before_labels": before[mid]})


def batch_mark_read(ids: list[str], read: bool = True) -> None:
    before = _before_labels(ids)
    batch_modify(ids, add=None if read else ["UNREAD"], remove=["UNREAD"] if read else None)
    for mid in ids:
        audit({"provider": "gmail", "op": "mark_read", "id": mid, "read": bool(read),
               "before_labels": before[mid]})


def batch_mark_spam(ids: list[str], spam: bool = True) -> None:
    before = _before_labels(ids)
    batch_modify(ids, add=["SPAM"] if spam else ["INBOX"], remove=["INBOX"] if spam else ["SPAM"])
    for mid in ids:
        audit({"provider": "gmail", "op": "mark_spam", "id": mid, "spam": bool(spam),
               "before_labels": before[mid]})


def _restore_labels(mid: str, labels: list[str]) -> None:
    current = set(_current_labels(mid))
    desired = set(labels)
    _modify(mid, add=sorted(desired - current), remove=sorted(current - desired))


def move_message(mid: str, to_folder: str) -> dict[str, Any]:
    dest = _label_id(to_folder)
    before = _current_labels(mid)
    _modify(mid, add=[dest] if dest else [], remove=["INBOX"])
    audit({"provider": "gmail", "op": "move", "id": mid, "to": to_folder, "dest": dest, "before_labels": before})
    return {"ok": True, "moved_to": to_folder}


def tag_message(mid: str, labels: list[str] | str, mode: str = "add") -> dict[str, Any]:
    if mode not in {"add", "remove"}:
        raise ValueError("mode must be 'add' or 'remove'.")
    label_names = labels if isinstance(labels, list) else [labels]
    ids = [label_id for label_id in (_label_id(label) for label in label_names) if label_id]
    before = _current_labels(mid)
    if mode == "remove":
        _modify(mid, remove=ids)
    else:
        _modify(mid, add=ids)
    audit({"provider": "gmail", "op": "tag", "id": mid, "mode": mode, "labels": ids, "before_labels": before})
    return {"ok": True, "labels": ids, "mode": mode}


def mark_read(mid: str, read: bool = True) -> dict[str, Any]:
    before = _current_labels(mid)
    _modify(mid, remove=["UNREAD"] if read else None, add=None if read else ["UNREAD"])
    audit({"provider": "gmail", "op": "mark_read", "id": mid, "read": bool(read), "before_labels": before})
    return {"ok": True, "read": bool(read)}


def flag_message(mid: str, on: bool = True) -> dict[str, Any]:
    before = _current_labels(mid)
    _modify(mid, add=["STARRED"] if on else None, remove=None if on else ["STARRED"])
    audit({"provider": "gmail", "op": "flag", "id": mid, "on": bool(on), "before_labels": before})
    return {"ok": True, "starred": bool(on)}


def trash_message(mid: str) -> dict[str, Any]:
    before = _current_labels(mid)
    http("POST", f"{API}/messages/{mid}/trash", _auth())
    cache.forget([mid])
    audit({"provider": "gmail", "op": "trash", "id": mid, "before_labels": before})
    return {"ok": True, "trashed": True}


def mark_spam(mid: str, spam: bool = True) -> dict[str, Any]:
    before = _current_labels(mid)
    if spam:
        _modify(mid, add=["SPAM"], remove=["INBOX"])
    else:
        _modify(mid, add=["INBOX"], remove=["SPAM"])
    audit({"provider": "gmail", "op": "mark_spam", "id": mid, "spam": bool(spam), "before_labels": before})
    return {"ok": True, "spam": bool(spam)}


def untrash_message(mid: str) -> dict[str, Any]:
    http("POST", f"{API}/messages/{mid}/untrash", _auth())
    _modify(mid, add=["INBOX"])
    audit({"provider": "gmail", "op": "untrash", "id": mid})
    return {"ok": True, "untrashed": True}


def delete_label(name: str) -> dict[str, Any]:
    label_id = _label_id(name)
    if not label_id or label_id in set(_FOLDER_LABEL.values()) or label_id.isupper():
        raise ValueError(f"'{name}' is a system label and cannot be deleted.")
    http("DELETE", f"{API}/labels/{label_id}", _auth())
    _labels_changed()
    return {"ok": True, "deleted": name}


def rename_label(name: str, new_name: str) -> dict[str, Any]:
    label_id = _label_id(name)
    if not label_id or label_id.isupper():
        raise ValueError(f"'{name}' is a system label and cannot be renamed.")
    http("PATCH", f"{API}/labels/{label_id}", _auth(), {"name": new_name})
    _labels_changed()
    return {"ok": True, "renamed": new_name}


def list_filters() -> list[dict[str, Any]]:
    return http("GET", f"{API}/settings/filters", _auth()).get("filter", [])


def create_filter(criteria: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    created = http("POST", f"{API}/settings/filters", _auth(), {"criteria": criteria, "action": action})
    audit({"provider": "gmail", "op": "create_filter", "id": created.get("id")})
    return {"ok": True, "id": created.get("id"), "criteria": criteria, "action": action}


def label_id_for_filter(name: str) -> str | None:
    return _label_id(name)


def delete_filter(filter_id: str) -> dict[str, Any]:
    http("DELETE", f"{API}/settings/filters/{filter_id}", _auth())
    return {"ok": True, "deleted": filter_id}


def create_draft(
    to: str, subject: str, body: str, cc: str = "", attachments: list[str] | None = None
) -> dict[str, Any]:
    em = EmailMessage()
    em["To"] = to
    if cc:
        em["Cc"] = cc
    em["Subject"] = subject
    em.set_content(body)
    names: list[str] = []
    for path in attachments or []:
        p = Path(path).expanduser()
        ctype, _ = mimetypes.guess_type(p.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        em.add_attachment(
            p.read_bytes(), maintype=maintype, subtype=subtype or "octet-stream", filename=p.name
        )
        names.append(p.name)
    raw = base64.urlsafe_b64encode(em.as_bytes()).decode()
    r = http("POST", f"{API}/drafts", _auth(), {"message": {"raw": raw}})
    audit({"provider": "gmail", "op": "create_draft", "id": r.get("id"), "subject": subject, "attachments": names})
    return {"ok": True, "draft_id": r.get("id"), "attachments": names}


def undo(e: dict[str, Any]) -> bool:
    op, mid = e.get("op"), e.get("id")
    if not isinstance(mid, str):
        return False
    if op == "trash":
        http("POST", f"{API}/messages/{mid}/untrash", _auth())
        if e.get("before_labels"):
            _restore_labels(mid, e["before_labels"])
        return True
    if op == "move":
        _restore_labels(mid, e.get("before_labels", ["INBOX"]))
        return True
    if op == "flag":
        _restore_labels(mid, e.get("before_labels", []))
        return True
    if op == "mark_read":
        _restore_labels(mid, e.get("before_labels", []))
        return True
    if op == "tag":
        _restore_labels(mid, e.get("before_labels", []))
        return True
    if op == "mark_spam":
        _restore_labels(mid, e.get("before_labels", []))
        return True
    return False
