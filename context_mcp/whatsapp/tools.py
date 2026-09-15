"""WhatsApp tools: read-only access to the local message store."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from context_mcp.toolkit import READ_LOCAL, threaded
from context_mcp.whatsapp import db


def register(mcp: FastMCP) -> None:
    tool = threaded(mcp)

    @tool(title="WhatsApp List Chats", annotations=READ_LOCAL)
    def whatsapp_list_chats(
        limit: Annotated[int, Field(default=30, ge=1, le=200, description="Maximum chats.")] = 30,
        query: Annotated[str, Field(description="Filter by chat name or number.")] = "",
        kind: Annotated[str, Field(description="Filter: direct, group, or status.")] = "",
    ) -> list[dict[str, Any]]:
        """List recent WhatsApp chats, newest first, with unread counts and last message. Read-only."""
        return db.list_chats(limit=limit, query=query, kind=kind)

    @tool(title="WhatsApp List Contacts", annotations=READ_LOCAL)
    def whatsapp_list_contacts(
        query: Annotated[str, Field(description="Filter by name or number.")] = "",
        limit: Annotated[int, Field(default=50, ge=1, le=500, description="Maximum contacts.")] = 50,
    ) -> list[dict[str, Any]]:
        """List direct-chat contacts by message volume. Read-only."""
        return db.list_contacts(query=query, limit=limit)

    @tool(title="WhatsApp Get Chat", annotations=READ_LOCAL)
    def whatsapp_get_chat(
        name_or_jid: Annotated[str, Field(description="Chat name or jid from whatsapp_list_chats.")],
        limit: Annotated[int, Field(default=50, ge=1, le=500, description="Most recent messages to return.")] = 50,
    ) -> dict[str, Any]:
        """Read the most recent messages in one chat, oldest to newest. Read-only."""
        return db.get_chat(name_or_jid, limit=limit)

    @tool(title="WhatsApp Search Messages", annotations=READ_LOCAL)
    def whatsapp_search_messages(
        text: Annotated[str, Field(description="Text to find in message bodies.")],
        contact: Annotated[str, Field(description="Optional chat name/number to restrict to.")] = "",
        limit: Annotated[int, Field(default=50, ge=1, le=500, description="Maximum matches.")] = 50,
    ) -> list[dict[str, Any]]:
        """Search message text across all chats, newest first. Read-only."""
        return db.search_messages(text, contact=contact, limit=limit)

    @tool(title="WhatsApp Person Stats", annotations=READ_LOCAL)
    def whatsapp_person_stats(
        name_or_jid: Annotated[str, Field(description="Chat name or jid.")],
    ) -> dict[str, Any]:
        """Message totals for one chat: total, sent, received, first and last dates. Read-only."""
        return db.person_stats(name_or_jid)

    @tool(title="WhatsApp Schema", annotations=READ_LOCAL)
    def whatsapp_schema() -> dict[str, list[str]]:
        """Return the ZWA* table and column names, so whatsapp_query can be written against them. Read-only."""
        return db.schema()

    @tool(title="WhatsApp Raw Query", annotations=READ_LOCAL)
    def whatsapp_query(
        sql: Annotated[str, Field(description="A single read-only SELECT/WITH over the ZWA* tables. See whatsapp_schema.")],
        limit: Annotated[int, Field(default=200, ge=1, le=2000, description="Maximum rows.")] = 200,
    ) -> list[dict[str, Any]]:
        """Run one read-only SELECT against the WhatsApp store for questions the helpers do not cover. Writes are rejected and the connection is read-only. Read-only."""
        return db.query(sql, limit=limit)
