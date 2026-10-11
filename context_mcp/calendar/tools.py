"""Calendar tools for Outlook and Google, dispatched by provider."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from context_mcp.calendar import calendar_api
from context_mcp.common import parallel_map
from context_mcp.toolkit import DESTRUCTIVE, READ, REVERSIBLE, threaded

Read = Annotated[Literal["gmail", "outlook", "both"], Field(description="Calendar to read. 'both' merges; mutations need a specific one.")]
Mut = Annotated[Literal["gmail", "outlook"], Field(description="Calendar that owns the event. Never 'both'.")]
Notify = Annotated[bool, Field(description="Email attendees/organizer about this change. Default false is silent.")]


def _read(fn: str, provider: str, **kwargs: Any) -> list[dict[str, Any]]:
    def call(name: str) -> list[dict[str, Any]]:
        try:
            return getattr(calendar_api, fn)(name, **kwargs)
        except Exception as exc:
            return [{"provider": name, "error": str(exc)}]

    out = [row for rows in parallel_map(call, ["gmail", "outlook"] if provider == "both" else [provider])
           for row in rows]
    out.sort(key=lambda e: e.get("start", "") or "")
    return out


def register(mcp: FastMCP) -> None:
    tool = threaded(mcp)

    @tool(title="Calendar List Events", annotations=READ)
    def calendar_list_events(provider: Read = "both",
                             days: Annotated[int, Field(default=14, ge=1, le=365)] = 14,
                             start: str = "", end: str = "", query: str = "",
                             limit: Annotated[int, Field(default=50, ge=1, le=200)] = 50) -> list[dict[str, Any]]:
        """List upcoming Outlook and/or Google events over the live API. Read-only."""
        return _read("list_events", provider, days=days, start=start, end=end, query=query, limit=limit)

    @tool(title="Calendar Search", annotations=READ)
    def calendar_search(provider: Read = "both", query: str = "",
                        back_days: Annotated[int, Field(default=30, ge=0, le=730)] = 30,
                        ahead_days: Annotated[int, Field(default=180, ge=1, le=730)] = 180,
                        limit: Annotated[int, Field(default=50, ge=1, le=200)] = 50) -> list[dict[str, Any]]:
        """Search events by keyword across a past and future window. Read-only."""
        return _read("search_events", provider, query=query, back_days=back_days, ahead_days=ahead_days, limit=limit)

    @tool(title="Calendar Get Event", annotations=READ)
    def calendar_get_event(provider: Mut, id: str) -> dict[str, Any]:
        """Read one event by provider and id. Read-only."""
        return calendar_api.get_event(provider, id)

    @tool(title="Calendar Respond", annotations=REVERSIBLE)
    def calendar_respond(provider: Mut, id: str,
                         response: Literal["accept", "decline", "tentative"],
                         comment: str = "", notify: Notify = True) -> dict[str, Any]:
        """RSVP accept, decline, or tentative to an invitation. Respond again to change it."""
        return calendar_api.respond_event(provider, id, response, comment=comment, notify=notify)

    @tool(title="Calendar Create Event", annotations=REVERSIBLE)
    def calendar_create_event(provider: Mut, subject: str, start: str, end: str,
                              location: str = "", body: str = "", attendees: list[str] | None = None,
                              all_day: bool = False, notify: Notify = False) -> dict[str, Any]:
        """Create an event. Attendees are emailed only when notify=true. Remove with calendar_delete_event."""
        return calendar_api.create_event(provider, subject, start, end, location=location, body=body,
                                         attendees=attendees or [], all_day=all_day, notify=notify)

    @tool(title="Calendar Update Event", annotations=REVERSIBLE)
    def calendar_update_event(provider: Mut, id: str, subject: str = "", start: str = "",
                              end: str = "", location: str = "", body: str = "",
                              notify: Notify = False) -> dict[str, Any]:
        """Update fields on an event you own. Attendees emailed only when notify=true."""
        return calendar_api.update_event(provider, id, subject=subject, start=start, end=end,
                                         location=location, body=body, notify=notify)

    @tool(title="Calendar Delete Event", annotations=DESTRUCTIVE)
    def calendar_delete_event(provider: Mut, id: str, notify: Notify = False) -> dict[str, Any]:
        """Delete one event by id. Not reversible; requires a concrete id, never a wildcard."""
        return calendar_api.delete_event(provider, id, notify=notify)

    @tool(title="Calendar Bulk Delete", annotations=DESTRUCTIVE)
    def calendar_bulk_delete(provider: Mut, start: str = "", end: str = "", query: str = "",
                             dry_run: bool = True, confirm: bool = False, notify: Notify = False,
                             limit: Annotated[int, Field(default=100, ge=1, le=500)] = 100) -> dict[str, Any]:
        """Preview and delete a batch of events by range or query. Not reversible; refuses to match everything, previews first, needs confirm=true past the cap."""
        return calendar_api.bulk_delete(provider, start=start, end=end, query=query,
                                        dry_run=dry_run, confirm=confirm, notify=notify, limit=limit)
