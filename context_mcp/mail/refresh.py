"""Keep the Outlook refresh token alive for the background LaunchAgent."""

from __future__ import annotations

import datetime

from context_mcp.common import CONFIG_DIR
from context_mcp.mail import outlook_auth

LOG = CONFIG_DIR / "refresh.log"
LOG_MAX_BYTES = 256 * 1024


def main() -> None:
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        outlook_auth.get_token()
        line = f"{stamp} ok"
    except Exception as exc:
        line = f"{stamp} failed: {exc}"
    if LOG.exists() and LOG.stat().st_size > LOG_MAX_BYTES:
        LOG.write_text("".join(LOG.read_text().splitlines(keepends=True)[-200:]))
    with LOG.open("a") as handle:
        handle.write(line + "\n")


if __name__ == "__main__":
    main()
