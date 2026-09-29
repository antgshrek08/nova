# Reference character integration

The existing Electron compact window now renders `Nova-Miniplayer.html` through
`MiniplayerCharacter.jsx`. Vite imports the reference as raw text into a lazy
chunk; no network resource, duplicate artwork, or generated replacement is used.
The original file is unchanged. SHA-256:
`5FC584BE47DB286BFACC378B199C20944C4749EA4B43CD416FFAABE73C0057CD`.

The wrapper removes the standalone page margins and duplicate header. All
embedded sprites, autonomous decisions, walking, peeking, sleep/wake sequences,
idle gestures, reactions, expression frames and eight mouth shapes remain in
the reference implementation. The character canvas clips movement to the compact
window, including the offstage portion of the peeking sequence.

## Connections

- `subscribeTtsPlayback` supplies the existing audio owner's HTMLAudioElement,
  analyser and optional timing cues. The character never creates or plays audio.
  Playback completion, cancellation and replacement detach the old speech hook.
- The compact renderer polls the narrow `getDesktopActivity` IPC once a second.
  Electron supplies `powerMonitor.getSystemIdleTime`, lock/unlock events and an
  initial lock-state check. Compact recording/thinking/speaking also reports busy.
  Failed reports expire through the reference's existing six-second timeout.
- Windows is not monitored for keystroke contents or screenshots by this bridge.
- Separate desktop roaming no longer starts at login. The old open-pet IPC now
  opens the compact window, and the desktop-roaming Settings switch is removed.
- Listeners, timers and character animation frames are removed on unmount.

## Verification (September 12, 2026)

Tested in the actual Electron compact window using its temporary local debugging
port, then returned to a normal launch:

- Embedded artwork loaded and rendered; captured in
  `scripts/miniplayer-reference-integrated.png`.
- Autonomous scheduler entered walking (random choice controlled for the test).
- Walking changed character position; peek action entered its sequence.
- Simulated locked/idle activity reports reached sleeping; clicking entered waking.
- All cue shapes rendered: rest, MBP, AA, EE, OH, OO, FV, L.
- Synthetic microphone/STT input drove a real clock request and real Nova TTS.
  The character entered speaking, used rest/EE/AA frames and returned to idle.
  Instrumentation counted exactly one call to audio playback.
- 57 backend tests passed. Frontend production build passed.
- Reference checksum remained unchanged across integration verification.

Reusable inspection scripts: `scripts/inspect-nova.cjs`,
`scripts/verify-miniplayer-speech.js`, `scripts/verify-miniplayer-behavior.js`.
The speech test substitutes microphone/STT input only and removes its temporary
conversation. The behavior test simulates locked reports without locking Windows.

## Limits

Current Nova TTS returns audio without phoneme timing cues. Normal mouth animation
therefore uses the reference's real-volume fallback (rest/EE/AA); all eight shapes
are preserved and verified for a future timed-cue provider. No phoneme timing is
invented from text.

The compact character follows audio owned by its renderer. Speech initiated in
the main window retains the existing cross-window audio owner; its analyser is
not mirrored into the compact renderer and its speech is not replayed there.

Actual Windows idle values were checked. Lock/unlock integration uses Electron's
native events, but verification simulated lock reports rather than locking the
user's workstation. No live-user microphone accuracy claim is made.

Launch the normal app and compact window together:
`powershell -File scripts/Start-Nova.ps1 -SkipBuild -Miniplayer`.

The frontend preserves FastAPI's returned error detail for failures that occur
before streaming begins, and reports malformed or truncated NDJSON as a
retryable Nova error. This keeps provider and startup diagnostics actionable
instead of showing only a generic HTTP status.
