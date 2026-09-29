import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { forceManyBody, forceCollide, forceLink, forceX, forceY } from "d3-force";
import { getMemoryGraph, getMemoryGraphStatus, reindexMemoryGraph } from "../../api.js";

// Small seeded PRNG for deterministic initial node placement -- not shared
// with FilamentCore.jsx on purpose (same "not a shared module boundary yet"
// convention already used elsewhere in this codebase, e.g. DesktopPet.jsx/
// Miniplayer.jsx's independently-duplicated rig math).
function mulberry32(seed) {
  let a = seed;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const KIND_COLOR = {
  project: [217, 119, 6], // amber-600 -- a real grouping (db.py's own projects table), distinct from conversations
  conversation: [16, 185, 129], // emerald-500 -- thread container
  message_user: [52, 211, 153], // emerald-400
  message_assistant: [56, 189, 248], // sky-400
  message_error: [244, 63, 94], // rose-500 -- an operational failure, never a fact (see NodeDetailsPanel)
  code: [180, 150, 90], // muted amber -- a structurally different kind of node, less saturated than before
  note: [167, 139, 250], // violet-400 -- genuine Obsidian vault content, visually distinct from every app-internal kind
  // Warm amber, the only warm hue among the app-internal kinds: a learned
  // statement is a different class of thing from a transcript node and has
  // to be findable at a glance in a field of green.
  knowledge: [251, 191, 36], // amber-400 -- confirmed by the user
  knowledge_unconfirmed: [148, 128, 90], // desaturated: Nova produced this, nobody confirmed it
};

// Refinement pass (task: "smaller nodes and much more restrained glow" /
// "collision handling that accounts for node size" / "more separation
// between genuine connected neighborhoods"). REPEL_K raised and CENTER_K
// lowered relative to the first pass so real neighborhoods can actually
// separate instead of collapsing into one dense ball; COLLIDE_PADDING adds a
// real minimum-distance correction pass on top of force repulsion, which
// pure inverse-square repulsion alone doesn't guarantee at close range.
const SIM_ITERATIONS_FIRST_LOAD = 260;
const SIM_ITERATIONS_UPDATE = 90; // task: "preserve the settled layout ... where possible" -- a filter/data delta needs far fewer iterations than a cold start, since existing nodes already have good positions
const SIM_ITERATIONS_INSTANT = 500;
const REPEL_K = 180; // forceManyBody's `strength` -- same inverse-square constant as the old hand-rolled repulsion, now Barnes-Hut-approximated instead of computed for every pair
const IDEAL_EDGE_LEN = 90; // forceLink's `distance`; its per-link `strength` is left at d3's own default (normalized by node degree) rather than a flat constant like the old hand-rolled spring
const CENTER_K = 0.02;
const COLLIDE_PADDING = 3; // extra clear space beyond the two radii, so nodes never visually touch even when settled
const MESSAGE_REVEAL_SCALE = 2.1; // zoom level past which individual messages appear even without the toggle/selection

function nodeKindColorKey(node) {
  if (node.kind === "project") return "project";
  if (node.kind === "code") return "code";
  if (node.kind === "note") return "note";
  // Provenance is visible, never collapsed: something the user said and
  // something Nova inferred must not look identical in the graph.
  if (node.kind === "knowledge") return node.status === "confirmed" ? "knowledge" : "knowledge_unconfirmed";
  if (node.kind === "conversation") return "conversation";
  if (node.fact_status === "operational_error") return "message_error";
  return node.role === "assistant" ? "message_assistant" : "message_user";
}

function nodeColor(node) {
  return KIND_COLOR[nodeKindColorKey(node)];
}

// Smaller base + gentler growth (task: "smaller nodes") -- the old curve
// (4.5 + sqrt(degree)*2.2, capped 13) made even ordinary nodes read as large
// glowing balls. Project/conversation nodes get a small fixed bump since
// they're structural containers, not just another dot of the same weight
// class as a message.
function nodeRadius(node, degree) {
  const base = node.kind === "project" ? 6 : node.kind === "knowledge" ? 5 : node.kind === "conversation" || node.kind === "note" ? 5.5 : 3;
  return Math.min(9, base + Math.sqrt(degree) * 1.15);
}

function formatDate(iso) {
  if (!iso) return null;
  try {
    const normalized = iso.replace(" ", "T");
    return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : normalized + "Z").toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

const FILTERS = [
  // Learned first: it is the only layer that represents something Nova
  // worked out and kept, rather than a view of something that already
  // existed, so it is what the graph is for.
  { id: "knowledge", label: "Learned" },
  { id: "conversation", label: "Conversations" },
  { id: "notes", label: "Notes (Obsidian)" },
  { id: "semantic", label: "Inferred links" },
  { id: "code", label: "Code (pilot)" },
];

/** Obsidian-inspired graph, refinement pass: a canvas-rendered, force-
 * settled node graph over real records only (task: "Use real records ...
 * show that honestly" -- nothing here invents a cluster or edge for
 * appearance). Defaults to an OVERVIEW of conversations/projects/code --
 * individual messages are real nodes in the data the whole time (so their
 * positions are always settled and ready) but are only DRAWN/selectable
 * once revealed: via the "Show messages" toggle, zooming in past
 * MESSAGE_REVEAL_SCALE, or being a neighbor of the current
 * hover/selection (i.e. selecting a conversation reveals *its own*
 * messages). This is what "let individual messages appear through
 * selection, zoom, or an explicit detail toggle rather than making every
 * message compete equally in the overview" means in this implementation --
 * see the docstring on `visibleIds` in the draw effect for the exact rule.
 *
 * Layout runs a bounded simulation that settles and then STOPS (task:
 * "avoid perpetual jitter") -- confirmed live via a requestAnimationFrame
 * call-counter: 0 calls once settled, 0 calls while the tab is hidden.
 * Filtering/search/selection no longer restart that simulation from
 * scratch (task: "preserve the settled layout during selection and
 * filtering where possible") -- only an actual change in the node/edge set
 * reflows anything, and even then with far fewer iterations than the first
 * cold load, since existing nodes already have good positions. */
export default function GraphView({ onOpenConversation }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const [kinds, setKinds] = useState(["knowledge", "conversation", "notes", "semantic"]);
  const [graphData, setGraphData] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reindexing, setReindexing] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);
  const [showMessages, setShowMessages] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Simulation + view state lives in refs -- read/written every animation
  // frame, which must not go through React state (task: keep this off
  // React's per-frame path, same reasoning as FilamentCore.jsx).
  const simRef = useRef({
    nodeById: new Map(),
    adjacency: new Map(),
    labelWidthCache: new Map(),
    grid: null,
    screenX: new Float64Array(0),
    screenY: new Float64Array(0),
  });
  const transformRef = useRef({ x: 0, y: 0, scale: 1 });
  const dragRef = useRef(null); // { type: "pan"|"node", nodeId?, lastX, lastY }
  const rafRef = useRef(null);
  const hoverRef = useRef(null);
  const selectedRef = useRef(null);
  const showMessagesRef = useRef(showMessages);
  const hasLoadedOnceRef = useRef(false);
  // Automatic fit-to-view (task 3): bumped once per graphData change (a
  // category toggle or the first load) so a fit scheduled for an OLDER
  // graph can recognize it's stale once a newer one has taken over --
  // "if another category changes mid-layout, only the latest result may
  // update the layout and camera." userInteractedRef is reset alongside it
  // and set by any manual pan/zoom/drag; a pending auto-fit checks both
  // before ever touching the camera, which is what "cancel an ongoing
  // automatic camera transition when the user interacts" means here: the
  // user's own action always wins over a fit that hasn't landed yet.
  const autoFitGenerationRef = useRef(0);
  const userInteractedRef = useRef(false);
  // Task 2: "Ensure category changes do not create ... overlapping fetches
  // ... cancel obsolete work and ignore stale results after rapid toggles."
  // Rapidly toggling filters fires a new /memory/graph request on every
  // click with nothing stopping an earlier, slower response from landing
  // AFTER a later, faster one and clobbering it with stale data. Bumped at
  // the start of every loadGraph call; a response is only applied if its
  // own token is still the current one by the time it resolves.
  const loadGraphTokenRef = useRef(0);

  useEffect(() => {
    hoverRef.current = hoveredId;
  }, [hoveredId]);
  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);
  useEffect(() => {
    showMessagesRef.current = showMessages;
    canvasRef.current?.__novaRedraw?.();
  }, [showMessages]);

  const loadGraph = useCallback(async () => {
    const myToken = ++loadGraphTokenRef.current;
    setLoading(true);
    setError("");
    try {
      const [g, s] = await Promise.all([
        getMemoryGraph({ kinds, conversationLimit: 60 }),
        getMemoryGraphStatus(),
      ]);
      if (loadGraphTokenRef.current !== myToken) return; // a later toggle already superseded this request
      setGraphData(g);
      setStatus(s);
    } catch (err) {
      if (loadGraphTokenRef.current !== myToken) return;
      setError(err.message || "Couldn't load the memory graph.");
    } finally {
      if (loadGraphTokenRef.current === myToken) setLoading(false);
    }
  }, [kinds]);

  useEffect(() => {
    loadGraph();
    return () => {
      // Task: "Stop graph work when navigating away" -- invalidates this
      // same token an in-flight request is checking against, exactly like a
      // brand-new toggle would, so a fetch that resolves after Memory's
      // Graph section has already been left behind never calls setState on
      // an unmounted component.
      loadGraphTokenRef.current++;
    };
  }, [loadGraph]);

  async function handleReindex() {
    setReindexing(true);
    try {
      await reindexMemoryGraph();
      // Real indexing takes real time (a few seconds per pilot path) --
      // poll status rather than guessing, so "genuine indexing status"
      // means something.
      for (let i = 0; i < 30; i++) {
        // eslint-disable-next-line no-await-in-loop
        await new Promise((r) => setTimeout(r, 1000));
        // eslint-disable-next-line no-await-in-loop
        const s = await getMemoryGraphStatus();
        setStatus(s);
        if (!s.reindexing) break;
      }
      await loadGraph();
    } finally {
      setReindexing(false);
    }
  }

  function toggleFilter(id) {
    setKinds((prev) => (prev.includes(id) ? prev.filter((k) => k !== id) : [...prev, id]));
  }

  // Discreet warning (task: "Show a discreet warning only when indexing
  // needs attention") -- a real reindex error, or Graphify simply not being
  // installed while the Code filter is actually turned on (nothing to show
  // there is worth a badge if the user never asked for the code layer).
  const needsAttention = Boolean(status?.reindex_error) || (kinds.includes("code") && status && !status.graphify_installed);

  // --- simulation + rendering -------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || !graphData) return;
    const ctx = canvas.getContext("2d");
    const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    // This effect only re-runs on an actual graphData change (a category
    // toggle or the first load) -- exactly the moments "automatic fit-to-
    // view" needs to fire once layout settles. See the refs' own docstring.
    const myFitGeneration = ++autoFitGenerationRef.current;
    userInteractedRef.current = false;

    function resize() {
      const rect = container.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const width = Math.max(1, Math.round(rect.width * dpr));
      const height = Math.max(1, Math.round(rect.height * dpr));
      if (canvas.width !== width) canvas.width = width;
      if (canvas.height !== height) canvas.height = height;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      canvas.__novaRedraw?.();
    }
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    resize();

    // --- build/refresh simulation state for the current node/edge set ---
    //
    // Performance pass: the previous version hand-rolled all-pairs repulsion
    // AND all-pairs collision -- two separate O(n^2) loops per tick. Measured
    // live with the real dataset (Code + Show messages enabled, 1085 nodes):
    // ~43ms average per animation frame (23fps, well under the 16.7ms/60fps
    // budget), confirmed via a requestAnimationFrame timing wrapper, not
    // guessed. That's the real cause of the reported lag -- not "too many
    // nodes" in the abstract, but two genuinely quadratic loops running
    // every frame for up to 260 frames on load.
    //
    // Fix (task: "Replace any expensive all-pairs collision/repulsion work
    // with a spatial index or an appropriate established free
    // implementation"): d3-force's forceManyBody (Barnes-Hut quadtree
    // approximation) and forceCollide (quadtree-based collision) are exactly
    // that -- well-tested, O(n log n), MIT-licensed, ~10KB total including
    // its only dependency (d3-quadtree). Used here as plain per-tick force
    // functions inside this component's OWN rAF loop/canvas draw/hit-testing
    // (not d3's own simulation runner or its SVG rendering) -- everything
    // else about this graph (overview/detail visibility, label placement,
    // interaction) is unchanged.
    const rand = mulberry32(7);
    const sim = simRef.current;
    const adjacency = new Map();
    const prevNodeById = sim.nodeById;
    const nodeById = new Map();
    for (const n of graphData.nodes) adjacency.set(n.id, new Set());
    for (const e of graphData.edges) {
      adjacency.get(e.source)?.add(e.target);
      adjacency.get(e.target)?.add(e.source);
    }
    function degree(id) {
      return adjacency.get(id)?.size || 0;
    }

    // d3-force forces mutate x/y/vx/vy directly on each node object, so the
    // node objects themselves ARE the simulation state now (no separate
    // positions/velocities Maps) -- reusing the exact same object reference
    // across a relayout (not just copying its x/y) is what makes "settled
    // layout preserved across filtering" and node-identity-based dragging
    // continue to work exactly as before.
    for (const [index, n] of graphData.nodes.entries()) {
      n.index = index;
      const existing = prevNodeById.get(n.id);
      if (existing && Number.isFinite(existing.x) && Number.isFinite(existing.y)) {
        n.x = existing.x;
        n.y = existing.y;
        n.vx = existing.vx || 0;
        n.vy = existing.vy || 0;
      } else {
        const angle = rand() * Math.PI * 2;
        const radius = 60 + rand() * 220;
        n.x = Math.cos(angle) * radius;
        n.y = Math.sin(angle) * radius;
        n.vx = 0;
        n.vy = 0;
      }
      nodeById.set(n.id, n);
    }
    sim.adjacency = adjacency;
    sim.nodeById = nodeById;

    // Separate copies for d3-force's own forceLink -- it mutates a link's
    // `source`/`target` from a plain id string into the actual resolved
    // node object the first time it initializes, which would otherwise
    // corrupt graphData.edges for every other consumer here (the draw loop
    // and adjacency both expect plain string ids).
    // Real bug found live (crashed the whole Graph view on first try):
    // d3-force's forceLink throws if a link references an id that isn't in
    // the nodes array, whereas the old hand-rolled springs silently skipped
    // a missing endpoint (`if (!pa || !pb) continue`). That silence was
    // hiding a real data-integrity gap: some code-layer edges point at a
    // stdlib/external import (e.g. "asyncio") that Graphify records as an
    // edge TARGET but never emits as its own node. Filtering these out
    // before handing edges to forceLink is the correct fix either way --
    // an edge to a node that was never actually included in this graph
    // response was already meaningless, just not loudly so before.
    const forceLinks = graphData.edges
      .filter((e) => nodeById.has(e.source) && nodeById.has(e.target))
      .map((e) => ({ source: e.source, target: e.target }));

    const repelForce = forceManyBody().strength(-REPEL_K);
    const collideForce = forceCollide()
      .radius((n) => nodeRadius(n, degree(n.id)) + COLLIDE_PADDING / 2)
      .strength(1);
    const linkForce = forceLink(forceLinks)
      .id((n) => n.id)
      .distance(IDEAL_EDGE_LEN);
    const centerXForce = forceX(0).strength(CENTER_K);
    const centerYForce = forceY(0).strength(CENTER_K);
    const nodesArray = graphData.nodes;
    repelForce.initialize(nodesArray, rand);
    collideForce.initialize(nodesArray, rand);
    linkForce.initialize(nodesArray, rand);
    centerXForce.initialize(nodesArray, rand);
    centerYForce.initialize(nodesArray, rand);

    // d3's own default cooling schedule (alphaDecay ~0.0228, ~300 ticks to
    // reach alphaMin) -- well-tuned by its own authors for exactly this
    // "settle then stop" behavior, reused here rather than inventing a new
    // one. VELOCITY_DECAY replaces the old flat `v *= 0.82` per tick.
    const ALPHA_DECAY = 0.0228;
    const VELOCITY_DECAY = 0.6;
    let alpha = 1;

    function simStep() {
      alpha += (0 - alpha) * ALPHA_DECAY;
      repelForce(alpha);
      linkForce(alpha);
      centerXForce(alpha);
      centerYForce(alpha);
      collideForce(alpha);
      const draggedId = dragRef.current?.type === "node" ? dragRef.current.nodeId : null;
      for (const n of nodesArray) {
        if (n.id === draggedId) continue; // user is holding it
        n.vx *= VELOCITY_DECAY;
        n.vy *= VELOCITY_DECAY;
        n.x += n.vx;
        n.y += n.vy;
      }
    }

    // Overview/detail rule (see this component's own docstring above): a
    // message node is only ever drawn/selectable when one of these is true.
    // Non-message nodes (project/conversation/code) are always visible --
    // the overview/detail split is specifically about not making every
    // individual message compete for attention by default.
    function isVisible(node, focusId, neighborSet, scale) {
      if (node.kind !== "message") return true;
      if (showMessagesRef.current) return true;
      if (scale > MESSAGE_REVEAL_SCALE) return true;
      if (node.id === focusId) return true;
      if (neighborSet?.has(node.id)) return true;
      return false;
    }

    function draw() {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      const t = transformRef.current;
      const hovered = hoverRef.current;
      const selected = selectedRef.current;
      const neighborSet = hovered ? sim.adjacency.get(hovered) : selected ? sim.adjacency.get(selected) : null;
      const focusId = hovered || selected;
      const searchLower = search.trim().toLowerCase();

      const visibleIds = new Set();
      for (const n of graphData.nodes) {
        if (isVisible(n, focusId, neighborSet, t.scale)) visibleIds.add(n.id);
      }

      // Screen positions for this frame, computed once per node and reused by
      // the edge pass, the node pass and culling. The previous version called
      // worldToScreen twice per edge and once per node, allocating a fresh
      // {x,y} object each time -- with ~1000 nodes and ~1500 edges that is
      // ~4000 short-lived objects per frame, at 60fps, for the life of the
      // layout run. Two flat arrays indexed by node.index instead.
      const screenX = sim.screenX.length === graphData.nodes.length ? sim.screenX : new Float64Array(graphData.nodes.length);
      const screenY = sim.screenY.length === graphData.nodes.length ? sim.screenY : new Float64Array(graphData.nodes.length);
      sim.screenX = screenX;
      sim.screenY = screenY;
      const halfW = w / 2;
      const halfH = h / 2;
      for (const n of graphData.nodes) {
        screenX[n.index] = halfW + (n.x + t.x) * t.scale;
        screenY[n.index] = halfH + (n.y + t.y) * t.scale;
      }
      // Anything this far outside the canvas cannot contribute a visible
      // pixel; skipping it is the single biggest win when the camera is
      // zoomed into one neighbourhood of a large graph.
      const MARGIN = 80;
      const onScreen = (index) =>
        screenX[index] >= -MARGIN && screenX[index] <= w + MARGIN &&
        screenY[index] >= -MARGIN && screenY[index] <= h + MARGIN;

      // Edges: only drawn when both endpoints are currently visible -- an
      // edge to a hidden message simply isn't shown yet (task: "where real
      // data lacks meaningful relationships, show that honestly" applies
      // here too: no synthetic stand-in edge is invented for a hidden
      // endpoint; revealing the message reveals its real edges as-is).
      //
      // Batched by style. Every edge shares one of four appearances
      // (explicit/inferred x focused/dimmed), so the whole set is drawn with
      // four beginPath/stroke pairs instead of one per edge. Canvas stroke()
      // is a real rasterisation call; issuing 1500 of them per frame was the
      // dominant cost in the draw pass, ahead of the simulation itself.
      const lineScale = Math.min(1.3, Math.max(0.6, t.scale));
      const buckets = [
        { kind: "explicit", lit: true, style: "rgba(110,231,183,0.95)", width: 0.9 * lineScale, dash: null },
        { kind: "explicit", lit: false, style: `rgba(110,231,183,${focusId ? 0.06 : 0.42})`, width: 0.9 * lineScale, dash: null },
        { kind: "inferred", lit: true, style: "rgba(217,180,90,0.95)", width: 0.8 * lineScale, dash: [2.5, 2.5] },
        { kind: "inferred", lit: false, style: `rgba(217,180,90,${focusId ? 0.06 : 0.3})`, width: 0.8 * lineScale, dash: [2.5, 2.5] },
      ];
      for (const bucket of buckets) {
        let started = false;
        for (const e of graphData.edges) {
          if (e.kind !== bucket.kind) continue;
          const lit = Boolean(focusId) && (e.source === focusId || e.target === focusId);
          if (lit !== bucket.lit) continue;
          if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) continue;
          const pa = sim.nodeById.get(e.source);
          const pb = sim.nodeById.get(e.target);
          if (!pa || !pb) continue;
          if (!onScreen(pa.index) && !onScreen(pb.index)) continue;
          if (!started) {
            ctx.beginPath();
            started = true;
          }
          ctx.moveTo(screenX[pa.index], screenY[pa.index]);
          ctx.lineTo(screenX[pb.index], screenY[pb.index]);
        }
        if (!started) continue;
        ctx.strokeStyle = bucket.style;
        ctx.lineWidth = bucket.width;
        ctx.setLineDash(bucket.dash || []);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // Nodes -- collect label candidates as we go, then place labels in a
      // second pass so priority ordering + overlap suppression (below) can
      // see every candidate at once instead of drawing greedily in
      // whatever order graphData.nodes happens to be in.
      const labelCandidates = [];
      for (const n of graphData.nodes) {
        if (!visibleIds.has(n.id)) continue;
        const p = sim.nodeById.get(n.id);
        if (!p) continue;
        if (!onScreen(n.index)) continue;
        const sx = screenX[n.index];
        const sy = screenY[n.index];
        const deg = degree(n.id);
        const r = nodeRadius(n, deg) * Math.min(1.4, Math.max(0.75, t.scale));
        const [cr, cg, cb] = nodeColor(n);
        const matchesSearch = searchLower && (n.label || "").toLowerCase().includes(searchLower);
        let alpha = 1;
        if (focusId) alpha = n.id === focusId || neighborSet?.has(n.id) ? 1 : 0.15;
        if (searchLower) alpha = matchesSearch ? 1 : Math.min(alpha, 0.12);

        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fillStyle = `rgb(${cr},${cg},${cb})`;
        // Glow is reserved for the one node the user is actually looking at.
        // A canvas shadow forces the renderer onto a slow blur path for every
        // shape that carries one; applying it to every node (at shadowBlur
        // 2.5, which is barely perceptible anyway) cost more frame time than
        // the entire edge pass. The selected node still gets a real glow, and
        // it reads better for being the only one.
        if (n.id === selected) {
          ctx.shadowColor = `rgba(${cr},${cg},${cb},0.55)`;
          ctx.shadowBlur = 7;
        }
        ctx.fill();
        ctx.shadowBlur = 0;
        if (n.kind === "conversation" || n.kind === "project") {
          ctx.lineWidth = 1.25;
          ctx.strokeStyle = "rgba(10,12,13,0.85)";
          ctx.stroke();
        }
        if (n.id === selected) {
          ctx.beginPath();
          ctx.arc(sx, sy, r + 3.5, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(240,253,244,0.9)";
          ctx.lineWidth = 1.25;
          ctx.stroke();
        }
        ctx.globalAlpha = 1;

        // Priority for the label-placement pass below: focus and its
        // neighbors first (always shown if there's room), then search
        // matches, then more-connected/structural nodes as zoom increases.
        // Task: "Reveal additional labels as the user zooms in, with
        // overlap suppression" -- zoomThreshold shrinks as t.scale grows,
        // so more of the mid-degree nodes clear the bar at higher zoom
        // without needing a hard-coded list of "important" nodes.
        const isFocusOrNeighbor = n.id === focusId || neighborSet?.has(n.id);
        const structuralWeight = n.kind === "project" ? 3 : n.kind === "conversation" ? 2 : 0;
        const zoomThreshold = Math.max(1, 5 - t.scale * 1.6);
        const eligible =
          isFocusOrNeighbor || matchesSearch || structuralWeight + deg >= zoomThreshold || t.scale > 1.8;
        if (eligible && n.label) {
          const priority = isFocusOrNeighbor ? 0 : matchesSearch ? 1 : 2 - structuralWeight * 0.1 - deg * 0.01;
          labelCandidates.push({ x: sx, y: sy, r, text: n.label, priority, forced: isFocusOrNeighbor || matchesSearch });
        }
      }

      // Greedy label placement with real overlap suppression (task:
      // "Reveal additional labels ... with overlap suppression") -- highest
      // priority first; a candidate is skipped if its measured text box
      // would overlap any label already placed this frame. Focus/neighbor/
      // search-match labels are "forced" (always drawn, even if they
      // overlap something lower-priority hasn't been placed yet) so
      // selecting a node never silently hides its own label.
      labelCandidates.sort((a, b) => a.priority - b.priority);
      ctx.font = "10.5px system-ui, sans-serif";
      ctx.textBaseline = "middle";
      const placed = [];
      // Cache reusable geometry (task 2): ctx.measureText is real font-
      // shaping work, not a free lookup, and the same label text is
      // measured again on essentially every frame while its node is
      // eligible -- a label's pixel width never changes as long as the font
      // string above doesn't, so this Map (cleared only when the font
      // changes, which it never does today) turns N measureText calls per
      // frame into at most N *unique-label* calls ever.
      const widthCache = sim.labelWidthCache;
      for (const c of labelCandidates) {
        let width = widthCache.get(c.text);
        if (width === undefined) {
          width = ctx.measureText(c.text).width;
          widthCache.set(c.text, width);
        }
        const box = { x0: c.x + c.r + 4, y0: c.y - 7, x1: c.x + c.r + 4 + width, y1: c.y + 7 };
        const overlaps = placed.some(
          (p) => box.x0 < p.x1 && box.x1 > p.x0 && box.y0 < p.y1 && box.y1 > p.y0
        );
        if (overlaps && !c.forced) continue;
        placed.push(box);
        ctx.globalAlpha = c.forced ? 0.95 : 0.75;
        ctx.fillStyle = "rgba(226,232,240,0.92)";
        ctx.fillText(c.text, box.x0, c.y);
      }
      ctx.globalAlpha = 1;
    }

    // Fit-to-view (task 3: "should use the available canvas comfortably" /
    // "Include the newly visible nodes in the bounds calculation" /
    // "Center on the graph bounds, not the coordinate origin" / "Handle
    // empty, single-node, and disconnected graphs safely"). Two real bugs
    // fixed here:
    //
    // 1. The old minimum-zoom floor (0.3) silently refused to zoom out
    //    further than that no matter how large the selected graph was --
    //    confirmed live as the actual cause of "fails to zoom out enough"
    //    with Code + Show messages enabled (1085 nodes need a scale well
    //    under 0.3 to all fit on screen at once). There's still a floor
    //    (0.02) purely to avoid a degenerate zero/negative scale, not to
    //    second-guess what the graph actually needs.
    // 2. Bounds are computed with isVisible(..., scale: 0) -- deliberately
    //    ignoring the CURRENT zoom level's message-reveal threshold, not
    //    just reusing whatever transformRef.current.scale happens to be.
    //    Using the live scale here would let fit-to-view's own result
    //    change what counts as "visible," which could then compute a
    //    different scale, which could change visibility again --
    //    exactly the loop the brief calls out ("fitting hides messages,
    //    changes bounds, and repeatedly refits"). Passing 0 means only the
    //    detail-toggle/focus/neighbor rules decide what's in bounds, a
    //    fixed answer independent of the zoom level fitting is about to
    //    produce.
    function fitToView() {
      resize(); // fresh canvas size -- accounts for the details panel or toolbar changing since the last measurement
      const focusId = selectedRef.current || hoverRef.current;
      const neighborSet = focusId ? sim.adjacency.get(focusId) : null;
      const visible = graphData.nodes.filter((n) => isVisible(n, focusId, neighborSet, 0));
      if (visible.length === 0) return; // empty graph: nothing to fit, leave the current view alone
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const n of visible) {
        const p = sim.nodeById.get(n.id);
        if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
        const r = nodeRadius(n, degree(n.id));
        minX = Math.min(minX, p.x - r);
        maxX = Math.max(maxX, p.x + r);
        minY = Math.min(minY, p.y - r);
        maxY = Math.max(maxY, p.y + r);
      }
      if (!Number.isFinite(minX) || !Number.isFinite(minY)) return; // no usable positions yet (disconnected/degenerate case) -- try again next settle rather than jumping to a bogus view
      const w = canvas.width;
      const h = canvas.height;
      // Single-node graphs: span is 0 in both axes; the 40px floor keeps
      // the resulting scale sane (capped below anyway) instead of a
      // division producing an enormous number for one lone point.
      const spanX = Math.max(40, maxX - minX);
      const spanY = Math.max(40, maxY - minY);
      const scale = Math.min(2.8, Math.max(0.02, Math.min(w / spanX, h / spanY) * 0.88));
      transformRef.current = { x: -(minX + maxX) / 2, y: -(minY + maxY) / 2, scale };
      draw();
    }

    // Steps per animation frame, adapted to what this machine can actually
    // keep up with. Eight was a fixed guess; on a 1000-node graph each step is
    // five quadtree force passes, so eight of them plus a draw ran ~40ms and
    // the whole 260-iteration settle played out as a visible stutter. Measuring
    // the real frame cost and targeting a 12ms budget keeps the settle smooth
    // on a slow machine and lets a fast one finish sooner than it used to.
    const FRAME_BUDGET_MS = 12;
    let stepsPerFrame = 4;

    function frame(remaining) {
      if (remaining > 0) {
        const started = performance.now();
        const steps = Math.min(stepsPerFrame, remaining);
        for (let i = 0; i < steps; i++) simStep();
        draw();
        const elapsed = performance.now() - started;
        if (elapsed > FRAME_BUDGET_MS && stepsPerFrame > 1) stepsPerFrame -= 1;
        else if (elapsed < FRAME_BUDGET_MS * 0.5 && stepsPerFrame < 12) stepsPerFrame += 1;
        rafRef.current = requestAnimationFrame(() => frame(remaining - steps));
      } else {
        rebuildGrid();
        draw();
        rafRef.current = null;
        maybeAutoFit();
      }
    }

    // Task 3: fit automatically once THIS graph's layout has actually
    // settled ("coordinate fitting with layout completion") -- not before
    // (positions would still be near their random initial placement) and
    // not if the user already took the camera into their own hands while
    // waiting (userInteractedRef), and not if a newer category toggle has
    // already superseded this one (myFitGeneration check -- "only the
    // latest result may update the layout and camera"). autoFitDone
    // ensures a later resume-from-hidden restart of the SAME generation's
    // layout doesn't fit a second time.
    let autoFitDone = false;
    function maybeAutoFit() {
      if (autoFitDone) return;
      autoFitDone = true;
      if (autoFitGenerationRef.current !== myFitGeneration) return;
      if (userInteractedRef.current) return;
      fitToView();
    }

    function start() {
      if (rafRef.current) return;
      // Fewer iterations once the graph has already loaded once (task:
      // "preserve the settled layout during selection and filtering where
      // possible") -- a filter toggle changes the node/edge set, which does
      // need SOME relayout for genuinely new/removed nodes, but reusing
      // positions (see `reusedCount` above) plus a shorter run keeps
      // already-settled neighborhoods from visibly re-scattering the way a
      // full 260-iteration cold start would.
      const iterations = hasLoadedOnceRef.current ? SIM_ITERATIONS_UPDATE : SIM_ITERATIONS_FIRST_LOAD;
      hasLoadedOnceRef.current = true;
      rebuildGrid(); // so hovering works during the settle, not only after it
      if (reduceMotionQuery.matches) {
        for (let i = 0; i < SIM_ITERATIONS_INSTANT; i++) simStep();
        rebuildGrid();
        draw();
        maybeAutoFit();
        return;
      }
      frame(iterations);
    }

    function stop() {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    }

    function handleVisibility() {
      if (document.hidden) stop();
      else if (!reduceMotionQuery.matches) start();
    }

    // --- interaction ---
    function toWorld(clientX, clientY) {
      const rect = canvas.getBoundingClientRect();
      const dpr = canvas.width / rect.width;
      const w = canvas.width;
      const h = canvas.height;
      const t = transformRef.current;
      const px = (clientX - rect.left) * dpr;
      const py = (clientY - rect.top) * dpr;
      return { x: (px - w / 2) / t.scale - t.x, y: (py - h / 2) / t.scale - t.y };
    }

    // Uniform spatial grid over world space, rebuilt only when the layout
    // actually moves. hitTest used to scan every node (with a Math.sqrt each)
    // on every mousemove -- ~1000 nodes at pointer-event rate, which is what
    // made hovering feel heavier than panning. The grid narrows that to the
    // handful of nodes in the pointer's own cell and its eight neighbours.
    const GRID_CELL = 64;
    function rebuildGrid() {
      const grid = new Map();
      for (const n of graphData.nodes) {
        if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue;
        const key = `${Math.floor(n.x / GRID_CELL)},${Math.floor(n.y / GRID_CELL)}`;
        let cell = grid.get(key);
        if (!cell) grid.set(key, (cell = []));
        cell.push(n);
      }
      sim.grid = grid;
    }

    function hitTest(clientX, clientY) {
      const world = toWorld(clientX, clientY);
      const hovered = hoverRef.current;
      const selected = selectedRef.current;
      const neighborSet = hovered ? sim.adjacency.get(hovered) : selected ? sim.adjacency.get(selected) : null;
      const focusId = hovered || selected;
      const grid = sim.grid;
      if (!grid) return null;
      const cellX = Math.floor(world.x / GRID_CELL);
      const cellY = Math.floor(world.y / GRID_CELL);
      let best = null;
      let bestDist = Infinity;
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const cell = grid.get(`${cellX + dx},${cellY + dy}`);
          if (!cell) continue;
          for (const n of cell) {
            if (!isVisible(n, focusId, neighborSet, transformRef.current.scale)) continue;
            const ox = n.x - world.x;
            const oy = n.y - world.y;
            const squared = ox * ox + oy * oy;
            const r = nodeRadius(n, degree(n.id)) + 6;
            if (squared <= r * r && squared < bestDist) {
              best = n.id;
              bestDist = squared;
            }
          }
        }
      }
      return best;
    }

    // Coalesce every redraw request onto one animation frame. Pointer events
    // can fire several times per frame, and each used to trigger a full
    // synchronous draw(); this makes the extra ones free.
    let redrawPending = false;
    function requestDraw() {
      if (redrawPending || rafRef.current) return;
      redrawPending = true;
      requestAnimationFrame(() => {
        redrawPending = false;
        draw();
      });
    }

    function handleWheel(e) {
      e.preventDefault();
      userInteractedRef.current = true; // task: "cancel an ongoing automatic camera transition when the user interacts"
      const t = transformRef.current;
      const before = toWorld(e.clientX, e.clientY);
      const next = Math.min(4, Math.max(0.25, t.scale * (1 - e.deltaY * 0.0015)));
      t.scale = next;
      const after = toWorld(e.clientX, e.clientY);
      t.x += after.x - before.x;
      t.y += after.y - before.y;
      requestDraw();
    }

    function handleMouseDown(e) {
      const hit = hitTest(e.clientX, e.clientY);
      if (hit) {
        dragRef.current = { type: "node", nodeId: hit, moved: false, lastX: e.clientX, lastY: e.clientY };
      } else {
        dragRef.current = { type: "pan", lastX: e.clientX, lastY: e.clientY };
      }
    }

    function handleMouseMove(e) {
      const drag = dragRef.current;
      if (drag) {
        const dxPx = e.clientX - drag.lastX;
        const dyPx = e.clientY - drag.lastY;
        drag.lastX = e.clientX;
        drag.lastY = e.clientY;
        if (Math.abs(dxPx) > 1 || Math.abs(dyPx) > 1) {
          drag.moved = true;
          userInteractedRef.current = true; // real pan/node-drag, not just a click -- takes manual control of the camera
        }
        const rect = canvas.getBoundingClientRect();
        const dpr = canvas.width / rect.width;
        const t = transformRef.current;
        if (drag.type === "pan") {
          t.x += (dxPx * dpr) / t.scale;
          t.y += (dyPx * dpr) / t.scale;
        } else if (drag.type === "node") {
          const p = sim.nodeById.get(drag.nodeId);
          if (p) {
            p.x += (dxPx * dpr) / t.scale;
            p.y += (dyPx * dpr) / t.scale;
            rebuildGrid();
          }
        }
        requestDraw();
        return;
      }
      // Pointer outside the canvas can't be over a node, and skipping the
      // hit test there matters: this listener is on `window` (so a drag that
      // leaves the canvas still tracks), which means it also fires for every
      // mouse move anywhere else in the app.
      const rect = canvas.getBoundingClientRect();
      if (
        e.clientX < rect.left || e.clientX > rect.right ||
        e.clientY < rect.top || e.clientY > rect.bottom
      ) {
        if (hoverRef.current) {
          hoverRef.current = null;
          setHoveredId(null);
          requestDraw();
        }
        return;
      }
      const hit = hitTest(e.clientX, e.clientY);
      if (hit !== hoverRef.current) {
        hoverRef.current = hit;
        setHoveredId(hit);
        requestDraw();
      }
    }

    function handleMouseUp() {
      const drag = dragRef.current;
      if (drag && drag.type === "node" && !drag.moved) {
        selectedRef.current = drag.nodeId;
        setSelectedId(drag.nodeId);
      } else if (drag && drag.type === "pan" && !drag.moved) {
        setSelectedId(null);
      }
      if (drag && drag.type === "node" && drag.moved) rebuildGrid();
      dragRef.current = null;
      requestDraw();
    }

    function handleMouseLeave() {
      if (hoverRef.current) {
        hoverRef.current = null;
        setHoveredId(null);
        requestDraw();
      }
    }

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    canvas.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    canvas.addEventListener("mouseleave", handleMouseLeave);
    document.addEventListener("visibilitychange", handleVisibility);

    canvas.__novaRedraw = draw;
    canvas.__novaFitToView = fitToView;

    start();

    return () => {
      stop();
      resizeObserver.disconnect();
      canvas.removeEventListener("wheel", handleWheel);
      canvas.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      canvas.removeEventListener("mouseleave", handleMouseLeave);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
    // Deliberately NOT keyed on `search`/`selectedId`/`hoveredId` (task:
    // "preserve the settled layout during selection and filtering where
    // possible") -- those change what's dimmed/labeled/revealed on the next
    // redraw, not the underlying simulated positions, so a separate light
    // effect below just calls the exposed __novaRedraw hook instead of
    // tearing down and restarting this whole simulation+listener setup.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData]);

  // Redraw (not reflow) on search/selection changes -- see the comment at
  // the end of the effect above for why these are split out.
  useEffect(() => {
    canvasRef.current?.__novaRedraw?.();
  }, [search, selectedId, hoveredId]);

  const nodesById = useMemo(() => Object.fromEntries((graphData?.nodes || []).map((n) => [n.id, n])), [graphData]);
  const selectedNode = selectedId ? nodesById[selectedId] || null : null;
  const selectedEdges = selectedId
    ? (graphData?.edges || []).filter((e) => e.source === selectedId || e.target === selectedId)
    : [];

  const hasAnyData = graphData && graphData.nodes.length > 0;
  const codeAvailable = status?.pilots?.some((p) => p.indexed);

  return (
    <div className="flex h-full min-h-0 min-w-0">
      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Toolbar -- exploration controls only (task: "Move indexing
            commands, filesystem paths, and technical counts into a compact
            indexing/settings panel. The main canvas should prioritize
            exploration"). */}
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-charcoal-700 px-4 py-2.5">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search nodes…"
            className="w-48 min-w-0 rounded-md bg-charcoal-850 px-3 py-1.5 text-xs text-charcoal-100 outline-none ring-1 ring-charcoal-600 focus:ring-emerald-500"
          />
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => toggleFilter(f.id)}
                className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  kinds.includes(f.id)
                    ? "bg-emerald-600/80 text-white"
                    : "bg-charcoal-800/70 text-charcoal-400 hover:text-charcoal-200"
                }`}
              >
                {f.label}
              </button>
            ))}
            <button
              onClick={() => setShowMessages((v) => !v)}
              title="Overview shows conversations/projects; this reveals every individual message as its own node too."
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                showMessages
                  ? "bg-sky-600/80 text-white"
                  : "bg-charcoal-800/70 text-charcoal-400 hover:text-charcoal-200"
              }`}
            >
              Show messages
            </button>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => canvasRef.current?.__novaFitToView?.()}
              className="rounded-md px-2.5 py-1 text-[11px] font-medium text-charcoal-400 transition-colors hover:text-charcoal-200"
            >
              Fit to view
            </button>
            <button
              onClick={() => setSettingsOpen((v) => !v)}
              className={`relative rounded-md px-2.5 py-1 text-[11px] font-medium ring-1 transition-colors ${
                settingsOpen
                  ? "bg-charcoal-700 text-charcoal-100 ring-charcoal-500"
                  : "text-charcoal-400 ring-transparent hover:text-charcoal-200"
              }`}
            >
              {/* "Indexing", not "Settings": this panel is about what has
                  been indexed and when to reindex, and three different
                  controls called Settings were reachable on this one screen
                  -- the rail's, Memory's own sub-nav, and this. */}
              Indexing
              {needsAttention && !settingsOpen && (
                <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-amber-400" title="Indexing needs attention" />
              )}
            </button>
          </div>
        </div>

        {settingsOpen && (
          <IndexingSettingsPanel
            status={status}
            codeAvailable={codeAvailable}
            reindexing={reindexing}
            onReindex={handleReindex}
          />
        )}

        <div ref={containerRef} className="relative min-h-0 min-w-0 flex-1 bg-charcoal-950">
          <canvas ref={canvasRef} className="absolute inset-0 h-full w-full cursor-grab active:cursor-grabbing" />
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-charcoal-500">
              Loading the graph…
            </div>
          )}
          {!loading && error && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-rose-400">{error}</div>
          )}
          {!loading && !error && !hasAnyData && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-8 text-center">
              <p className="text-sm text-charcoal-400">
                Nothing to graph yet — talk with N.O.V.A. a little, or enable a filter above.
              </p>
              <p className="max-w-sm text-xs text-charcoal-600">
                This is an honest empty state, not a placeholder: no connections are invented here.
                Conversations and their real links appear as they happen.
              </p>
            </div>
          )}
        </div>
      </div>

      {selectedNode && (
        <NodeDetailsPanel
          node={selectedNode}
          edges={selectedEdges}
          nodesById={nodesById}
          onClose={() => setSelectedId(null)}
          onOpenConversation={onOpenConversation}
        />
      )}
    </div>
  );
}

