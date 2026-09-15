import asyncio

import pytest

import server


def _tools():
    return asyncio.run(server.mcp.list_tools())


def test_server_registers_all_domains():
    names = {t.name for t in _tools()}
    assert any(n.startswith("mail_") for n in names)
    assert any(n.startswith("calendar_") for n in names)
    assert any(n.startswith("linkedin_") for n in names)
    assert any(n.startswith("whatsapp_") for n in names)


def test_no_send_or_post_tools_anywhere():
    names = {t.name for t in _tools()}
    forbidden = ("send", "post", "connect", "invite", "reply", "message_", "publish")
    leaked = [n for n in names if any(f in n for f in forbidden)]
    assert not leaked, f"forbidden write tools exposed: {leaked}"


def test_no_permanent_delete():
    names = {t.name for t in _tools()}
    assert not any("permanent" in n or "empty_trash" in n for n in names)


def test_whatsapp_tools_are_read_only():
    ro = {t.name for t in _tools() if t.annotations and t.annotations.readOnlyHint}
    wa = {t.name for t in _tools() if t.name.startswith("whatsapp_")}
    assert wa and wa <= ro, "every whatsapp tool must be read-only"


def test_linkedin_tools_are_read_only():
    ro = {t.name for t in _tools() if t.annotations and t.annotations.readOnlyHint}
    li = {t.name for t in _tools() if t.name.startswith("linkedin_")}
    assert li and li <= ro


def test_destructive_tools_flagged():
    destructive = {t.name for t in _tools() if t.annotations and t.annotations.destructiveHint}
    assert "calendar_delete_event" in destructive
    assert "calendar_bulk_delete" in destructive
    assert "mail_trash" in destructive
