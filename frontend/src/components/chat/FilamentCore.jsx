import { useEffect, useRef, useState } from "react";

// --- deterministic RNG: the strand system's initial spawn (and every later
// respawn, since each strand keeps drawing from this same continuing
// sequence) comes from one seeded generator, so a given run's evolution is
// reproducible for testing even though the silhouette keeps changing over
// the session -- unlike the old fixed-loop reactor, "the same six filaments
// every session" is no longer the goal (the brief wants the outer silhouette
// to genuinely change over time), but an un-seeded Math.random() would make
// every launch's motion impossible to compare frame-for-frame while
// debugging. ---------------------------------------------------------------
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

// Bounded complexity (task: "bounded visual complexity ... reused buffers"):
// 16 short flowing strands, each a small open arc (not a closed loop) --
// fewer total points than the old 6-closed-loop formation (6*32=192), never
// reallocated per frame (see strandsRef below, mutated in place).
const STRAND_COUNT = 16;
const POINTS_PER_STRAND = 9;
const CHANNEL_COUNT = 3;

function rotate(u, v, angle) {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  return [u * c - v * s, u * s + v * c];
}

/** One strand's shape/orientation is entirely re-rolled on spawn and again
 * on every respawn once its lifespan elapses -- this is the mechanism
 * behind "strands gather, stretch, separate, fade, and reform" and "the
 * outer silhouette changes rather than merely rotating": at any moment a
 * few of the 16 are always mid-fade while the rest sit at full life, so the
 * formation's edge is never the same shape twice in a row. `birth` is
 * backdated by a random fraction of `lifespan` at initial spawn only, so
 * strands start already staggered across their lifecycle instead of all
 * fading out together the first time. */
function spawnStrand(rand, now, { stagger = false } = {}) {
  const lifespan = 7 + rand() * 8;
  return {
    channel: Math.floor(rand() * CHANNEL_COUNT),
    tiltX: (rand() - 0.5) * 2.4,
    tiltY: rand() * Math.PI * 2,
    arcLen: 0.8 + rand() * 0.9,
    flatten: 0.55 + rand() * 0.35,
    undulation: 0.3 + rand() * 0.35,
    radiusScale: 0.82 + rand() * 0.3,
    widthBase: 1.1 + rand() * 1.4,
    colorBias: rand(),
    speedMul: 0.7 + rand() * 0.7,
    phase: rand() * Math.PI * 2,
    birth: now - (stagger ? rand() * lifespan : 0),
    lifespan,
  };
}

function buildStrands() {
  const rand = mulberry32(1337);
  const strands = [];
  for (let i = 0; i < STRAND_COUNT; i++) strands.push(spawnStrand(rand, 0, { stagger: true }));
  return { rand, strands };
}

/** Smoothstep fade-in (first 18% of life) / fade-out (last 28%), 1
 * in between -- the per-strand opacity envelope that makes lifecycle
 * transitions read as a soft dissolve rather than a pop. */
function lifeEnvelope(lifeT) {
  if (lifeT < 0.18) {
    const u = lifeT / 0.18;
    return u * u * (3 - 2 * u);
  }
  if (lifeT > 0.72) {
    const u = (1 - lifeT) / 0.28;
    return u * u * (3 - 2 * u);
  }
  return 1;
}