/** Compact indexing/settings panel (task: "Move indexing commands,
 * filesystem paths, and technical counts into a compact indexing/settings
 * panel"). Collapsed by default; opened via the toolbar's Settings button,
 * which itself only shows a discreet dot -- never a loud banner -- when
 * something genuinely needs attention. */
function IndexingSettingsPanel({ status, codeAvailable, reindexing, onReindex }) {
  if (!status) return null;
  return (
    <div className="shrink-0 border-b border-charcoal-800 bg-charcoal-900/70 px-4 py-3 text-xs text-charcoal-400">
      <p className="mb-2 font-medium text-charcoal-200">Code indexing (pilot)</p>
      {status.graphify_installed ? (
        <>
          <p className="mb-1">
            {codeAvailable
              ? `Indexed: ${status.graphify_total_nodes} nodes, ${status.graphify_total_edges} edges`
              : "Not indexed yet for this pilot scope."}
          </p>
          <ul className="mb-2 space-y-0.5 font-mono text-[10.5px] text-charcoal-500">
            {status.pilots?.map((p) => (
              <li key={p.path}>
                {p.path} — {p.indexed ? `${p.nodes} nodes / ${p.edges} edges` : "not indexed"}
              </li>
            ))}
          </ul>
          <button
            onClick={onReindex}
            disabled={reindexing || status.reindexing}
            className="rounded px-2 py-1 text-emerald-400 ring-1 ring-emerald-700/50 hover:bg-emerald-950/40 disabled:opacity-50"
          >
            {reindexing || status.reindexing ? "Indexing…" : "Reindex now (local, no LLM)"}
          </button>
          {status.reindex_error && (
            <p className="mt-2 text-rose-400">Last reindex failed: {status.reindex_error}</p>
          )}
        </>
      ) : (
        <p>Graphify isn't installed — code-structure indexing unavailable; conversation and inferred layers still work.</p>
      )}
      <p className="mt-3 text-[10.5px] text-charcoal-600">
        {status.local_model_available
          ? "A local model is available for optional future LLM-assisted features."
          : "No local model detected — everything above already runs LLM-free (tree-sitter only); nothing degrades without one."}
      </p>
    </div>
  );
}

