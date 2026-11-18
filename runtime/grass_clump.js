// Procedural grass CLUMPS for tall fields (rice paddies, meadow grass, reeds): each instance is a small bouquet of arching blades, some carrying a drooping
// seed head (panicle), in three levels of detail. One clump replaces ~7 single blades, so a dense field costs a few hundred thousand triangles, not millions.
//
// Geometry conventions (shared with grass.js):  y = height as a FRACTION of the instance height (uv.y = the same value, 0 base .. 1 tip, used by the shader for
// bending and colour); x / z are metres at instance width scale 1. Extra per-vertex attributes: aBlade (random 0..1 per blade) and aHead (1 on seed-head vertices).
import * as THREE from 'three';
import { mulberry32 } from './noise.js';

function clump({ seed, blades, segs, spread, heads, halfW, lean0 = 0.12, lean1 = 0.26 }) {
  const rng = mulberry32(seed), pos = [], uv = [], blade = [], head = [], idx = [];
  const push = (x, y, z, t, b, h) => { pos.push(x, y, z); uv.push(h, t); blade.push(b); head.push(h); };
  for (let i = 0; i < blades; i++) {
    const r = spread * Math.sqrt(rng()), a = rng() * Math.PI * 2, cx = Math.cos(a) * r, cz = Math.sin(a) * r;
    const out = Math.atan2(cz, cx) + (rng() - 0.5) * 1.6;                              // blades arch outward from the clump centre
    const hf = 0.74 + 0.26 * rng(), lean = lean0 + (lean1 - lean0) * rng(), wv = 0.85 + 0.3 * rng(), b = rng();
    const dx = Math.cos(out), dz = Math.sin(out), ax = -dz, az = dx;                    // lean direction and the ribbon's width axis
    const base = pos.length / 3;
    for (let k = 0; k <= segs; k++) {
      const t = k / segs, y = t * hf, f = Math.pow(t, 1.65), lat = lean * f, w = halfW * wv * (1 - Math.pow(t, 0.9) * 0.94) + 0.0006;
      const px = cx + dx * lat, pz = cz + dz * lat;
      push(px - ax * w, y, pz - az * w, y, b, 0); push(px + ax * w, y, pz + az * w, y, b, 0);
      if (k > 0) { const j = base + (k - 1) * 2; idx.push(j, j + 1, j + 2, j + 1, j + 3, j + 2); }
    }
    if (rng() < heads && hf > 0.82) {                                                   // a panicle: a thick ribbon that rises a little, then droops over
      const tx = cx + dx * lean * 1.0, tz = cz + dz * lean * 1.0, hb = pos.length / 3, rows = 4;
      for (let k = 0; k <= rows; k++) {
        const s = k / rows, fx = 0.13 * Math.pow(s, 1.35), y = hf + 0.045 * s - 0.15 * s * s, w = 0.021 * (1 - 0.55 * s) + 0.0008;
        const px = tx + dx * fx, pz = tz + dz * fx;
        push(px - ax * w, y, pz - az * w, Math.min(1, y), b, 1); push(px + ax * w, y, pz + az * w, Math.min(1, y), b, 1);
        if (k > 0) { const j = hb + (k - 1) * 2; idx.push(j, j + 1, j + 2, j + 1, j + 3, j + 2); }
      }
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('aBlade', new THREE.Float32BufferAttribute(blade, 1)); g.setAttribute('aHead', new THREE.Float32BufferAttribute(head, 1));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
}

/** @returns [LOD0, LOD1, LOD2] clump geometries (about 140 / 36 / 16 triangles) */
export function createClumpLods(seed = 3) {
  return [
    clump({ seed, blades: 9, segs: 6, spread: 0.24, heads: 0.5, halfW: 0.0175 }),
    clump({ seed: seed + 1, blades: 6, segs: 3, spread: 0.30, heads: 0.25, halfW: 0.026 }),
    clump({ seed: seed + 2, blades: 4, segs: 2, spread: 0.34, heads: 0, halfW: 0.045 }),
  ];
}
