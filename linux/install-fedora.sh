#!/usr/bin/env bash
# Set Nova up on Fedora. Safe to re-run: every step checks before it acts.
#
# This installs the half of Nova that is portable -- chat, School, memory, the
# tool loop, skills, the phone bridge -- and is honest about the half that is
# not. Window control ("close Discord") is win32-only and stays off here; Nova
# will say so plainly rather than fail with a traceback.
#
# The UI is served by the backend itself at /app, so there is no Electron
# build to do and no GUI toolchain to install. Nova runs in a browser tab.

set -euo pipefail

NOVA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$NOVA_DIR/backend/.venv"
MODEL="qwen3.5:4b"
VISION_MODEL="gemma3:4b"

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m !\033[0m %s\n' "$1"; }

say "Nova will be installed from: $NOVA_DIR"

# ---------------------------------------------------------------- system deps
say "Checking system packages"
NEED=()
command -v python3 >/dev/null || NEED+=(python3)
python3 -c 'import venv' 2>/dev/null || NEED+=(python3-virtualenv)
command -v gcc >/dev/null || NEED+=(gcc)
python3 -c 'import sysconfig,os;f=sysconfig.get_paths()["include"]+"/Python.h";exit(0 if os.path.exists(f) else 1)' 2>/dev/null \
  || NEED+=(python3-devel)

if [ ${#NEED[@]} -gt 0 ]; then
  echo "Installing: ${NEED[*]}"
  sudo dnf install -y "${NEED[@]}"
else
  echo "All present."
fi

# ---------------------------------------------------------------------- ollama
# Nova's default chat model runs locally. Without it Nova still starts, but
# every reply needs a configured cloud key, so this is worth the wait.
if ! command -v ollama >/dev/null; then
  say "Installing Ollama (local models)"
  curl -fsSL https://ollama.com/install.sh | sh
else
  say "Ollama already installed"
fi

if ! systemctl is-active --quiet ollama 2>/dev/null; then
  sudo systemctl enable --now ollama 2>/dev/null || {
    warn "Could not start ollama as a service. Run 'ollama serve &' yourself before starting Nova."
  }
fi

# ------------------------------------------------------------------ python env
say "Building the Python environment"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip wheel >/dev/null

# Voice is installed separately and is allowed to fail.
#
# chatterbox-tts pulls torch -- gigabytes, and the longest and most fragile
# part of this install by far. Left in the main list, one failed wheel on a
# laptop takes the entire environment down with it and Nova does not run at
# all. Chat, School and memory do not need any of this, so they should not be
# held hostage to it: core first, so there is a working Nova within minutes,
# then voice as a bonus that reports itself if it does not land.
VOICE_PKGS='chatterbox-tts|faster-whisper|piper-tts|vosk|openwakeword'
CORE_REQ="$(mktemp)"
grep -vE "^($VOICE_PKGS)" "$NOVA_DIR/backend/requirements.txt" > "$CORE_REQ"

say "Installing Nova (core)"
"$VENV/bin/pip" install -r "$CORE_REQ"
rm -f "$CORE_REQ"

say "Installing voice (optional -- Nova runs without it)"
if "$VENV/bin/pip" install \
      chatterbox-tts==0.1.7 faster-whisper piper-tts==1.8.0 vosk==0.3.45 openwakeword; then
  echo "Voice installed."
else
  warn "Voice did not install. Nova still works -- you just type instead of talk."
  warn "Retry later with: $VENV/bin/pip install chatterbox-tts==0.1.7 faster-whisper piper-tts==1.8.0 vosk==0.3.45 openwakeword"
fi

say "Checking that Nova imports on this machine"
cd "$NOVA_DIR/backend"
"$VENV/bin/python" - <<'PY'
from app import desktop, nova_tools  # noqa: F401
missing = desktop.unavailable()
print("Nova's Python side imports cleanly.")
if missing:
    print("\nNot available on this machine (expected on Linux):")
    for key, reason in missing.items():
        print(f"  - {key}: {reason}")
    print("\nEverything else -- chat, School, memory, skills, tools -- works.")
PY

# ------------------------------------------------------------------- the model
if ! ollama list 2>/dev/null | grep -q "${MODEL%%:*}"; then
  say "Pulling $MODEL (about 3 GB, one time)"
  ollama pull "$MODEL"
else
  say "$MODEL already pulled"
fi

# Reading screenshots locally. Offered rather than assumed: it is another
# 3.3 GB, and a laptop on a hotel connection should get to decide. Declining
# does not break anything -- Nova falls back to a free cloud vision model and,
# failing that, says it cannot see the image instead of inventing a
# description of it.
if ! ollama list 2>/dev/null | grep -q "$VISION_MODEL"; then
  say "Local image reading is optional ($VISION_MODEL, 3.3 GB)"
  read -r -p "    Pull it now so Nova can read screenshots offline? [y/N] " answer </dev/tty || answer=n
  case "$answer" in
    [yY]*) ollama pull "$VISION_MODEL" ;;
    *) warn "Skipped. Run 'ollama pull $VISION_MODEL' later to enable it." ;;
  esac
else
  say "$VISION_MODEL already pulled"
fi

say "Done. Start Nova with:  $NOVA_DIR/linux/start-nova.sh"
