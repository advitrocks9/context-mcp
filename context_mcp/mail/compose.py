"""Draft body helpers shared by the Gmail and Outlook backends."""

from __future__ import annotations

from html import escape


def html_text(text: str) -> str:
    return escape(text, quote=False).replace("\n", "<br>")
