import re

import pytest

from tests.client import call, one

pytestmark = pytest.mark.parametrize("provider", ["gmail", "outlook"])


def _inbox(provider: str) -> list[dict]:
    messages = one("mail", "list", provider=provider, limit=5)["messages"]
    assert messages, f"{provider} inbox is empty"
    return messages


def test_list_returns_inbox_messages(provider):
    assert all(m["provider"] == provider and m["id"] for m in _inbox(provider))


def test_search_finds_a_listed_message(provider):
    message = _inbox(provider)[0]
    words = re.findall(r"[A-Za-z]{4,}", message["subject"])
    assert words, f"newest subject has no searchable word: {message['subject']!r}"
    found = one("mail", "search", provider=provider, query=max(words, key=len), limit=50)["messages"]
    assert message["id"] in {m["id"] for m in found}


def test_get_returns_the_full_message(provider):
    message = _inbox(provider)[0]
    full = one("mail", "get", provider=provider, id=message["id"])
    assert full["id"] == message["id"] and full["subject"] == message["subject"] and "body" in full


def test_folders_include_the_inbox(provider):
    names = {str(f.get("name", "")).lower() for f in call("mail", "folders", provider=provider)}
    assert "inbox" in names


def test_list_filters_returns_rules(provider):
    assert all(f["id"] for f in call("mail", "list_filters", provider=provider))


def test_recent_actions_reads_the_audit_log(provider):
    log = one("mail", "recent_actions", provider=provider)
    assert all(e.get("provider") == provider for e in log["entries"])
