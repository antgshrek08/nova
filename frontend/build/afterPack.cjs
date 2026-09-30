// Runs after the app is assembled, before the .dmg/.zip are made.
//
// On a Mac, when no Developer ID certificate is available (see SIGNING.md),
// electron-builder skips signing -- and a bundle changed after Electron's own
// signature reads as tampered, which macOS reports as "malware". An ad-hoc
// signature makes the bundle consistent again. It is not trusted by Gatekeeper
// the way a Developer ID signature is, but it is honest about what the app is.
const { execFileSync } = require("node:child_process");
const path = require("node:path");

// On Linux: Ubuntu 23.10 and later (and others following it) block the
// unprivileged namespaces Chromium's sandbox needs, and an AppImage can't carry
// the setuid helper that is the fallback -- so Electron aborts at launch. The
// executable becomes a small launcher that turns the Chromium sandbox off only
// in exactly that case; the .deb installs the setuid helper and keeps it.
const LINUX_LAUNCHER = `#!/bin/sh
here="$(dirname "$(readlink -f "$0")")"
helper="$here/chrome-sandbox"
restricted="$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null)"
if [ "$restricted" = 1 ] && ! { [ -u "$helper" ] && [ "$(stat -c %u "$helper" 2>/dev/null)" = 0 ]; }; then
  set -- --no-sandbox "$@"
fi
exec "$here/nova-bin" "$@"
`;

function linuxLauncher(context) {
  const fs = require("node:fs");
  const exe = path.join(context.appOutDir, context.packager.executableName);
  fs.renameSync(exe, path.join(context.appOutDir, "nova-bin"));
  fs.writeFileSync(exe, LINUX_LAUNCHER, { mode: 0o755 });
  console.log(`  • sandbox-aware launcher  ${exe}`);
}

exports.default = async function afterPack(context) {
  if (context.electronPlatformName === "linux") return linuxLauncher(context);
  if (context.electronPlatformName !== "darwin") return;
  if (process.env.CSC_LINK || process.env.CSC_NAME) return; // real signing follows
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const entitlements = path.join(__dirname, "entitlements.mac.plist");
  console.log(`  • ad-hoc signing  ${app}`);
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", "--entitlements", entitlements, app], { stdio: "inherit" });
  execFileSync("codesign", ["--verify", "--deep", "--strict", "--verbose=2", app], { stdio: "inherit" });
};
