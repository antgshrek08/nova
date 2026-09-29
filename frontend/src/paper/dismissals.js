// Help notes and popups the user has closed with "Got it" or "Later" stay
// closed for good -- on this computer, the phone and every later launch.
// The list lives in Nova's engine (/ui/dismissed); a local copy answers at
// once on startup and covers the moment the engine isn't reachable yet.
import { useEffect, useState } from "react";
import { BACKEND_URL } from "../api.js";

const LOCAL = (id) => `nova.dismissed.${id}`;
const PENDING = "nova.dismissed.pending";
// Where the old versions kept the same answers, so nothing reappears after updating.
const LEGACY = [["workspace.unlock", "nova.workspace.unlockSeen", "1"]];
const LEGACY_GUIDE = /^nova\.guide\.(.+)$/;

let ids = null; // Set once the engine answered
let loading = null;
const listeners = new Set();

function readLocal(id) {
  try { return localStorage.getItem(LOCAL(id)) === "1"; } catch { return false; }
}
function writeLocal(id, on) {
  try { if (on) localStorage.setItem(LOCAL(id), "1"); else localStorage.removeItem(LOCAL(id)); } catch { /* private window */ }
}
function pending() {
  try { return JSON.parse(localStorage.getItem(PENDING) || "[]"); } catch { return []; }
}
function setPending(list) {
  try { localStorage.setItem(PENDING, JSON.stringify([...new Set(list)])); } catch { /* private window */ }
}
function notify() { for (const fn of listeners) fn(); }

function legacyIds() {
  const found = [];
  try {
    for (const [id, key, value] of LEGACY) if (localStorage.getItem(key) === value) found.push(id);
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      const m = key && key.match(LEGACY_GUIDE);
      if (m && localStorage.getItem(key) === "done") found.push(`guide.${m[1]}`);
    }
  } catch { /* private window */ }
  return found;
}

function send(list) {
  if (!list.length) return Promise.resolve();
  return fetch(`${BACKEND_URL}/ui/dismissed`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: list }),
  }).then((r) => { if (!r.ok) throw new Error(String(r.status)); setPending([]); })
    .catch(() => setPending([...pending(), ...list]));
}

export function loadDismissed() {
  if (!loading) {
    loading = fetch(`${BACKEND_URL}/ui/dismissed`).then((r) => r.json()).then((d) => {
      ids = new Set(d.ids || []);
      // Dismissed earlier (old storage, or while the engine was unreachable): save them now.
      const carry = [...legacyIds(), ...pending()].filter((id) => !ids.has(id));
      carry.forEach((id) => { ids.add(id); writeLocal(id, true); });
      for (const id of ids) writeLocal(id, true);
      return send(carry);
    }).catch(() => { loading = null; }).finally(notify);
  }
  return loading;
}

/** true / false, or null while it isn't known yet (show nothing until then). */
export function isDismissed(id) {
  if (readLocal(id) || legacyIds().includes(id)) return true;
  return ids ? ids.has(id) : null;
}

export function dismiss(id) {
  writeLocal(id, true);
  if (ids) ids.add(id);
  notify();
  send([id]);
}

export function undismiss(id) {
  writeLocal(id, false);
  if (id.startsWith("guide.")) { try { localStorage.removeItem(`nova.guide.${id.slice(6)}`); } catch { /* ignore */ } }
  if (id === "workspace.unlock") { try { localStorage.removeItem("nova.workspace.unlockSeen"); } catch { /* ignore */ } }
  if (ids) ids.delete(id);
  setPending(pending().filter((p) => p !== id));
  notify();
  fetch(`${BACKEND_URL}/ui/dismissed/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => {});
}

/** [dismissed (true/false/null), dismiss, showAgain] for one note. */
export function useDismissed(id) {
  const [, tick] = useState(0);
  useEffect(() => {
    const fn = () => tick((n) => n + 1);
    listeners.add(fn);
    loadDismissed();
    return () => listeners.delete(fn);
  }, []);
  return [isDismissed(id), () => dismiss(id), () => undismiss(id)];
}
