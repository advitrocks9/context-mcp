"""Unified personal-context MCP: mail, calendar, LinkedIn, WhatsApp."""

from __future__ import annotations

import threading

from mcp.server.fastmcp import FastMCP

from context_mcp.calendar import tools as calendar_tools
from context_mcp.linkedin import tools as linkedin_tools
from context_mcp.mail import dispatch
from context_mcp.mail import tools as mail_tools
from context_mcp.whatsapp import tools as whatsapp_tools

mcp = FastMCP("context")
mail_tools.register(mcp)
calendar_tools.register(mcp)
linkedin_tools.register(mcp)
whatsapp_tools.register(mcp)


if __name__ == "__main__":
    threading.Thread(target=dispatch.prewarm, daemon=True).start()
    mcp.run()
