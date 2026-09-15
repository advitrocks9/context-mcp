"""One-time interactive OWA sign-in for the shared browser profile."""

from __future__ import annotations

import time

from context_mcp import browser
from context_mcp.mail import outlook_auth


def main() -> None:
    browser.reap()
    browser.open_page(outlook_auth.MAIL_URL, headed=True)
    print("Sign into Outlook in the window that opened. Tick Stay signed in.")
    deadline = time.time() + 600
    while time.time() < deadline:
        if browser.current_url().startswith(outlook_auth.MAIL_URL):
            break
        time.sleep(4)
    outlook_auth.state_clear()
    token = outlook_auth.get_token()
    print("outlook ready, token length", len(token))


if __name__ == "__main__":
    main()
