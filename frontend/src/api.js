import { isBackendRequest } from './lib/backendOrigin.js';

// The packaged app always serves its own backend on 8000 (see electron/
// main.cjs), so that stays the default. The two overrides exist for running
// the UI against a second backend without rebuilding: VITE_BACKEND_URL at
// build/dev-server time, or ?backend=... on the URL for a one-off window.
// Only localhost origins are accepted -- a query parameter is attacker-
// controllable in principle, and this one decides where every request and
// every API key in them is sent.
const TOKEN_KEY = "nova.accessToken";

/** The access token for this device, if it has one.
 *
 * Only ever needed off the machine Nova runs on: the backend lets loopback
 * through untouched (see backend/app/access.py), so the desktop app has never
 * needed a token and still does not. A phone does.
 *
 * It arrives once as ?token=... on the link the user opens, is kept, and is
 * then stripped from the address bar -- a secret sitting in a URL ends up in
 * history, in screenshots and in anything the page later links to.
 */
function storedToken() {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("token");
    if (fromUrl) {
      localStorage.setItem(TOKEN_KEY, fromUrl);
      const clean = new URL(window.location.href);
      clean.searchParams.delete("token");
      window.history.replaceState({}, "", clean);
      return fromUrl;
    }
    return localStorage.getItem(TOKEN_KEY) || null;
  } catch {
    return null; // private window, or storage blocked
  }
}

export let ACCESS_TOKEN = storedToken();

export function setAccessToken(value) {
  ACCESS_TOKEN = value || null;
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* nothing to do about it */ }
}

// The packaged app always serves its own backend on 8000 (see electron/
// main.cjs), so that stays the default. Two overrides exist for running the
// UI against a second backend without rebuilding: VITE_BACKEND_URL at
// build/dev-server time, or ?backend=... on the URL for a one-off window.
// Only localhost origins are accepted there -- a query parameter is
// attacker-controllable in principle, and this one decides where every
// request and every API key in them is sent.
//
// The exception is the page Nova serves itself. When the frontend is loaded
// from the backend (http://<machine>:8000/app, which is how a phone reaches
// it), its own origin IS the backend -- no query parameter involved, nothing
// for an attacker to choose, and same-origin so no CORS to widen.
function resolveBackendUrl() {
  const fromQuery = new URLSearchParams(window.location.search).get("backend");
  const candidate = fromQuery || import.meta.env?.VITE_BACKEND_URL;
  if (candidate) {
    try {
      const url = new URL(candidate);
      if (url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "::1") {
        return url.origin;
      }
    } catch { /* fall through */ }
  }
  // Served by Nova itself: address the API relative to where the page came from.
  if (window.location.protocol.startsWith("http") && window.location.pathname.startsWith("/app")) {
    return window.location.origin;
  }
  return "http://localhost:8000";
}

export const BACKEND_URL = resolveBackendUrl();

