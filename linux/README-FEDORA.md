# Nova on Fedora

## Start here

Copy the `Nova` folder off this drive onto the laptop, then:

```bash
cd ~/Nova
chmod +x linux/*.sh
./linux/install-fedora.sh      # once, ~10 min (most of it is the 3 GB model)
./linux/start-nova.sh          # every time after
```

It opens `http://127.0.0.1:8000/app/` in your browser. That is the whole app —
same UI as the desktop, served by Nova's own backend. There is no Electron
build to do on Linux.

## Bring your data across

The drive has `nova-data/`. Put it where Nova looks for it:

```bash
mkdir -p ~/.ai-council
cp -r /path/to/usb/nova-data/* ~/.ai-council/
```

That carries your conversations, memory, and the Canvas assignments, so School
works and Nova still knows what you told it.

## Your API keys are not on the drive

Deliberately — a USB stick with live keys on it is a bad thing to lose. Nova
runs fine without them: chat routes to the local `qwen3.5:4b` by default, which
is what the laptop will use anyway.

If you want the cloud fallbacks (Gemini, OpenRouter, TypeSafe), copy the file
yourself from the Windows machine:

```
%USERPROFILE%\.ai-council\.env   →   ~/.ai-council/.env
```

## What does not work on Linux, and why

**Window control.** "Close Discord", "focus Chrome", listing open windows — all
of it goes through the Windows API. There is no Linux equivalent wired up.

**Screenshots and mouse/keyboard control.** Off here too. `pyautogui` needs an
X display and is pinned to Windows in `requirements.txt` so it can't break the
install.

**The interactive terminal.** It runs on `pywinpty`, which is Windows-only.
Nova says so if you ask for one; everything else in the Code tab is unaffected.

None of this fails silently. Ask Nova to close something and it says so in a
sentence, rather than throwing a traceback at you.

**Everything else works**: chat, School, memory and recall, skills, the tool
loop, file reading, the phone bridge, sharing links to Nova, reading images,
and push notifications.

Verified statically: every Windows-only import in Nova's own code is lazy or
guarded, and none sits at module level, so nothing takes the backend down at
startup. What has *not* been verified is a real run on Fedora hardware — this
machine has none. The first `./linux/install-fedora.sh` is still the first
time any of it executes on Linux.

## Reading images on the laptop

Nova reads screenshots with a local vision model, `gemma3:4b`. The installer
pulls `qwen3.5:4b` for chat but not this one, since it is another 3.3 GB. Add
it when you want it:

```bash
ollama pull gemma3:4b
```

Without it, Nova falls back to a free cloud vision model, and if that is
unreachable it says it cannot see the image rather than guessing at it.

## Reaching it from your phone

Same as on the desktop — Tailscale. On the laptop:

```bash
sudo dnf install -y tailscale && sudo systemctl enable --now tailscaled
sudo tailscale up
NOVA_PHONE_ACCESS=1 ./linux/start-nova.sh
```

Then `tailscale serve --bg --https=8443 8000` and open the laptop's
`*.ts.net:8443/app/` on the phone. The access token still applies — binding to
`0.0.0.0` widens the address Nova answers on, never who is allowed in.

## Working on Nova itself

The full git repo is on the drive, history included:

```bash
cd ~/Nova && git log --oneline -5
```

Frontend changes need a rebuild before the backend serves them:

```bash
cd frontend && npm install && npm run build
```

## If something goes wrong

```bash
cd ~/Nova/backend
.venv/bin/python -c "from app import main; print('backend imports OK')"
```

That is the one command that tells you whether the problem is Nova or the
environment around it.