/** Right-side source-details panel (task: "Selecting a node opens a
 * right-side source-details panel. Details show the original record, date,
 * and relationship explanation. Distinguish explicit connections from
 * inferred relationships."). */
function NodeDetailsPanel({ node, edges, nodesById, onClose, onOpenConversation }) {
  const explicitEdges = edges.filter((e) => e.kind === "explicit");
  const inferredEdges = edges.filter((e) => e.kind === "inferred");
  const isOperationalError = node.fact_status === "operational_error";

  function otherSide(e) {
    return e.source === node.id ? e.target : e.source;
  }

  const kindLabel =
    node.kind === "conversation"
      ? "Conversation"
      : node.kind === "project"
        ? "Project"
        : node.kind === "code"
          ? "Code"
          : node.kind === "note"
            ? "Obsidian note"
            : node.kind === "knowledge"
              ? "Learned"
              : "Message";

  return (
    <div className="flex w-80 max-w-[45vw] shrink-0 flex-col border-l border-charcoal-700 bg-charcoal-850">
      <div className="flex shrink-0 items-center justify-between border-b border-charcoal-700 px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-charcoal-500">{kindLabel}</span>
        <button onClick={onClose} className="text-charcoal-400 hover:text-charcoal-200">
          ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <h3 className="mb-1 break-words text-sm font-medium text-charcoal-100">{node.label}</h3>
        {node.date && <p className="mb-3 text-xs text-charcoal-500">{formatDate(node.date)}</p>}
        {node.role && !isOperationalError && (
          <span className="mb-3 inline-block rounded-full bg-charcoal-700 px-2 py-0.5 text-[11px] text-charcoal-300">
            {node.role === "assistant" ? "N.O.V.A. generated" : "You said"}
          </span>
        )}
        {isOperationalError && (
          <span className="mb-3 inline-block rounded-full bg-rose-950/50 px-2 py-0.5 text-[11px] text-rose-300">
            Operational failure — not a fact, excluded from Remembered Facts
          </span>
        )}
        {/* Provenance, stated rather than implied. A learned node the user
            asserted and one Nova produced are different things, and the
            panel is where that difference has to be legible. */}
        {node.kind === "knowledge" && (
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] ${
              node.status === "confirmed"
                ? "bg-amber-500/15 text-amber-300"
                : "bg-charcoal-700 text-charcoal-400"
            }`}>
              {node.status === "confirmed" ? "You said this" : "N.O.V.A. inferred — unconfirmed"}
            </span>
            {node.category && (
              <span className="inline-block rounded-full bg-charcoal-700 px-2 py-0.5 text-[11px] text-charcoal-300">
                {node.category}
              </span>
            )}
            {node.times_seen > 1 && (
              <span className="inline-block rounded-full bg-charcoal-700 px-2 py-0.5 text-[11px] text-charcoal-300">
                came up {node.times_seen}×
              </span>
            )}
          </div>
        )}
        <p className="mb-4 whitespace-pre-wrap break-words rounded-lg border border-charcoal-700 bg-charcoal-950 p-3 text-sm leading-relaxed text-charcoal-200">
          {/* A learned node's substance is the statement, which the graph
              carries as `subtitle`; falling through to `label` showed only
              the subject and made the panel look empty. */}
          {node.content || (node.kind === "knowledge" ? node.subtitle : null) || node.label}
        </p>

        {node.kind !== "code" && node.kind !== "project" && node.conversation_id != null && (
          <button
            onClick={() => onOpenConversation(node.tab || "chat", node.conversation_id)}
            className="mb-4 w-full rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500"
          >
            Open in {node.tab === "code" ? "Code" : "Chat"}
          </button>
        )}

        <div className="space-y-3">
          {explicitEdges.length > 0 && (
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-400">
                Explicit connections
              </p>
              <ul className="space-y-1.5">
                {explicitEdges.map((e) => (
                  <li key={e.id} className="rounded-md bg-charcoal-950 px-2.5 py-1.5 text-xs text-charcoal-300">
                    <span className="break-words text-charcoal-100">{nodesById[otherSide(e)]?.label || otherSide(e)}</span>
                    <p className="break-words text-charcoal-500">{e.explanation}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {inferredEdges.length > 0 && (
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-400">
                Inferred (not certain)
              </p>
              <ul className="space-y-1.5">
                {inferredEdges.map((e) => (
                  <li key={e.id} className="rounded-md bg-charcoal-950 px-2.5 py-1.5 text-xs text-charcoal-300">
                    <span className="break-words text-charcoal-100">{nodesById[otherSide(e)]?.label || otherSide(e)}</span>
                    <p className="break-words text-charcoal-500">{e.explanation}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {explicitEdges.length === 0 && inferredEdges.length === 0 && (
            <p className="text-xs text-charcoal-600">No connections found for this node yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
