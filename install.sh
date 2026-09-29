#!/usr/bin/env bash
# Set Nova up on macOS or Linux (Ubuntu/Debian, Fedora, Arch, openSUSE).
# Safe to re-run: every step checks before it acts.
#
#   ./install.sh            core + voice (voice may fail; Nova runs without it)
#   ./install.sh --no-voice skip the voice packages (they pull PyTorch, ~2 GB)
#
# Windows uses the installer from the Releases page instead.

set -euo pipefail

NOVA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$NOVA_DIR/backend/.venv"
VOICE=1
[ "${1:-}" = "--no-voice" ] && VOICE=0

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m !\033[0m %s\n' "$1"; }
die()  { printf '\033[1;31m x\033[0m %s\n' "$1"; exit 1; }

OS="$(uname -s)"
PM=""
if [ "$OS" = "Darwin" ]; then
  command -v brew >/dev/null && PM=brew
else
  for m in apt-get dnf pacman zypper; do command -v "$m" >/dev/null && { PM=$m; break; }; done
fi

install_pkgs() {
  [ $# -eq 0 ] && return 0
  case "$PM" in
    brew)    brew install "$@" ;;
    apt-get) sudo apt-get update -qq && sudo apt-get install -y "$@" ;;
    dnf)     sudo dnf install -y "$@" ;;
    pacman)  sudo pacman -S --needed --noconfirm "$@" ;;
    zypper)  sudo zypper install -y "$@" ;;
    *)       die "Please install these yourself, then run this again: $*" ;;
  esac
}

say "Installing Nova from $NOVA_DIR ($OS)"

# ------------------------------------------------------------- system packages
say "Checking system packages"
NEED=()
PY="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3 || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)'; then
  case "$PM" in brew) NEED+=(python@3.12) ;; pacman) NEED+=(python) ;; *) NEED+=(python3) ;; esac
fi
if ! command -v node >/dev/null; then
  case "$PM" in
    brew) NEED+=(node) ;;
    dnf|zypper) NEED+=(nodejs npm) ;;
    *) NEED+=(nodejs npm) ;;
  esac
fi
if [ "$OS" != "Darwin" ]; then
  case "$PM" in
    apt-get) dpkg -s python3-venv >/dev/null 2>&1 || NEED+=(python3-venv python3-dev build-essential) ;;
    dnf)     rpm -q python3-devel >/dev/null 2>&1 || NEED+=(python3-devel gcc gcc-c++) ;;
    pacman)  command -v gcc >/dev/null || NEED+=(base-devel) ;;
    zypper)  rpm -q python3-devel >/dev/null 2>&1 || NEED+=(python3-devel gcc gcc-c++) ;;
  esac
  # Clipboard and window tools Nova uses when they are there.
  command -v xclip >/dev/null || command -v wl-copy >/dev/null || NEED+=(xclip)
  # The accessibility bus apps use to show Nova their buttons and fields.
  [ -x /usr/libexec/at-spi-bus-launcher ] || [ -x /usr/lib/at-spi2-core/at-spi-bus-launcher ] || [ -x /usr/lib/at-spi-bus-launcher ]     || NEED+=(at-spi2-core)
fi
if [ ${#NEED[@]} -gt 0 ]; then
  echo "Installing: ${NEED[*]}"
  install_pkgs "${NEED[@]}"
  PY="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)"
else
  echo "All present."
fi
echo "Python: $("$PY" --version)"

# --------------------------------------------------------------- python side
say "Building the Python environment"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip wheel >/dev/null

# Voice pulls PyTorch -- the biggest and most fragile download by far. Core
# goes in first so a failed voice wheel never leaves Nova unable to start.
VOICE_PKGS='chatterbox-tts|faster-whisper|piper-tts|vosk|setuptools'
CORE_REQ="$(mktemp)"
grep -vE "^($VOICE_PKGS)" "$NOVA_DIR/backend/requirements.txt" > "$CORE_REQ"
say "Installing Nova (core)"
"$VENV/bin/python" -m pip install -r "$CORE_REQ"
rm -f "$CORE_REQ"

say "Installing the browser Nova drives (Playwright Chromium)"
"$VENV/bin/python" -m playwright install chromium || warn "Skipped. Nova uses your own browser instead."

if [ "$VOICE" = 1 ]; then
  say "Installing voice (optional -- Nova runs without it)"
  if "$VENV/bin/python" -m pip install "setuptools<81" chatterbox-tts==0.1.7 faster-whisper "vosk>=0.3.42,<0.4"; then
    echo "Voice installed."
    "$VENV/bin/python" "$NOVA_DIR/backend/download_models.py" </dev/tty || warn "Voice models did not download. Retry: backend/.venv/bin/python backend/download_models.py"
  else
    warn "Voice did not install. Nova still works, and the online voices in Settings > Voice need nothing extra."
    warn "Retry later with: ./install.sh"
  fi
fi

if [ "$OS" != "Darwin" ] && command -v gsettings >/dev/null; then
  # GNOME: make apps publish their controls to accessibility (what lets Nova
  # press buttons and fill fields in them, like it does on Windows and macOS).
  gsettings set org.gnome.desktop.interface toolkit-accessibility true 2>/dev/null || true
fi

say "Checking that Nova starts on this machine"
(cd "$NOVA_DIR/backend" && "$VENV/bin/python" - <<'PY'
from app import main, desktop  # noqa: F401
missing = desktop.unavailable()
print("Nova's engine imports cleanly.")
if missing:
    print("\nNot available on this system (Nova says so instead of failing):")
    for key, reason in missing.items():
        print(f"  - {key}: {reason}")
PY
)

# ------------------------------------------------------------------ the app
say "Building the app"
(cd "$NOVA_DIR/frontend" && npm ci --no-audit --no-fund && npm run build)

if ! command -v ollama >/dev/null; then
  warn "Optional: Ollama runs free models on this computer. Get it from https://ollama.com"
  warn "Nova also works with cloud models; onboarding walks you through both."
fi

say "Done. Start Nova with:"
echo "    cd frontend && npm start        # the desktop app"
if [ "$OS" = "Darwin" ]; then
  echo "    ./mac/start-nova.sh             # or in your browser"
else
  echo "    ./linux/start-nova.sh           # or in your browser"
fi
