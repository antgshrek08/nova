# N.O.V.A. on macOS

N.O.V.A. is fully compatible with macOS (Apple Silicon M-series & Intel).

## Quick Start (Development & Direct Run)

1. **Prerequisites**:
   - Python 3.10+ (`brew install python@3.11`)
   - Node.js 18+ (`brew install node`)
   - Optional: Ollama (`brew install ollama`)

2. **Launch Nova**:
   ```bash
   chmod +x mac/start-nova.sh
   ./mac/start-nova.sh
   ```

3. **Launch Desktop App (Electron)**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## Packaging for macOS (.dmg / .zip)

To build the standalone macOS `.dmg` installer and `.zip` distribution:
```bash
cd frontend
npm install
npm run dist:mac
```
The output installers will be created in `frontend/release/`:
- `Nova-<version>.dmg` (Intel) or `Nova-<version>-arm64.dmg` (Apple chip)
- `Nova-<version>-mac.zip`

## macOS Specific Features

- **Frameless Hidden Inset Titlebar**: Integrated with native macOS traffic lights (Close, Minimize, Zoom) positioned at `x: 14, y: 14`.
- **Global Clipboard**: Native integration with `pbcopy` and `pbpaste`.
- **Obsidian Vaults**: Automatic discovery from `~/Library/Application Support/obsidian/obsidian.json`.
- **Browser Automation**: Auto-detects Chrome, Brave, Arc, Edge, Opera GX, and Firefox in `/Applications` and `~/Applications`.
- **Interactive Terminal**: Powered by `ptyprocess` with default `$SHELL` (`/bin/zsh` or `/bin/bash`).
- **Window Management**: Listing, focusing, and closing application windows natively supported via AppleScript & System Events.