// Every call in this file goes through window.fetch, and there are around a
// hundred of them. Rather than thread a header through each one -- which is
// a hundred chances to miss one, and a missed one is a request that fails
// only on the phone -- the token is attached here, to Nova's own origin only.
// Requests to anywhere else are passed through untouched, so this cannot leak
// the token to a third party.
if (typeof window !== "undefined" && window.fetch) {
  const original = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const sameBackend = isBackendRequest(input, BACKEND_URL, window.location.href);
    if (!ACCESS_TOKEN || !sameBackend) return original(input, init);
    const headers = new Headers(init.headers || (typeof input !== "string" ? input.headers : undefined));
    if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${ACCESS_TOKEN}`);
    return original(input, { ...init, headers });
  };
}

/** Shared reader for the app's NDJSON-streaming POST endpoints (/chat,
 * /models/ollama/pull): parses newline-delimited JSON as it arrives and
 * calls onEvent(event) per line, rather than waiting for the whole body. */
async function streamNdjson(url, body, onEvent, signal) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok || !response.body) {
    // FastAPI returns useful detail for validation/provider failures. Preserve
    // it instead of reducing every failure to an opaque "500 Internal Server
    // Error" banner. This is especially important when a model is offline or
    // a request is rejected before the NDJSON stream starts.
    let detail = "";
    try {
      const raw = await response.text();
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          detail = typeof parsed.detail === "string"
            ? parsed.detail
            : parsed.detail?.message || parsed.message || "";
        } catch {
          detail = raw.replace(/\s+/g, " ").trim();
        }
      }
    } catch { /* keep the status fallback below */ }
    const status = `${response.status} ${response.statusText}`.trim();
    throw new Error(detail ? `Nova could not process that request: ${detail}` : `Nova backend error (${status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try { while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let newlineIndex;
    while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) {
        try {
          onEvent(JSON.parse(line));
        } catch {
          onEvent({ type: "error", message: "Nova returned an invalid response. Please retry." });
        }
      }
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    try {
      onEvent(JSON.parse(buffer));
    } catch {
      onEvent({ type: "error", message: "Nova returned an incomplete response. Please retry." });
    }
  }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

/**
 * Streams a chat response as NDJSON lines: {type: "meta"|"token"|"error"|"done", ...}
 * Calls onEvent(event) for each parsed line as it arrives. History is no
 * longer passed from the client (Phase 2): the backend loads it from SQLite
 * via conversation_id and persists both the user message and the response.
 */
export async function streamChat(
  conversationId,
  message,
  onEvent,
  { homework = false, attachmentIds = [], overrideModelId = null, signal } = {}
) {
  await streamNdjson(
    `${BACKEND_URL}/chat`,
    {
      conversation_id: conversationId,
      message,
      homework,
      attachment_ids: attachmentIds,
      override_model_id: overrideModelId,
    },
    onEvent,
    signal
  );
}

/** Manual routing overrides -- Settings > Routing lets the user pin a
 * specific model to a category (persistent, on top of automatic routing);
 * ChatWindow's per-message model picker uses streamChat's overrideModelId
 * for a one-off pin instead. Both use the same catalog id shape listModels()
 * returns (e.g. "claude_cli:sonnet", "openrouter:<id>"). */
export async function listRoutingCategories() {
  const res = await fetch(`${BACKEND_URL}/routing/categories`);
  if (!res.ok) throw new Error(`Failed to load categories (${res.status})`);
  const data = await res.json();
  return data.categories;
}

export async function getRoutingOverrides() {
  const res = await fetch(`${BACKEND_URL}/routing/overrides`);
  if (!res.ok) throw new Error(`Failed to load routing overrides (${res.status})`);
  return res.json();
}

/** Code tab's file tree + editor pane -- all scoped server-side to the
 * current project (see backend/app/code_files.py; defaults to a built-in
 * sandbox, changes when the user opens a real folder via getWorkspaceRoot/
 * setWorkspaceRoot below). */
export async function listCodeTree(path = "") {
  const res = await fetch(`${BACKEND_URL}/code/tree?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`Failed to list files (${res.status})`);
  return res.json();
}

export async function readCodeFile(path) {
  const res = await fetch(`${BACKEND_URL}/code/file?path=${encodeURIComponent(path)}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.detail || `Failed to read file (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/** Throws a real, typed conflict error (err.conflict = {currentContent,
 * currentFingerprint}) on 409 rather than a plain message -- task: "Never
 * silently overwrite a file changed externally. Detect the conflict and
 * offer a clear comparison/reload/overwrite choice" needs the file's actual
 * current content in hand to offer that choice, not just a string. Pass
 * `force: true` for the user's own explicit "overwrite anyway". */
export async function saveCodeFile(path, content, { expectedFingerprint = null, force = false } = {}) {
  const res = await fetch(`${BACKEND_URL}/code/file`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content, expected_fingerprint: expectedFingerprint, force }),
  });
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.detail?.message || "This file was changed outside the editor.");
    err.status = 409;
    err.conflict = { currentContent: body.detail?.current_content ?? "", currentFingerprint: body.detail?.current_fingerprint ?? null };
    throw err;
  }
  if (!res.ok) throw new Error(`Failed to save file (${res.status})`);
  return res.json();
}

export async function createCodeFile(path, content = "") {
  const res = await fetch(`${BACKEND_URL}/code/file`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content, force: false }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed to create file (${res.status})`);
  }
  return res.json();
}

export async function getCodeWorkspaceRoot() {
  const res = await fetch(`${BACKEND_URL}/code/workspace-root`);
  if (!res.ok) throw new Error(`Failed to load the current project (${res.status})`);
  return res.json();
}

export async function setCodeWorkspaceRoot(path) {
  const res = await fetch(`${BACKEND_URL}/code/workspace-root`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed to open that folder (${res.status})`);
  }
  return res.json();
}

export async function resetCodeWorkspaceRoot() {
  const res = await fetch(`${BACKEND_URL}/code/workspace-root/reset`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to reset the project (${res.status})`);
  return res.json();
}

/** First-version local-Ollama-driven idle/ambient mascot behavior (task 13)
 * -- see backend/app/idle_behavior.py. Polled by NovaReactorWindow.jsx while idle. */
export async function getIdleBehavior() {
  const res = await fetch(`${BACKEND_URL}/idle/behavior`);
  if (!res.ok) throw new Error(`Idle behavior request failed (${res.status})`);
  return res.json();
}

export async function setRoutingOverride(category, modelId) {
  const res = await fetch(`${BACKEND_URL}/routing/overrides`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category, model_id: modelId }),
  });
  if (!res.ok) throw new Error(`Failed to save routing override (${res.status})`);
  return res.json();
}

/** Uploads a file to attach to the NEXT chat message (Chat tab, any
 * message -- not just Projects). Returns {id, filename, content_type,
 * size_bytes}; pass the id in streamChat's attachmentIds. Upload happens
 * immediately on file pick, before Send, so the user sees it attached (and
 * can remove it) before committing to sending the message. */
