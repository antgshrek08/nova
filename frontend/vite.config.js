import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { execSync } from "node:child_process";

// Real bug found live: this project's own `npm run dist` output
// (release/win-unpacked/resources/backend/.venv/Lib/site-packages/...) sits
// INSIDE the Vite project root and was never excluded from the dev-server's
// file watcher. That tree is 3GB+ and includes litellm's bundled proxy UI
// (thousands of static HTML files) -- Vite/chokidar was watching all of it,
// firing spurious full-page reloads for files nobody touched (confirmed live
// in vite_out.log: "page reload .../release/win-unpacked/.../litellm/proxy/
// _experimental/out/.../index.html" over and over) and burning enough
// CPU/handles that a real edit's own reload could get lost in the noise --
// the likely reason a rebuilt UI sometimes never appeared to actually
// change. `dist/` (this project's own build output) is excluded for the
// same reason even though it's much smaller.
const WATCH_IGNORED = ["**/release/**", "**/dist/**", "**/*.log"];

// Build identifier (task: "add a build identifier in About for
// verification") -- real git short hash when available, falling back to
// just a timestamp in a non-git checkout, so every dev reload and every
// packaged build carries a value that changes when the source does and can
// be checked against what's on screen.
function buildId() {
  const time = new Date().toISOString().replace("T", " ").slice(0, 16) + "Z";
  try {
    const hash = execSync("git rev-parse --short HEAD", { cwd: process.cwd() }).toString().trim();
    const dirty = execSync("git status --porcelain", { cwd: process.cwd() }).toString().trim() ? "+dirty" : "";
    return `${hash}${dirty} · ${time}`;
  } catch {
    return time;
  }
}

export default defineConfig({
  base: "./",
  plugins: [react()],
  define: {
    __NOVA_BUILD_ID__: JSON.stringify(buildId()),
  },
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      ignored: WATCH_IGNORED,
    },
  },
});
