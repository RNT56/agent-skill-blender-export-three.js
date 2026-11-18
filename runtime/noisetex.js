// Tileable noise texture: four independent fBm patterns (one per RGBA channel), so a single texture fetch replaces ~4 octaves x 4 channels of
// procedural ALU noise in a fragment shader. Used by fog, cloud shadows, water and anything else that needs cheap, drifting, wind-advected noise.
//
//   uniform sampler2D tNoise;   vec4 n = texture2D(tNoise, worldXZ * scale + offset);   // n.r, n.g, n.b, n.a in 0..1, roughly uniform
//
// Octave lattices are 8/16/32/64 cells over the texture and wrap, so the texture tiles seamlessly in both directions.
import * as THREE from 'three';
import { mulberry32 } from './noise.js';

const smooth = t => t * t * (3 - 2 * t);
const OCTAVES = [[8, 0.5], [16, 0.25], [32, 0.125], [64, 0.0625]], NORM = 0.9375;

export function createNoiseTexture(size = 256, seed = 1) {
  const data = new Uint8Array(size * size * 4);
  for (let ch = 0; ch < 4; ch++) {
    const rng = mulberry32(seed * 7919 + ch * 104729);
    const lattices = OCTAVES.map(([n]) => Float32Array.from({ length: n * n }, rng));
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      let v = 0;
      for (let o = 0; o < OCTAVES.length; o++) {
        const [n, a] = OCTAVES[o], L = lattices[o], u = x / size * n, w = y / size * n, i = Math.floor(u), j = Math.floor(w), fu = smooth(u - i), fv = smooth(w - j);
        const i0 = i % n, i1 = (i + 1) % n, j0 = j % n, j1 = (j + 1) % n;
        v += a * ((L[j0 * n + i0] * (1 - fu) + L[j0 * n + i1] * fu) * (1 - fv) + (L[j1 * n + i0] * (1 - fu) + L[j1 * n + i1] * fu) * fv);
      }
      data[(y * size + x) * 4 + ch] = Math.max(0, Math.min(255, Math.round(v / NORM * 255)));
    }
  }
  const tex = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.magFilter = tex.minFilter = THREE.LinearFilter; tex.generateMipmaps = false; tex.needsUpdate = true;
  return tex;
}
