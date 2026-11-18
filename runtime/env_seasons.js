// Seasons: a continuous season value (0..4, see env_clock.js) -> a smooth, data-driven description of the world's seasonal state
// (grass colour / height / density, leaf colour and fall per tree kind, ground tint, snow, falling particles, light modifiers).
// The descriptors live in looks/atmosphere.json under "seasons"; this module only interpolates them (cyclically, with eased blends).
import { leafKind } from './foliage.js';

const smooth = t => t * t * (3 - 2 * t);

/** interpolate any JSON-like tree of numbers / arrays / objects (same shape on both sides) */
export function lerpTree(a, b, t, out) {
  if (typeof a === 'number') return a + (b - a) * t;
  if (Array.isArray(a)) { const o = out ?? new Array(a.length); for (let i = 0; i < a.length; i++) o[i] = lerpTree(a[i], b[i], t, o[i]); return o; }
  if (a && typeof a === 'object') { const o = out ?? {}; for (const k of Object.keys(a)) o[k] = lerpTree(a[k], b[k], t, o[k]); return o; }
  return a;
}

export class Seasons {
  /** @param descriptors { spring: {at, ...}, summer: {at, ...}, autumn: {...}, winter: {...} }  `at` = season value at which the descriptor is exact */
  constructor(descriptors) {
    this.keys = Object.entries(descriptors).map(([name, d]) => ({ name, at: d.at, data: d })).sort((a, b) => a.at - b.at);
    this.state = null;
  }

  /** @param season continuous 0..4 (cyclic). Returns a shared state object (valid until the next call). */
  at(season) {
    const K = this.keys, n = K.length, s = ((season % 4) + 4) % 4;
    let i = n - 1;                                                           // find the key at or before s (wrapping from the last key)
    for (let k = 0; k < n; k++) if (K[k].at <= s) i = k;
    const a = K[i], b = K[(i + 1) % n], span = (b.at - a.at + 4) % 4 || 4, t = smooth(Math.min(1, Math.max(0, (((s - a.at) % 4) + 4) % 4 / span)));
    this.state = lerpTree(a.data, b.data, t, this.state);
    this.state.name = t < 0.5 ? a.name : b.name; this.state.blend = t; this.state.from = a.name; this.state.to = b.name;
    return this.state;
  }
}

// ---------------------------------------------------------------------------------------------------- appliers: season state -> uniforms
/** grass uniforms (createGrassUniforms): blade colour multiplier, saturation, height, density, frost */
export function applyGrassSeason(U, ssn) {
  const g = ssn.grass;
  U.uSeasonTint.value.set(g.tint[0], g.tint[1], g.tint[2]); U.uSeasonSat.value = g.sat; U.uSeasonHeight.value = g.height; U.uSeasonKeep.value = g.keep; U.uFrost.value = g.frost; U.uRipe.value = g.ripe ?? 1;
}
/** foliage uniforms (createFoliageUniforms): leaf recolour + leaf fall for every tree kind that has been patched */
export function applyLeafSeason(U, ssn) {
  for (const [kind, d] of Object.entries(ssn.leaf)) {
    const K = U.kinds[kind]; if (!K) continue;
    K.uLeafMix.value = d.mix; K.uLeafColor.value.set(d.color[0], d.color[1], d.color[2]); K.uLeafKeep.value = d.keep;
  }
}
/** terrain uniforms (createTerrain().uniforms): grassy ground tint and snow cover */
export function applyTerrainSeason(U, ssn) {
  U.uGroundTint.value.set(ssn.ground.tint[0], ssn.ground.tint[1], ssn.ground.tint[2]); U.uSnow.value = ssn.ground.snow;
}
export { leafKind };
