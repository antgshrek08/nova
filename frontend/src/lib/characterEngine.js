/**
 * One implementation of the limb-rig geometry, shared by DesktopPet.jsx and
 * the miniplayer character. (The miniplayer's original component,
 * Miniplayer.jsx, was superseded by NovaReactorWindow.jsx and deleted; the
 * history below is why this module exists and still applies.)
 *
 * Why this module exists (CLAUDE_CODE_HANDOFF.md section 7, item 3): the rig
 * positioning/pivot code was copy-pasted between those two components almost
 * verbatim -- Miniplayer.jsx's own comment described itself as "duplicated per
 * this file's own 'not a shared module boundary yet' convention". Two copies of
 * animation math is exactly how the walk mechanism drifted apart once already,
 * so the handoff asked for a single shared module before any further behavior
 * was built on top of it.
 *
 * The two copies were byte-identical apart from one number: the character
 * height they scale to (DesktopPet 118px, Miniplayer 145px). That is the only
 * parameter `createRig` takes.
 *
 * Source of truth for every number here is rig-spec.json, which carries the
 * measurements taken from the actual layer cut -- the shared canvas size, each
 * part's position on that canvas, and each part's own joint pivot expressed
 * inside that part's own image (for CSS transform-origin, so a limb rotates at
 * the shoulder/hip rather than around its image centre). Do not re-derive any
 * of it by eye; convert straight from the JSON.
 */
import rigSpec from "../assets/character/rig/rig-spec.json";
import rigTorsoImage from "../assets/character/rig/torso.png";
import rigArmLeftImage from "../assets/character/rig/arm-left.png";
import rigArmRightImage from "../assets/character/rig/arm-right.png";
import rigLegLeftImage from "../assets/character/rig/leg-left.png";
import rigLegRightImage from "../assets/character/rig/leg-right.png";

export const RIG_CANVAS_W = rigSpec.canvas_size[0];
export const RIG_CANVAS_H = rigSpec.canvas_size[1];

/** The four independently-rotatable parts. The torso (head+torso+pelvis) is
 *  deliberately unsplit -- face articulation stays with eyes.png/mouth.png. */
export const RIG_LIMBS = ["arm-left", "arm-right", "leg-left", "leg-right"];

export const RIG_IMAGES = {
  torso: rigTorsoImage,
  "arm-left": rigArmLeftImage,
  "arm-right": rigArmRightImage,
  "leg-left": rigLegLeftImage,
  "leg-right": rigLegRightImage,
};

/** Maps a rig part to the key it uses in a pose object ({armLeft, legRight, ...}). */
export const LIMB_ANGLE_KEY = {
  "arm-left": "armLeft",
  "arm-right": "armRight",
  "leg-left": "legLeft",
  "leg-right": "legRight",
};

export const RIG_SWAY_CLASS = {
  "arm-left": "rig-sway-arm-left",
  "arm-right": "rig-sway-arm-right",
  "leg-left": "rig-sway-leg-left",
  "leg-right": "rig-sway-leg-right",
};

/**
 * wave.png's raised arm is on the image's own left side -- arm-left occupies
 * canvas x:0-654, left of the torso's ~830px centre, i.e. the same side -- so
 * arm-left is the one that raises for a rig-driven wave, matching the flat
 * art's gesture if the two ever appear near each other.
 */
export const WAVE_ARM_PART = "arm-left";

/** Shared walk-cycle shape. Contralateral gait: each arm swings with the
 *  opposite-side leg, the way a real walk does. */
export const WALK_LEG_SWING_DEG = 22;
export const WALK_ARM_SWING_RATIO = 0.55;

/**
 * Builds the geometry for one character size.
 *
 * @param {number} charHeight rendered character height in CSS px
 * @returns {{charWidth:number, scale:number, partStyle:Record<string,object>, pivot:Record<string,string>}}
 *   `partStyle` positions every part (torso + limbs) absolutely inside a shared
 *   container so that, at zero rotation, they reconstruct the original pose
 *   exactly. `pivot` is the CSS transform-origin for each limb.
 */
export function createRig(charHeight) {
  const scale = charHeight / RIG_CANVAS_H;

  const partStyle = (part) => {
    const [w, h] = rigSpec.part_sizes[part];
    const [left, top] = rigSpec.part_positions_on_canvas[part];
    return {
      position: "absolute",
      left: left * scale,
      top: top * scale,
      width: w * scale,
      height: h * scale,
    };
  };

  const pivotPercent = (part) => {
    const [w, h] = rigSpec.part_sizes[part];
    const [px, py] = rigSpec.joint_pivot_within_part[part];
    return `${(px / w) * 100}% ${(py / h) * 100}%`;
  };

  const styles = { torso: partStyle("torso") };
  const pivots = {};
  for (const part of RIG_LIMBS) {
    styles[part] = partStyle(part);
    pivots[part] = pivotPercent(part);
  }

  return {
    charWidth: charHeight * (RIG_CANVAS_W / RIG_CANVAS_H),
    scale,
    partStyle: styles,
    pivot: pivots,
  };
}
