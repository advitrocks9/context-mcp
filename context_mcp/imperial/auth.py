"""Imperial credential store and background refresh over the shared browser profile.

Reads keep to a small JSON store so no API call ever launches a browser. The
refresher drives the one signed-in Chrome profile, harvests each provider's
cookie or token, and notifies once when a provider falls back to a 2FA wall.
"""

from __future__ import annotations

import base64
import contextlib
import datetime
import httpx
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from context_mcp import browser
from context_mcp.common import CONFIG_DIR

STORE = CONFIG_DIR / "imperial-auth.json"
ED_API = "https://us.edstem.org/api"
SCIENTIA_API = "https://scientia.doc.ic.ac.uk/api"
SCIENTIA_MAX_AGE = 780
PROBE = {
    "canvas": "https://canvas.imperial.ac.uk/api/v1/users/self",
    "panopto": "https://imperial.cloud.panopto.eu/Panopto/api/v1/auth/legacyLogin",
    "ed": f"{ED_API}/user",
    "scientia": "https://scientia.doc.ic.ac.uk/",
    "labts": "https://teaching.doc.ic.ac.uk/labts/home/index/2627",
}
WARM = {
    "canvas": "https://canvas.imperial.ac.uk/",
    "panopto": "https://imperial.cloud.panopto.eu/Panopto/Pages/Home.aspx",
    "ed": "https://edstem.org/us/dashboard",
    "scientia": "https://scientia.doc.ic.ac.uk/",
    "labts": "https://teaching.doc.ic.ac.uk/labts",
}
COOKIE_DOMAINS = {
    "canvas": "canvas.imperial.ac.uk",
    "panopto": "panopto",
    "scientia": "scientia.doc.ic.ac.uk",
    "labts": "teaching.doc.ic.ac.uk",
}
LOGIN_MARKERS = ("login.microsoftonline.com", "login.live.com", "/users/sign_in", "/eu/login", "/us/login")

_lock = threading.Lock()


