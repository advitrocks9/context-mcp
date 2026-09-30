"""One-time interactive OWA sign-in for the shared browser profile."""

from __future__ import annotations

from context_mcp.mail import outlook_auth


def main() -> None:
    print("Sign into Outlook in the window that opens. Tick Stay signed in.")
    token = outlook_auth.sign_in()
    print("outlook ready, token length", len(token))


if __name__ == "__main__":
    main()
