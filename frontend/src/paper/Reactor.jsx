// Nova's reactor: ribbons of light wrapped around a sphere, with real depth.
//
// Clean and smooth by construction:
// - supersampled: the canvas is drawn at no less than 2x its CSS size (3x on
//   high-density screens), so edges are smooth even on a 1x monitor;
// - each ribbon is one continuous curve (quadratic segments through the
//   midpoints of its samples), split only where its depth band changes, and a
//   band is only entered well past its boundary, so ribbons never flicker
//   into dashes;
// - detail scales with size, so a small reactor stays light and legible.
//
// Cheap by construction:
// - one shared animation loop for every reactor on screen; small reactors
//   redraw at 30 fps, large ones at the display's rate;
// - sizes come from a ResizeObserver, never from a layout read per frame, so
//   a streaming chat never forces the page to re-layout for the reactor;
// - trigonometry for ribbon longitudes is cached per detail level, and a
//   reactor that takes too long to draw lowers its own detail.
//
// Audio is real: speaking follows the TTS playback analyser, listening the
// microphone analyser. Nothing here is a timer pretending to be a voice.
import { useEffect, useRef } from "react";
import { getAudioLevels } from "../lib/ttsPlayback.js";
import { getMicLevels } from "../lib/micLevels.js";
import { hexToRgb } from "./palettes.js";
import { useNovaState } from "./novaState.js";

const TAU = Math.PI * 2;
const BANDS = 4;
const HYSTERESIS = 0.07;
// flow drives how fast the ribbons ripple; spin is the turn rate (rad/s).
const MOTION = {
  idle: { flow: 1.5, spin: 0.62, inward: 0, tight: 0 },
  listening: { flow: 1.8, spin: 0.8, inward: 0, tight: 1 },
  thinking: { flow: 3.4, spin: 1.7, inward: 1, tight: 0 },
  speaking: { flow: 2, spin: 0.95, inward: 0, tight: 0 },
};

const sin = Math.sin;
const noise = (x, y, t) => sin(x * 1.7 + t * 0.9) * 0.5 + sin(y * 2.3 - t * 0.7) * 0.3
  + sin((x + y) * 3.1 + t * 1.3) * 0.2 + sin(x * 5.3 - y * 4.1 + t * 0.5) * 0.12;

const trig = new Map();
function lonTable(segs) {
  if (!trig.has(segs)) {
    const c = new Float32Array(segs + 1);
    const s = new Float32Array(segs + 1);
    for (let i = 0; i <= segs; i += 1) { c[i] = Math.cos((i / segs) * TAU); s[i] = Math.sin((i / segs) * TAU); }
    trig.set(segs, { c, s });
  }
  return trig.get(segs);
}

const rgbCache = new Map();
const rgb = (hex) => { if (!rgbCache.has(hex)) rgbCache.set(hex, hexToRgb(hex)); return rgbCache.get(hex); };
const mix = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];

function level(data, from, to) {
  if (!data) return 0;
  let sum = 0;
  const end = Math.min(to, data.length);
  for (let i = from; i < end; i += 1) sum += data[i];
  return end > from ? sum / ((end - from) * 255) : 0;
}

function strokeCurve(ctx, pts) {
  const n = pts.length / 2;
  ctx.beginPath();
  ctx.moveTo(pts[0], pts[1]);
  if (n < 3) { ctx.lineTo(pts[2], pts[3]); return; }
  for (let i = 1; i < n - 1; i += 1) {
    const x = pts[i * 2], y = pts[i * 2 + 1];
    ctx.quadraticCurveTo(x, y, (x + pts[i * 2 + 2]) / 2, (y + pts[i * 2 + 3]) / 2);
  }
  ctx.lineTo(pts[(n - 1) * 2], pts[(n - 1) * 2 + 1]);
}

