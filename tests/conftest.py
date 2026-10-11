import threading
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from context_mcp.common import load_env
from context_mcp.imperial import auth as imperial_auth
from context_mcp.imperial import http as imperial_http
from context_mcp.imperial import tools as imperial_tools
from context_mcp.imperial import util as imperial_util
from context_mcp.linkedin import browser as linkedin_browser
from context_mcp.mail import outlook_auth
from context_mcp.whatsapp import db as whatsapp_db

GMAIL_KEYS = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
IMPERIAL_SETUP = "uv run python -m context_mcp.imperial.setup scientia labts, then context_mcp.imperial.refresh"
SSO_SETUP = "uv run python -m context_mcp.imperial.refresh after the Outlook sign-in"


def _imperial(provider: str) -> bool:
    return imperial_auth.status()[provider]["signed_in"]


GROUPS = {
    "mcp": (lambda: True, ""),
    "imperial": (lambda: True, ""),
    "gmail": (
        lambda: all(load_env().get(k) for k in GMAIL_KEYS),
        "fill .env, then uv run python -m context_mcp.mail.auth",
    ),
    "outlook": (lambda: outlook_auth.STATE.exists(), "uv run python -m context_mcp.mail.setup"),
    "scientia": (lambda: _imperial("scientia"), IMPERIAL_SETUP),
    "labts": (lambda: _imperial("labts"), IMPERIAL_SETUP),
    "canvas": (lambda: _imperial("canvas"), SSO_SETUP),
    "panopto": (lambda: _imperial("panopto"), SSO_SETUP),
    "ed": (lambda: _imperial("ed"), SSO_SETUP),
    "whatsapp": (lambda: whatsapp_db.DB_PATH.exists(), "sign in to WhatsApp Desktop"),
    "linkedin": (lambda: linkedin_browser.USER_DATA_DIR.exists(), "uv run python -m context_mcp.linkedin.login"),
}

_group: dict[str, str] = {}
_outcomes: dict[str, Counter[str]] = defaultdict(Counter)


@cache
def ready(group: str) -> bool:
    return GROUPS[group][0]()


@pytest.fixture(scope="session", autouse=True)
def isolated_imperial_state(tmp_path_factory: pytest.TempPathFactory):
    with pytest.MonkeyPatch.context() as patch:
        files = tmp_path_factory.mktemp("files")
        patch.setattr(imperial_util, "FILES_DIR", files)
        patch.setattr(imperial_tools, "FILES_DIR", files)
        patch.setattr(imperial_http, "DB_PATH", tmp_path_factory.mktemp("cache") / "imperial-cache.sqlite")
        patch.setattr(imperial_http, "_local", threading.local())
        yield


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        callspec = getattr(item, "callspec", None)
        provider = callspec.params.get("provider") if callspec else None
        _group[item.nodeid] = provider or Path(str(item.path)).stem.removeprefix("test_")


def pytest_runtest_setup(item: pytest.Item) -> None:
    group = _group[item.nodeid]
    if not ready(group):
        pytest.skip(f"{group} not set up")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or report.outcome != "passed":
        _outcomes[_group[report.nodeid]][report.outcome] += 1


def pytest_terminal_summary(terminalreporter: Any) -> None:
    terminalreporter.section("connectors")
    for group, (_, hint) in GROUPS.items():
        counts = _outcomes.get(group)
        if counts is None:
            continue
        if not ready(group):
            terminalreporter.write_line(f"{group:<9} not set up: {hint}", yellow=True)
            continue
        line = f"{group:<9} {counts['passed']} passed"
        for outcome in ("failed", "skipped"):
            if counts[outcome]:
                line += f", {counts[outcome]} {outcome}"
        terminalreporter.write_line(line, red=bool(counts["failed"]), green=not counts["failed"])
