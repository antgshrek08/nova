// Backend calls the Paper interface needs beyond api.js. Requests go through
// the same fetch wrapper (api.js attaches the access token to Nova's origin).
import { BACKEND_URL } from "../api.js";

async function json(path, init) {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

const post = (path, body) => json(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

// Send/stop button (backend: app/chat_runs.py)
export const chatStatus = (conversationId) => json(`/chat/${conversationId}/status`);
export const stopChat = (conversationId) => post(`/chat/${conversationId}/stop`);

// Operator controls and durable coursework queues (app/operator_api.py)
export const operatorStatus = () => json("/operator/status");
export const operatorStop = () => post("/operator/stop");
export const operatorResume = () => post("/operator/resume");
export const cancelQueue = (id) => post(`/operator/queues/${id}/cancel`);
export const reconcileQueueItem = (id, itemId) => post(`/operator/queues/${id}/items/${itemId}/reconcile`);

// Canvas assignments cached by the sync (app/canvas_sync.py)
export const canvasAssignments = () => json("/canvas/assignments");

// Which browsers Nova can drive (app/browser_control.py)
export const browserSupport = () => json("/browser/support");

// A browser task is only live while its record is "running" AND it has shown
// activity recently: the record is written by the model, and a turn that ends
// (or a restart) without closing it must not read as Nova still working.
const STALE_SECONDS = 20 * 60;
export const taskLive = (t) => t?.status === "running"
  && Date.now() / 1000 - (t.updated_at || t.created_at || 0) < STALE_SECONDS;
export const taskUnfinished = (t) => t?.status === "interrupted" || (t?.status === "running" && !taskLive(t));
// A queue item is only being worked on while its queue holds a live lease.
export const queueItemLive = (q, i) => i?.state === "executing" && (q?.lease_until || 0) * 1000 > Date.now();

// Assignments on homework platforms other than Canvas (app/homework_discovery.py)
export const homeworkSources = () => json("/homework/sources");
export const addHomeworkSource = (portal, url) => post("/homework/sources", { portal: portal || null, url: url || null });
export const removeHomeworkSource = (id) => json(`/homework/sources/${id}`, { method: "DELETE" });
export const signInHomeworkSource = (id) => post(`/homework/sources/${id}/sign-in`);
export const discoverHomework = (sourceId) => post("/homework/discover", sourceId ? { source_id: sourceId } : {});
export const homeworkAssignments = () => json("/homework/assignments");
