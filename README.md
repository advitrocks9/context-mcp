# context-mcp

A local MCP server that gives an agent your personal context and your Imperial
coursework through one connection. It reads and triages. It never sends a message,
posts, submits coursework or permanently deletes anything. macOS only.

Each connector is one tool. Call it with `op="help"` to list its operations,
`op="schema"` for their arguments, then `op="<name>", params={...}` to run one.

## Connectors

| Tool | What it reads | Sign-in |
| --- | --- | --- |
| `mail` | Gmail and Imperial Outlook. Lists, searches and reads mail, and files, tags or trashes it recoverably | Gmail OAuth, Outlook web |
| `calendar` | Google and Outlook calendars. Reads events, and can RSVP, create or delete them | same as mail |
| `scientia` | DoC modules, exercises and specs, resources, past papers, marks | DoC login |
| `labts` | Lab exercises, submission and test state, repositories | DoC login |
| `canvas` | Maths courses, pages, deadlines, announcements, files | Microsoft SSO |
| `panopto` | Lecture recordings, transcripts, search across lectures | Microsoft SSO |
| `ed` | Ed Discussion courses, threads, announcements, search | Microsoft SSO |
| `imperial` | Session status, refresh, downloaded files, cache | none |
| `whatsapp` | WhatsApp Desktop chats, contacts, message search, read-only SQL | none |
| `linkedin` | Profiles, people and job search, feed, messages, notifications | LinkedIn login |

Imperial downloads land in `~/Projects/imperial/files`, or `IMPERIAL_DIR` if set.
Sessions and tokens live in `~/.config/context-mcp`.

## Setup

1. Install the tools.

   ```bash
   brew install uv node
   npm install -g agent-browser
   agent-browser install
   uv sync
   ```

2. Sign in to Outlook web in the window that opens, and tick Stay signed in. This
   also signs in Canvas, Panopto and Ed.

   ```bash
   uv run python -m context_mcp.mail.setup
   ```

3. Sign in to Scientia and LabTS with your DoC login, then harvest every Imperial
   session.

   ```bash
   uv run python -m context_mcp.imperial.setup scientia labts
   uv run python -m context_mcp.imperial.refresh
   ```

4. Keep the sessions alive in the background. This refreshes Outlook and Imperial
   every 8 hours, and sends one macOS notification if a provider needs a fresh
   sign-in. Rerun it if you move the repo.

   ```bash
   scripts/install-launchagents.sh
   ```

5. Register the server from inside the repo, then restart Claude Code.

   ```bash
   claude mcp add -s user context -- uv run --directory "$PWD" python server.py
   ```

### Optional connectors

- Gmail and Google Calendar. In Google Cloud Console create a project, enable the
  Gmail API and the Google Calendar API, add yourself as a test user on the consent
  screen, and create an OAuth client of type Desktop app. Copy `.env.example` to
  `.env`, fill in the client id and secret, then run
  `uv run python -m context_mcp.mail.auth`. Publish the consent screen, or the token
  expires after 7 days.
- LinkedIn. Run `uv run patchright install chromium`, then
  `uv run python -m context_mcp.linkedin.login`.
- WhatsApp. Sign in to WhatsApp Desktop, and give the app that runs your agent Full
  Disk Access in System Settings, Privacy & Security.

## Check

```bash
uv run pytest
```

Every operation runs live against your accounts, read-only. The run ends with one
line per connector: passed, failed, or not set up with the command that fixes it.

```bash
uv run ruff check .
```
