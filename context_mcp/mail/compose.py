"""Draft body helpers shared by the Gmail and Outlook backends."""

from __future__ import annotations

import re
from html import escape

_HTML_CHARS = {"'": "(?:'|&#39;|&#x27;)", '"': '(?:"|&quot;)', "&": "&amp;", "<": "&lt;", ">": "&gt;"}


def html_text(text: str) -> str:
    return escape(text).replace("&#x27;", "&#39;").replace("\n", "<br>")


def html_body(text: str, style: str = "") -> str:
    div = f'<div class="gmail_default" style="{style}">' if style else "<div>"
    return (
        '<div dir="ltr">' + "".join(f"{div}{html_text(line) or '<br>'}</div>" for line in text.splitlines()) + "</div>"
    )


def _pattern(old: str, html: bool) -> re.Pattern[str]:
    words = ("".join(_HTML_CHARS.get(c, re.escape(c)) for c in w) if html else re.escape(w) for w in old.split())
    return re.compile(r"(?:\s|&nbsp;)+".join(words))


def swap(text: str, swaps: list[dict[str, str]], html: bool) -> str:
    for edit in swaps:
        new = edit["new"].replace("\r\n", "\n")
        if html:
            new = html_text(new)
        elif "\r\n" in text:
            new = new.replace("\n", "\r\n")
        matches = list(_pattern(edit["old"], html).finditer(text)) if edit["old"].split() else []
        if len(matches) != 1:
            kind = "HTML" if html else "Plain"
            raise ValueError(f"{kind} body matches {edit['old']!r} {len(matches)} times; it must match exactly once.")
        text = text[: matches[0].start()] + new + text[matches[0].end() :]
    return text
