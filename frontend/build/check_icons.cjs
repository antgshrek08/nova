// Every installer and app icon comes from the one current logo in public/
// (icon.ico for Windows, icon.png for Mac and Linux). The release build runs
// this before packaging, so an old logo can't sneak back in through a stale
// setting or file. The Windows build also checks the icon inside the built
// .exe files themselves (.github/workflows/release.yml).
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const build = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).build;
const want = {
  "win.icon": [build.win?.icon, "public/icon.ico"],
  "nsis.installerIcon": [build.nsis?.installerIcon, "public/icon.ico"],
  "nsis.uninstallerIcon": [build.nsis?.uninstallerIcon, "public/icon.ico"],
  "mac.icon": [build.mac?.icon, "public/icon.png"],
  "dmg.icon": [build.dmg?.icon, "public/icon.png"],
  "linux.icon": [build.linux?.icon, "public/icon.png"],
};
const wrong = Object.entries(want).filter(([, [is, should]]) => is !== should);
// electron-builder falls back to build/icon.* for anything not set above.
for (const ext of ["ico", "png"]) {
  const fallback = path.join(root, "build", `icon.${ext}`);
  if (fs.existsSync(fallback) && !fs.readFileSync(fallback).equals(fs.readFileSync(path.join(root, "public", `icon.${ext}`)))) {
    wrong.push([`build/icon.${ext}`, ["different from the current logo", `a copy of public/icon.${ext}`]]);
  }
}
if (wrong.length) {
  for (const [key, [is, should]] of wrong) console.error(`${key} is ${is}; it should be ${should}`);
  process.exit(1);
}
console.log("Every icon setting uses the current logo.");
