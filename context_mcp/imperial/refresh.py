"""Background refresh for the LaunchAgent: keep every Imperial session live.

Scientia renews cheaply through its 30-day refresh token. The rest are
re-harvested from the shared signed-in browser profile. A provider that has
fallen back to a login wall triggers one macOS notification.
"""

from __future__ import annotations

from context_mcp.imperial import auth


def main() -> None:
    try:
        auth.scientia_refresh()
    except Exception:
        pass
    auth.refresh()


if __name__ == "__main__":
    main()
