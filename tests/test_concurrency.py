import asyncio
import concurrent.futures
import json
import sqlite3
import threading
import time

import httpx
from mcp.server.fastmcp import FastMCP

import context_mcp.common as common
from context_mcp.common import http
from context_mcp.mail import cache, outlook_auth
from context_mcp.toolkit import threaded
from context_mcp.whatsapp import db


def test_concurrent_whatsapp_reads(tmp_path):
    p = tmp_path / "t.sqlite"
    seed = sqlite3.connect(p)
    seed.execute("CREATE TABLE t (a INTEGER)")
    seed.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(500)])
    seed.commit()
    seed.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: db.query("SELECT COUNT(*) n FROM t", path=p), range(64)))
    assert all(r[0]["n"] == 500 for r in results)


def test_token_state_write_is_atomic(tmp_path, monkeypatch):
    state_file = tmp_path / "outlook-token.json"
    monkeypatch.setattr(outlook_auth, "STATE", state_file)

    def writer(i):
        outlook_auth._state_save({"access": f"tok{i}", "refresh": f"r{i}", "exp": float(i)})

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(writer, range(200)))
    loaded = json.loads(state_file.read_text())
    assert loaded["access"].startswith("tok") and "exp" in loaded


def test_read_only_connection_blocks_writes(tmp_path):
    p = tmp_path / "t.sqlite"
    seed = sqlite3.connect(p)
    seed.execute("CREATE TABLE t (a INTEGER)")
    seed.commit()
    seed.close()
    conn = db._connect(p)
    try:
        for stmt in ("INSERT INTO t VALUES (1)", "UPDATE t SET a=2", "DROP TABLE t"):
            try:
                conn.execute(stmt)
                assert False, f"write succeeded on ro connection: {stmt}"
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()


def test_sync_tools_run_off_the_event_loop():
    mcp = FastMCP("t")
    tool = threaded(mcp)

    @tool(title="Sleep")
    def sleeper() -> str:
        """Block."""
        time.sleep(0.5)
        return "ok"

    async def drive():
        stalls = []

        async def tick():
            last = time.perf_counter()
            while True:
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                stalls.append(now - last)
                last = now

        ticker = asyncio.create_task(tick())
        started = time.perf_counter()
        await asyncio.gather(*[mcp.call_tool("sleeper", {}) for _ in range(3)])
        elapsed = time.perf_counter() - started
        ticker.cancel()
        return elapsed, max(stalls)

    elapsed, worst = asyncio.run(drive())
    assert elapsed < 1.0, f"three 0.5s calls serialised: {elapsed:.2f}s"
    assert worst < 0.2, f"event loop stalled for {worst:.2f}s"


def test_history_deltas_update_cached_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "c.sqlite")
    monkeypatch.setattr(cache, "_local", threading.local())
    cache.put([{"id": "a", "subject": "one", "folders": ["INBOX", "UNREAD"]},
               {"id": "b", "subject": "two", "folders": ["INBOX"]}])
    cache.apply_history([
        {"labelsRemoved": [{"message": {"id": "a"}, "labelIds": ["UNREAD"]}]},
        {"labelsAdded": [{"message": {"id": "a"}, "labelIds": ["STARRED"]}]},
        {"messagesDeleted": [{"message": {"id": "b"}}]},
    ])
    rows = cache.get(["a", "b"])
    assert rows["a"]["folders"] == ["INBOX", "STARRED"]
    assert rows["a"]["unread"] is False
    assert "b" not in rows


def test_rate_limited_requests_retry(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if len(seen) < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "slow down"})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(common, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    assert http("GET", "https://example.test/x") == {"ok": True}
    assert len(seen) == 3
