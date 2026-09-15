import concurrent.futures
import json
import sqlite3

from context_mcp.mail import outlook_auth
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
