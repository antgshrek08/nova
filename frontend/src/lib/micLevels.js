// Live input-mic analyser, same shape as ttsPlayback.js's playback analyser
// (attach/detach + getLevels()) so the reactor can read real microphone
// energy while recording -- not a fake reactive loop. Deliberately never
// wired to ctx.destination: this taps the stream for analysis only, it must
// never play the mic back out (that would be an instant feedback loop).
let micContext = null;
let micSource = null;
let micAnalyser = null;

/** Call with the exact MediaStream a recording just started on (see
 * ChatWindow.jsx's handleMicToggle). Real measurements only exist for as
 * long as this stream stays attached -- callers must call
 * detachMicAnalyser() when recording stops so getMicLevels() correctly
 * reports "no data" again rather than stale/silent readings. */
export function attachMicAnalyser(stream) {
  detachMicAnalyser();
  try {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    micContext = new Ctor();
    micSource = micContext.createMediaStreamSource(stream);
    micAnalyser = micContext.createAnalyser();
    micAnalyser.fftSize = 64;
    micSource.connect(micAnalyser);
  } catch {
    // Web Audio unavailable -- getMicLevels() below just reports null,
    // which callers already treat as "no real data, don't fake it."
    micAnalyser = null;
  }
}

export function detachMicAnalyser() {
  micSource?.disconnect();
  micSource = null;
  micAnalyser = null;
  if (micContext) {
    micContext.close().catch(() => {});
    micContext = null;
  }
}

/** Real-time frequency-domain snapshot (0-255 per bin), or null when no mic
 * is currently attached. Mirrors ttsPlayback.js's getAudioLevels() exactly
 * so the reactor can treat both the same way. */
export function getMicLevels() {
  if (!micAnalyser) return null;
  const data = new Uint8Array(micAnalyser.frequencyBinCount);
  micAnalyser.getByteFrequencyData(data);
  return data;
}
