# N.O.V.A.

A desktop AI assistant that runs on your own computer: chat with any model you
like (free local ones or cloud ones), keep track of your classes and deadlines, write
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
- **Voice**: wake word, speech-to-text and a choice of voices (online voices
  built in; an offline voice is an optional download).
- **Phone**: open Nova on your phone as an app (no app store needed), with
  notifications.
- **Yours to shape**: tell Nova how to answer you in your own words, and pick
  its look, voice, models, how much it may do on its own, and what it notifies
  you about.
- **Fixes itself**: when something breaks because of a mistake in Nova's own
  code, Nova can repair it. A coding model writes the smallest change, and the
  change is kept only if all of Nova's tests still pass; otherwise it's undone.
  Settings > Health lets you choose: ask first, fix automatically, or off. If
  Nova's engine crashes, the app restarts it.

The first run walks you through everything: your name, the look, which models
to use (with step-by-step help for each), permissions, voice, notes and
connections. Every main screen has a **?** button with a short guide.

## Install

### Windows

Download the installer from the [Releases](../../releases) page and run it. Releases have
installers for macOS (.dmg, for Apple-chip and Intel Macs) and Linux (.AppImage, .deb) too.

**[Which computers can run Nova, and which file to download](DEVICES.md)**: Windows 10
and 11, Macs on macOS 11 or newer (Apple chip or Intel), and 64-bit Linux such as
Ubuntu 20.04 or newer.

Or from source: install [Python 3.12+](https://www.python.org/downloads/) and
[Node.js 20+](https://nodejs.org), then:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python download_models.py   # wake word, and the offline voice if you want it
.venv\Scripts\python -m playwright install chromium
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

## Windows, macOS and Linux

Nova does the same things on all three, including using other apps for you:
its own pointer that never moves your mouse, pressing buttons and filling in
fields through each system's accessibility, typing any character (accents,
emoji), reading windows even when they're covered, and the stop key and
screen-corner gesture. Every change is tested on all three, including live
tests where Nova uses real apps on real Windows, macOS and Linux desktops.

What each system asks of you:

- **macOS:** switch Nova on once in System Settings > Privacy & Security, under
  Accessibility and Screen Recording. Onboarding takes you there. The stop key
  is Control+Option+Esc.
- **Linux:** works on X11 and Wayland. On Wayland the desktop asks once before
  Nova takes screenshots or presses keys in other apps, and Nova works with
  windows by their controls, since Wayland doesn't tell apps where other
  windows are. If your desktop already uses Ctrl+Alt+Esc (KDE does), Nova uses
  Ctrl+Alt+Shift+Esc and says so.
- **Installers aren't code-signed yet.** Windows shows a SmartScreen warning
  (More info, then Run anyway) and macOS asks you to right-click the app and
  choose Open the first time.

## Your data

Nova keeps everything in `~/.ai-council/` (`%USERPROFILE%\.ai-council\` on
Windows): the database, your settings and your API keys (in `.env`). Set
`NOVA_DATA_DIR` to keep it somewhere else. Nothing
there is part of this repository or of the installers.

## Try it as a new user

A separate test copy of Nova, with its own data, runs next to your real one,
so you can go through onboarding, the tour and everything else as if Nova
were brand new, without touching your chats, memory or keys:

```bash
cd frontend
npm run start:test         # the test copy (marked TEST in the title bar)
npm run start:test:fresh   # start over: the test copy forgets everything first
```

## Development

```bash
# engine tests
cd backend && .venv/bin/python -m pytest tests -q     # .venv\Scripts\python on Windows

# app, with live reload
cd frontend && npm run dev

# installers, built on the system you are packaging for
python build/prepare_python.py   # Nova's own Python (needs uv)
npm run dist:win                 # or dist:mac, dist:linux
```

Releases are built by GitHub: push a tag like `v0.2.0` and the Release
workflow builds the Windows, macOS and Linux installers, checks that each
one's engine starts, and attaches them to a GitHub release.

On Windows, don't start the engine with uvicorn's `--reload`: it switches to
an event loop that can't start subprocesses, which breaks the CLI-based
models. `scripts/dev-backend.ps1` restarts it on changes instead.

Every push is tested on Windows, macOS and Linux (see `.github/workflows`).

## License

Copyright (c) 2026 Anthony Grant. Nova is **source-available**, not open
source: the code is public so you can read it, learn from it and use it, under
the [PolyForm Strict License 1.0.0](LICENSE).

- **Free** for personal use, study, hobby projects, and for schools,
  charities, research and public organizations.
- **Not allowed** without permission: redistributing Nova, publishing changed
  versions of it, or using it for commercial purposes.
- **Commercial use, buying or other licensing**: email
  [anthonygrant08@gmail.com](mailto:anthonygrant08@gmail.com), or open an issue titled "Commercial license".

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md), including
the contributor terms. Nova is built on many open-source packages, listed with
their licenses in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
