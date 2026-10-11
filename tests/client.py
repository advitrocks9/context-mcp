import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import server

_loop = asyncio.new_event_loop()


def tools() -> dict[str, Any]:
    return {t.name: t for t in _loop.run_until_complete(server.mcp.list_tools())}


def _parse(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def raw(tool: str, op: str, **params: Any) -> list[Any]:
    blocks = _loop.run_until_complete(server.mcp.call_tool(tool, {"op": op, "params": params}))
    return [_parse(b.text) for b in blocks]


def call(tool: str, op: str, **params: Any) -> list[Any]:
    try:
        rows = raw(tool, op, **params)
    except ToolError as exc:
        rows = [{"error": str(exc)}]
    for row in rows:
        if isinstance(row, dict) and (row.get("error") or row.get("errors")):
            pytest.fail(f"{tool}.{op} failed: {row.get('error') or row.get('errors')}", pytrace=False)
    return rows


def one(tool: str, op: str, **params: Any) -> dict[str, Any]:
    rows = call(tool, op, **params)
    assert len(rows) == 1 and isinstance(rows[0], dict), f"{tool}.{op} expected one object, got {rows!r:.200}"
    return rows[0]


def assert_download(result: dict[str, Any]) -> None:
    path = Path(result["path"])
    assert path.is_file() and path.stat().st_size > 0, f"download missing or empty: {path}"
