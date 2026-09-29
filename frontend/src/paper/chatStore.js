// Chat state that outlives the Chat screen: switching tabs mid-reply keeps the
// stream running and the tokens landing here, and coming back shows them.
import { useEffect, useState } from "react";
import {
  createConversation, getAppSettings, getConversation, streamChat, summarizeForSpeech, textToSpeech,
} from "../api.js";
import { playTtsAudio, primeAudioContext, stopTtsAudio } from "../lib/ttsPlayback.js";
import { spokenText } from "../lib/spokenText.js";
import { chatStatus, stopChat } from "./paperApi.js";
import { beginThinking } from "./novaState.js";

const chats = new Map(); // id -> { messages, busy, loaded, error, controller }
let prefill = "";

/** Text to put in the composer the next time Chat opens (not sent). */
export function setPrefill(text) { prefill = text; }
export function takePrefill() { const t = prefill; prefill = ""; return t; }
const listeners = new Set();

function entry(id) {
  if (!chats.has(id)) chats.set(id, { messages: [], busy: false, loaded: false, error: "", controller: null });
  return chats.get(id);
}

function update(id, fn) {
  const e = entry(id);
  fn(e);
  e.version = (e.version || 0) + 1;
  listeners.forEach((l) => l(id));
}

export function useChat(id) {
  const [, force] = useState(0);
  useEffect(() => {
    const listener = (changed) => { if (changed === id) force((n) => n + 1); };
    listeners.add(listener);
    return () => listeners.delete(listener);
  }, [id]);
  return id == null ? { messages: [], busy: false, loaded: true, error: "" } : entry(id);
}

/** Loads a conversation's history once, and whether a turn is still running
 * on the backend (after a reload, the send button must still show Stop). */
export async function loadChat(id) {
  const e = entry(id);
  if (e.loaded || e.busy) return;
  try {
    const [conversation, status] = await Promise.all([getConversation(id), chatStatus(id).catch(() => ({ running: false }))]);
    update(id, (x) => {
      x.messages = conversation.messages || [];
      x.loaded = true;
      x.remoteRunning = Boolean(status.running);
    });
  } catch (error) {
    update(id, (x) => { x.error = error.message; x.loaded = true; });
  }
}

export async function refreshChat(id) {
  entry(id).loaded = false;
  await loadChat(id);
}

async function speakReply(text) {
  try {
    const settings = await getAppSettings();
    if (settings?.voice_replies !== true && settings?.voice_replies !== "1") return;
    const short = await summarizeForSpeech(text);
    const blob = await textToSpeech(spokenText(short));
    await playTtsAudio(blob);
  } catch (error) {
    console.warn("Voice reply unavailable", error);
  }
}

/** Sends a message. Creates the conversation first when there isn't one;
 * returns its id so the caller can select it. */
export async function sendMessage(id, text, attachments = [], { tab = "chat", onEvent, onCreated } = {}) {
  primeAudioContext(); // inside the click or Enter, so speech can play later
  stopTtsAudio();
  let conversationId = id;
  if (conversationId == null) {
    const created = await createConversation({ tab, title: text.slice(0, 60) || "New conversation" });
    conversationId = created.id;
    update(conversationId, (x) => { x.loaded = true; });
    onCreated?.(conversationId);
  }
  const controller = new AbortController();
  const endThinking = beginThinking();
  update(conversationId, (x) => {
    x.busy = true;
    x.error = "";
    x.controller = controller;
    x.messages = [...x.messages,
      { role: "user", content: text, created_at: new Date().toISOString(), attachments },
      { role: "assistant", content: "", pending: true }];
  });
  const patchReply = (fn) => update(conversationId, (x) => {
    const last = x.messages[x.messages.length - 1];
    x.messages = [...x.messages.slice(0, -1), fn({ ...last })];
  });
  let full = "";
  let failed = false;
  try {
    await streamChat(conversationId, text, (event) => {
      onEvent?.(event, conversationId);
      if (event.type === "token") {
        full += event.content || "";
        patchReply((m) => ({ ...m, content: full }));
      } else if (event.type === "meta") {
        patchReply((m) => ({ ...m, label: event.label || m.label, model: event.model || m.model }));
      } else if (event.type === "attachments") {
        patchReply((m) => ({ ...m, attachments: [...(m.attachments || []), ...(event.attachments || [])] }));
      } else if (event.type === "stopped") {
        patchReply((m) => ({ ...m, stopped: true }));
      } else if (event.type === "error") {
        failed = true;
        patchReply((m) => ({ ...m, error: event.message || "Something went wrong." }));
      }
    }, { attachmentIds: attachments.map((a) => a.id), signal: controller.signal });
  } catch (error) {
    if (error.name !== "AbortError") {
      failed = true;
      patchReply((m) => ({ ...m, error: error.message }));
    }
  } finally {
    endThinking();
    update(conversationId, (x) => {
      x.busy = false;
      x.controller = null;
      x.remoteRunning = false;
      const last = x.messages[x.messages.length - 1];
      if (last?.pending) x.messages = [...x.messages.slice(0, -1), { ...last, pending: false }];
    });
  }
  if (full && !failed) speakReply(full);
  return conversationId;
}

/** The Stop button: the backend ends the turn and keeps what was said. */
export async function stopMessage(id) {
  if (id == null) return;
  stopTtsAudio();
  try {
    await stopChat(id);
  } catch {
    entry(id).controller?.abort();
  }
  update(id, (x) => { x.remoteRunning = false; });
}
