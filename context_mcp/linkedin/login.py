"""One-time interactive LinkedIn login into the persistent Patchright profile."""

import asyncio

from context_mcp.linkedin import browser

if __name__ == "__main__":
    print("Opening a browser window. Log into LinkedIn (complete any 2FA). Waiting...")
    result = asyncio.run(browser.login())
    print(result)
