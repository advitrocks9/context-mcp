"""Shared MCP annotations and tool registration used across every domain's tools."""

from __future__ import annotations

import functools
from typing import Any, Callable

import anyio.to_thread
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
READ_LOCAL = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
REVERSIBLE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
IDEMPOTENT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)


def threaded(mcp: FastMCP) -> Callable[..., Callable[[Callable[..., Any]], Any]]:
    """mcp.tool for sync bodies: runs them in a worker thread so one call cannot stall the server."""
    def tool(**kwargs: Any) -> Callable[[Callable[..., Any]], Any]:
        def register(fn: Callable[..., Any]) -> Any:
            @functools.wraps(fn)
            async def run(*args: Any, **params: Any) -> Any:
                return await anyio.to_thread.run_sync(functools.partial(fn, *args, **params))
            return mcp.tool(**kwargs)(run)
        return register
    return tool
