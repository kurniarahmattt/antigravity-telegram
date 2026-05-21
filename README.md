# antigravity-telegram

A minimal Telegram bot that wraps the [Antigravity CLI (`agy`)](https://antigravity.google.com) so you can talk to it from anywhere.

Inspired by [claude-code-telegram](https://github.com/RichardAtCT/claude-code-telegram) — but built around `agy --print` instead of the Claude Agent SDK, so it works with whatever Antigravity sessions you already have locally.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What you get

```
You (Telegram)  →  bot  →  agy --print [--add-dir <project>] [--conversation <id>] <prompt>
                                                              ↓
                                          ~/.gemini/antigravity-cli/conversations/*.pb
                                                              ↓
                                                     stdout → reply on Telegram
```

The bot runs in one of two modes per user:

| Mode | Trigger | What agy sees |
|------|---------|---------------|
| **chat** *(default)* | the moment you `/start` | no workspace → agy answers conversationally |
| **code** | `/repo <project>` | `--add-dir <project>` + `--dangerously-skip-permissions` → agy can read and edit files |

Switch back to chat any time with `/chat`. Each `(user, scope)` pair has its own conversation ID stored in a local SQLite file, so follow-up messages resume the right thread.

## Limitations

`agy` v1.0.0 exposes only `--print` with plain-text stdout. That means:

- **No live tool streaming** — you won't see `📖 Read` / `✏️ Edit` progress; the bot stays "typing" until agy finishes.
- **No cost tracking** — agy doesn't surface cost or token usage.
- **No image, voice, or file attachments** — `agy --print` doesn't accept attachments.
- **No mid-flight interrupt** — once agy is running, the bot waits for completion or timeout.

For a richer experience with tool streaming, cost tracking, and image input, check out [claude-code-telegram](https://github.com/RichardAtCT/claude-code-telegram).

## Quick start

### Prerequisites

- Python **3.11+**
- [`agy` CLI](https://antigravity.google.com) installed and authenticated (`agy --print "hello"` should reply, not error)
- A Telegram bot token from [@BotFather](https://t.me/botfather)
- Your Telegram user ID (message [@userinfobot](https://t.me/userinfobot))

### Install & run

```bash
git clone https://github.com/kurniarahmattt/antigravity-telegram.git
cd antigravity-telegram

# Python env (uv recommended; pip / poetry also fine)
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .

# Configure
cp .env.example .env
# Edit .env: set TELEGRAM_BOT_TOKEN, APPROVED_DIRECTORY, ALLOWED_USERS

# Run
python -m agytg.main
```

Then open Telegram, send `/start` to your bot, and chat away.

## Commands

| Command | Effect |
|---|---|
| `/start` | Greeting + current mode info |
| `/repo` | List subdirectories of `APPROVED_DIRECTORY` |
| `/repo <name>` | Enter **code mode** scoped to project `<name>` (resumes its conversation if any) |
| `/chat` | Return to **chat mode** (no workspace) |
| `/new` | Reset the conversation for the current scope — next message starts fresh |
| `/status` | Show user ID, current mode, scope, and conversation ID |
| `/whoami` | Show your Telegram user ID (handy for filling `ALLOWED_USERS`) |
| *any text* | Forwarded to `agy --print`; the reply is whatever agy printed |

## Configuration

See [`.env.example`](.env.example) for the full list. The essentials:

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token from @BotFather |
| `APPROVED_DIRECTORY` | ✅ | Absolute path. The bot can only touch this directory and its descendants. |
| `ALLOWED_USERS` | ✅ | Comma-separated Telegram user IDs allowed to use the bot |
| `AGY_BIN` |   | Path to the `agy` binary (default: `agy` from `$PATH`) |
| `AGY_TIMEOUT_SECONDS` |   | Per-invocation wall-clock timeout (default: 300) |
| `AGY_SKIP_PERMISSIONS` |   | Pass `--dangerously-skip-permissions` in code mode (default: `true`) |
| `AGY_CONVERSATIONS_DIR` |   | Where agy stores conversation `.pb` files |
| `DATABASE_PATH` |   | SQLite path for per-user conversation mapping |

### Finding your Telegram user ID

Easiest: send `/whoami` to your running bot.  
Alternative: message [@userinfobot](https://t.me/userinfobot).

## How conversation continuity works

`agy --print` does not print its conversation ID to stdout. After each invocation the bot reads `~/.gemini/antigravity-cli/cli.log` (a symlink agy rotates per call) and matches one of these patterns to extract the UUID:

```
conversationID="<uuid>"
Created conversation <uuid>
Print mode: conversation=<uuid>
```

That UUID is stored in `data/agytg.sqlite` keyed by `(user_id, scope)`. The next message reuses it with `agy --conversation <uuid> --print …` so agy resumes where you left off.

## Security model

This is an MVP, so defence-in-depth is intentionally light:

- **Whitelist** — only `ALLOWED_USERS` can chat.
- **Workspace sandbox** — `--add-dir` is always validated against `APPROVED_DIRECTORY` to prevent path traversal.
- **No code execution by default** — chat mode runs agy without `--add-dir`. You opt in to file access by entering a project with `/repo`.

`--dangerously-skip-permissions` is enabled by default for code mode because the bot can't surface interactive permission prompts. Treat the bot as having the same authority as your terminal `agy` session.

## Development

```bash
# Smoke test imports
python -c "from agytg import main, bot, agy_runner, session, security, config, formatter; print('OK')"

# Run with debug logging
DEBUG=true python -m agytg.main
```

The project structure:

```
src/agytg/
├── __init__.py       version
├── agy_runner.py     subprocess wrapper + conversation-ID extraction
├── bot.py            Telegram handlers (commands + chat)
├── config.py         pydantic-settings env loader
├── formatter.py      markdown → Telegram HTML
├── main.py           entry point (boot + polling loop)
├── security.py       whitelist + project-path resolution
└── session.py        SQLite-backed conversation mapping
```

## Roadmap ideas

- Pluggable session backend (Postgres for multi-host deploys)
- Auto-restart on `agy` upgrade
- Tool-stream surfacing if/when `agy` exposes JSON output
- Optional cost extraction from agy logs

PRs welcome.

## License

MIT — see [LICENSE](LICENSE).
