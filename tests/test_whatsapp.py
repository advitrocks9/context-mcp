import sqlite3
import pathlib
import pytest

from context_mcp.whatsapp import db


def test_guard_accepts_select():
    assert db.guard_sql("SELECT 1").lower().startswith("select")
    assert db.guard_sql("  select a from t  ").strip()
    assert db.guard_sql("WITH c AS (SELECT 1) SELECT * FROM c").lower().startswith("with")


@pytest.mark.parametrize("bad", [
    "", "   ", "DELETE FROM ZWAMESSAGE", "update t set x=1", "DROP TABLE t",
    "INSERT INTO t VALUES (1)", "PRAGMA table_info(t)", "ATTACH DATABASE 'x' AS y",
    "SELECT 1; DROP TABLE t", "VACUUM", "REINDEX",
])
def test_guard_rejects_non_read_or_multi(bad):
    with pytest.raises(ValueError):
        db.guard_sql(bad)


def test_connection_is_read_only(tmp_path):
    p = tmp_path / "t.sqlite"
    seed = sqlite3.connect(p)
    seed.execute("CREATE TABLE t (a INTEGER)")
    seed.execute("INSERT INTO t VALUES (1)")
    seed.commit()
    seed.close()
    conn = db._connect(p)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO t VALUES (2)")
    conn.close()


def test_query_runs_select_on_fixture(tmp_path):
    p = tmp_path / "t.sqlite"
    seed = sqlite3.connect(p)
    seed.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    seed.executemany("INSERT INTO t VALUES (?,?)", [(1, "x"), (2, "y")])
    seed.commit()
    seed.close()
    rows = db.query("SELECT a, b FROM t ORDER BY a", path=p)
    assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]


def test_query_limit_caps_rows(tmp_path):
    p = tmp_path / "t.sqlite"
    seed = sqlite3.connect(p)
    seed.execute("CREATE TABLE t (a INTEGER)")
    seed.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
    seed.commit()
    seed.close()
    assert len(db.query("SELECT a FROM t", limit=10, path=p)) == 10


live = pytest.mark.skipif(not db.DB_PATH.exists(), reason="WhatsApp store not present")


@live
def test_schema_exposes_core_tables():
    s = db.schema()
    assert "ZWAMESSAGE" in s and "ZWACHATSESSION" in s
    assert any("ZTEXT" in c for c in s["ZWAMESSAGE"])


@live
def test_list_chats_shape():
    chats = db.list_chats(limit=5)
    assert chats and all("name" in c and "jid" in c for c in chats)


@live
def test_search_messages_returns_list():
    assert isinstance(db.search_messages("the", limit=3), list)


@live
def test_get_chat_and_person_stats():
    chats = db.list_chats(limit=1)
    chat = db.get_chat(chats[0]["jid"], limit=5)
    assert "messages" in chat
    stats = db.person_stats(chats[0]["jid"])
    assert "total" in stats and stats["total"] >= 0
