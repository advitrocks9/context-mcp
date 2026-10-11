"""Unified personal-context MCP: mail, calendar, LinkedIn, WhatsApp."""

from __future__ import annotations

import os
import threading

from mcp.server.fastmcp import FastMCP

from context_mcp import gateway
from context_mcp.calendar import tools as calendar_tools
from context_mcp.imperial import tools as imperial_tools
from context_mcp.linkedin import tools as linkedin_tools
from context_mcp.mail import dispatch
from context_mcp.mail import tools as mail_tools
from context_mcp.whatsapp import tools as whatsapp_tools

mcp = FastMCP("context")
mail_tools.register(mcp)
calendar_tools.register(mcp)
linkedin_tools.register(mcp)
whatsapp_tools.register(mcp)

if os.environ.get("CONTEXT_FOLD", "1") != "0":
    gateway.fold(mcp, "mail", "Mail (Gmail and Outlook)")
    gateway.fold(mcp, "calendar", "Calendar (Outlook and Google)")
    gateway.fold(mcp, "whatsapp", "WhatsApp")
    gateway.fold(mcp, "linkedin", "LinkedIn")

imperial_tools.register(mcp)


if __name__ == "__main__":
    threading.Thread(target=dispatch.prewarm, daemon=True).start()
    mcp.run()