function draw(r, now) {
  const { ctx, canvas, cssSize, scale, props, motion } = r;
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!cssSize) return;
  const t = now / 1000;
  const pal = props.palette;
  const A = rgb(pal.a), B = rgb(pal.b), BACK = rgb(pal.back);
  const rings = Math.max(6, Math.min(22, Math.round(cssSize / 8)));
  const segs = Math.max(28, Math.round(Math.min(84, cssSize / 2.4) * r.quality));
  const { c: cosL, s: sinL } = lonTable(segs);
  // Breathing: a slow swell with a faster flutter on top, so it never sits still.
  const breath = sin(t * 1.3) * 0.022 + sin(t * 3.7 + 1) * 0.006;
  const R = Math.min(W, H) * 0.4 * (1 + motion.env * 0.16 + breath);
  const cx = W / 2, cy = H / 2;
  const rotY = motion.spin;
  const rotX = 0.5 + sin(t * 0.37) * 0.22 + sin(t * 0.91) * 0.05;
  const cY = Math.cos(rotY), sY = Math.sin(rotY), cX = Math.cos(rotX), sX = Math.sin(rotX);
  const px = cssSize < 60 ? 0.8 : Math.max(0.9, cssSize / 140);
  const base = px * scale;
  const env = motion.env, tight = motion.tight, inward = motion.inward, phase = motion.phase;
  const lively = env > 0.01 || tight > 0.01;
  const runs = [];

  for (let k = 0; k < rings; k += 1) {
    const lat0 = (k / (rings - 1) - 0.5) * Math.PI * 0.92;
    const hue = mix(A, B, (sin(k * 0.35 + t * 1.1) + 1) / 2);
    let run = null;
    for (let i = 0; i <= segs; i += 1) {
      const cl = cosL[i], sl = sinL[i];
      const lon = (i / segs) * TAU;
      let warp = 0.22 * noise(cl * 1.2 + k * 0.12, sl * 1.2, phase * 0.5)
        + 0.035 * sin(lon * 3 + k * 0.6 - phase * 2.2);
      if (lively) warp += env * 0.34 * noise(lon * 2.2, k * 0.3, t * 3.4) + tight * 0.08 * sin(lon * 12 + t * 11);
      const lat = lat0 + warp * (1 - inward * 0.6);
      const rr = 1 + 0.05 * noise(k * 0.3, lon, t * 1.1) + (lively ? env * 0.08 * sin(lon * 5 + t * 9) : 0);
      const cLat = Math.cos(lat);
      const x = cLat * cl * rr, y = Math.sin(lat) * rr * (1 - inward * 0.22), z = cLat * sl * rr;
      const x1 = x * cY + z * sY, z1 = -x * sY + z * cY;
      const y2 = y * cX - z1 * sX, z2 = y * sX + z1 * cX;
      const front = Math.max(0, Math.min(1, (z2 + 1) / 2));
      let band = Math.min(BANDS - 1, (front * BANDS) | 0);
      if (run && band !== run.band) {
        const edge = band > run.band ? band / BANDS : (band + 1) / BANDS;
        if (Math.abs(front - edge) < HYSTERESIS) band = run.band;
      }
      const X = cx + x1 * R, Y = cy + y2 * R;
      if (!run || run.band !== band) {
        const next = { band, hue, pts: run ? [run.pts[run.pts.length - 2], run.pts[run.pts.length - 1]] : [] };
        if (run) runs.push(run);
        run = next;
      }
      run.pts.push(X, Y);
    }
    runs.push(run);
  }

  // A soft core glow that pulses with the breath and the voice.
  const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.05);
  const ga = (props.dark ? 0.2 : 0.12) * (0.75 + breath * 8 + env * 0.9);
  glow.addColorStop(0, `rgba(${A[0] | 0},${A[1] | 0},${A[2] | 0},${Math.max(0, ga)})`);
  glow.addColorStop(1, `rgba(${A[0] | 0},${A[1] | 0},${A[2] | 0},0)`);
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(cx, cy, R * 1.05, 0, TAU); ctx.fill();

  runs.sort((m, n) => m.band - n.band);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const run of runs) {
    if (run.pts.length < 4) continue;
    const front = (run.band + 0.5) / BANDS;
    const col = front < 0.5 ? mix(BACK, run.hue, front / 0.5) : run.hue;
    const alpha = (props.dark ? 0.14 + front * 0.8 : 0.16 + front * 0.84) * (0.9 + env * 0.25);
    ctx.strokeStyle = `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},${Math.min(1, alpha)})`;
    ctx.lineWidth = base * (0.5 + front * 1.1) * (1 + env * 0.3);
    strokeCurve(ctx, run.pts);
    ctx.stroke();
  }

  // Sparks: a few points of light racing around tilted orbits, bright only
  // on the near side, so the sphere always reads as moving and in depth.
  if (cssSize >= 40) {
    for (let j = 0; j < 3; j += 1) {
      const a = phase * (1.4 + j * 0.35) + j * 2.1;
      const tilt = 0.6 + j * 0.7;
      let x = Math.cos(a), y = Math.sin(a) * Math.sin(tilt), z = Math.sin(a) * Math.cos(tilt);
      const x1 = x * cY + z * sY, z1 = -x * sY + z * cY;
      const y2 = y * cX - z1 * sX, z2 = y * sX + z1 * cX;
      if (z2 <= 0) continue;
      x = cx + x1 * R * 1.02; y = cy + y2 * R * 1.02;
      const c = j % 2 ? B : A;
      const rad = base * (1.6 + z2 * 1.6) * (1 + env * 0.5);
      const sg = ctx.createRadialGradient(x, y, 0, x, y, rad * 4);
      sg.addColorStop(0, `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${0.9 * z2})`);
      sg.addColorStop(1, `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},0)`);
      ctx.fillStyle = sg;
      ctx.beginPath(); ctx.arc(x, y, rad * 4, 0, TAU); ctx.fill();
    }
  }
}