def _load() -> dict[str, Any]:
    if not STORE.exists():
        return {}
    try:
        return json.loads(STORE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(STORE.parent), prefix=".imperial-auth.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(state))
        os.chmod(tmp, 0o600)
        os.replace(tmp, STORE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def credential(provider: str) -> dict[str, Any]:
    return _load().get(provider, {})


def _cookie_dict(cookie: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in cookie.split("; "):
        if "=" in part:
            name, value = part.split("=", 1)
            out[name] = value
    return out


def scientia_refresh() -> bool:
    cred = credential("scientia")
    cookie = cred.get("cookie", "")
    jar = _cookie_dict(cookie)
    csrf = jar.get("csrf_refresh_token")
    if not csrf:
        return False
    response = httpx.post(f"{SCIENTIA_API}/auth/refresh",
                          headers={"Cookie": cookie, "X-CSRF-TOKEN": csrf}, timeout=30)
    if response.status_code != 200:
        return False
    for raw in response.headers.get_list("set-cookie"):
        pair = raw.split(";", 1)[0]
        if "=" in pair:
            name, value = pair.split("=", 1)
            jar[name] = value
    with _lock:
        state = _load()
        entry = state.get("scientia", {})
        entry["cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
        entry["fetched"] = time.time()
        state["scientia"] = entry
        _save(state)
    return True


def _jwt_exp(token: str) -> float:
    try:
        seg = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(seg + "=" * ((4 - len(seg) % 4) % 4)))
        return float(payload.get("exp", 0))
    except Exception:
        return 0.0


def ensure(provider: str) -> None:
    if provider != "scientia":
        return
    jar = _cookie_dict(credential("scientia").get("cookie", ""))
    access = jar.get("access_token_cookie", "")
    if not access or _jwt_exp(access) - time.time() < 60:
        scientia_refresh()


def headers(provider: str) -> dict[str, str]:
    cred = credential(provider)
    if provider == "ed":
        return {"x-token": cred.get("token", ""), "accept": "application/json"}
    out = {"Cookie": cred.get("cookie", "")}
    if provider == "panopto" and cred.get("csrf"):
        out["X-CSRF-TOKEN"] = cred["csrf"]
    return out


def status() -> dict[str, Any]:
    state = _load()
    now = time.time()
    out = {}
    for provider in PROBE:
        cred = state.get(provider, {})
        fetched = cred.get("fetched", 0)
        has = bool(cred.get("token") or cred.get("cookie"))
        out[provider] = {
            "signed_in": has,
            "age_hours": round((now - fetched) / 3600, 1) if fetched else None,
            "stale": (now - fetched) > 24 * 3600 if fetched else True,
        }
    return out


def _state_save() -> dict[str, Any]:
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        done = subprocess.run(
            ["agent-browser", "--profile", str(browser.PROFILE), "--session", browser.SESSION, "state", "save", tmp],
            capture_output=True, text=True, timeout=browser.TIMEOUT)
        if done.returncode != 0:
            return {}
        return json.loads(Path(tmp).read_text())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {}
    finally:
        Path(tmp).unlink(missing_ok=True)


def _cookie_header(state: dict[str, Any], domain_sub: str) -> str:
    parts = [f"{c['name']}={c['value']}" for c in state.get("cookies", []) if domain_sub in c.get("domain", "")]
    return "; ".join(parts)


def _cookie_value(state: dict[str, Any], domain_sub: str, name: str) -> str:
    for c in state.get("cookies", []):
        if domain_sub in c.get("domain", "") and c.get("name") == name:
            return c.get("value", "")
    return ""


def _localstorage(state: dict[str, Any], origin_sub: str, key: str) -> str:
    for origin in state.get("origins", []):
        if origin_sub in origin.get("origin", ""):
            for item in origin.get("localStorage", []):
                if item.get("name") == key:
                    return item.get("value", "")
    return ""


def _extract(provider: str, state: dict[str, Any]) -> dict[str, Any]:
    if provider == "ed":
        token = _localstorage(state, "edstem.org", "authToken")
        return {"token": token} if token else {}
    cookie = _cookie_header(state, COOKIE_DOMAINS[provider])
    if not cookie:
        return {}
    cred: dict[str, Any] = {"cookie": cookie}
    if provider == "panopto":
        cred["csrf"] = _cookie_value(state, "panopto", "csrfToken")
    return cred


def notify(title: str, message: str) -> None:
    script = f'display notification {json.dumps(message)} with title {json.dumps(title)} sound name "Submarine"'
    with contextlib.suppress(Exception):
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)


def _reset_browser() -> None:
    with contextlib.suppress(Exception):
        subprocess.run(["pkill", "-9", "-f", str(browser.PROFILE)], capture_output=True, timeout=10)
    with contextlib.suppress(Exception):
        browser.DAEMON_PID.unlink(missing_ok=True)
    time.sleep(2)


def refresh(providers: list[str] | None = None, headed: bool = False) -> dict[str, str]:
    targets = providers or list(PROBE)
    result: dict[str, str] = {}
    with _lock, browser.session():
        _reset_browser()
        state = _load()
        for provider in targets:
            try:
                browser.open_page(WARM[provider], headed=headed)
                time.sleep(6)
                url = browser.current_url()
                cred = _extract(provider, _state_save())
                if cred and not any(m in url for m in LOGIN_MARKERS):
                    cred["fetched"] = time.time()
                    state[provider] = cred
                    result[provider] = "ok"
                else:
                    result[provider] = "needs_login"
            except Exception as exc:
                result[provider] = f"error:{type(exc).__name__}"
        _save(state)
        with contextlib.suppress(Exception):
            browser.close()
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"{stamp} " + " ".join(f"{k}={v}" for k, v in result.items())
    with (CONFIG_DIR / "imperial-refresh.log").open("a") as handle:
        handle.write(line + "\n")
    walls = [p for p, v in result.items() if v != "ok"]
    if walls:
        notify("Imperial sign-in needed", f"Open the browser and sign in: {', '.join(walls)}")
    return result
