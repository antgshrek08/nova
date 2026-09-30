// Using Nova from another device (the phone app), like a remote session.
//
// The desktop app IS the session: always live. On a phone, Nova's screens
// come from the computer Nova runs on, so this keeps track of whether that
// computer can be reached right now ("live"), remembers the last data each
// screen showed (so Memory, Academics and Agents still open when it can't),
// and gives features that need the computer one clear message instead of a
// request that silently goes nowhere.
import { useEffect, useState } from "react";
import { ACCESS_TOKEN, BACKEND_URL } from "../api.js";

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);
/** This screen is a remote: not the desktop app on the computer Nova runs on. */
export const IS_REMOTE = typeof window !== "undefined"
  && !window.electronAPI && !LOCAL_HOSTS.has(window.location.hostname);

const CHECK_MS = 8000;
const listeners = new Set();
let state = {
  remote: IS_REMOTE,
  configured: !IS_REMOTE || Boolean(ACCESS_TOKEN),
  live: !IS_REMOTE,
  checking: false,
  checkedAt: 0,
  name: "",
};
let timer = null;
let asking = null; // the "needs a live session" message, when open

function publish(patch) {
  state = { ...state, ...patch };
  for (const fn of listeners) fn(state);
}

/** Look for the computer now. Resolves to whether it answered. */
export async function checkSession() {
  if (!IS_REMOTE) return true;
  if (!state.configured) return false;
  publish({ checking: true });
  let live = false;
  let name = state.name;
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    live = res.ok;
    if (live) {
      const body = await res.json().catch(() => ({}));
      name = body.device_name || body.host || name;
    }
  } catch { live = false; }
  publish({ live, name, checking: false, checkedAt: Date.now() });
  return live;
}

function startWatching() {
  if (timer || !IS_REMOTE) return;
  // Keep a copy of the app on the phone, so it opens even when the computer is off.
  if ("serviceWorker" in navigator && window.location.pathname.startsWith("/app")) {
    navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" }).catch(() => {});
  }
  checkSession();
  timer = setInterval(checkSession, CHECK_MS);
  window.addEventListener("online", checkSession);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkSession(); });
}

export function useSession() {
  const [s, setS] = useState(state);
  useEffect(() => {
    listeners.add(setS);
    startWatching();
    setS(state);
    return () => listeners.delete(setS);
  }, []);
  return s;
}

/** Is the computer's Nova reachable right now? (Always, in the desktop app.) */
export function sessionLive() {
  return !IS_REMOTE || state.live;
}

/** Run `action` if the computer's Nova is live; otherwise say what's needed. */
export function requireLive(action, what = "This") {
  if (!IS_REMOTE || state.live) return action();
  asking = { what };
  publish({ asking });
  checkSession();
  return undefined;
}

export function closeAsk() {
  asking = null;
  publish({ asking: null });
}

// ---------------------------------------------------------------- last-known data

const SNAP = (key) => `nova.snapshot.${key}`;

/** Remember what a screen last showed (only phones need this). */
export function remember(key, data) {
  if (!IS_REMOTE) return;
  try { localStorage.setItem(SNAP(key), JSON.stringify({ at: Date.now(), data })); } catch { /* storage full or blocked */ }
}

/** { at, data } from the last time, or null. */
export function recall(key) {
  try { return JSON.parse(localStorage.getItem(SNAP(key)) || "null"); } catch { return null; }
}

export function agoText(ms) {
  const mins = Math.round((Date.now() - ms) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `${hours} h ago` : new Date(ms).toLocaleDateString([], { month: "short", day: "numeric" });
}
