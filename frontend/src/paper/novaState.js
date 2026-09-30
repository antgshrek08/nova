// What Nova is doing right now, for every reactor on screen: speaking while
// real TTS audio plays, listening while the microphone is open, thinking while
// a chat turn runs, otherwise idle. Derived from the real sources, never from
// a timer.
import { useEffect, useState } from "react";
import { stopTtsAudio, subscribeTtsPlayback } from "../lib/ttsPlayback.js";

let speaking = false;
let listening = false;
let busyCount = 0;
const listeners = new Set();

function current() {
  if (speaking) return "speaking";
  if (listening) return "listening";
  if (busyCount > 0) return "thinking";
  return "idle";
}

function publish() {
  const state = current();
  listeners.forEach((fn) => fn(state));
}

subscribeTtsPlayback((playback) => {
  speaking = Boolean(playback);
  publish();
});

let hushedAt = 0;

/** Stop Nova talking right now, everywhere -- and drop any reply that was
 * still being turned into speech when the user asked for quiet. */
export function stopSpeaking() {
  hushedAt = Date.now();
  stopTtsAudio();
  window.electronAPI?.silenceVoice?.();
}

/** Was Nova told to be quiet after `since` (ms)? */
export function hushedSince(since) {
  return hushedAt >= since;
}

export function setListening(on) {
  listening = on;
  publish();
}

/** Marks a chat turn as running; returns the function that ends it. */
export function beginThinking() {
  busyCount += 1;
  publish();
  let ended = false;
  return () => {
    if (ended) return;
    ended = true;
    busyCount = Math.max(0, busyCount - 1);
    publish();
  };
}

export function useNovaState() {
  const [state, setState] = useState(current);
  useEffect(() => {
    listeners.add(setState);
    setState(current());
    return () => listeners.delete(setState);
  }, []);
  return state;
}
