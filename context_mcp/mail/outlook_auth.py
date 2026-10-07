"""Outlook tokens harvested from the signed-in OWA session, then refreshed over HTTPS."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import tempfile
import threading
import time
from typing import Any

from context_mcp import browser
from context_mcp.common import CONFIG_DIR, http

CLIENT_ID = "9199bf20-a13f-4107-85dc-02114787ef48"
ORIGIN = "https://outlook.office.com"
SCOPE = "https://outlook.office.com/.default openid profile offline_access"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MAIL_URL = "https://outlook.office.com/mail/"

STATE = CONFIG_DIR / "outlook-token.json"
_token_lock = threading.Lock()
SKEW = 300
HARVEST_DEADLINE = 90
SIGN_IN_DEADLINE = 600

SETUP_HINT = ("OWA session is not signed in. Run `python -m context_mcp.mail.setup` "
              "and sign in once with Stay signed in ticked.")

_HARVEST_JS = r"""
(function () {
  function aud(t) {
    try {
      var p = t.split('.')[1];
      return (JSON.parse(atob(p.replace(/-/g, '+').replace(/_/g, '/')
        .padEnd(p.length + (4 - p.length % 4) % 4, '='))).aud) || '';
    } catch (e) { return ''; }
  }
  if (!/^https:\/\/outlook\.(office\.com|cloud\.microsoft)$/.test(location.origin)) return {stage: 'offsite'};
  var ls;
  try { ls = window.localStorage; } catch (e) { return {stage: 'nostore'}; }
  var refresh = null, access = null, bestExp = 0;
  for (var i = 0; i < ls.length; i++) {
    var k = ls.key(i), v;
    if (k.indexOf('msal.') !== 0 || k.indexOf('|') < 0) continue;
    try { v = JSON.parse(ls.getItem(k)); } catch (e) { continue; }
    if (!v || !v.secret) continue;
    if (k.indexOf('|refreshtoken|') >= 0) { refresh = v.secret; }
    else if (k.indexOf('|accesstoken|') >= 0 &&
             aud(v.secret).indexOf('outlook.office.com') >= 0) {
      var exp = parseInt(v.expiresOn || 0, 10);
      if (exp >= bestExp) { bestExp = exp; access = v.secret; }
    }
  }
  return {stage: 'ok', refresh: refresh, access: access};
})()
"""


def _state_load() -> dict[str, Any]:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _state_save(state: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(STATE.parent), prefix=".outlook-token.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(state))
        os.chmod(tmp, 0o600)
        os.replace(tmp, STATE)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def drop_access(token: str | None = None) -> None:
    with _token_lock:
        state = _state_load()
        if state.get("access") and token in (None, state["access"]):
            state.pop("access")
            _state_save(state)


def _jwt_exp(token: str) -> float:
    seg = token.split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(seg + "=" * ((4 - len(seg) % 4) % 4)))
    return float(payload["exp"])


def _walled() -> bool:
    url = browser.current_url()
    return "login.microsoftonline.com" in url or "login.live.com" in url


def _read_tokens() -> dict[str, Any] | None:
    found = browser.evaluate(_HARVEST_JS) or {}
    access = found.get("access")
    if found.get("stage") == "ok" and access and _jwt_exp(access) - time.time() > SKEW:
        return found
    return None


def _harvest() -> dict[str, Any]:
    with browser.session():
        cached = _state_load()
        if cached.get("access") and cached.get("exp", 0) - time.time() > SKEW:
            return cached
        browser.reap()
        try:
            browser.open_page(MAIL_URL)
            deadline = time.time() + HARVEST_DEADLINE
            walls = 0
            while time.time() < deadline:
                found = _read_tokens()
                if found:
                    return found
                walls = walls + 1 if _walled() else 0
                if walls >= 3:
                    raise RuntimeError(SETUP_HINT)
                time.sleep(3)
            raise RuntimeError("OWA did not settle on the mailbox in time. Retry, or re-run setup.")
        finally:
            browser.close()


def sign_in() -> str:
    with browser.session():
        browser.close()
        try:
            browser.open_page(MAIL_URL, headed=True)
            deadline = time.time() + SIGN_IN_DEADLINE
            while time.time() < deadline:
                found = _read_tokens()
                if found:
                    return _commit(found)
                time.sleep(4)
            raise RuntimeError("Outlook sign-in did not finish within 10 minutes.")
        finally:
            browser.close()


def _mint(refresh_token: str) -> dict[str, Any]:
    data = http("POST", TOKEN_URL, {"Origin": ORIGIN},
                {"client_id": CLIENT_ID, "grant_type": "refresh_token",
                 "refresh_token": refresh_token, "scope": SCOPE}, form=True)
    return {"access": data["access_token"], "refresh": data.get("refresh_token") or refresh_token}


def _commit(found: dict[str, Any]) -> str:
    access = found.get("access")
    refresh_token = found.get("refresh")
    if refresh_token and not access:
        minted = _mint(refresh_token)
        access, refresh_token = minted["access"], minted["refresh"]
    if not access:
        raise RuntimeError(SETUP_HINT)
    _state_save({"access": access, "refresh": refresh_token, "exp": _jwt_exp(access)})
    return access


def _fresh(state: dict[str, Any]) -> str | None:
    access = state.get("access")
    return str(access) if access and state.get("exp", 0) - time.time() > SKEW else None


def have_credentials() -> bool:
    state = _state_load()
    return bool(state.get("refresh") or state.get("access"))


def get_token() -> str:
    token = _fresh(_state_load())
    if token:
        return token
    with _token_lock:
        state = _state_load()
        token = _fresh(state)
        if token:
            return token
        refresh_token = state.get("refresh")
        if refresh_token:
            try:
                return _commit(_mint(refresh_token))
            except RuntimeError as exc:
                if "AADSTS" not in str(exc):
                    raise
        return _commit(_harvest())
