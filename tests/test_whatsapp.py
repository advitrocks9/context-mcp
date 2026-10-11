import pytest
from mcp.server.fastmcp.exceptions import ToolError

from tests.client import call, one, raw


@pytest.fixture(scope="module")
def chat() -> dict:
    chats = call("whatsapp", "list_chats", limit=10, kind="direct")
    assert chats, "no direct chats"
    return chats[0]


def test_list_chats_returns_chats():
    assert all(c["name"] and c["jid"] for c in call("whatsapp", "list_chats", limit=10))


def test_list_contacts_returns_contacts():
    assert all(c["jid"] for c in call("whatsapp", "list_contacts", limit=10))


def test_get_chat_returns_recent_messages(chat):
    assert one("whatsapp", "get_chat", name_or_jid=chat["jid"], limit=10)["messages"]


def test_search_messages_finds_text_from_a_chat(chat):
    messages = one("whatsapp", "get_chat", name_or_jid=chat["jid"], limit=50)["messages"]
    text = next((m["text"] for m in messages if len(m.get("text") or "") >= 8), None)
    assert text, "no text message to search for"
    found = call("whatsapp", "search_messages", text=text, contact=chat["name"], limit=5)
    assert any(text in m["text"] for m in found)


def test_person_stats_counts_messages(chat):
    assert one("whatsapp", "person_stats", name_or_jid=chat["jid"])["total"] > 0


def test_schema_lists_the_store_tables():
    tables = one("whatsapp", "schema")
    assert "ZWAMESSAGE" in tables and "ZWACHATSESSION" in tables


def test_query_runs_a_select():
    assert one("whatsapp", "query", sql="SELECT COUNT(*) AS n FROM ZWAMESSAGE")["n"] > 0


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM ZWAMESSAGE WHERE 0",
        "WITH x AS (SELECT 1) DELETE FROM ZWAMESSAGE WHERE 0",
    ],
)
def test_query_cannot_write_the_store(sql):
    with pytest.raises(ToolError):
        raw("whatsapp", "query", sql=sql)
