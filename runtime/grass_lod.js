// The continuous level-of-detail law of the grass field, as plain functions. The vertex shader in grass.js evaluates the same formulas per blade (densAt / widthAt there);
// this module is the reference that the tests check: smooth, monotonic, no ring where the field gets sparser, and thinning to nothing at the far edge.
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

/** the cross-over between two density tiers is centred on the tier radius and this wide (+/- fraction of the radius); a denser tier's chunks reach to the outer end */
export const RAMP_HALF = 0.22, RAMP_OUT = 1 + RAMP_HALF;
/** the far thinning starts at this fraction of the outer radius */
export const FAR_START = 0.55;

const ramp = (d, r) => smooth(r * (1 - RAMP_HALF), r * (1 + RAMP_HALF), d);

/**
 * @param tiers [{r, density, wScale}] x3 (outer radius at scale 1, clumps per m^2, blade width multiplier)   @param scale detail scale (radii x scale, density / scale^2)
 * @returns { density(d), width(d), reach } with d = distance (m) from the view focus
 */
export function grassLod(tiers, scale = 1) {
  const R = tiers.map(t => t.r * scale), L = tiers.map(t => Math.log(t.density / (scale * scale))), W = tiers.map(t => t.wScale);
  return {
    reach: R[2],
    density(d) { let l = L[0] + (L[1] - L[0]) * ramp(d, R[0]); l += (L[2] - l) * ramp(d, R[1]); return Math.exp(l) * (1 - smooth(FAR_START * R[2], R[2], d)); },
    width(d) { let w = W[0] + (W[1] - W[0]) * ramp(d, R[0]); w += (W[2] - w) * ramp(d, R[1]); return w; },
    /** which tier a chunk at distance d (to its near edge) is built at: a denser tier reaches through the whole cross-over */
    tierAt(d) { for (let t = 0; t < 3; t++) if (d < R[t] * (t < 2 ? RAMP_OUT : 1)) return t; return -1; },
  };
}
