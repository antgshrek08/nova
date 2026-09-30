# Signing Nova's installers

Windows and macOS warn about any app that isn't signed by a developer whose
identity they've verified. The warnings are about who made the app, not about
what it does. They go away only with a signing certificate from Apple and one
for Windows. Linux doesn't need one.

The release workflow already knows how to sign. Add the secrets below
(GitHub > the repository > Settings > Secrets and variables > Actions > New
repository secret), push a release tag, and the installers come out signed.

## Mac: Developer ID + notarization (removes the "malware" / "can't be opened" dialogs)

1. Join the **Apple Developer Program** at developer.apple.com/programs
   ($99 a year, as an individual).
2. In Xcode (Settings > Accounts > Manage Certificates) or at
   developer.apple.com > Certificates, create a **Developer ID Application**
   certificate. Export it from Keychain Access as a `.p12` file with a password.
3. At appleid.apple.com > Sign-In and Security > App-Specific Passwords, make a
   password for "Nova notarization".
4. Add these secrets:

| Secret | Value |
|---|---|
| `MAC_CERTIFICATE_P12` | the `.p12` file, base64-encoded (`base64 -i cert.p12 \| pbcopy`) |
| `MAC_CERTIFICATE_PASSWORD` | the password you exported it with |
| `APPLE_ID` | your Apple Account email |
| `APPLE_APP_SPECIFIC_PASSWORD` | the app-specific password from step 3 |
| `APPLE_TEAM_ID` | the 10-character Team ID from developer.apple.com > Membership |

With these, every Mac build is signed with your Developer ID, sent to Apple
for notarization, and stapled. It opens with a double-click, no warnings.

## Windows: code signing (removes the SmartScreen "Windows protected your PC" screen)

Get a code signing certificate as a `.pfx` file. Options for an individual:

- A standard **OV code signing certificate** (Sectigo, SSL.com, Certum and
  others; roughly $100–300 a year).
- **Azure Trusted Signing** (about $10 a month) is the cheapest ongoing
  option, but it uses a cloud signing service instead of a `.pfx`. Ask to have
  the workflow switched over if you choose it.

| Secret | Value |
|---|---|
| `WIN_CERTIFICATE_PFX` | the `.pfx` file, base64-encoded (`[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))` in PowerShell) |
| `WIN_CERTIFICATE_PASSWORD` | its password |

A newly signed app can still see SmartScreen for a short while until enough
people have installed it; the signature is what lets that reputation build.

## Without certificates

- **Mac:** the app carries an ad-hoc signature, so it's intact. macOS still
  asks once: open Nova, choose Done, then go to System Settings > Privacy &
  Security and click **Open Anyway**.
- **Windows:** SmartScreen shows "Windows protected your PC". Click **More
  info > Run anyway**.
- **Linux:** nothing to do.
