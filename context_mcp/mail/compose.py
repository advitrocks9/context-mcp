"""Draft body helpers shared by the Gmail and Outlook backends."""

from __future__ import annotations

from html import escape


def html_text(text: str) -> str:
    return escape(text, quote=False).replace("\n", "<br>")


def swap(text: str, swaps: list[dict[str, str]], html: bool) -> str:
    for edit in swaps:
        old, new = (edit[k].replace("\r\n", "\n") for k in ("old", "new"))
        if html:
            old, new = html_text(old), html_text(new)
        elif "\r\n" in text:
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        found = text.count(old)
        if found != 1:
            kind = "HTML" if html else "Plain"
            raise ValueError(f"{kind} body matches {edit['old']!r} {found} times; it must match exactly once.")
        text = text.replace(old, new)
    return text
