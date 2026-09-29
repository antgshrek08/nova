import { BACKEND_URL } from "../api.js";

/** Shared /ws/agents connection used by the Workspace network view,
 * AgentWorkspace's original card list, and (workspace/team-orchestration
 * milestone) workspaceStore.js's live task feed. Auto-reconnects on close.
 *
 * `onOpen`, called on the *first* connect and every reconnect (task:
 * "verify... reconnect"): a real gap found while planning that
 * verification, not yet hit live -- a socket drop mid-session (e.g. the dev
 * backend restarting) reconnects fine, but any broadcasts that happened
 * server-side *during* the gap (most notably reconciliation's own
 * interrupted-task broadcasts, which fire at startup before any client has
 * had a chance to reconnect yet) would never reach this client at all,
 * since a broadcast only reaches sockets connected at the moment it's
 * sent. Without a way to say "refetch your source of truth, you may have
 * missed something," a reconnecting client's in-memory state could go
 * stale silently. Optional and additive -- existing callers that don't
 * pass it keep working exactly as before. */
const FIRST_RETRY_MS = 1000;
const MAX_RETRY_MS = 30000;

export function connectAgentSocket(onMessage, onOpen) {
  const url = BACKEND_URL.replace(/^http/, "ws") + "/ws/agents";
  let ws;
  let closedByUs = false;
  let retryMs = FIRST_RETRY_MS;
  let timer = null;

  function open() {
    ws = new WebSocket(url);
    ws.onopen = () => {
      retryMs = FIRST_RETRY_MS; // a real connection resets the backoff
      onOpen?.();
    };
    ws.onmessage = (event) => onMessage(JSON.parse(event.data));
    ws.onclose = () => {
      if (closedByUs) return;
      // Backoff, not a fixed interval. A flat 1.5s retry against a backend
      // that is down (restarting, not started yet, crashed) is a busy loop:
      // a few minutes of it produced hundreds of console errors and a steady
      // trickle of failed connections. Doubling to a 30s ceiling keeps
      // recovery quick when the backend blips and quiet when it is simply
      // not there.
      timer = setTimeout(open, retryMs);
      retryMs = Math.min(MAX_RETRY_MS, retryMs * 2);
    };
  }
  open();

  return () => {
    closedByUs = true;
    if (timer) clearTimeout(timer);
    ws?.close();
  };
}
