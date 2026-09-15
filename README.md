# context-mcp

One local MCP over Advit's personal context, so an agent has a single interface
for mail, calendar, LinkedIn and WhatsApp. Read and triage only: it never sends a
message, posts, or permanently deletes.

## Domains

| Prefix | Source | Auth |
| --- | --- | --- |
| `mail_` | Gmail + Imperial Outlook | Gmail refresh token; Outlook token harvested from the OWA web session |
| `calendar_` | Google + Outlook calendars | same tokens as mail |
| `linkedin_` | LinkedIn, read-only | stealth browser profile, signed in once |
| `whatsapp_` | local WhatsApp Desktop store | read-only sqlite, no auth |

## Safety model

- No tool sends mail, posts to LinkedIn, or messages anyone. No permanent delete.
- Mail is recoverable: trash moves to Trash/Deleted Items and `mail_undo` reverses
  moves, tags, read/flag/spam and trash.
- The one irreversible surface is calendar deletion. `calendar_delete_event` and
  `calendar_bulk_delete` are destructive-hinted, refuse an unfiltered match, dry-run
  first, cap large batches behind a confirm, and belong in `permissions.ask`.
- WhatsApp opens the store read-only (`mode=ro`, `PRAGMA query_only`), so
  `whatsapp_query` can never write. Only single `SELECT`/`WITH` statements are run.

## Browser layers, by purpose

Two browser paths, each fit to its risk. Mail's Outlook token is harvested with
`agent-browser` (CDP) against a headless Chrome profile; Microsoft does not police
headless reads of your own mailbox. LinkedIn keeps a stealth Patchright profile,
because LinkedIn detects automation and the account matters. They share nothing but
the package.

## Layout

```
server.py                     unified FastMCP, registers every domain
context_mcp/
  common.py                   env, HTTP, audit log, Core Data time
  browser.py                  shared agent-browser CDP layer (Outlook harvest)
  toolkit.py                  shared MCP annotations
  mail/      gmail.py outlook.py outlook_auth.py auth.py dispatch.py tools.py
  calendar/  calendar_api.py tools.py
  linkedin/  browser.py extract.py login.py tools.py
  whatsapp/  db.py tools.py
tests/                        pytest, behavior-encoding
```

## Setup

```bash
uv sync
uv run patchright install chromium        # LinkedIn stealth browser
uv run python -m context_mcp.mail.setup    # sign into Outlook web once
uv run python -m context_mcp.linkedin.login # sign into LinkedIn once
```

Gmail credentials live in `.env` (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`,
`GMAIL_REFRESH_TOKEN`); mint the token with `uv run python -m context_mcp.mail.auth`.

## Checks

```bash
uv run python -m pytest -q
uv run python -c "import server; print('import ok')"
```

## Register

```bash
claude mcp add -s user context -- uv run --directory /Users/advitarora/.claude/mcp/context-mcp python server.py
```
