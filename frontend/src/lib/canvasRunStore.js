/** Canvas node runs that survive AgentCanvas unmounting.
 *
 * The same bug chatStreamStore.js already fixed for chat, in the other place
 * it happens. AgentCanvas is mounted only while the Canvas mode is showing
 * (App.jsx), so switching to Crew, Chat or Code destroys it -- and its unmount
 * effect aborted every in-flight controller on the way out. Start a five-node
 * pipeline, glance at something else, come back to nothing.
 *
 * That abort was deliberate and its reasoning was sound: a canvas node holds
 * an open stream, and several of those running invisibly is exactly the
 * "which session was doing what" confusion the view exists to prevent. But
 * the answer to invisible work is to make it visible when you return, not to
 * destroy it -- a run that takes two minutes is precisely the one you would
 * step away from.
 *
 * So runs live here, in a module-level Map that outlives any component.
 * Status and output are written here by the run loop and read by whichever
 * AgentCanvas happens to be mounted, or none. Layout and prompts already
 * persist to disk in canvasStore.js; this is the live half, and it is
 * deliberately memory-only -- a run belongs to this session, and a backend
 * job model would be a much larger change than the problem needs.
 */
const runs = new Map(); // nodeId -> { status, output, activity, ranOn, controller, sessionId }
const listeners = new Set();

function notify() {
  for (const listener of listeners) listener();
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Everything known about a node's run, or undefined if it has never run. */
export function getRun(nodeId) {
  return runs.get(nodeId);
}

export function isRunning(nodeId) {
  return runs.get(nodeId)?.status === "running";
}

/** Node ids with a run still in flight -- what a returning canvas needs to
 * know to show the work it walked away from. */
export function runningNodeIds() {
  return [...runs.entries()].filter(([, run]) => run.status === "running").map(([id]) => id);
}

/** Merge into a node's run state and tell every listener. Shaped like the
 * patchNode it replaces so call sites read the same. */
export function patchRun(nodeId, patch) {
  const current = runs.get(nodeId) || {};
  runs.set(nodeId, { ...current, ...patch });
  notify();
}

export function beginRun(nodeId, controller) {
  // Starting a node again replaces its previous attempt, exactly as before.
  runs.get(nodeId)?.controller?.abort();
  runs.set(nodeId, {
    ...(runs.get(nodeId) || {}),
    controller,
    status: "running",
    activity: "",
    output: "",
  });
  notify();
}

export function endRun(nodeId, controller) {
  const run = runs.get(nodeId);
  // Only the attempt that is still current may clear the controller: a node
  // re-run while the old stream was closing would otherwise have its new
  // controller dropped by the old one finishing.
  if (run && run.controller === controller) {
    runs.set(nodeId, { ...run, controller: null });
    notify();
  }
}

export function stopRun(nodeId) {
  const run = runs.get(nodeId);
  if (!run) return;
  run.controller?.abort();
  runs.set(nodeId, { ...run, controller: null, status: "idle", activity: "" });
  notify();
}

export function stopAllRuns() {
  for (const nodeId of [...runs.keys()]) stopRun(nodeId);
}

/** Forget a node entirely -- called when one is deleted from the canvas. */
export function forgetRun(nodeId) {
  runs.get(nodeId)?.controller?.abort();
  runs.delete(nodeId);
  notify();
}

/** Drop runs for nodes that no longer exist, so a long session does not
 * accumulate state for deleted nodes. */
export function pruneRuns(liveNodeIds) {
  const live = new Set(liveNodeIds);
  let changed = false;
  for (const nodeId of [...runs.keys()]) {
    if (!live.has(nodeId)) {
      runs.get(nodeId)?.controller?.abort();
      runs.delete(nodeId);
      changed = true;
    }
  }
  if (changed) notify();
}
