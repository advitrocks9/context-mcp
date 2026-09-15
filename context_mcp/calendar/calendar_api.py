"""Outlook and Google Calendar reads and edits; Google reuses the Gmail refresh token."""

from __future__ import annotations

import datetime
import urllib.parse
from typing import Any

from context_mcp.mail import gmail
from context_mcp.mail import outlook
from context_mcp.common import http, parallel_map

OUTLOOK = "https://outlook.office.com/api/v2.0/me"
GOOGLE = "https://www.googleapis.com/calendar/v3"
_RESPONSES = {"accept": "accepted", "decline": "declined", "tentative": "tentative"}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _window(days: int, start: str, end: str) -> tuple[datetime.datetime, datetime.datetime]:
    lo = datetime.datetime.fromisoformat(start) if start else _now()
    if lo.tzinfo is None:
        lo = lo.replace(tzinfo=datetime.timezone.utc)
    hi = datetime.datetime.fromisoformat(end) if end else lo + datetime.timedelta(days=days)
    if hi.tzinfo is None:
        hi = hi.replace(tzinfo=datetime.timezone.utc)
    return lo, hi


def _o_auth() -> dict[str, str]:
    return {"Authorization": "Bearer " + outlook.get_token(), "Accept": "application/json",
            "Prefer": 'outlook.timezone="UTC"'}


def _g_auth() -> dict[str, str]:
    return {"Authorization": "Bearer " + gmail.get_token()}


def _o_event(e: dict[str, Any]) -> dict[str, Any]:
    org = ((e.get("Organizer") or {}).get("EmailAddress") or {})
    return {
        "provider": "outlook",
        "id": e.get("Id"),
        "subject": e.get("Subject"),
        "start": (e.get("Start") or {}).get("DateTime", "")[:16],
        "end": (e.get("End") or {}).get("DateTime", "")[:16],
        "all_day": bool(e.get("IsAllDay")),
        "organizer": org.get("Address", ""),
        "location": (e.get("Location") or {}).get("DisplayName", ""),
        "response": (e.get("ResponseStatus") or {}).get("Response", ""),
        "online_meeting": (e.get("OnlineMeeting") or {}).get("JoinUrl", "") if e.get("OnlineMeeting") else "",
    }


def _g_event(e: dict[str, Any]) -> dict[str, Any]:
    start = e.get("start") or {}
    end = e.get("end") or {}
    self_status = ""
    for a in e.get("attendees") or []:
        if a.get("self"):
            self_status = a.get("responseStatus", "")
    return {
        "provider": "gmail",
        "id": e.get("id"),
        "subject": e.get("summary"),
        "start": (start.get("dateTime") or start.get("date") or "")[:16],
        "end": (end.get("dateTime") or end.get("date") or "")[:16],
        "all_day": "date" in start,
        "organizer": (e.get("organizer") or {}).get("email", ""),
        "location": e.get("location", ""),
        "response": self_status,
        "online_meeting": e.get("hangoutLink", ""),
    }


