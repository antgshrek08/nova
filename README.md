# N.O.V.A.

A desktop AI assistant that runs on your own computer: chat with any model you
like (free local ones or cloud ones), keep your homework in one place, write
code in a built-in studio, run teams of agents, and talk to it by voice. Your
chats, memory and keys stay on your machine.

Works on **Windows, macOS and Linux**.

## What it does

- **Chat** with local models (Ollama, LM Studio), app sign-ins (Claude, Codex,
  Antigravity) or API keys (OpenRouter, Gemini, Groq, OpenAI, Anthropic and
  more, or any service by name). Nova picks a model per message, and falls back
  when one fails.
- **Academics**: everything due from Canvas and other homework sites (Pearson,
  ALEKS, WebAssign, Lumen and more), grouped by day, with study time planned
  into your calendar.
- **Calendar**: Google, Apple (iCloud) and any calendar link (Outlook, school
  calendars).
- **Studio**: a code editor with a terminal, Git, a live preview and one-click
  publishing.
- **Agents and Workspace**: hand Nova longer jobs and watch them run.
- **Memory**: what Nova knows about you, which you can read, edit and delete,
  plus your Obsidian notes.
- **Voice**: wake word, speech-to-text and a choice of voices.
- **Phone**: open Nova on your phone as an app (no app store needed), with
  notifications.

The first run walks you through everything: your name, the look, which models
to use (with step-by-step help for each), permissions, voice, notes and
connections. Every main screen has a **?** button with a short guide.

## Install

### Windows

Download the installer from the [Releases](../../releases) page and run it.

Or from source: install [Python 3.12+](https://www.python.org/downloads/) and
[Node.js 20+](https://nodejs.org), then:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python download_models.py   # offline voice and wake word
cd ..\frontend
npm ci
npm run build
npm start
```

### macOS and Linux

```bash
git clone <this repository>
cd nova
./install.sh            # add --no-voice to skip the ~2 GB voice packages
cd frontend && npm start
```

`install.sh` works on macOS (with [Homebrew](https://brew.sh)), Ubuntu/Debian,
Fedora, Arch and openSUSE. It installs what is missing, builds the Python
environment and the app, and tells you what is not available on your system.

Prefer a browser tab over the desktop app? Run `./mac/start-nova.sh` or
`./linux/start-nova.sh` and Nova opens at `http://127.0.0.1:8000/app/`.

### Free local models (optional)

Install [Ollama](https://ollama.com), then pick a model in onboarding or
Settings, Models. Nova also works with only cloud models.

## What differs by system

Everything works everywhere except controlling other apps' windows directly
(clicking buttons in another program for you), which uses Windows UI
Automation and is Windows-only. On macOS and Linux Nova says so plainly
instead of failing. Web browsing, homework, chat, code, memory and voice work
the same on all three.

## Your data

Nova keeps everything in `~/.ai-council/` (`%USERPROFILE%\.ai-council\` on
Windows): the database, your settings and your API keys (in `.env`). Nothing
there is part of this repository or of the installers.

## Development

```bash
# engine tests
cd backend && .venv/bin/python -m pytest tests -q     # .venv\Scripts\python on Windows

# app, with live reload
cd frontend && npm run dev

# installers (build on the system you are packaging for)
npm run dist:win    # or dist:mac, dist:linux
```

On Windows, don't start the engine with uvicorn's `--reload`: it switches to
an event loop that can't start subprocesses, which breaks the CLI-based
models. `scripts/dev-backend.ps1` restarts it on changes instead.

Every push is tested on Windows, macOS and Linux (see `.github/workflows`).