// --- palette --------------------------------------------------------------
// [shadow, emerald, mint, near-white highlight] -- brightness 0..1 walks
// through these four stops. `mute`/`amber` (see MOTION_FIELDS) blend the
// whole ramp continuously instead of swapping to a different array, so a
// state change never pops to a different color -- see mixPalette below.
const BASE_PALETTE = ["#04120d", "#0d8f68", "#5eead4", "#f0fdf4"].map(hexToRgb);
const DISCONNECTED_PALETTE = ["#0a0c0d", "#3a4249", "#5b6570", "#8b939b"].map(hexToRgb);
const AMBER_HIGHLIGHT = hexToRgb("#fde68a");

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mixRgb(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/** Blends the base ramp toward amber (highlight stop only) and toward the
 * disconnected grey (all stops, wins last) by continuously-smoothed amounts
 * -- called once per frame with the motion controller's current `amber`/
 * `mute` values, never with a raw state string. */
function mixPalette(amberAmount, muteAmount) {
  return BASE_PALETTE.map((stop, i) => {
    let s = i === 3 ? mixRgb(stop, AMBER_HIGHLIGHT, amberAmount) : stop;
    return mixRgb(s, DISCONNECTED_PALETTE[i], muteAmount);
  });
}

function lerpPaletteColor(rgbStops, t) {
  const clamped = Math.max(0, Math.min(1, t));
  const segs = rgbStops.length - 1;
  const pos = clamped * segs;
  const i = Math.min(segs - 1, Math.floor(pos));
  const f = pos - i;
  const a = rgbStops[i];
  const b = rgbStops[i + 1];
  return `rgb(${(a[0] + (b[0] - a[0]) * f) | 0}, ${(a[1] + (b[1] - a[1]) * f) | 0}, ${(a[2] + (b[2] - a[2]) * f) | 0})`;
}

// --- authored per-state motion targets --------------------------------------
// A persistent motion controller (the `motion` ref inside the component)
// blends its CURRENT values toward these targets every frame -- nothing
// here is ever applied directly. That's what makes a state change morph the
// formation into its next behavior instead of snapping to it, and what lets
// an interrupted transition keep blending smoothly from wherever it already
// was rather than restarting. `speaking`/`listening`/`thinking` are gate
// amounts (0..1) that fade authored per-state motion (speaking's pulse,
// listening's mic deformation, thinking's directional current) in and out,
// same mechanism as everything else here.
const STATE_TARGETS = {
  idle: { speed: 0.26, radiusMul: 1.0, openness: 0, current: 0.22, glow: 0.85, mute: 0, amber: 0, speaking: 0, listening: 0, thinking: 0 },
  listening: { speed: 0.3, radiusMul: 1.09, openness: 0.36, current: 0.26, glow: 1.0, mute: 0, amber: 0, speaking: 0, listening: 1, thinking: 0 },
  thinking: { speed: 0.5, radiusMul: 1.0, openness: 0.14, current: 0.85, glow: 1.05, mute: 0, amber: 0, speaking: 0, listening: 0, thinking: 1 },
  speaking: { speed: 0.4, radiusMul: 1.02, openness: 0.2, current: 0.5, glow: 1.08, mute: 0, amber: 0, speaking: 1, listening: 0, thinking: 0 },
  disconnected: { speed: 0.04, radiusMul: 0.9, openness: -0.12, current: 0.05, glow: 0.4, mute: 1, amber: 0, speaking: 0, listening: 0, thinking: 0 },
  approval: { speed: 0.14, radiusMul: 1.0, openness: 0.04, current: 0.16, glow: 0.95, mute: 0, amber: 1, speaking: 0, listening: 0, thinking: 0 },
};
const MOTION_FIELDS = Object.keys(STATE_TARGETS.idle);

// ~350-700ms visual settle at this time constant (1-e^-350/220=.80,
// 1-e^-700/220=.96) -- a starting point per the brief, tuned visually
// afterward rather than derived analytically.
const TRANSITION_TAU_MS = 220;

function smoothTo(current, target, dt, tauMs) {
  const rate = 1 - Math.exp(-dt / tauMs);
  return current + (target - current) * rate;
}

function avgLevel(levels) {
  if (!levels || !levels.length) return 0;
  let sum = 0;
  for (let i = 0; i < levels.length; i++) sum += levels[i];
  return sum / levels.length / 255;
}

const STATUS_LABEL = {
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  disconnected: "Disconnected — check that the backend is running",
  approval: "Waiting for your approval",
};

const SUPPORTS_CANVAS_FILTER = typeof CanvasRenderingContext2D !== "undefined" && "filter" in CanvasRenderingContext2D.prototype;

/** The reactor: an evolving body of light rendered on a <canvas> -- 16 short,
 * independent strands (see spawnStrand) drifting within a small number of
 * shared "current" channels around a glowing core. Each strand sweeps a
 * short open arc (not a closed loop), slowly precesses within its channel's
 * shared drift, and lives a finite, staggered lifespan before fading out and
 * respawning with fresh orientation/shape -- so the formation's outer edge
 * keeps changing rather than just rotating, while enough strands are always
 * mid-life for the whole shape to stay composed in any single frame. Some
 * dip behind the core's own glow and re-emerge in front of it (drawn in two
 * depth-sorted passes around the core fill), which is what gives it real
 * dimensionality instead of reading as a flat badge.
 *
 * Motion is continuous across state changes (task: "one continuous form"):
 * strand identity/lifecycle (`strandsRef`), animation clock (`startRef`,
 * never reset), and a persistent motion-parameter controller (`motionRef`,
 * `audioEnvRef`, `micEnvRef`) all live for the component's whole lifetime
 * and are blended toward each new state's authored target every frame (see
 * STATE_TARGETS/smoothTo) rather than swapped on state change -- an
 * interrupted transition keeps blending from wherever it currently
 * rendered, never resets. `state` itself only feeds `stateRef`, read fresh
 * each frame; React re-renders from a state change are not what drives the
 * animation.
 *
 * The rAF loop writes directly to the canvas -- nothing here drives a React
 * state update per frame (the one exception, `renderFailed`, only ever
 * flips once, on a genuine draw error, to swap in the CSS fallback). It
 * pauses outright when the tab is hidden and renders exactly one static
 * frame (no rAF at all) under prefers-reduced-motion. Audio-reactive terms
 * are strictly optional: they only apply when the caller's
 * getMicLevels/getPlaybackLevels actually returns data, and decay back to
 * the state's authored (non-audio) motion the instant it doesn't -- this
 * never invents activity that isn't real. */
export default function FilamentCore({ state = "idle", getMicLevels, getPlaybackLevels }) {
  const canvasRef = useRef(null);
  const strandsRef = useRef(null);
  const strandRandRef = useRef(null);
  const stateRef = useRef(state);
  const motionRef = useRef(null);
  const audioEnvRef = useRef(0); // speaking: fast-attack/slow-release playback envelope
  const micEnvRef = useRef(0); // listening: moderate mic envelope
  const lastTimeRef = useRef(null);
  const rafRef = useRef(null);
  const startRef = useRef(performance.now());
  // Lets a state change repaint immediately under prefers-reduced-motion
  // (no rAF loop running to pick it up on its own otherwise) -- populated
  // by the drawing effect below, so "state labels update immediately"
  // holds for the canvas too, not just the DOM text next to it.
  const redrawRef = useRef(null);
  // Rendering-failure fallback (task: "reduced-motion and rendering-failure
  // fallbacks"): flips at most once, the first time a draw genuinely throws
  // (e.g. an unsupported canvas call in some embedder), swapping the canvas
  // out for a plain CSS glow rather than a blank or half-drawn frame.
  const [renderFailed, setRenderFailed] = useState(false);

  useEffect(() => {
    stateRef.current = state;
    if (!rafRef.current) redrawRef.current?.();
  }, [state]);

  if (!strandsRef.current) {
    const { rand, strands } = buildStrands();
    strandRandRef.current = rand;
    strandsRef.current = strands;
  }
  if (!motionRef.current) motionRef.current = { ...(STATE_TARGETS[state] || STATE_TARGETS.idle) };

  useEffect(() => {
    if (renderFailed) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      setRenderFailed(true);
      return;
    }
    const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

    function resize() {
      const rect = canvas.getBoundingClientRect();
      // Capped pixel density (task: "capped pixel density") -- 1.5x is
      // already indistinguishable from native on this reactor's soft,
      // blurred strokes, and keeps the point/pixel budget bounded on
      // high-DPI displays.
      const dpr = Math.min(1.5, window.devicePixelRatio || 1);
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
    }
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    resize();

    function drawFrame(timeMs) {
      const dt = lastTimeRef.current == null ? 16 : Math.min(64, timeMs - lastTimeRef.current);
      lastTimeRef.current = timeMs;
      const t = (timeMs - startRef.current) / 1000;

      // Advance the persistent motion controller toward this frame's target
      // -- see STATE_TARGETS' doc comment. This is the whole "one continuous
      // form" mechanism: every field blends independently, so an
      // interrupted transition just keeps blending toward whatever the new
      // target is from its current value, never resets.
      const target = STATE_TARGETS[stateRef.current] || STATE_TARGETS.idle;
      const m = motionRef.current;
      if (reduceMotionQuery.matches) {
        // No continuous animation to finish a blend over -- a state change
        // should read as immediate here, not stuck partway through a
        // transition that will never keep playing.
        for (const f of MOTION_FIELDS) m[f] = target[f];
      } else {
        for (const f of MOTION_FIELDS) m[f] = smoothTo(m[f], target[f], dt, TRANSITION_TAU_MS);
      }

      // Real audio envelopes -- independent of the general motion blend
      // above since they need their own attack/release character, not a
      // fixed transition time. Listening uses symmetric smoothing (mic
      // energy doesn't need phrasing); speaking uses fast attack / slow
      // release so speech reads as fluid phrasing rather than flicker or
      // bass-pumping, per the brief. Both raw inputs are 0 whenever no real
      // analyser is attached OR the state doesn't match, so the envelope
      // always decays honestly toward silence rather than holding a fake
      // value or snapping.
      const micRaw = stateRef.current === "listening" ? avgLevel(getMicLevels?.()) : 0;
      micEnvRef.current = smoothTo(micEnvRef.current, micRaw, dt, 160);
      const speakRaw = stateRef.current === "speaking" ? avgLevel(getPlaybackLevels?.()) : 0;
      const speakTau = speakRaw > audioEnvRef.current ? 55 : 260;
      audioEnvRef.current = smoothTo(audioEnvRef.current, speakRaw, dt, speakTau);

      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2;
      const baseRadius = Math.min(w, h) * 0.28;
      const dpr = w / Math.max(1, canvas.getBoundingClientRect().width || 1);

      // Slow irregular "breathing" -- two off-period sines summed instead
      // of one, so it reads as organic rather than a metronomic pulse.
      const breathe = 1 + Math.sin(t * 0.5) * 0.03 + Math.sin(t * 0.19 + 1.1) * 0.02;
      // Speaking's authored "flowing expansion and release" -- a slow
      // pulse that runs continuously but only contributes once `speaking`
      // (the gate) has faded in, plus a real contribution from the fast/
      // slow audio envelope on top.
      const speakPulse = Math.sin(t * 1.15) * 0.5 + 0.5;
      const radiusMulFinal = m.radiusMul + speakPulse * 0.045 * m.speaking + audioEnvRef.current * 0.13 * m.speaking;
      const radius = baseRadius * radiusMulFinal * breathe;

      // Ambient whole-formation parallax -- deliberately subtle (unlike the
      // old fixed-loop reactor, where a full-speed global rotation WAS the
      // primary motion and read as a spinning cage). Here the dominant
      // motion is each strand's own current-driven precession below; this
      // term only adds gentle dimensionality on top.
      const globalYaw = t * m.speed * 0.07;
      const globalPitch = Math.sin(t * 0.08) * 0.1;
      const opennessFinal = m.openness + micEnvRef.current * 0.1 * m.listening;
      const audioBrightness = audioEnvRef.current * 0.3 * m.speaking + micEnvRef.current * 0.22 * m.listening;
      const glowFinal = m.glow + audioEnvRef.current * 0.15 * m.speaking;

      const palette = mixPalette(m.amber, m.mute);
      const focal = radius * 2.05;

      // Coherent currents (task: "elements move independently within
      // coherent currents"): a handful of shared drift angles, one per
      // channel, that strands in that channel precess around in common --
      // computed once per frame, not per point. `thinking` both speeds
      // these up and (via the undulation damping below) aligns strands
      // within a channel more tightly, so it reads as "gathering into
      // directional flowing currents" rather than just faster idle motion.
      const channelDrift = [];
      for (let c = 0; c < CHANNEL_COUNT; c++) {
        const channelSpeed = 0.5 + c * 0.22;
        channelDrift.push(t * channelSpeed * m.speed * (0.35 + m.current));
      }

      // Geometry pass: compute every strand's screen-space points once;
      // both the glow and crisp render passes below reuse this same array
      // instead of recomputing it, which is what keeps two render passes
      // cheap enough for 60fps.
      const backSegs = [];
      const frontSegs = [];
      for (const strand of strandsRef.current) {
        let age = t - strand.birth;
        if (age > strand.lifespan) {
          // Respawn in place (task: "strands ... reform"; "reused buffers"
          // -- mutates the existing object rather than allocating a new
          // one). Draws the next shape/orientation from the same continuing
          // seeded sequence, not Math.random, so the whole session stays
          // reproducible.
          const fresh = spawnStrand(strandRandRef.current, t);
          Object.assign(strand, fresh);
          age = 0;
        }
        const lifeT = age / strand.lifespan;
        const envelope = lifeEnvelope(lifeT);
        if (envelope <= 0.002) continue; // fully faded -- skip, not even a zero-alpha stroke

        // Per-strand independent undulation, damped during `thinking` so
        // strands within a channel align into a more unified current
        // instead of each doing their own thing (task: "gathers into
        // directional flowing currents").
        const undulationFinal = strand.undulation * (1 - 0.4 * m.thinking);
        // Speaking's non-uniform response: one real playback envelope
        // scalar, but distributed unevenly across strands via each one's
        // own phase, so several strands visibly pulse at slightly different
        // moments instead of the whole formation breathing in lockstep --
        // still strictly gated by the real audioEnvRef (0 with no audio).
        const strandPulse = 0.5 + 0.5 * Math.sin(t * 1.3 + strand.phase * 2);
        const audioPulse = audioEnvRef.current * m.speaking * strandPulse;

        // Slow precession within the strand's channel current, plus a
        // gentle extra turn as the strand ages -- together these migrate
        // the strand's arc across the volume's surface over its lifetime,
        // which (combined with staggered lifespans) is what makes the
        // outer silhouette itself change rather than merely rotate.
        const precess = channelDrift[strand.channel] * 0.6 + lifeT * 0.5;

        const pts = [];
        for (let i = 0; i <= POINTS_PER_STRAND; i++) {
          const a = -strand.arcLen / 2 + (i / POINTS_PER_STRAND) * strand.arcLen;
          let x = Math.cos(a);
          let y = Math.sin(a) * (strand.flatten + opennessFinal);
          let z = Math.sin(a * 2 + strand.phase + t * strand.speedMul * 0.3) * (undulationFinal + audioPulse * 0.5);
          [y, z] = rotate(y, z, strand.tiltX);
          [x, z] = rotate(x, z, strand.tiltY);
          [x, z] = rotate(x, z, precess);
          [x, z] = rotate(x, z, globalYaw);
          [y, z] = rotate(y, z, globalPitch);
          const R = radius * strand.radiusScale;
          const px = x * R;
          const py = y * R;
          const pz = z * R;
          const persp = focal / (focal + pz);
          const depthNorm = Math.max(0, Math.min(1, (pz / R + 1) / 2));
          // A steep power curve on depth (rather than linear) is what
          // actually produces "internal shadow" -- most of a strand reads
          // as dim near-shadow, with only the front-most arc catching real
          // light, instead of every point sitting at some washed-out middle
          // brightness that reads as one flat glowing tangle.
          const lit = Math.pow(depthNorm, 2.4);
          const brightness = Math.min(1, (0.035 + lit * 0.78 + strand.colorBias * 0.08 + audioBrightness) * envelope);
          pts.push({
            x: cx + px * persp,
            y: cy + py * persp,
            depthNorm,
            brightness,
            width: strand.widthBase * (0.5 + lit * 0.9) * dpr,
          });
        }
        for (let i = 0; i < pts.length - 1; i++) {
          const a = pts[i];
          const b = pts[i + 1];
          const seg = {
            a,
            b,
            color: lerpPaletteColor(palette, (a.brightness + b.brightness) / 2),
            width: (a.width + b.width) / 2,
            alpha: envelope,
          };
          if ((a.depthNorm + b.depthNorm) / 2 < 0.5) backSegs.push(seg);
          else frontSegs.push(seg);
        }
      }

      ctx.clearRect(0, 0, w, h);

      function strokeSegs(segs, widthMul, alphaMul) {
        for (const s of segs) {
          ctx.beginPath();
          ctx.moveTo(s.a.x, s.a.y);
          ctx.lineTo(s.b.x, s.b.y);
          ctx.strokeStyle = s.color;
          ctx.globalAlpha = alphaMul * s.alpha;
          ctx.lineWidth = Math.max(0.6, s.width * widthMul);
          ctx.lineCap = "round";
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }

      function drawCoreGlow() {
        const outerR = radius * (1.55 + glowFinal * 0.35 + audioBrightness * 0.18);
        const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, outerR);
        const [er, eg, eb] = palette[1];
        grad.addColorStop(0, `rgba(${er},${eg},${eb},${0.34 * glowFinal})`);
        grad.addColorStop(0.45, `rgba(${er},${eg},${eb},${0.14 * glowFinal})`);
        grad.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
        ctx.fill();

        const innerR = radius * (0.62 + audioBrightness * 0.08);
        const inner = ctx.createRadialGradient(cx - innerR * 0.25, cy - innerR * 0.3, innerR * 0.05, cx, cy, innerR);
        const [mr, mg, mb] = palette[2];
        const [hr, hg, hb] = palette[3];
        inner.addColorStop(0, `rgba(${hr},${hg},${hb},0.68)`);
        inner.addColorStop(0.4, `rgba(${mr},${mg},${mb},0.4)`);
        inner.addColorStop(1, `rgba(${er},${eg},${eb},0.06)`);
        ctx.fillStyle = inner;
        ctx.beginPath();
        ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
        ctx.fill();
      }

      // Internal shadow -- a dark, slightly off-center disc seated behind
      // everything else, so the formation reads as wrapping a shaded volume
      // rather than floating strands on flat black.
      function drawShadow() {
        const shR = radius * 1.15;
        const sh = ctx.createRadialGradient(cx + shR * 0.22, cy + shR * 0.28, 0, cx, cy, shR);
        sh.addColorStop(0, "rgba(0,0,0,0.5)");
        sh.addColorStop(0.6, "rgba(0,0,0,0.22)");
        sh.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = sh;
        ctx.beginPath();
        ctx.arc(cx, cy, shR, 0, Math.PI * 2);
        ctx.fill();
      }

      drawShadow();

      if (SUPPORTS_CANVAS_FILTER) {
        ctx.save();
        ctx.filter = `blur(${Math.max(1.2, radius * 0.026)}px)`;
        strokeSegs(backSegs, 1.7, 0.4);
        drawCoreGlow();
        strokeSegs(frontSegs, 1.7, 0.5);
        ctx.restore();
      }

      strokeSegs(backSegs, 1, 0.6);
      if (!SUPPORTS_CANVAS_FILTER) drawCoreGlow();
      strokeSegs(frontSegs, 1, 1);
    }

    function safeDrawFrame(timeMs) {
      try {
        drawFrame(timeMs);
      } catch (err) {
        console.error("FilamentCore draw failed, falling back to static glow:", err);
        stop();
        setRenderFailed(true);
      }
    }

    function loop(timeMs) {
      safeDrawFrame(timeMs);
      if (!renderFailed) rafRef.current = requestAnimationFrame(loop);
    }

    function start() {
      if (rafRef.current) return;
      if (reduceMotionQuery.matches) {
        lastTimeRef.current = null;
        safeDrawFrame(performance.now());
        return;
      }
      rafRef.current = requestAnimationFrame(loop);
    }

    function stop() {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    }

    function handleVisibility() {
      if (document.hidden) stop();
      else start();
    }
    function handleMotionChange() {
      stop();
      lastTimeRef.current = null;
      start();
    }

    redrawRef.current = () => {
      lastTimeRef.current = null;
      safeDrawFrame(performance.now());
    };
    document.addEventListener("visibilitychange", handleVisibility);
    reduceMotionQuery.addEventListener("change", handleMotionChange);
    start();

    return () => {
      stop();
      redrawRef.current = null;
      resizeObserver.disconnect();
      document.removeEventListener("visibilitychange", handleVisibility);
      reduceMotionQuery.removeEventListener("change", handleMotionChange);
    };
  }, [getMicLevels, getPlaybackLevels, renderFailed]);

  if (renderFailed) {
    // Rendering-failure fallback: a plain CSS radial glow, still colored by
    // state, with no canvas/rAF involved at all.
    const color = state === "disconnected" ? "#3a4249" : state === "approval" ? "#fbbf24" : "#10b981";
    return (
      <div
        role="img"
        aria-label={STATUS_LABEL[state] || "N.O.V.A. reactor"}
        className="h-full w-full rounded-full"
        style={{ background: `radial-gradient(circle, ${color}55 0%, ${color}22 45%, transparent 75%)` }}
      />
    );
  }

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={STATUS_LABEL[state] || "N.O.V.A. reactor"}
      className="block h-full w-full"
    />
  );
}

export { STATUS_LABEL };
