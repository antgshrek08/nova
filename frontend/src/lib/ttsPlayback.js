// Real audio playback for ElevenLabs TTS, with a live AnalyserNode so the
// reactor's bars can be driven by actual audio energy per animation frame
// instead of a fake timer. One AudioContext is reused for the app's
// lifetime (browsers cap how many can exist, and each needs a user
// gesture to start -- reusing one avoids re-triggering that).
let audioContext = null;
let analyser = null;
let currentAudio = null;
let currentCleanup = null;
let playbackEpoch = 0;
const playbackListeners = new Set();
let playbackSnapshot = null;
function publishPlayback(value) {
  playbackSnapshot = value;
  for (const listener of playbackListeners) {
    try { listener(value); } catch (error) { console.warn("Character playback observer failed", error); }
  }
}
export function subscribeTtsPlayback(listener) {
  playbackListeners.add(listener);
  listener(playbackSnapshot);
  return () => playbackListeners.delete(listener);
}
window.electronAPI?.onStopVoiceAudio?.(() => {
  stopTtsAudio();
  window.dispatchEvent(new Event("nova-voice-interrupted"));
});

function getContext() {
  if (!audioContext) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    audioContext = new Ctor();
  }
  return audioContext;
}

/** Real bug found live: speak() fires *after* the full response streams in,
 * which can be anywhere from a couple seconds to a couple minutes later
 * (see providers.py's MCP tool-loop timing) -- by the time playTtsAudio
 * actually calls audio.play(), the browser no longer treats it as tied to
 * the user's original click/Enter keypress, and autoplay policy silently
 * blocks it (audio.play()'s promise rejects, ChatWindow.jsx's speak()
 * catches it and just logs a console warning -- from the user's side, that
 * reads as "should have spoken and didn't," with nothing visibly wrong).
 * The fix is priming here, synchronously inside the real user gesture
 * (Send click / Enter keypress -- see ChatWindow.jsx's handleSend), well
 * before the response even starts generating: once an AudioContext has
 * been resumed from a genuine gesture, browsers let it keep serving
 * programmatic playback for the rest of the page's lifetime without
 * needing a fresh gesture each time. Fire-and-forget on purpose -- the
 * caller shouldn't wait on this before proceeding with the actual send. */
export function primeAudioContext() {
  try {
    const ctx = getContext();
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
  } catch {
    // Web Audio unsupported/blocked entirely -- playTtsAudio's own
    // try/catch at the actual speak() call site handles that gracefully.
  }
}

/** Plays a TTS audio Blob for real, tapping an AnalyserNode along the way.
 * onStart fires on actual playback start (audio.onplay), onEnd fires on
 * actual completion or error -- both driven by the real HTMLAudioElement,
 * not a setTimeout. Returns the Audio element so the caller can stop() it. */
export async function playTtsAudio(blob, { onStart, onEnd, cues = [] } = {}) {
  stopTtsAudio();
  const epoch = playbackEpoch;
  if (window.electronAPI?.claimVoiceAudio && !await window.electronAPI.claimVoiceAudio()) {
    onEnd?.();
    return null;
  }
  const ctx = getContext();
  if (ctx.state === "suspended") await ctx.resume();
  if (epoch !== playbackEpoch) { onEnd?.(); return null; }

  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  currentAudio = audio;

  const source = ctx.createMediaElementSource(audio);
  const node = ctx.createAnalyser();
  node.fftSize = 64; // 32 frequency bins -- plenty for a 15-bar visualizer, cheap per-frame
  source.connect(node);
  node.connect(ctx.destination);
  analyser = node;
  publishPlayback({ audio, analyser: node, cues });

  function cleanup() {
    if (playbackSnapshot?.audio === audio) publishPlayback(null);
    source.disconnect();
    node.disconnect();
    URL.revokeObjectURL(url);
    if (analyser === node) analyser = null;
    if (currentAudio === audio) currentAudio = null;
    if (currentCleanup === cleanup) currentCleanup = null;
  }
  currentCleanup = cleanup;

  audio.onplay = () => onStart?.();
  audio.onended = () => {
    window.electronAPI?.releaseVoiceAudio?.();
    cleanup();
    onEnd?.();
  };
  audio.onerror = () => {
    window.electronAPI?.releaseVoiceAudio?.();
    cleanup();
    onEnd?.();
  };

  try {
    await audio.play();
  } catch (error) {
    window.electronAPI?.releaseVoiceAudio?.();
    cleanup();
    onEnd?.();
    throw error;
  }
  return audio;
}

export function stopTtsAudio() {
  window.electronAPI?.releaseVoiceAudio?.();
  playbackEpoch += 1;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.onended = null;
    currentAudio.onerror = null;
    currentAudio = null;
  }
  currentCleanup?.();
  analyser = null;
}

/** Real-time frequency-domain snapshot (0-255 per bin) of whatever's
 * currently playing, or null when nothing is. Called once per animation
 * frame by the reactor -- this is the actual "sync to audio" mechanism. */
export function getAudioLevels() {
  if (!analyser) return null;
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  return data;
}
