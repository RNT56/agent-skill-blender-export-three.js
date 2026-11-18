// Water wave model: ONE definition used by the vertex shader, the fragment shader (normals) and the CPU (floating objects, ripples, fauna), so
// a duck, a lily pad and a drifting petal sit exactly on the surface the GPU draws. Pure (no three.js).
//
// Each component is a sharpened sine, h = a * (exp(sin(theta) - 1) - MEAN): narrow crests and broad troughs, like real wind waves, with an
// analytic derivative. Wavelengths follow deep-water dispersion (omega = sqrt(g k)). The longest waves displace the mesh; the shorter ones only
// bend the normal (the mesh is too coarse to carry them), the CPU height uses the same displacing set the mesh uses.
const G = 9.81, MEAN = 0.4661;                              // mean of exp(sin(x) - 1) over a period (so the surface has zero mean)

/** wavelength (m), amplitude at wind 1 (m), direction offset from the wind (rad), phase */
export const WAVES = [
  { L: 8.2, a: 0.075, dir: 0.00, phase: 0.3 },
  { L: 5.1, a: 0.050, dir: 0.50, phase: 1.7 },
  { L: 3.3, a: 0.032, dir: -0.62, phase: 4.1 },
  { L: 2.0, a: 0.018, dir: 1.10, phase: 2.2 },               // normal-only from here on
  { L: 1.2, a: 0.010, dir: -1.25, phase: 5.3 },
];
export const DISPLACING = 3;                               // the first N waves move the mesh vertices

for (const w of WAVES) { w.k = 2 * Math.PI / w.L; w.omega = Math.sqrt(G * w.k); }

/**
 * Surface height at (x, z) and its slope. `wind` = {x, z} unit direction, `amp` = amplitude multiplier (wind strength), `t` seconds.
 * @param n how many waves to sum (DISPLACING for the mesh height, WAVES.length for normals)
 * @param out optional {h, dx, dz} to fill
 */
export function waveSample(x, z, t, windX, windZ, amp = 1, n = DISPLACING, out = { h: 0, dx: 0, dz: 0 }) {
  const base = Math.atan2(windZ, windX);
  let h = 0, dx = 0, dz = 0;
  for (let i = 0; i < n; i++) {
    const w = WAVES[i], ang = base + w.dir, ux = Math.cos(ang), uz = Math.sin(ang);
    const th = w.k * (ux * x + uz * z) - w.omega * t + w.phase, s = Math.sin(th), e = Math.exp(s - 1);
    const a = w.a * amp;
    h += a * (e - MEAN);
    const d = a * e * Math.cos(th) * w.k;                    // d/dtheta = a e cos(theta); dtheta/dx = k ux
    dx += d * ux; dz += d * uz;
  }
  out.h = h; out.dx = dx; out.dz = dz;
  return out;
}

/** GLSL for the same model: `vec3 waveGrad(vec2 p, int n)` (x = height, yz = d/dx, d/dz). Needs uniforms uTime, uWindDir, uAmp. */
export function waveGLSL() {
  const consts = WAVES.map((w, i) => `const vec4 W${i} = vec4(${w.k.toFixed(5)}, ${w.omega.toFixed(5)}, ${w.dir.toFixed(4)}, ${w.phase.toFixed(4)}); const float A${i} = ${w.a.toFixed(5)};`).join('\n');
  const body = WAVES.map((w, i) => `
    if (${i} < n) { float ang = base + W${i}.z; vec2 u = vec2(cos(ang), sin(ang)); float th = W${i}.x * dot(u, p) - W${i}.y * uTime + W${i}.w;
      float s = sin(th), e = exp(s - 1.0), a = A${i} * uAmp; r.x += a * (e - ${MEAN.toFixed(4)}); r.yz += a * e * cos(th) * W${i}.x * u; }`).join('');
  return `${consts}
    vec3 waveGrad(vec2 p, int n){ float base = atan(uWindDir.y, uWindDir.x); vec3 r = vec3(0.0);${body}
      return r; }`;
}