export async function uploadChatAttachment(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BACKEND_URL}/chat/attachments`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Attachment upload failed (${res.status})`);
  }
  return res.json();
}

export function chatAttachmentDownloadUrl(attachmentId) {
  return `${BACKEND_URL}/chat/attachments/${attachmentId}`;
}

/** Explicit, manual "Send to Claw" action -- dispatches `task` straight to
 * the local OpenClaw Gateway bridge (backend/app/openclaw.py), bypassing
 * routing/classification entirely. Same NDJSON event shape as streamChat
 * (meta/token/error/done), so callers can reuse the same onEvent handling;
 * there's just one "token" event since the Gateway's own API is
 * synchronous, not incremental. */
export async function sendToOpenClaw(conversationId, task, onEvent) {
  await streamNdjson(
    `${BACKEND_URL}/openclaw/send`,
    { conversation_id: conversationId, task },
    onEvent
  );
}

/** Responds to a pending gated desktop action (see backend/app/
 * desktop_registry.py). The chat request that's waiting on this action is a
 * genuinely separate, already-open HTTP request (the NDJSON /chat stream) --
 * this call just resolves the backend's asyncio.Event; the real outcome
 * (desktop_result) arrives back through that original stream, not this
 * response. */
export async function respondToDesktopAction(actionId, approved) {
  const res = await fetch(`${BACKEND_URL}/desktop/actions/${actionId}/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  return res.json();
}

export async function getSpend() {
  const res = await fetch(`${BACKEND_URL}/spend`);
  return res.json();
}

export async function getSettings() {
  const res = await fetch(`${BACKEND_URL}/settings`);
  return res.json();
}

export async function saveSettings({ geminiApiKey, openrouterApiKey }) {
  const res = await fetch(`${BACKEND_URL}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      gemini_api_key: geminiApiKey || null,
      openrouter_api_key: openrouterApiKey || null,
    }),
  });
  return res.json();
}

// --- text-to-speech --------------------------------------------------------

/** Calls the real, local Chatterbox-backed /tts endpoint and returns an
 * audio Blob (WAV). No API key -- synthesis runs on this machine. Throws
 * with the backend's real error detail (e.g. a model-load failure) rather
 * than swallowing it, since the caller needs to distinguish "TTS is
 * unavailable" from "network error" to fail gracefully in the UI. */
export async function textToSpeech(text, voiceId = null, signal = null) {
  const res = await fetch(`${BACKEND_URL}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice_id: voiceId }),
    signal,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `TTS request failed (${res.status})`);
  }
  return res.blob();
}

/** Task: spoken-summary mode -- fast, separate call that turns a full
 * reply into one short spoken sentence, used in place of the full text
 * when generating speech (see ChatWindow.jsx/NovaReactorWindow.jsx). Returns the
 * original text back if summarization fails, so a caller that doesn't
 * special-case the error just speaks the full reply as before. */
export async function summarizeForSpeech(text, signal = null) {
  if (text.trim().length <= 280 && !/```/.test(text)) return text;
  const res = await fetch(`${BACKEND_URL}/tts/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });
  if (!res.ok) return text;
  const data = await res.json().catch(() => null);
  return data?.summary || text;
}

/** Uploads one recorded mic clip (a Blob from MediaRecorder) and returns
 * {text}. Replaces the browser's native webkitSpeechRecognition, which
 * doesn't work in Electron -- see backend/app/stt.py's module docstring. */
export async function transcribeAudio(blob, signal) {
  const form = new FormData();
  form.append("file", blob, "recording.webm");
  const res = await fetch(`${BACKEND_URL}/stt/transcribe`, { method: "POST", body: form, signal });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Transcription failed (${res.status})`);
  }
  return res.json();
}

/** List of {id, name, kind} -- "default" (Chatterbox's one built-in voice)
 * plus every voice cloned from a user-uploaded reference clip. */
export async function listTtsVoices() {
  const res = await fetch(`${BACKEND_URL}/tts/voices`);
  if (!res.ok) throw new Error(`Failed to load voices (${res.status})`);
  const body = await res.json();
  const voices = body.voices || [];
  voices.cloning = body.cloning !== false; // whether "Clone a voice" can work here
  return voices;
}

/** Clones a new voice from a short reference audio clip (any common audio
 * format -- wav/mp3/m4a/etc). Returns the created {id, name, audio_filename}. */
