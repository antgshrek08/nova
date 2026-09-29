import { useEffect, useRef, useState } from "react";
import { connectAgentSocket } from "../lib/agentSocket.js";
import walk1Image from "../assets/character/walk-1.png";
import walk2Image from "../assets/character/walk-2.png";
import waveImage from "../assets/character/wave.png";
import {
  createRig,
  LIMB_ANGLE_KEY,
  RIG_CANVAS_H,
  RIG_CANVAS_W,
  RIG_IMAGES,
  RIG_LIMBS,
  RIG_SWAY_CLASS,
  WALK_ARM_SWING_RATIO,
  WALK_LEG_SWING_DEG,
  WAVE_ARM_PART,
} from "../lib/characterEngine.js";

const CHAR_HEIGHT = 118;
// Movement-bounds math below still needs *a* width; the old front-facing composite's 363x368
// ratio is gone (retired in favor of the rig, see below) but this stays as the box the walk AI
// reasons about, matching the frame width closely enough that the character never visually
// clips off the work area's edge.
const CHAR_WIDTH = CHAR_HEIGHT * (363 / 368);
// AI-generated angle/pose frames (RESEARCH.md, 2026-09-04 "Character frames" entry) all share
// one 733x1033 canvas -- a different aspect ratio than the rig's canvas below -- so they get
// their own width so the box never stretches/squashes an image whose native ratio doesn't match.
const FRAME_NATURAL_W = 733;
const FRAME_NATURAL_H = 1033;
const FRAME_CHAR_WIDTH = CHAR_HEIGHT * (FRAME_NATURAL_W / FRAME_NATURAL_H);

// Limb rig geometry now comes from the one shared implementation in
// lib/characterEngine.js (CLAUDE_CODE_HANDOFF.md section 7 item 3) -- this
// block and Miniplayer.jsx's copy of it were identical apart from the height
// they scale to. Verified numerically identical to the previous inline math at
// both 118px and 145px by bench/rigEquivalence.mjs.
const {
  charWidth: RIG_CHAR_WIDTH,
  scale: RIG_SCALE,
  partStyle: RIG_PART_STYLE,
  pivot: RIG_PIVOT,
} = createRig(CHAR_HEIGHT);

const GROUND_MARGIN = 4; // px above the bottom edge of the work area
const WALK_SPEED = 55; // px/s -- classic unhurried desktop-pet pace
const REACT_ANIM_MS = 480;
const SHAKE_ANIM_MS = 420;
const SAY_DISPLAY_MS = 5000;

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

/** Character system phase 2 (task: "desktop roaming... using
 * TonyNa-code/desktop-pet's architecture as reference... let the character
 * move around the actual desktop outside the miniplayer circle"). Loads
 * into its own transparent, click-through, always-on-top window sized to
 * the screen's work area (see electron/main.cjs's createDesktopPetWindow) --
 * this component only ever worries about *where inside that window* the
 * character is and how it's posed, never actual screen coordinates.
 *
 * Idle/thinking/shaking render the limb rig (torso.png + 4 independently-
 * rotating parts, RESEARCH.md 2026-09-04) instead of the old flat front
 * composite -- real per-limb motion, not the whole image bobbing as one
 * piece (the exact distinction the user drew after watching the earlier
 * whole-image sprite-swap live). Walking and reacting alternate, one phase/
 * reaction at a time, between the existing flat walk-1/walk-2/wave swap and
 * a rig-driven equivalent (continuous leg/arm swing for walking, a raised
 * waving arm for reacting) -- both mechanisms genuinely exercised rather
 * than one silently replacing the other, since the two art sets (rig vs.
 * flat frames) come from different generations with no calibration data
 * linking their canvases, so showing both AT ONCE in one frame isn't
 * attempted -- see the walkMechanismRef/reactMechanismRef alternation below
 * and the RESEARCH.md entry this session writes for the live verification
 * and the reasoning against a spatial (same-frame) combination.
 *
 * Integration-plan Phase 2 (RESEARCH.md, 2026-09-03): also subscribes to
 * the same /ws/agents socket that already drives the Workspace tab's live
 * dashboard, so the character has real ambient awareness of what N.O.V.A.
 * is doing elsewhere in the app (a Chat reply generating, a Workspace
 * agent chain running) instead of only reacting to being clicked. The
 * "is anything active" and one-shot success/error pulses are derived
 * locally from the per-job status stream (see the effect below) rather
 * than trusted from the backend's own single shared pet.state field --
 * that field is real (agents.py's AgentRegistry calls
 * pet.nova_pet_react/nova_pet_say on every job transition) but is a
 * one-size-fits-all simplification that can't distinguish "job A just
 * finished" from "job B is still running" when multiple jobs overlap;
 * deriving "active" from this window's own view of every job's status
 * avoids that edge case entirely. pet.text (the backend's short "what's
 * it doing" blurb) is trusted as-is for the speech bubble, since it's
 * already sanitized server-side (see pet.py) and is genuinely fine as
 * shared ambient flavor text even under overlapping jobs.
 */
