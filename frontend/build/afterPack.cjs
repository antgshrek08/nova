// Runs after the app is assembled, before the .dmg/.zip are made.
//
// On a Mac, when no Developer ID certificate is available (see SIGNING.md),
// electron-builder skips signing -- and a bundle changed after Electron's own
// signature reads as tampered, which macOS reports as "malware". An ad-hoc
// signature makes the bundle consistent again. It is not trusted by Gatekeeper
// the way a Developer ID signature is, but it is honest about what the app is.
const { execFileSync } = require("node:child_process");
const path = require("node:path");

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "darwin") return;
  if (process.env.CSC_LINK || process.env.CSC_NAME) return; // real signing follows
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const entitlements = path.join(__dirname, "entitlements.mac.plist");
  console.log(`  • ad-hoc signing  ${app}`);
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", "--entitlements", entitlements, app], { stdio: "inherit" });
  execFileSync("codesign", ["--verify", "--deep", "--strict", "--verbose=2", app], { stdio: "inherit" });
};