export async function createTtsVoice(name, file) {
  const form = new FormData();
  form.append("name", name);
  form.append("file", file);
  const res = await fetch(`${BACKEND_URL}/tts/voices`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Voice upload failed (${res.status})`);
  }
  return res.json();
}

export async function deleteTtsVoice(voiceId) {
  const res = await fetch(`${BACKEND_URL}/tts/voices/${voiceId}`, { method: "DELETE" });
  return res.json();
}

// --- app settings (General/Voice) ------------------------------------------

export async function getAppSettings() {
  const res = await fetch(`${BACKEND_URL}/settings/app`);
  return res.json();
}

export async function updateAppSettings(patch) {
  const res = await fetch(`${BACKEND_URL}/settings/app`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return res.json();
}

// --- models / workspace ------------------------------------------------

// Module-level cache, not per-component state: App's header counter,
// WorkspaceTab's graph, and WorkspaceSidebar each independently mounted
// their own listModels() fetch-on-mount before this existed, so every
// switch INTO the Workspace tab re-fetched from scratch and rendered blank
// until it resolved -- the "load delay". Survives across component mounts
// (reset only on a full page reload), so a component can render the last
// known roster immediately via getCachedModels() while still kicking off
// its own fresh fetch in the background exactly as before.
let _modelsCache = null;

export function getCachedModels() {
  return _modelsCache;
}

export async function listModels() {
  const res = await fetch(`${BACKEND_URL}/models`);
  const data = await res.json();
  _modelsCache = data;
  return data;
}

export async function toggleModel(modelId, enabled) {
  const res = await fetch(`${BACKEND_URL}/models/${encodeURIComponent(modelId)}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return res.json();
}

// --- Add Model (Settings > Models > Add Model) ------------------------------

/** Browse/search OpenRouter's current free-tier roster -- the same live list
 * routing.py matches against, not a separate static one. Empty query
 * returns the full list (capped server-side). */
export async function searchOpenRouterModels(q = "") {
  const res = await fetch(`${BACKEND_URL}/models/openrouter/search?q=${encodeURIComponent(q)}`);
  return res.json();
}

export async function listCustomModels() {
  const res = await fetch(`${BACKEND_URL}/custom-models`);
  return res.json();
}

/** Ask an OpenAI-compatible endpoint what models it serves, so the id can be
 * picked rather than typed. Returns a plain array of ids. */
export async function discoverCustomModels(apiBase, apiKey) {
  const data = await jsonOrThrow(await fetch(`${BACKEND_URL}/custom-models/discover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_base: apiBase, api_key: apiKey || null }),
  }));
  return data.models || [];
}

export async function createCustomModel({ name, provider, modelId, category, apiBase, apiKey }) {
  const res = await fetch(`${BACKEND_URL}/custom-models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      provider,
      model_id: modelId,
      category,
      api_base: apiBase || null,
      api_key: apiKey || null,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed (${res.status})`);
  }
  return res.json();
}

export async function deleteCustomModel(id) {
  const res = await fetch(`${BACKEND_URL}/custom-models/${id}`, { method: "DELETE" });
  return res.json();
}

export async function toggleCustomModel(id, enabled) {
  const res = await fetch(`${BACKEND_URL}/custom-models/${id}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return res.json();
}

// --- skills --------------------------------------------------------------

export async function listSkills() {
  const res = await fetch(`${BACKEND_URL}/skills`);
  return res.json();
}

export async function createSkill({ name, description, keywords, body, preferredModelId }) {
  const res = await fetch(`${BACKEND_URL}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      description,
      keywords,
      body,
      preferred_model_id: preferredModelId || null,
    }),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.detail || `Failed (${res.status})`);
  }
  return res.json();
}

export async function deleteSkill(name) {
  const res = await fetch(`${BACKEND_URL}/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
  return res.json();
}

// --- user-directed multi-model chain (task 11) ----------------------------

export async function runAgentChain(conversationId, steps) {
  const res = await fetch(`${BACKEND_URL}/agents/chain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      steps: steps.map((s) => ({ model_id: s.modelId, instructions: s.instructions })),
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed (${res.status})`);
  }
  return res.json();
}

/** Streams real Ollama pull progress as NDJSON ({type: "progress", status,
 * completed, total} per line, then a final {type: "done"|"error"}). Only a
 * genuinely successful pull adds the model to routing -- see main.py. */
export async function pullOllamaModel({ name, category, displayName }, onEvent) {
  await streamNdjson(
    `${BACKEND_URL}/models/ollama/pull`,
    { name, category, display_name: displayName || null },
    onEvent
  );
}

// --- MCP servers ---------------------------------------------------------

export async function listMcpServers() {
  const res = await fetch(`${BACKEND_URL}/mcp/servers`);
  return res.json();
}

/** `transport` is "stdio" for a local command or "http"/"sse" for a remote
 * server reached by URL. The backend already supported remote servers with
 * OAuth; only this call and the Settings form did not, which made the official
 * hosted servers (Vercel, Hugging Face, Figma) unaddable from the UI. */
export async function createMcpServer({ name, command = "", args = [], env = {}, transport = "stdio", url = null }) {
  const res = await fetch(`${BACKEND_URL}/mcp/servers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, command, args, env, transport, url }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ? JSON.stringify(body.detail) : `Failed (${res.status})`);
  }
  return res.json();
}

export async function deleteMcpServer(serverId) {
  const res = await fetch(`${BACKEND_URL}/mcp/servers/${serverId}`, { method: "DELETE" });
  return res.json();
}

export async function toggleMcpServer(serverId, enabled) {
  const res = await fetch(`${BACKEND_URL}/mcp/servers/${serverId}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return res.json();
}

// --- Secrets (Settings > Secrets, see backend/app/secrets_store.py) --------
// There is deliberately no "read a secret" call: values go in and are only
// ever used by the backend's type_secret tool.

export async function listSecrets() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/secrets`));
}

export async function putSecret(name, value) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/secrets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, value }),
  }));
}

export async function deleteSecret(name) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/secrets/${encodeURIComponent(name)}`, { method: "DELETE" }));
}

// --- TypeSafe / Jev (Settings > Models, see backend/app/typesafe.py) -------

export async function getTypeSafeStatus() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/typesafe/status`));
}

/** One way only: the key is written to .env and never read back to the UI.
 * The backend verifies it with a real call before reporting success. */
export async function saveTypeSafeKey(apiKey) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/typesafe/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  }));
}

// --- Apple Calendar (Settings > Calendar, see backend/app/apple_calendar.py)

export async function getAppleCalendarStatus() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/apple-calendar/status`));
}

