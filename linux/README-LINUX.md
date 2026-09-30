# N.O.V.A. on Linux (Ubuntu, Debian, Fedora, Arch)

N.O.V.A. is fully compatible with Linux distributions.

## Quick Start (Web or Desktop)

1. **Prerequisites**:
   - Python 3.10+
   - Node.js 18+ (for Electron desktop app or UI dev)
   - Packages: `xclip` or `wl-clipboard` (for clipboard operations)

2. **Launch Nova (Backend + Web UI)**:
   ```bash
   chmod +x linux/*.sh
   ./linux/start-nova.sh
   ```
   This serves the full N.O.V.A. application on `http://127.0.0.1:8000/app/`.

3. **Packaging Desktop App (AppImage, deb, tar.gz)**:
   ```bash
   cd frontend
   npm install
   npm run dist:linux
   ```
   Outputs will be created in `frontend/release/`:
   - `Nova-<version>.AppImage`
   - `nova_<version>_amd64.deb`

## Supported Features on Linux

- **Interactive Terminal**: Fully supported via `ptyprocess` using the user's default `$SHELL` (`/bin/bash`, `/bin/zsh`, or `/bin/sh`).
- **Browser Automation & Virtual Cursor**: Fully supported with Playwright, discovering Chrome, Chromium, Brave, Edge, and Firefox across `/usr/bin`, Flatpak, and Snap.
- **Obsidian Vaults**: Auto-detected via `~/.config/obsidian/obsidian.json` or `$XDG_CONFIG_HOME/obsidian/obsidian.json`.
- **Clipboard Sync**: Seamless clipboard reading and writing using `wl-copy`/`wl-paste` on Wayland or `xclip` on X11.
- **Window Management**: Listing, focusing, and closing application windows natively supported via `wmctrl` / `xdotool`.
- **Multi-Agent Workspace & Homework Learner**: 100% feature-complete with persistent SQLite storage in `~/.ai-council/nova.db`.
