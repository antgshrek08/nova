/** Per-conversation chat state that survives ChatWindow unmounting.
 *
 * Bug this fixes: "ask N.O.V.A. a question, switch tabs, come back -- no
 * response." Root cause (confirmed by reading ChatWindow.jsx + App.jsx):
 * App.jsx's <main> switches between CodeTab and the shared ChatWindow
 * instance (which Chat and Workspace both render -- see App.jsx's own
 * comment on that container), so switching to Code or Memory still genuinely
 * unmounts ChatWindow -- it isn't hidden, it's destroyed. `messages` and
 * `busy` were plain useState, which
 * dies with the component. But handleSend's streaming loop (see api.js's
 * streamChat) is a plain async function kicked off from an onClick, not tied
 * to the component's lifecycle at all -- nothing cancels it on unmount, so
 * it keeps running and keeps calling the (now-unmounted) instance's
 * setMessages/setBusy, which React silently no-ops. The backend was always
 * finishing the reply and saving it to the database correctly; the frontend
 * just had nowhere left to put it, and nothing ever told the next mount to
 * go looking for it -- so returning to the tab showed whatever the very
 * first fetch loaded, forever, even after the real answer was long done.
 *
 * Fix: keep `messages` and `busy` in a plain module-level Map keyed by
 * conversationId instead of component state, so they outlive any single
 * ChatWindow instance. useConversationMessages/useConversationBusy below are
 * drop-in replacements for useState with the exact same calling convention
 * (a value or an updater function) -- every existing setMessages(...)/
 * setBusy(...) call site in ChatWindow.jsx keeps working completely
 * unchanged; only the two declarations at the top of the component change.
 */
import { useEffect, useState } from "react";

const streams = new Map(); // conversationId -> { messages: array|null, busy: boolean, listeners: Set<fn> }
const controllers = new Map();
export function beginChatRequest(id) {
  controllers.get(id)?.abort();
  const controller = new AbortController();
  controllers.set(id, controller);
  return controller;
}
export function cancelChatRequest(id) { controllers.get(id)?.abort(); }
export function finishChatRequest(id, controller) { if (controllers.get(id) === controller) controllers.delete(id); }

function getEntry(conversationId) {
  let entry = streams.get(conversationId);
  if (!entry) {
    entry = { messages: null, busy: false, listeners: new Set() };
    streams.set(conversationId, entry);
  }
  return entry;
}

function notify(entry) {
  entry.listeners.forEach((fn) => fn());
}

/** True once this conversation has real state cached this session --
 * either mid-stream or just finished. Lets ChatWindow's conversationId
 * effect skip re-seeding messages from the backend and clobbering state
 * that's actually more current than what a fresh GET would return. */
export function hasLiveState(conversationId) {
  return conversationId != null && streams.has(conversationId) && streams.get(conversationId).messages !== null;
}

/** Sets the initial message list for a conversation loaded fresh from the
 * backend (first time this session touches this conversationId). Does
 * nothing to `busy` -- a freshly-loaded conversation is never mid-stream. */
export function seedMessages(conversationId, messages) {
  const entry = getEntry(conversationId);
  entry.messages = messages;
  notify(entry);
}

/** useState-compatible [messages, setMessages] pair, backed by the shared
 * store instead of local component state, so it keeps accumulating tokens
 * even while no ChatWindow instance is mounted to look at it. */
export function useConversationMessages(conversationId) {
  const [, forceRender] = useState(0);

  useEffect(() => {
    const entry = getEntry(conversationId);
    const listener = () => forceRender((n) => n + 1);
    entry.listeners.add(listener);
    return () => entry.listeners.delete(listener);
  }, [conversationId]);

  const entry = getEntry(conversationId);
  function setMessages(updater) {
    const target = getEntry(conversationId);
    target.messages = typeof updater === "function" ? updater(target.messages ?? []) : updater;
    notify(target);
  }
  return [entry.messages ?? [], setMessages];
}

/** Same pattern as useConversationMessages, for the "is a response still
 * generating" flag -- so returning to a conversation that's still streaming
 * in the background correctly shows busy/disabled instead of silently
 * allowing a second message into the same in-flight conversation. */
export function useConversationBusy(conversationId) {
  const [, forceRender] = useState(0);

  useEffect(() => {
    const entry = getEntry(conversationId);
    const listener = () => forceRender((n) => n + 1);
    entry.listeners.add(listener);
    return () => entry.listeners.delete(listener);
  }, [conversationId]);

  const entry = getEntry(conversationId);
  function setBusy(updater) {
    const target = getEntry(conversationId);
    target.busy = typeof updater === "function" ? updater(target.busy) : updater;
    notify(target);
  }
  return [entry.busy, setBusy];
}

/** Chat -> Code handoff (task: "chat -> code thing like cline" -- Cline's
 * Plan/Act split: plan in one mode, the plan carries over as context when
 * you switch to the mode that actually executes it). App.jsx's
 * handleSendChatToCode creates a brand-new Code-tab conversation and needs
 * to hand its opening text to whatever ChatWindow instance mounts for that
 * conversationId next -- which happens a render or two later, in a
 * completely separate component instance, so a normal prop/callback can't
 * carry it. A tiny separate module-level map (deliberately not reusing
 * `streams` above -- this is a one-shot handoff payload, not per-
 * conversation chat state) keyed by conversationId solves the same
 * "survive a remount" problem `streams` does, consumed exactly once so a
 * later real visit to that conversation never sees stale prefill text. */
const pendingHandoffs = new Map(); // conversationId -> prefill text

export function setPendingHandoff(conversationId, text) {
  pendingHandoffs.set(conversationId, text);
}

/** Reads and clears in one step -- ChatWindow calls this from its
 * conversationId-change effect; a non-null return means "prefill the input
 * box with this," and it must not fire again on a later revisit. */
export function consumePendingHandoff(conversationId) {
  const text = pendingHandoffs.get(conversationId);
  if (text !== undefined) pendingHandoffs.delete(conversationId);
  return text ?? null;
}