def list_events(provider: str, days: int = 14, start: str = "", end: str = "",
                query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    lo, hi = _window(days, start, end)
    if provider == "outlook":
        params = urllib.parse.urlencode({
            "startDateTime": lo.isoformat(),
            "endDateTime": hi.isoformat(),
            "$select": "Subject,Start,End,Location,Organizer,ResponseStatus,IsAllDay,OnlineMeeting",
            "$orderby": "Start/DateTime",
            "$top": int(limit),
        })
        rows = http("GET", f"{OUTLOOK}/calendarview?{params}", _o_auth()).get("value", [])
        events = [_o_event(e) for e in rows]
        if query:
            events = [e for e in events if query.lower() in (e["subject"] or "").lower()]
        return events
    query_params = {"timeMin": lo.isoformat(), "timeMax": hi.isoformat(), "singleEvents": "true",
                    "orderBy": "startTime", "maxResults": int(limit)}
    if query:
        query_params["q"] = query
    params = urllib.parse.urlencode(query_params)
    rows = http("GET", f"{GOOGLE}/calendars/primary/events?{params}", _g_auth()).get("items", [])
    return [_g_event(e) for e in rows]


def search_events(provider: str, query: str, back_days: int = 30, ahead_days: int = 180,
                  limit: int = 50) -> list[dict[str, Any]]:
    now = _now()
    return list_events(provider, start=(now - datetime.timedelta(days=back_days)).isoformat(),
                       end=(now + datetime.timedelta(days=ahead_days)).isoformat(),
                       query=query, limit=limit)


def get_event(provider: str, event_id: str) -> dict[str, Any]:
    if provider == "outlook":
        return _o_event(http("GET", f"{OUTLOOK}/events/{event_id}", _o_auth()))
    return _g_event(http("GET", f"{GOOGLE}/calendars/primary/events/{event_id}", _g_auth()))


def respond_event(provider: str, event_id: str, response: str, comment: str = "",
                  notify: bool = True) -> dict[str, Any]:
    if response not in _RESPONSES:
        raise ValueError("response must be 'accept', 'decline', or 'tentative'.")
    if provider == "outlook":
        action = {"accept": "accept", "decline": "decline", "tentative": "tentativelyaccept"}[response]
        http("POST", f"{OUTLOOK}/events/{event_id}/{action}", _o_auth(),
             {"Comment": comment, "SendResponse": bool(notify)})
        return {"ok": True, "response": response}
    event = http("GET", f"{GOOGLE}/calendars/primary/events/{event_id}", _g_auth())
    attendees = event.get("attendees") or []
    for a in attendees:
        if a.get("self"):
            a["responseStatus"] = _RESPONSES[response]
    send = "all" if notify else "none"
    http("PATCH", f"{GOOGLE}/calendars/primary/events/{event_id}?sendUpdates={send}",
         _g_auth(), {"attendees": attendees})
    return {"ok": True, "response": response}


def create_event(provider: str, subject: str, start: str, end: str, location: str = "",
                 body: str = "", attendees: list[str] | None = None, all_day: bool = False,
                 notify: bool = False) -> dict[str, Any]:
    if provider == "outlook":
        payload: dict[str, Any] = {
            "Subject": subject,
            "Start": {"DateTime": start, "TimeZone": "UTC"},
            "End": {"DateTime": end, "TimeZone": "UTC"},
            "IsAllDay": all_day,
        }
        if location:
            payload["Location"] = {"DisplayName": location}
        if body:
            payload["Body"] = {"ContentType": "Text", "Content": body}
        if attendees:
            payload["Attendees"] = [{"EmailAddress": {"Address": a.strip()}, "Type": "Required"}
                                    for a in attendees if a.strip()]
        created = http("POST", f"{OUTLOOK}/events", _o_auth(), payload)
        return {"ok": True, "id": created.get("Id")}
    payload = {
        "summary": subject,
        "start": {"date": start[:10]} if all_day else {"dateTime": start},
        "end": {"date": end[:10]} if all_day else {"dateTime": end},
    }
    if location:
        payload["location"] = location
    if body:
        payload["description"] = body
    if attendees:
        payload["attendees"] = [{"email": a.strip()} for a in attendees if a.strip()]
    send = "all" if notify else "none"
    created = http("POST", f"{GOOGLE}/calendars/primary/events?sendUpdates={send}", _g_auth(), payload)
    return {"ok": True, "id": created.get("id")}


def update_event(provider: str, event_id: str, subject: str = "", start: str = "", end: str = "",
                 location: str = "", body: str = "", notify: bool = False) -> dict[str, Any]:
    if provider == "outlook":
        patch: dict[str, Any] = {}
        if subject:
            patch["Subject"] = subject
        if start:
            patch["Start"] = {"DateTime": start, "TimeZone": "UTC"}
        if end:
            patch["End"] = {"DateTime": end, "TimeZone": "UTC"}
        if location:
            patch["Location"] = {"DisplayName": location}
        if body:
            patch["Body"] = {"ContentType": "Text", "Content": body}
        http("PATCH", f"{OUTLOOK}/events/{event_id}", _o_auth(), patch)
        return {"ok": True, "id": event_id}
    patch = {}
    if subject:
        patch["summary"] = subject
    if start:
        patch["start"] = {"dateTime": start}
    if end:
        patch["end"] = {"dateTime": end}
    if location:
        patch["location"] = location
    if body:
        patch["description"] = body
    send = "all" if notify else "none"
    http("PATCH", f"{GOOGLE}/calendars/primary/events/{event_id}?sendUpdates={send}", _g_auth(), patch)
    return {"ok": True, "id": event_id}


BULK_CONFIRM_THRESHOLD = 25


def delete_event(provider: str, event_id: str, notify: bool = False) -> dict[str, Any]:
    if not event_id or event_id.strip() in {"", "*", "all"}:
        raise ValueError("delete_event needs one concrete event id, never a wildcard.")
    if provider == "outlook":
        http("DELETE", f"{OUTLOOK}/events/{event_id}", _o_auth())
        return {"ok": True, "deleted": event_id}
    send = "all" if notify else "none"
    http("DELETE", f"{GOOGLE}/calendars/primary/events/{event_id}?sendUpdates={send}", _g_auth())
    return {"ok": True, "deleted": event_id}


def bulk_delete(provider: str, start: str = "", end: str = "", query: str = "",
                dry_run: bool = True, confirm: bool = False, notify: bool = False,
                limit: int = 100) -> dict[str, Any]:
    if not (start or end or query):
        raise ValueError("bulk_delete refuses to match every event: pass a date range or query.")
    lo = start or _now().isoformat()
    hi = end or (_now() + datetime.timedelta(days=1400)).isoformat()
    matches = list_events(provider, start=lo, end=hi, query=query, limit=limit)
    sample = [{"id": e["id"], "start": e["start"], "subject": e["subject"]} for e in matches[:10]]
    if dry_run:
        return {"provider": provider, "dry_run": True, "matched": len(matches), "sample": sample,
                "next_step": "Review, then re-run with dry_run=false to delete these events."}
    if len(matches) > BULK_CONFIRM_THRESHOLD and not confirm:
        return {"provider": provider, "dry_run": False, "blocked": True, "matched": len(matches),
                "sample": sample,
                "reason": f"{len(matches)} events exceeds the {BULK_CONFIRM_THRESHOLD}-event safety cap. "
                          "Re-run with confirm=true to proceed."}
    def remove(e: dict[str, Any]) -> Any:
        try:
            delete_event(provider, e["id"], notify=notify)
            return e["id"]
        except Exception as exc:
            return {"id": e["id"], "error": str(exc)}

    deleted = parallel_map(remove, matches)
    return {"provider": provider, "dry_run": False, "requested": len(matches),
            "deleted": sum(1 for d in deleted if isinstance(d, str)), "results": deleted}