/** The app-specific password goes one way only: it is stored in the OS
 * credential vault and never read back to the UI. */
export async function saveAppleCalendarCredentials(appleId, appPassword) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/apple-calendar/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apple_id: appleId, app_password: appPassword }),
  }));
}

export async function disconnectAppleCalendar() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/apple-calendar/disconnect`, { method: "POST" }));
}

export async function listAppleCalendars() {
  const data = await jsonOrThrow(await fetch(`${BACKEND_URL}/apple-calendar/calendars`));
  return data.calendars || [];
}

export async function listAppleEvents(days = 14) {
  const data = await jsonOrThrow(
    await fetch(`${BACKEND_URL}/apple-calendar/events?days=${encodeURIComponent(days)}`)
  );
  return data.events || [];
}

// --- Canvas (Settings > Canvas, see backend/app/canvas_sync.py) ------------

export async function getCanvasStatus() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/canvas/status`));
}

export async function saveCanvasCredentials(baseUrl, accessToken) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/canvas/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_url: baseUrl, access_token: accessToken }),
  }));
}

/** The token-free path, for schools that block student access tokens.
 * `feedUrl` is a credential (its auth token is in the path), so it is sent once
 * and never read back — the status endpoint returns only the host. */
export async function saveCanvasFeed(feedUrl) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/canvas/feed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feed_url: feedUrl }),
  }));
}

export async function saveCanvasSettings(
  { enabled, syncTime, reminderHours, staleDays, pushToApple, pushCalendar } = {}
) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/canvas/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enabled, sync_time: syncTime, reminder_hours: reminderHours,
      stale_days: staleDays, push_to_apple: pushToApple, push_calendar: pushCalendar,
    }),
  }));
}

export async function runCanvasSync() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/canvas/sync`, { method: "POST" }));
}

export async function listCanvasAssignments() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/canvas/assignments`));
}

// --- ACP agents (Settings > Agents, see backend/app/acp.py) ----------------

async function jsonOrThrow(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string" ? body.detail
        : body.detail ? JSON.stringify(body.detail)
        : `Request failed (${res.status})`
    );
  }
  return res.json();
}

export async function listAcpAgents() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/acp/agents`));
}

export async function createAcpAgent({ name, command, args = [], env = {}, cwd = null }) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/acp/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, command, args, env, cwd }),
  }));
}

export async function deleteAcpAgent(agentId) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/acp/agents/${agentId}`, { method: "DELETE" }));
}

export async function toggleAcpAgent(agentId, enabled) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/acp/agents/${agentId}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  }));
}

export async function connectAcpAgent(agentId) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/acp/agents/${agentId}/connect`, { method: "POST" }));
}

/** Stream one ACP agent turn. Same NDJSON event vocabulary as streamChat. */
export function promptAcpAgent(agentId, prompt, onEvent, { sessionId = null, cwd = null, signal } = {}) {
  return streamNdjson(`${BACKEND_URL}/acp/agents/${agentId}/prompt`,
    { prompt, session_id: sessionId, cwd }, onEvent, signal);
}

/** Nova's live tool inventory and autonomy level (backend /capabilities). */
export async function getCapabilities() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/capabilities`));
}

export async function getWorkspaceStats() {
  const res = await fetch(`${BACKEND_URL}/workspace/stats`);
  return res.json();
}

// --- workspace tasks (director/team orchestration) --------------------------

export async function createWorkspaceTask(message, conversationId = null) {
  const res = await fetch(`${BACKEND_URL}/workspace/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed to create task (${res.status})`);
  }
  return res.json();
}

