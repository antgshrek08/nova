#!/usr/bin/env bash
# Start Nova on macOS and open it in the browser. Ctrl-C stops it.
# (For the desktop app instead: cd frontend && npm start)
set -euo pipefail

NOVA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$NOVA_DIR/backend/.venv"
PORT="${NOVA_PORT:-8000}"

[ -x "$VENV/bin/python" ] || { echo "Run ./install.sh first."; exit 1; }
[ -f "$NOVA_DIR/frontend/dist/index.html" ] || (cd "$NOVA_DIR/frontend" && npm run build)

command -v ollama >/dev/null && ! pgrep -x ollama >/dev/null && {
  echo "Starting Ollama..."; (ollama serve >/dev/null 2>&1 &); sleep 2
}

cd "$NOVA_DIR/backend"

# Loopback by default. NOVA_PHONE_ACCESS=1 opens it to the Tailscale network
# for the phone; anything not on this computer still needs the access token.
HOST=127.0.0.1
[ "${NOVA_PHONE_ACCESS:-}" = "1" ] && HOST=0.0.0.0

URL="http://127.0.0.1:$PORT/app/"
echo "Nova is starting at $URL"
( sleep 3; open "$URL" >/dev/null 2>&1 || true ) &

exec "$VENV/bin/python" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
