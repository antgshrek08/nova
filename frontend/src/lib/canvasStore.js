/** Layout and wiring for the agent canvas.
 *
 * Kept out of the component because it is the part that has to survive a
 * reload: node positions, sizes, and the links between them. Persisted per
 * workspace in localStorage — the canvas is a view of live sessions, and the
 * sessions themselves are not durable, so there is nothing here worth a
 * round-trip to the backend.
 */
const STORAGE_KEY = "nova.canvas.v1";

export const NODE_W = 340;
export const NODE_H = 285; // title bar + model row + output + prompt, without scrolling

function read() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch {
    return null; // private window, cleared storage, or a shape from an older build
  }
}

export function loadCanvas() {
  const stored = read();
  return {
    nodes: Array.isArray(stored?.nodes) ? stored.nodes : [],
    links: Array.isArray(stored?.links) ? stored.links : [],
    view: stored?.view && Number.isFinite(stored.view.scale)
      ? stored.view
      : { x: 0, y: 0, scale: 1 },
  };
}

export function saveCanvas({ nodes, links, view }) {
  try {
    // Transient run state (output, status, the abort controller) is
    // deliberately dropped: a reloaded canvas should show empty nodes ready to
    // run, not a frozen transcript of a session that no longer exists.
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        nodes: nodes.map(({ id, kind, agentId, agentName, title, x, y, w, h, prompt, modelId, modelLabel, freshEachRun }) => ({
          id, kind, agentId, agentName, title, x, y, w, h, prompt, modelId, modelLabel, freshEachRun,
        })),
        links,
        view,
      })
    );
  } catch {
    /* over quota or blocked — the canvas still works, it just won't persist */
  }
}

export function newNodeId() {
  return `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/** A free slot near the middle of the current view, offset so a new node never
 * lands exactly on top of an existing one. */
export function placeNode(nodes, view, container) {
  const centreX = (container.width / 2 - view.x) / view.scale - NODE_W / 2;
  const centreY = (container.height / 2 - view.y) / view.scale - NODE_H / 2;
  let x = centreX;
  let y = centreY;
  for (let attempt = 0; attempt < 40; attempt++) {
    const clash = nodes.some((n) => Math.abs(n.x - x) < 60 && Math.abs(n.y - y) < 60);
    if (!clash) break;
    x += 40;
    y += 40;
  }
  return { x: Math.round(x), y: Math.round(y) };
}

/** Links that should fire when `nodeId` finishes, in a stable order. */
export function downstreamOf(links, nodeId) {
  return links.filter((l) => l.from === nodeId).map((l) => l.to);
}

/** Refuses a link that would create a cycle -- A -> B -> A would hand off
 * forever, each completion re-triggering the other. Checked on creation rather
 * than at run time so the canvas can say no while the user is still drawing. */
export function wouldCycle(links, from, to) {
  if (from === to) return true;
  const seen = new Set([to]);
  const queue = [to];
  while (queue.length) {
    const current = queue.shift();
    for (const next of downstreamOf(links, current)) {
      if (next === from) return true;
      if (!seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return false;
}