export default function DesktopPet({ embedded = false }) {
  const stageRef = useRef(null);
  const [pos, setPos] = useState(() => ({
    x: Math.max(0, (embedded ? 250 : window.innerWidth) / 2 - CHAR_WIDTH / 2),
  }));
  const [direction, setDirection] = useState(1); // 1 = facing right, -1 = facing left
  const [walking, setWalking] = useState(false);
  const [reacting, setReacting] = useState(false);
  const [shaking, setShaking] = useState(false);
  const [hovering, setHovering] = useState(false);
  const [bobTilt, setBobTilt] = useState({ bob: 0, tilt: 0 });
  const [limbAngles, setLimbAngles] = useState({ armLeft: 0, armRight: 0, legLeft: 0, legRight: 0 });
  const [agentsActive, setAgentsActive] = useState(false);
  const [sayText, setSayText] = useState(null);

  const targetXRef = useRef(pos.x);
  const modeUntilRef = useRef(0); // performance.now() timestamp the current idle/walk phase ends
  const rafRef = useRef(null);
  const reactTimeoutRef = useRef(null);
  const shakeTimeoutRef = useRef(null);
  const sayTimeoutRef = useRef(null);
  const walkPhaseRef = useRef(0);
  const agentsActiveRef = useRef(false);
  // Pre-existing bug, found and fixed this pass (RESEARCH.md, 2026-09-04 "Limb rig" entry): the
  // walk-AI effect below is mount-once ([] deps), so a bare `walking` read inside its tick()/
  // pickNew* closures is permanently stale at whatever it was on the FIRST render (false) --
  // `setWalking(true)` never updates that closure's binding, only schedules a new one for the
  // next render, which this effect never re-runs to pick up. Net effect: the character could
  // never actually reach "idle" (the modeUntil check's `if (walking)` always took the false
  // branch, re-picking a walk target forever) and bobTilt/limbAngles never updated (their own
  // `if (walking) {...}` block was equally unreachable) -- walking still LOOKED like it worked
  // because setPos's functional updater (which does get fresh state) kept moving the character
  // toward whatever target got picked, just with zero bob/tilt/limb motion underneath. Same fix
  // already applied to agentsActive just above -- mirror it here instead of reading state directly.
  const walkingRef = useRef(false);
  useEffect(() => {
    walkingRef.current = walking;
  }, [walking]);
  const activeJobIdsRef = useRef(new Set());
  // Alternate, don't randomize -- a deterministic flip on every new walk phase / every reaction
  // guarantees both mechanisms actually get exercised across a real test session instead of
  // leaving it to chance which one shows up.
  const walkLegCounterRef = useRef(0);
  const walkMechanismRef = useRef("flat"); // "flat" | "rig", set per walk phase
  const reactCounterRef = useRef(0);
  const reactMechanismRef = useRef("flat"); // "flat" | "rig", set per reaction
  useEffect(() => {
    agentsActiveRef.current = agentsActive;
  }, [agentsActive]);

  // Level 4-equivalent for this surface: real click-through toggling. The
  // window defaults to click-through (see createDesktopPetWindow) so the
  // desktop and every other app stay fully usable underneath; hovering the
  // character's actual hit area is the only thing that makes this window
  // start accepting clicks, and it reverts the instant the pointer leaves.
  function handleEnter() {
    setHovering(true);
    if (!embedded) window.electronAPI?.setDesktopPetClickThrough?.(false);
  }
  function handleLeave() {
    setHovering(false);
    if (!embedded) window.electronAPI?.setDesktopPetClickThrough?.(true);
  }

  // Shared by the click handler and the agent-awareness effect below --
  // "poked" and "a job just finished successfully" are the same bounce.
  function triggerReact() {
    reactCounterRef.current += 1;
    reactMechanismRef.current = reactCounterRef.current % 2 === 0 ? "flat" : "rig";
    setReacting(true);
    if (reactTimeoutRef.current) clearTimeout(reactTimeoutRef.current);
    reactTimeoutRef.current = setTimeout(() => setReacting(false), REACT_ANIM_MS);
  }

  function triggerShake() {
    setShaking(true);
    if (shakeTimeoutRef.current) clearTimeout(shakeTimeoutRef.current);
    shakeTimeoutRef.current = setTimeout(() => setShaking(false), SHAKE_ANIM_MS);
  }

  function handleClick() {
    triggerReact();
  }

  // Integration-plan Phase 2: agent-awareness. Tracks which job ids are
  // currently queued/working (not trusted from the backend's single shared
  // pet.state -- see this component's doc comment above for why) and
  // derives `agentsActive` from whether that set is non-empty. A job's
  // FIRST message ever seen already being done/error (a very fast job, or
  // one that started before this window connected via the initial
  // snapshot) intentionally does not trigger a success/error pulse -- only
  // a job actually observed transitioning out of the active set does,
  // otherwise every reconnect/mount would replay a burst of stale pulses.
  useEffect(() => {
    const disconnect = connectAgentSocket((msg) => {
      if (msg.type === "snapshot") {
        const active = new Set(
          (msg.jobs || []).filter((j) => j.status === "queued" || j.status === "working").map((j) => j.id)
        );
        activeJobIdsRef.current = active;
        setAgentsActive(active.size > 0);
        return;
      }
      if (msg.type !== "job") return;
      const job = msg.job;
      const wasActive = activeJobIdsRef.current.has(job.id);
      const isActive = job.status === "queued" || job.status === "working";
      if (isActive) {
        activeJobIdsRef.current.add(job.id);
      } else {
        activeJobIdsRef.current.delete(job.id);
        if (wasActive && job.status === "done") triggerReact();
        else if (wasActive && job.status === "error") triggerShake();
      }
      setAgentsActive(activeJobIdsRef.current.size > 0);

      const text = msg.pet?.text;
      if (text) {
        setSayText(text);
        if (sayTimeoutRef.current) clearTimeout(sayTimeoutRef.current);
        sayTimeoutRef.current = setTimeout(() => setSayText(null), SAY_DISPLAY_MS);
      } else if (activeJobIdsRef.current.size === 0) {
        setSayText(null);
      }
    });
    return disconnect;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The actual walk AI + animation loop. One requestAnimationFrame driving
  // everything (position, facing, bob/tilt, and now per-limb rig angles)
  // so they never drift out of sync with each other -- a separate
  // setInterval for "pick a new target" and a separate rAF for "animate
  // toward it" is the classic way to get walk cycles that stutter.
  useEffect(() => {
    function pickNewIdlePause() {
      walkingRef.current = false; // set synchronously -- setWalking's effect sync lags a frame
      setWalking(false);
      modeUntilRef.current = performance.now() + randomBetween(1500, 4200);
    }
    function pickNewWalkTarget() {
      const maxX = Math.max(0, (stageRef.current?.clientWidth || window.innerWidth) - Math.max(CHAR_WIDTH, RIG_CHAR_WIDTH));
      const nextTarget = randomBetween(0, maxX);
      targetXRef.current = nextTarget;
      walkLegCounterRef.current += 1;
      walkMechanismRef.current = walkLegCounterRef.current % 2 === 0 ? "flat" : "rig";
      walkingRef.current = true; // set synchronously -- setWalking's effect sync lags a frame
      setWalking(true);
      // Bounded by distance/speed too -- a long walk shouldn't get cut off
      // mid-stride by an arbitrary timer, and a short one shouldn't stall.
      setPos((current) => {
        const distance = Math.abs(nextTarget - current.x);
        modeUntilRef.current = performance.now() + (distance / WALK_SPEED) * 1000 + 300;
        return current;
      });
    }
    // First beat: mostly start walking (a pet that never moves is a bug,
    // not a personality), occasionally start idle.
    if (Math.random() < 0.8) pickNewWalkTarget();
    else pickNewIdlePause();

    let lastT = performance.now();
    // Plain closure variable, not a ref -- persists across tick() calls the normal JS way (this
    // closure isn't subject to the stale-React-state problem above, only bare reads of `walking`/
    // `bobTilt` state were), used only to skip a redundant setBobTilt once already at rest.
    let bobTiltIsZero = true;
    function tick(t) {
      const dt = Math.min(0.05, (t - lastT) / 1000); // clamp to avoid a huge jump after a tab/window stall
      lastT = t;

      // Integration-plan Phase 2: while any agent job is active, freeze the
      // walk AI in place (no new targets picked, no position change) and
      // let the render below show the sustained "thinking" pose instead --
      // a character that keeps wandering around while N.O.V.A. is visibly
      // busy elsewhere reads as not paying attention, the opposite of the
      // awareness this phase is for. modeUntilRef is deliberately left
      // untouched (not reset) so resuming after agentsActive drops back to
      // false continues the current idle/walk phase's timer from where it
      // left off, rather than restarting it.
      if (!agentsActiveRef.current) {
        if (t > modeUntilRef.current) {
          if (walkingRef.current) pickNewIdlePause();
          else pickNewWalkTarget();
        }

        setPos((current) => {
          const maxX = Math.max(0, (stageRef.current?.clientWidth || window.innerWidth) - Math.max(CHAR_WIDTH, RIG_CHAR_WIDTH));
          const target = Math.min(maxX, Math.max(0, targetXRef.current));
          const dx = target - current.x;
          if (Math.abs(dx) < 1) return current;
          const step = Math.sign(dx) * Math.min(Math.abs(dx), WALK_SPEED * dt);
          setDirection(step >= 0 ? 1 : -1);
          const nextX = Math.min(maxX, Math.max(0, current.x + step));
          return { x: nextX };
        });

        if (walkingRef.current) {
          walkPhaseRef.current += dt * 9; // gait frequency
          bobTiltIsZero = false;
          setBobTilt({
            bob: Math.abs(Math.sin(walkPhaseRef.current)) * -4,
            tilt: Math.sin(walkPhaseRef.current) * 3,
          });
          if (walkMechanismRef.current === "rig") {
            const legSwing = Math.sin(walkPhaseRef.current) * WALK_LEG_SWING_DEG;
            setLimbAngles({
              legLeft: legSwing,
              legRight: -legSwing,
              // Contralateral gait -- each arm swings with the OPPOSITE-side leg, same as a real walk.
              armRight: legSwing * WALK_ARM_SWING_RATIO,
              armLeft: -legSwing * WALK_ARM_SWING_RATIO,
            });
          }
        } else if (!bobTiltIsZero) {
          bobTiltIsZero = true;
          setBobTilt({ bob: 0, tilt: 0 });
        }
      } else if (!bobTiltIsZero) {
        bobTiltIsZero = true;
        setBobTilt({ bob: 0, tilt: 0 });
      }

      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
    // Deliberately mount-once: pickNewIdlePause/pickNewWalkTarget/tick read walkingRef (kept in
    // sync with `walking` both by the effect above and, synchronously, by the two functions
    // themselves), not the `walking` state binding directly -- a bare read of React state inside
    // a mount-once effect is stale forever (see walkingRef's own comment for the real bug this
    // was until this pass), and the whole point of mount-once here is to not restart (and reset
    // lastT/walkPhaseRef) every time `walking` flips.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(
    () => () => {
      if (reactTimeoutRef.current) clearTimeout(reactTimeoutRef.current);
      if (shakeTimeoutRef.current) clearTimeout(shakeTimeoutRef.current);
      if (sayTimeoutRef.current) clearTimeout(sayTimeoutRef.current);
    },
    []
  );

  // spriteMode: reacting always wins, then an actual walk cycle while genuinely walking,
  // otherwise the limb rig (idle/thinking/shaking all use it -- no dedicated flat art exists for
  // those, and unlike walk/wave there's no flat mechanism to alternate with). `walking &&
  // !agentsActive` mirrors the exact condition already used below for the bob/tilt transform.
  // "walk"/"wave" render the flat generated frame; "rig-walk"/"rig-wave" render the limb rig
  // driven into that same motion instead -- see walkMechanismRef/reactMechanismRef above for how
  // the two are chosen (alternating, not simultaneous -- see the file doc comment for why).
  const spriteMode = reacting
    ? reactMechanismRef.current === "rig"
      ? "rig-wave"
      : "wave"
    : walking && !agentsActive
      ? walkMechanismRef.current === "rig"
        ? "rig-walk"
        : "walk"
      : "rig";
  // Two-frame gait driven by the same walkPhaseRef sine that already drives bob/tilt (section 5's
  // plan: "reusing the existing bob/tilt phase loop to also drive a frame index") -- tilt's sign
  // already tracks that sine, so no new per-tick state is needed just to pick a frame.
  const walkFrameImage = bobTilt.tilt >= 0 ? walk1Image : walk2Image;
  const visualWidth = spriteMode === "walk" || spriteMode === "wave" ? FRAME_CHAR_WIDTH : RIG_CHAR_WIDTH;

  return (
    <div ref={stageRef} className={`relative ${embedded ? "h-full w-full" : "h-screen w-screen"} overflow-hidden select-none`} style={{ background: "transparent" }}>
      <div
        className="absolute"
        style={{
          left: pos.x,
          bottom: GROUND_MARGIN,
          width: visualWidth,
          height: CHAR_HEIGHT,
        }}
      >
        {/* Facing (scaleX mirror) lives on a stable outer wrapper, never
            touched by a CSS `animation` -- keeping it separate from the
            pose transform below means an idle-breathe pause can't
            momentarily "un-mirror" the character back to its default
            facing, since a running animation only overrides `transform`
            on the element it's actually applied to. */}
        {/* Integration-plan Phase 2: speech bubble for pet.text (the
            backend's short "what's it doing" blurb, already sanitized --
            see pet.py). Positioned above the character regardless of
            facing direction, so it doesn't need to un-mirror. */}
        {sayText && (
          <div
            className="pet-say-bubble absolute left-1/2 whitespace-nowrap rounded-lg bg-charcoal-900/90 px-2.5 py-1 text-[11px] font-medium text-charcoal-100 shadow-lg"
            style={{ bottom: "100%", marginBottom: 8, transform: "translateX(-50%)" }}
          >
            {sayText}
          </div>
        )}
        <div
          onClick={handleClick}
          onMouseEnter={handleEnter}
          onMouseLeave={handleLeave}
          title="Poke me"
          className="relative h-full w-full cursor-pointer"
          style={{
            transform: `scaleX(${direction})${hovering ? " scale(1.08)" : ""}`,
            transformOrigin: "50% 100%",
            transition: "transform 120ms linear",
            filter: `drop-shadow(0 4px 6px rgba(0,0,0,0.35))${
              agentsActive && !reacting && !shaking ? " drop-shadow(0 0 10px rgba(167,139,250,0.55))" : ""
            }`,
          }}
        >
          <div
            className={`relative h-full w-full ${
              reacting
                ? "pet-bounce-squash"
                : shaking
                  ? "pet-shake"
                  : agentsActive
                    ? "pet-thinking"
                    : !walking && !hovering
                      ? "pet-idle-breathe"
                      : ""
            }`}
            style={
              walking && !agentsActive
                ? { transform: `translateY(${bobTilt.bob}px) rotate(${bobTilt.tilt}deg)` }
                : undefined
            }
          >
            {spriteMode === "walk" || spriteMode === "wave" ? (
              // walk/wave frames are single flat images (no separately cut eyes/mouth layer),
              // so no blink/parallax overlay here -- see the RESEARCH.md entry on what came back.
              <img
                src={spriteMode === "wave" ? waveImage : walkFrameImage}
                alt="N.O.V.A."
                draggable={false}
                className="absolute inset-0 h-full w-full"
              />
            ) : (
              <div className="absolute inset-0">
                <img
                  src={RIG_IMAGES.torso}
                  alt="N.O.V.A."
                  draggable={false}
                  style={RIG_PART_STYLE.torso}
                />
                {RIG_LIMBS.map((part) => (
                  <img
                    key={part}
                    src={RIG_IMAGES[part]}
                    alt=""
                    draggable={false}
                    style={{
                      ...RIG_PART_STYLE[part],
                      transformOrigin: RIG_PIVOT[part],
                      transform:
                        spriteMode === "rig-walk"
                          ? `rotate(${limbAngles[LIMB_ANGLE_KEY[part]]}deg)`
                          : undefined,
                    }}
                    className={
                      spriteMode === "rig-walk"
                        ? ""
                        : spriteMode === "rig-wave" && part === WAVE_ARM_PART
                          ? "rig-wave-swing"
                          : RIG_SWAY_CLASS[part]
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes pet-idle-breathe {
          0%, 100% { transform: translateY(0) scale(1) rotate(0deg); }
          25% { transform: translateY(-2px) scale(1.015) rotate(-1.1deg); }
          50% { transform: translateY(-3.5px) scale(1.03) rotate(0deg); }
          75% { transform: translateY(-1px) scale(1.015) rotate(1.1deg); }
        }
        .pet-idle-breathe {
          animation: pet-idle-breathe 4.4s ease-in-out infinite;
        }
        @keyframes pet-bounce-squash {
          0% { transform: scale(1, 1) translateY(0); }
          25% { transform: scale(0.88, 1.16) translateY(2px); }
          50% { transform: scale(1.1, 0.9) translateY(-4px); }
          72% { transform: scale(0.96, 1.05) translateY(1px); }
          100% { transform: scale(1, 1) translateY(0); }
        }
        .pet-bounce-squash {
          animation: pet-bounce-squash ${REACT_ANIM_MS}ms cubic-bezier(.34,1.56,.64,1) 1;
        }
        /* Integration-plan Phase 2: sustained pose while an agent job is
           active -- a faster, smaller-amplitude bob than idle-breathe (2.1s
           vs 4.4s) so it reads as "alert/working" rather than "resting."
           The purple drop-shadow glow driving this apart from idle is set
           inline above (agentsActive), matching Miniplayer's existing
           thinking-state purple (#a78bfa) for one consistent color language
           across both surfaces. */
        @keyframes pet-thinking {
          0%, 100% { transform: translateY(0) scale(1) rotate(0deg); }
          50% { transform: translateY(-2.5px) scale(1.02) rotate(0deg); }
        }
        .pet-thinking {
          animation: pet-thinking 2.1s ease-in-out infinite;
        }
        /* Integration-plan Phase 2: one-shot error reaction -- a short
           horizontal shake, deliberately distinct from the vertical
           bounce-squash success reaction so the two read as different
           outcomes at a glance. */
        @keyframes pet-shake {
          0%, 100% { transform: translateX(0); }
          20% { transform: translateX(-5px) rotate(-2deg); }
          40% { transform: translateX(4px) rotate(2deg); }
          60% { transform: translateX(-3px) rotate(-1deg); }
          80% { transform: translateX(2px) rotate(1deg); }
        }
        .pet-shake {
          animation: pet-shake ${SHAKE_ANIM_MS}ms ease-in-out 1;
        }
        @keyframes pet-say-bubble-in {
          from { opacity: 0; transform: translateX(-50%) translateY(4px); }
          to { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
        .pet-say-bubble {
          animation: pet-say-bubble-in 180ms ease-out;
        }
        /* Limb rig (RESEARCH.md, 2026-09-04 "Limb-rig layers delivered"): each limb sways on its
           own period so none of the four move in lockstep -- same idea as pet-face-parallax
           drifting out of phase with pet-idle-breathe, just extended to real joints now. */
        @keyframes rig-sway-arm-left { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(-6deg); } }
        @keyframes rig-sway-arm-right { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(6deg); } }
        @keyframes rig-sway-leg-left { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(-3deg); } }
        @keyframes rig-sway-leg-right { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(3deg); } }
        .rig-sway-arm-left { animation: rig-sway-arm-left 3.6s ease-in-out infinite; }
        .rig-sway-arm-right { animation: rig-sway-arm-right 4.1s ease-in-out infinite; }
        .rig-sway-leg-left { animation: rig-sway-leg-left 5.2s ease-in-out infinite; }
        .rig-sway-leg-right { animation: rig-sway-leg-right 4.7s ease-in-out infinite; }
        /* One-shot raised-arm wave, timed to REACT_ANIM_MS -- two quick oscillations around the
           raised angle so it reads as an actual wave, not just an arm lifting once. */
        @keyframes rig-wave-swing {
          0% { transform: rotate(0deg); }
          25% { transform: rotate(-75deg); }
          45% { transform: rotate(-58deg); }
          65% { transform: rotate(-78deg); }
          85% { transform: rotate(-58deg); }
          100% { transform: rotate(-15deg); }
        }
        .rig-wave-swing {
          animation: rig-wave-swing ${REACT_ANIM_MS}ms ease-in-out 1;
        }
      `}</style>
    </div>
  );
}
