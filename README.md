# context-mcp

One local MCP over Advit's personal context, so an agent has a single interface
for mail, calendar, LinkedIn, WhatsApp and his Imperial coursework. Read and triage
only: it never sends a message, posts, submits coursework, or permanently deletes.

## Soft-loaded tools

Each domain is one dispatcher tool, not a wall of tools, so an agent sees ten tools
instead of forty. Call a tool with `op="help"` for its operations, `op="schema"`
for their argument shapes, then `op="<name>", params={...}` to run one. Set
`CONTEXT_FOLD=0` to expose every underlying tool individually instead.

## Domains

| Tool | Source | Auth |
| --- | --- | --- |
| `mail` | Gmail + Imperial Outlook | Gmail refresh token; Outlook token harvested from the OWA web session |
| `calendar` | Google + Outlook calendars | same tokens as mail |
| `linkedin` | LinkedIn, read-only | stealth browser profile, signed in once |
| `whatsapp` | local WhatsApp Desktop store | read-only sqlite, no auth |
| `scientia` | DoC VLE: modules, exercises, deadlines, resources, past papers, marks | DoC login; 15-min JWT auto-renewed via its 30-day refresh token |
| `canvas` | Maths VLE: courses, content, pages, deadlines, announcements, files | Microsoft SSO cookie from the shared profile |
| `panopto` | lecture recordings, transcripts, cross-lecture search | Microsoft SSO cookie |
| `ed` | Ed Discussion: courses, threads, announcements, search | 14-day session token from the shared profile |
| `labts` | lab submission and test state | DoC login cookie |
| `imperial` | auth `status`, `refresh`, downloaded `files`, `clear_cache` | — |

The five Imperial services are GET-only by construction (`imperial/http.py` has no
write path) and cache every response in `imperial-cache.sqlite`, so repeated reads
never re-hit a provider. Fetched files land under `~/Projects/imperial/files`
(override with `IMPERIAL_DIR`). Tokens live in `~/.config/context-mcp/imperial-auth.json`.

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
  imperial/  auth.py http.py util.py scientia.py canvas.py panopto.py ed.py labts.py tools.py refresh.py setup.py
  gateway.py                  folds each domain into one dispatcher tool
tests/                        pytest, behavior-encoding
```

## Setup

```bash
uv sync
uv run patchright install chromium        # LinkedIn stealth browser
uv run python -m context_mcp.mail.setup    # sign into Outlook web once
uv run python -m context_mcp.linkedin.login # sign into LinkedIn once
uv run python -m context_mcp.imperial.setup scientia labts  # sign in once; Canvas/Panopto/Ed ride the Outlook SSO
```

## Imperial auth, self-sustaining

Canvas, Panopto and Ed authenticate from the same signed-in browser profile the
Outlook harvest uses, so they need no separate login. Scientia and LabTS need a
one-time DoC sign-in into that profile (the `imperial.setup` line above). A
LaunchAgent (`com.advit.contextmcp.imperial-refresh`) re-harvests every 8 hours and
on wake; when a session has fully lapsed to a 2FA wall it fires one macOS
notification naming which provider to sign back in. `imperial status` shows the age
of each session; `uv run python -m context_mcp.imperial.refresh` forces a refresh.

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