export async function listWorkspaceTasks(status = null) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await fetch(`${BACKEND_URL}/workspace/tasks${qs}`);
  if (!res.ok) throw new Error(`Failed to load tasks (${res.status})`);
  return res.json();
}

export async function getWorkspaceTask(taskId) {
  const res = await fetch(`${BACKEND_URL}/workspace/tasks/${taskId}`);
  if (!res.ok) throw new Error(`Failed to load task (${res.status})`);
  return res.json();
}

export async function cancelWorkspaceTask(taskId) {
  const res = await fetch(`${BACKEND_URL}/workspace/tasks/${taskId}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to cancel task (${res.status})`);
  return res.json();
}

export async function retryWorkspaceTask(taskId, confirm = false) {
  const res = await fetch(`${BACKEND_URL}/workspace/tasks/${taskId}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed to retry task (${res.status})`);
  }
  return res.json();
}

export async function listTeams() {
  const res = await fetch(`${BACKEND_URL}/workspace/teams`);
  if (!res.ok) throw new Error(`Failed to load teams (${res.status})`);
  return res.json();
}

export async function setTeamRoleModel(roleKey, modelId) {
  const res = await fetch(`${BACKEND_URL}/workspace/teams/${encodeURIComponent(roleKey)}/model`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });
  if (!res.ok) throw new Error(`Failed to set role model (${res.status})`);
  return res.json();
}

export async function setMaxHeavyWorkers(n) {
  const res = await fetch(`${BACKEND_URL}/workspace/max-heavy-workers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_heavy_workers: n }),
  });
  if (!res.ok) throw new Error(`Failed to set worker limit (${res.status})`);
  return res.json();
}

// --- conversations ---------------------------------------------------------

export async function listConversations({ tab, projectId } = {}) {
  const params = new URLSearchParams();
  if (tab) params.set("tab", tab);
  if (projectId != null) params.set("project_id", projectId);
  const qs = params.toString();
  const res = await fetch(`${BACKEND_URL}/conversations${qs ? `?${qs}` : ""}`);
  return res.json();
}

export async function createConversation({ tab, projectId = null, title = "New conversation", homework = false }) {
  const res = await fetch(`${BACKEND_URL}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tab, project_id: projectId, title, homework }),
  });
  return res.json();
}

export async function getConversation(conversationId) {
  const res = await fetch(`${BACKEND_URL}/conversations/${conversationId}`);
  return res.json();
}

export async function renameConversation(conversationId, title) {
  const res = await fetch(`${BACKEND_URL}/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return res.json();
}

export async function setConversationPinned(conversationId, pinned) {
  const res = await fetch(`${BACKEND_URL}/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pinned }),
  });
  return res.json();
}

export async function setConversationHomework(conversationId, homework) {
  const res = await fetch(`${BACKEND_URL}/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ homework }),
  });
  return res.json();
}

export async function setConversationSchedule(conversationId, scheduleLabel) {
  const res = await fetch(`${BACKEND_URL}/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(
      scheduleLabel ? { schedule_label: scheduleLabel } : { clear_schedule_label: true }
    ),
  });
  return res.json();
}

export async function deleteConversation(conversationId) {
  const res = await fetch(`${BACKEND_URL}/conversations/${conversationId}`, {
    method: "DELETE",
  });
  return res.json();
}

// --- projects ----------------------------------------------------------

export async function listProjects() {
  const res = await fetch(`${BACKEND_URL}/projects`);
  return res.json();
}

