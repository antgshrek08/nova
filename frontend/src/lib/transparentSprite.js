// Lift the character off the flat sheet its artwork was generated on.
//
// The source sprites are RGB WebP with no alpha, drawn on a near-white sheet
// (sampled at ~#fefefe). The previous version flood-filled from the image
// edges and cleared any pixel whose darkest channel was >= 235, which removed
// the bulk of the sheet but left two visible artifacts:
//
//   1. A white fringe. Anti-aliased pixels around the silhouette blend the
//      character into the sheet, so their darkest channel sits below the
//      threshold and they survived as an opaque near-white outline -- read on
//      a dark panel as "the character still has a white background."
//   2. A hard edge. Every surviving pixel was fully opaque, so the silhouette
//      was aliased against whatever it was composited onto.
//
// Both are the same problem: the edge pixels are genuinely a *blend*, so they
// need fractional alpha, not a keep/discard decision. For a pixel P that is
// coverage a of foreground F over background W:  P = a*F + (1-a)*W.
// Estimating a from how far P sits from W gives both the soft edge and, by
// un-mixing W back out, a foreground colour that isn't washed out toward white.
//
// Only pixels reachable from an image edge are touched, so enclosed whites --
// eyes, shirt, highlights -- stay exactly as drawn.

// NOTE: everything this needs lives inside the function body on purpose.
// MiniplayerCharacter.jsx injects it into the character iframe via
// `transparentSprite.toString()`, where module scope does not come along --
// a helper or constant declared out here would be undefined at call time, and
// (since sprite loading catches its own errors) would fail as a silently
// un-keyed sprite rather than a visible exception.

export function transparentSprite(image) {
  const BACKGROUND_TOLERANCE = 26;   // distance from the sampled sheet colour that still counts as sheet
  const EDGE_BAND = 3;               // rings of feathering inward from the cleared region
  const SATURATION_DISTANCE = 118;   // distance at which a pixel counts as fully foreground

  const sampleBackground = (data, width, height) => {
    // Median of the four corners, so one stray pixel can't define the sheet.
    const corners = [
      0,
      (width - 1) * 4,
      (height - 1) * width * 4,
      ((height - 1) * width + width - 1) * 4,
    ];
    return [0, 1, 2].map(offset => {
      const values = corners.map(corner => data[corner + offset]).sort((a, b) => a - b);
      return (values[1] + values[2]) / 2;
    });
  };

  const canvas = document.createElement('canvas');
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(image, 0, 0);
  const width = canvas.width, height = canvas.height;
  const pixels = ctx.getImageData(0, 0, width, height);
  const data = pixels.data;
  const total = width * height;

  const [bgR, bgG, bgB] = sampleBackground(data, width, height);
  // Only treat this as a matte to remove if the sheet really is light. A sprite
  // that already ships with alpha, or one drawn on a dark ground, is returned
  // untouched rather than eaten from the edges inward.
  if (Math.min(bgR, bgG, bgB) < 200) return canvas;

  const state = new Uint8Array(total); // 0 unseen, 1 queued/background, 2 kept
  const queue = new Uint32Array(total);
  let head = 0, tail = 0;

  const distanceToBackground = index => {
    const p = index * 4;
    if (data[p + 3] === 0) return 0;
    const dr = data[p] - bgR, dg = data[p + 1] - bgG, db = data[p + 2] - bgB;
    return Math.sqrt(dr * dr + dg * dg + db * db);
  };

  const consider = index => {
    if (state[index]) return;
    if (distanceToBackground(index) <= BACKGROUND_TOLERANCE) {
      state[index] = 1;
      queue[tail++] = index;
    } else {
      state[index] = 2;
    }
  };

  for (let x = 0; x < width; x++) { consider(x); consider((height - 1) * width + x); }
  for (let y = 0; y < height; y++) { consider(y * width); consider(y * width + width - 1); }

  // Flood the sheet, clearing as we go and collecting the frontier -- the kept
  // pixels that sit directly against cleared ones, i.e. the silhouette edge.
  const frontier = [];
  while (head < tail) {
    const index = queue[head++];
    const x = index % width;
    data[index * 4 + 3] = 0;
    const neighbours = [
      x > 0 ? index - 1 : -1,
      x + 1 < width ? index + 1 : -1,
      index >= width ? index - width : -1,
      index + width < total ? index + width : -1,
    ];
    for (const neighbour of neighbours) {
      if (neighbour < 0) continue;
      consider(neighbour);
      if (state[neighbour] === 2) frontier.push(neighbour);
    }
  }

  // Feather inward. Each ring gets alpha from how far it sits from the sheet
  // colour, saturating at a modest distance so only genuinely blended pixels
  // become translucent -- a fully-saturated pixel one step from the edge stays
  // opaque. The same estimate un-mixes the sheet back out of the colour, which
  // is what actually removes the white halo rather than just softening it.
  const feathered = new Uint8Array(total);
  let ring = frontier;
  for (let depth = 0; depth < EDGE_BAND && ring.length; depth++) {
    const next = [];
    for (const index of ring) {
      if (feathered[index]) continue;
      feathered[index] = 1;
      const p = index * 4;
      const distance = distanceToBackground(index);
      const alpha = Math.min(1, distance / SATURATION_DISTANCE);
      if (alpha < 0.995) {
        // F = (P - (1-a)*W) / a, clamped. Below a floor the estimate is pure
        // noise, so the pixel is simply dropped instead of guessed at.
        if (alpha < 0.08) {
          data[p + 3] = 0;
        } else {
          data[p] = Math.max(0, Math.min(255, (data[p] - (1 - alpha) * bgR) / alpha));
          data[p + 1] = Math.max(0, Math.min(255, (data[p + 1] - (1 - alpha) * bgG) / alpha));
          data[p + 2] = Math.max(0, Math.min(255, (data[p + 2] - (1 - alpha) * bgB) / alpha));
          data[p + 3] = Math.round(alpha * 255);
        }
      }
      const x = index % width;
      const neighbours = [
        x > 0 ? index - 1 : -1,
        x + 1 < width ? index + 1 : -1,
        index >= width ? index - width : -1,
        index + width < total ? index + width : -1,
      ];
      for (const neighbour of neighbours) {
        if (neighbour >= 0 && state[neighbour] === 2 && !feathered[neighbour]) next.push(neighbour);
      }
    }
    ring = next;
  }

  ctx.putImageData(pixels, 0, 0);
  return canvas;
}
