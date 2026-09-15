"""Shared headless-Chrome layer over agent-browser CDP.

One persistent Chrome profile, logged into the sites this MCP reads (Outlook web
for the token harvest, LinkedIn for profile and feed reads). Every browser
operation runs under one file lock so mail and LinkedIn never fight over the
single Chrome instance that owns the profile.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import signal
import subprocess
from typing import Any, Iterator

from context_mcp.common import CONFIG_DIR

PROFILE = CONFIG_DIR / "browser-profile"
LOCK = CONFIG_DIR / "browser.lock"
SESSION = "context-mcp"
TIMEOUT = 150
PROFILE_MAX_BYTES = 250 * 1024 * 1024
PRUNABLE = (
    "Default/Cache", "Default/Code Cache", "Default/GPUCache",
    "Default/Service Worker/CacheStorage", "Default/Service Worker/ScriptCache",
    "Default/DawnGraphiteCache", "Default/DawnWebGPUCache",
    "GraphiteDawnCache", "GrShaderCache", "ShaderCache", "component_crx_cache",
)


@contextlib.contextmanager
def session() -> Iterator[None]:
    with LOCK.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def reap() -> None:
    found = subprocess.run(["pgrep", "-f", str(PROFILE)], capture_output=True, text=True)
    for pid in found.stdout.split():
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(int(pid), signal.SIGTERM)


def prune() -> None:
    if not PROFILE.exists():
        return
    if sum(f.stat().st_size for f in PROFILE.rglob("*") if f.is_file()) < PROFILE_MAX_BYTES:
        return
    for relative in PRUNABLE:
        shutil.rmtree(PROFILE / relative, ignore_errors=True)


def _run(*args: str, headed: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["agent-browser", "--profile", str(PROFILE), "--session", SESSION]
    if headed:
        command.append("--headed")
    command += args
    return subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)


def open_page(url: str, headed: bool = False) -> None:
    _run("open", url, headed=headed)


def current_url() -> str:
    done = _run("get", "url")
    return done.stdout.strip() if done.returncode == 0 else ""


def evaluate(js: str) -> Any:
    done = _run("--json", "eval", js)
    if done.returncode != 0 or not done.stdout.strip():
        return None
    payload = json.loads(done.stdout)
    return (payload.get("data") or {}).get("result")


def page_text(max_chars: int = 40000) -> str:
    done = _run("get", "text", "body")
    return done.stdout.strip()[:max_chars] if done.returncode == 0 else ""


def close() -> None:
    _run("close")
    reap()
    prune()