// ---- one loop for every reactor ------------------------------------------
const live = new Set();
let frame = 0;
let last = 0;
const reduceQuery = typeof window !== "undefined" ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

function tick(now) {
  frame = 0;
  const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
  last = now;
  let speaking = null;
  let mic = null;
  for (const r of live) {
    if (!r.visible) continue;
    const { props, motion } = r;
    const still = props.reducedMotion || reduceQuery?.matches;
    const target = MOTION[props.state] || MOTION.idle;
    const ease = 1 - Math.exp(-dt * 3);
    motion.flow += (target.flow - motion.flow) * ease;
    motion.inward += (target.inward - motion.inward) * ease;
    motion.tight += (target.tight - motion.tight) * ease;
    motion.spinRate += (target.spin - motion.spinRate) * ease;
    motion.spin += dt * motion.spinRate * (still ? 0.1 : 1);
    let env = 0;
    if (props.state === "speaking") {
      speaking ??= getAudioLevels();
      env = Math.min(1, level(speaking, 1, 6) * 1.3 + level(speaking, 6, 16) * 0.6);
    } else if (props.state === "listening") {
      mic ??= getMicLevels();
      env = Math.min(0.6, level(mic, 1, 12) * 1.2);
    }
    motion.env += (env - motion.env) * (env > motion.env ? 0.35 : 0.08);
    motion.phase += dt * motion.flow * (still ? 0.12 : 1);
    const interval = r.cssSize < 32 ? 33 : 0;
    if (now - r.drawnAt < interval) continue;
    r.drawnAt = now;
    const start = performance.now();
    draw(r, still ? motion.phase * 1000 : now);
    const spent = performance.now() - start;
    r.cost = r.cost * 0.9 + spent * 0.1;
    if (r.cost > 4 && r.quality > 0.5) r.quality -= 0.05;
    else if (r.cost < 1.5 && r.quality < 1) r.quality += 0.01;
  }
  schedule();
}

function schedule() {
  if (frame || document.visibilityState !== "visible") return;
  for (const r of live) if (r.visible) { frame = requestAnimationFrame(tick); return; }
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => { last = 0; schedule(); });
}

/**
 * <Reactor palette={...} dark={bool} state?="idle|listening|thinking|speaking" />
 * Fills its parent box. `state` defaults to Nova's real live state.
 */
export default function Reactor({ palette, dark = false, state, reducedMotion = false, className = "", label }) {
  const liveState = useNovaState();
  const canvasRef = useRef(null);
  const rec = useRef(null);
  if (rec.current) rec.current.props = { palette, dark, state: state || liveState, reducedMotion };

  useEffect(() => {
    const canvas = canvasRef.current;
    const r = {
      canvas, ctx: canvas.getContext("2d", { alpha: true }), cssSize: 0, scale: 2, visible: true,
      drawnAt: 0, cost: 0, quality: 1,
      motion: { env: 0, phase: Math.random() * 10, flow: 1.5, inward: 0, tight: 0, spin: Math.random() * TAU, spinRate: 0.62 },
      props: { palette, dark, state: state || liveState, reducedMotion },
    };
    rec.current = r;
    const resize = (w, h) => {
      const scale = Math.min(3, Math.max(2, window.devicePixelRatio || 1));
      r.scale = scale;
      r.cssSize = Math.min(w, h);
      canvas.width = Math.max(1, Math.round(w * scale));
      canvas.height = Math.max(1, Math.round(h * scale));
      r.drawnAt = 0;
    };
    const ro = new ResizeObserver(([entry]) => {
      const box = entry.contentBoxSize?.[0];
      resize(box ? box.inlineSize : entry.contentRect.width, box ? box.blockSize : entry.contentRect.height);
    });
    ro.observe(canvas);
    const io = new IntersectionObserver(([entry]) => { r.visible = entry.isIntersecting; if (r.visible) schedule(); });
    io.observe(canvas);
    live.add(r);
    schedule();
    return () => { live.delete(r); ro.disconnect(); io.disconnect(); };
  }, []);

  return <canvas ref={canvasRef} className={className} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} />;
}
