# context-mcp

One local MCP over your personal context, so an agent has a single interface
for mail, calendar, LinkedIn, WhatsApp and your Imperial coursework. Read and triage
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
scripts/install-launchagents.sh  background Outlook and Imperial refresh
tests/                        pytest, behavior-encoding
```

## Setup

macOS only. Needs [uv](https://docs.astral.sh/uv/), Node and `agent-browser`.

```bash
brew install uv node
npm install -g agent-browser
agent-browser install
uv sync
```

Imperial, Outlook mail and Outlook calendar:

```bash
uv run python -m context_mcp.mail.setup    # sign into Outlook web once, tick Stay signed in
uv run python -m context_mcp.imperial.setup scientia labts  # sign in once; Canvas/Panopto/Ed ride the Outlook SSO
uv run python -m context_mcp.imperial.refresh
scripts/install-launchagents.sh
```

Optional domains. Each one fails only when called until it is set up.

- Gmail and Google Calendar: see below.
- LinkedIn: `uv run patchright install chromium`, then `uv run python -m context_mcp.linkedin.login`.
- WhatsApp: WhatsApp Desktop signed in, and Full Disk Access for the app that runs
  your agent (System Settings, Privacy & Security, Full Disk Access).

## Imperial auth, self-sustaining

Canvas, Panopto and Ed authenticate from the same signed-in browser profile the
Outlook harvest uses, so they need no separate login. Scientia and LabTS need a
one-time DoC sign-in into that profile (the `imperial.setup` line above). A
LaunchAgent (`com.context-mcp.imperial-refresh`) re-harvests every 8 hours and
on wake; when a session has fully lapsed to a 2FA wall it fires one macOS
notification naming which provider to sign back in. `imperial status` shows the age
of each session; `uv run python -m context_mcp.imperial.refresh` forces a refresh.

Outlook tokens rotate the same way under `com.context-mcp.outlook-refresh`. Both
agents are written by `scripts/install-launchagents.sh` for the clone they run
from; rerun it after moving the repo.

## Gmail

Gmail and Google Calendar use your own OAuth client. In Google Cloud Console, create
a project, enable the Gmail API and the Google Calendar API, configure the consent
screen with yourself as a test user, and create an OAuth client of type Desktop app.
Copy `.env.example` to `.env`, fill in `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET`,
then mint the refresh token with `uv run python -m context_mcp.mail.auth`. A consent
screen left in Testing expires the token after 7 days; publish it to keep it.

## Checks

```bash
uv run python -m pytest -q
uv run python -c "import server; print('import ok')"
```

## Register

```bash
claude mcp add -s user context -- uv run --directory "$PWD" python server.py
```
