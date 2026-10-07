"""Soft-loading: collapse each domain to one dispatcher tool.

A caller sees one tool per service (mail, calendar, whatsapp, linkedin, scientia,
panopto, canvas, ed, labts, imperial) instead of the full set. Each dispatcher
lists its operations on `op="help"` and their argument schema on `op="schema"`,
then runs an operation with `op="<name>", params={...}`.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

import anyio.to_thread
from mcp.server.fastmcp import Context, FastMCP

from context_mcp.toolkit import READ, REVERSIBLE


def _help(ops: dict[str, str]) -> dict[str, Any]:
    return {"ops": ops, "usage": "call again with op=<name> and params={...}; op='schema' for argument shapes"}


def _signature(fn: Callable[..., Any]) -> dict[str, Any]:
    out = {}
    for name, param in inspect.signature(fn).parameters.items():
        if name in ("self", "ctx"):
            continue
        out[name] = {"required": param.default is inspect.Parameter.empty,
                     "default": None if param.default is inspect.Parameter.empty else param.default}
    return out


def service(mcp: FastMCP, name: str, title: str, ops: dict[str, Callable[..., Any]]) -> None:
    summaries = {op: (fn.__doc__ or "").strip().split("\n")[0] for op, fn in ops.items()}

    async def dispatcher(op: str = "", params: dict[str, Any] | None = None) -> Any:
        if op in ("", "help", "ops"):
            return _help(summaries)
        if op == "schema":
            return {op: _signature(fn) for op, fn in ops.items()}
        fn = ops.get(op)
        if fn is None:
            return {"error": f"unknown op '{op}'", "ops": sorted(ops)}
        return await anyio.to_thread.run_sync(functools.partial(fn, **(params or {})))

    dispatcher.__name__ = name
    dispatcher.__doc__ = f"{title}. Read-only. Operations: {', '.join(sorted(ops))}. Call op='help' or op='schema'."
    mcp.add_tool(dispatcher, name=name, title=title, description=dispatcher.__doc__, annotations=READ)


def fold(mcp: FastMCP, name: str, title: str) -> None:
    manager = mcp._tool_manager
    members = {full[len(name) + 1:]: full for full in list(manager._tools) if full.startswith(name + "_")}
    if not members:
        return
    tools = {op: manager.get_tool(full) for op, full in members.items()}
    summaries = {op: (t.description or "").split("\n")[0] for op, t in tools.items()}
    read_only = all((t.annotations and t.annotations.readOnlyHint) for t in tools.values())

    async def dispatcher(op: str = "", params: dict[str, Any] | None = None,
                         ctx: Context | None = None) -> Any:
        if op in ("", "help", "ops"):
            return _help(summaries)
        if op == "schema":
            return {op: t.parameters for op, t in tools.items()}
        member = tools.get(op)
        if member is None:
            return {"error": f"unknown op '{op}'", "ops": sorted(members)}
        return await member.run(params or {}, context=ctx, convert_result=False)

    for full in members.values():
        manager.remove_tool(full)
    dispatcher.__name__ = name
    verb = "Read-only." if read_only else "Some operations write (drafts, moves, RSVPs); they never auto-send."
    dispatcher.__doc__ = f"{title}. {verb} Operations: {', '.join(sorted(members))}. Call op='help' or op='schema'."
    mcp.add_tool(dispatcher, name=name, title=title, description=dispatcher.__doc__,
                 annotations=READ if read_only else REVERSIBLE)