export async function createProject({ name, instructions = "" }) {
  const res = await fetch(`${BACKEND_URL}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, instructions }),
  });
  return res.json();
}

export async function getProject(projectId) {
  const res = await fetch(`${BACKEND_URL}/projects/${projectId}`);
  return res.json();
}

export async function updateProject(projectId, { name, instructions } = {}) {
  const body = {};
  if (name !== undefined) body.name = name;
  if (instructions !== undefined) body.instructions = instructions;
  const res = await fetch(`${BACKEND_URL}/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function deleteProject(projectId) {
  const res = await fetch(`${BACKEND_URL}/projects/${projectId}`, { method: "DELETE" });
  return res.json();
}

export async function listProjectFiles(projectId) {
  const res = await fetch(`${BACKEND_URL}/projects/${projectId}/files`);
  return res.json();
}

export async function uploadProjectFile(projectId, file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BACKEND_URL}/projects/${projectId}/files`, {
    method: "POST",
    body: form,
  });
  return res.json();
}

export function projectFileDownloadUrl(projectId, fileId) {
  return `${BACKEND_URL}/projects/${projectId}/files/${fileId}`;
}

export async function deleteProjectFile(projectId, fileId) {
  const res = await fetch(`${BACKEND_URL}/projects/${projectId}/files/${fileId}`, {
    method: "DELETE",
  });
  return res.json();
}

// --- memory (Phase 3) ----------------------------------------------------

export async function searchMemory(query, limit = 10) {
  const res = await fetch(
    `${BACKEND_URL}/memory/search?q=${encodeURIComponent(query)}&limit=${limit}`
  );
  return res.json();
}

export async function listMemory(limit = 50) {
  const res = await fetch(`${BACKEND_URL}/memory?limit=${limit}`);
  return res.json();
}

export async function updateMemory(memoryId, content) {
  const res = await fetch(`${BACKEND_URL}/memory/${memoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return res.json();
}

export async function deleteMemory(memoryId) {
  const res = await fetch(`${BACKEND_URL}/memory/${memoryId}`, { method: "DELETE" });
  return res.json();
}

// --- memory graph (Milestone 2) -------------------------------------------

export async function getMemoryGraph({ kinds, conversationLimit = 40 } = {}) {
  const params = new URLSearchParams();
  if (kinds?.length) params.set("kinds", kinds.join(","));
  params.set("conversation_limit", String(conversationLimit));
  const res = await fetch(`${BACKEND_URL}/memory/graph?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to load memory graph (${res.status})`);
  return res.json();
}

export async function getMemoryGraphStatus() {
  const res = await fetch(`${BACKEND_URL}/memory/graph/status`);
  if (!res.ok) throw new Error(`Failed to load graph status (${res.status})`);
  return res.json();
}

export async function reindexMemoryGraph() {
  const res = await fetch(`${BACKEND_URL}/memory/graph/reindex`, { method: "POST" });
  return res.json();
}

export async function getLegacyMigrationStatus() {
  const res = await fetch(`${BACKEND_URL}/memory/legacy-migration`);
  if (!res.ok) throw new Error(`Failed to load legacy migration status (${res.status})`);
  return res.json();
}

export async function applyLegacyMigration() {
  const res = await fetch(`${BACKEND_URL}/memory/legacy-migration`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to apply legacy migration (${res.status})`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Granted file access (backend/app/file_access.py)
//
// Separate from the /code/* helpers above, which are scoped to the one open
// project. These cover folders the user has explicitly granted so N.O.V.A. can
// read and search material that lives outside it. Credential files are refused
// server-side and reported as skipped rather than silently omitted.
// ---------------------------------------------------------------------------
async function fileAccessJson(res, what) {
  if (!res.ok) {
    // The backend returns a real explanation for a refusal (outside a granted
    // root, credential file, binary); surface that rather than a bare status.
    let detail = "";
    try {
      detail = (await res.json())?.detail || "";
    } catch {
      detail = "";
    }
    throw new Error(detail || `${what} failed (${res.status})`);
  }
  return res.json();
}

export async function listFileRoots() {
  return fileAccessJson(await fetch(`${BACKEND_URL}/files/roots`), "Loading granted folders");
}

export async function addFileRoot(path) {
  const res = await fetch(`${BACKEND_URL}/files/roots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  return fileAccessJson(res, "Granting that folder");
}

export async function removeFileRoot(path) {
  const res = await fetch(`${BACKEND_URL}/files/roots?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });
  return fileAccessJson(res, "Removing that folder");
}

export async function readGrantedFile(path) {
  return fileAccessJson(
    await fetch(`${BACKEND_URL}/files/read?path=${encodeURIComponent(path)}`),
    "Reading that file"
  );
}

export async function findGrantedFiles(q) {
  return fileAccessJson(
    await fetch(`${BACKEND_URL}/files/find?q=${encodeURIComponent(q)}`),
    "Searching file names"
  );
}

export async function searchGrantedContents(q) {
  return fileAccessJson(
    await fetch(`${BACKEND_URL}/files/search?q=${encodeURIComponent(q)}`),
    "Searching file contents"
  );
}

// --- Mascots (Settings > Models, see backend/app/mascots.py) ---------------

/** Store an image the user picked as one model's mascot. The file stays in
 * their own ~/.ai-council/mascots and never enters the repo or a build --
 * which is the whole reason this route exists rather than bundled art. */
export async function uploadMascot(name, file) {
  const form = new FormData();
  form.append("file", file);
  return jsonOrThrow(await fetch(`${BACKEND_URL}/mascots/${name}`, { method: "POST", body: form }));
}

/** Revert one mascot to the bundled art. */
export async function deleteMascot(name) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/mascots/${name}`, { method: "DELETE" }));
}

/** Open the mascots folder in Explorer, for dropping several files at once. */
export async function revealMascotDirectory() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/mascots/reveal`, { method: "POST" }));
}

// --- School / Canvas assignments (see backend/app/canvas.py) ---------------

/** Every assignment Nova has synced. Note `submitted` is meaningful only when
 * Canvas is connected by API token; over the calendar feed it is always false,
 * because the feed carries no submission data at all. */
export async function listAssignments({ includeSubmitted = false } = {}) {
  const query = includeSubmitted ? "?include_submitted=true" : "";
  const data = await jsonOrThrow(await fetch(`${BACKEND_URL}/canvas/assignments${query}`));
  return data.assignments || [];
}

// --- Ship (Code > Ship, see backend/app/ship.py) ---------------------------

/** Project, git and provider state, plus what would stop a deploy. */
export async function getShipStatus(path) {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  return jsonOrThrow(await fetch(`${BACKEND_URL}/ship/status${query}`));
}

/** Run the project's own build. Returns immediately; poll status for output. */
export async function runShipBuild(path) {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  return jsonOrThrow(await fetch(`${BACKEND_URL}/ship/build${query}`, { method: "POST" }));
}

/** 1-Click Zero-API Push to GitHub / Git remote */
export async function pushShipGit(path, remote = "origin", branch = null) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/ship/push`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, remote, branch }),
  }));
}

