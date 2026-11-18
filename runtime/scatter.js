// Deterministic rejection scatter with a minimum-distance grid (Poisson-ish), for trees/rocks/props.
import { mulberry32 } from './noise.js';

/**
 * @param region   {x0,z0,x1,z1}
 * @param accept   (x,z) => probability 0..1 that a candidate is accepted (0 = never)
 * @param minDist  minimum spacing between accepted points (metres) or a function (x,z)=>metres
 */
export function scatter({ seed = 1, region, count, accept, minDist = 6, maxTries = 40000 }) {
  const rng = mulberry32(seed);
  const cell = (typeof minDist === 'number' ? minDist : 8) / Math.SQRT2;
  const grid = new Map();
  const out = [];
  for (let t = 0; t < maxTries && out.length < count; t++) {
    const x = region.x0 + rng() * (region.x1 - region.x0), z = region.z0 + rng() * (region.z1 - region.z0);
    if (rng() > accept(x, z)) continue;
    const md = typeof minDist === 'number' ? minDist : minDist(x, z);
    const gi = Math.floor(x / cell), gj = Math.floor(z / cell);
    const reach = Math.ceil(md / cell);
    let ok = true;
    for (let j = gj - reach; j <= gj + reach && ok; j++) {
      for (let i = gi - reach; i <= gi + reach && ok; i++) {
        const p = grid.get(i + ',' + j);
        if (p) for (const q of p) if (Math.hypot(q.x - x, q.z - z) < Math.max(md, q.md)) { ok = false; break; }
      }
    }
    if (!ok) continue;
    const p = { x, z, md, r1: rng(), r2: rng(), r3: rng() };
    out.push(p);
    const key = gi + ',' + gj;
    (grid.get(key) ?? grid.set(key, []).get(key)).push(p);
  }
  return out;
}
