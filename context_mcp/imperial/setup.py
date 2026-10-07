"""Open the shared browser profile to sign a provider in once, then harvest."""

from __future__ import annotations

import sys
import time

from context_mcp import browser
from context_mcp.imperial import auth


def main() -> None:
    providers = [p for p in sys.argv[1:] if p in auth.WARM] or ["scientia", "labts"]
    with browser.session():
        browser.reap()
        for i, provider in enumerate(providers):
            if i:
                browser._run("tab", "new")
            browser.open_page(auth.WARM[provider], headed=True)
            time.sleep(1)
    auth.notify("Imperial sign-in", f"Browser open. Sign in to: {', '.join(providers)}")
    print("Signed-in window open. Log in to:", ", ".join(providers))
    print("When done, run: uv run --frozen python -m context_mcp.imperial.refresh")


if __name__ == "__main__":
    main()
