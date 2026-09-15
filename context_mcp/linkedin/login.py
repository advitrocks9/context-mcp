"""One-time interactive LinkedIn login into the persistent Patchright profile."""

import asyncio

from linkedin_mcp import browser

if __name__ == "__main__":
    print("Opening a browser window. Log into LinkedIn (complete any 2FA). Waiting...")
    result = asyncio.run(browser.login())
    print(result)