/** 1-Click Zero-API Deploy to Vercel, Netlify, GitHub Pages, Replit, or Lovable */
export async function deployShipProvider(path, target = "vercel") {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/ship/deploy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, target }),
  }));
}

/** Custom Extensibility: Get all user & Nova designed custom tabs */
export async function getCustomTabs() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/custom_tabs`));
}

/** Register or update a custom tab */
export async function createCustomTab(data) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/custom_tabs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}

/** Delete a custom tab */
export async function deleteCustomTab(tabId) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/custom_tabs/${encodeURIComponent(tabId)}`, {
    method: "DELETE",
  }));
}

/** Get list of connectors */
export async function getCustomConnectors() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/custom_connectors`));
}

/** Save or update a connector */
export async function saveCustomConnector(data) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/custom_connectors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}


/** Where the money actually goes, kept apart from where it does not --
 * see backend/app/costs.py's classify(). */
export async function getSpendBreakdown(days = 30) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/spend/breakdown?days=${days}`));
}


// --- User Profile & Universal Academic Hub ---

export async function getUserProfile() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/profile`));
}

export async function updateUserProfile(data) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}

export async function listCourses() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/courses`));
}

export async function createCourse(data) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/courses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}

export async function updateCourse(courseId, data) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/courses/${courseId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}

export async function deleteCourse(courseId) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/courses/${courseId}`, {
    method: "DELETE",
  }));
}

export async function analyzeCourses() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/courses/analyze`, {
    method: "POST",
  }));
}

export async function uploadSyllabus(file, courseId = null) {
  const form = new FormData();
  form.append("file", file);
  if (courseId) form.append("course_id", courseId);
  return jsonOrThrow(await fetch(`${BACKEND_URL}/syllabi/upload`, {
    method: "POST",
    body: form,
  }));
}

export async function listSyllabi(courseId = null) {
  const query = courseId ? `?course_id=${courseId}` : "";
  return jsonOrThrow(await fetch(`${BACKEND_URL}/syllabi${query}`));
}

export async function listStudyNotes(courseId = null) {
  const query = courseId ? `?course_id=${courseId}` : "";
  return jsonOrThrow(await fetch(`${BACKEND_URL}/notes${query}`));
}

export async function createStudyNote(data) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}

export async function updateStudyNote(noteId, data) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/notes/${noteId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}

export async function deleteStudyNote(noteId) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/notes/${noteId}`, {
    method: "DELETE",
  }));
}

export async function listObsidianVaults() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/obsidian/vaults`));
}

export async function detectObsidianVaults() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/obsidian/detect`));
}

export async function connectObsidianVault(name, path) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/obsidian/vaults`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, path }),
  }));
}

export async function disconnectObsidianVault(vaultId) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/obsidian/vaults/${vaultId}`, {
    method: "DELETE",
  }));
}

export async function selectDesktopFolder() {
  if (window.electronAPI?.chooseProjectFolder) {
    const res = await window.electronAPI.chooseProjectFolder();
    if (res) return res;
  }
  const res = await fetch(`${BACKEND_URL}/desktop/select-folder`, { method: "POST" }).catch(() => null);
  if (res && res.ok) {
    const data = await res.json();
    return data.path || null;
  }
  return null;
}

// --- Sentinel & Self-Healing Telemetry ---

export async function getSentinelStatus() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/sentinel/status`));
}

export async function getSentinelErrors(limit = 50) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/sentinel/errors?limit=${limit}`));
}

export async function clearSentinelErrors() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/sentinel/errors`, {
    method: "DELETE",
  }));
}

export async function runSentinelDiagnostics(testPattern = "test_selfcheck") {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/sentinel/diagnose?test_pattern=${encodeURIComponent(testPattern)}`, {
    method: "POST",
  }));
}

export async function rollbackSentinelCheckpoint() {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/sentinel/rollback`, {
    method: "POST",
  }));
}

export async function repairSentinel(filePath, newContent) {
  return jsonOrThrow(await fetch(`${BACKEND_URL}/sentinel/repair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_path: filePath, new_content: newContent }),
  }));
}
