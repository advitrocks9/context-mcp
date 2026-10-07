"""Mask passwords, keys and tokens in free text before it leaves the server."""

from __future__ import annotations

import re

MASK = "••••••••"


def _hide(token: str) -> str:
    return (token[:8] + MASK) if len(token) > 12 else MASK


def _mask(match: "re.Match[str]") -> str:
    return _hide(match.group(0))

_VALUE = r"""['"]?([^\s'"`]{3,})['"]?"""
_LABELLED = re.compile(
    r"(?i)\b(password|passwd|pwd|passphrase|pass|secret|token|api[\s_-]?key|apikey|"
    r"access[\s_-]?key|private[\s_-]?key|client[\s_-]?secret|seed[\s_-]?phrase|credentials?)"
    r"\b\s*(?:is|are|:|=|->|→)\s*" + _VALUE)

_PATTERNS = [
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b"),          # JWT
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}\b"),                                    # bearer token
    re.compile(r"\bsk-(?:ant-|proj-|live-)?[A-Za-z0-9_-]{20,}\b"),                           # OpenAI/Anthropic
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),                             # GitHub token
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),                                          # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                                      # AWS key id
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                                                 # Google API key
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b"),                                              # Google OAuth
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),                           # Stripe
    re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]+?-----END[A-Z ]*PRIVATE KEY-----"),  # PEM
    re.compile(r"\b[0-9a-fA-F]{40,}\b"),                                                      # long hex (sha/token)
    re.compile(r"\b[A-Za-z0-9+/]{44,}={0,2}\b"),                                              # long base64 blob
]


def scrub(text: str | None) -> str | None:
    if not text or not isinstance(text, str):
        return text
    out = _LABELLED.sub(lambda m: f"{m.group(1)}: {_hide(m.group(2))}", text)
    for pattern in _PATTERNS:
        out = pattern.sub(_mask, out)
    return out
