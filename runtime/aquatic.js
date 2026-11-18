// Aquatic flora and shore props, all instanced:
//   ReedField     cattail / reed bundles on the wet bank and in the shallows; wind sway, season colour / height / die-back (shares the grass uniforms)
//   LilyPads      floating pads (+ lotus blooms): ride the wave surface exactly (CPU wave model), drift slowly, grow and die back with the seasons
//   Flotsam       petals / leaves drifting on the water, pushed by the wind, bobbing on the waves
//   ShoreRocks    boulders along the waterline (static, shadow casting)
// Placement helpers (placeShore) only need the Water object and a few rules, so any basin works.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { scatter } from './scatter.js';
import { mulberry32 } from './noise.js';

/**
 * Scatter points around a water body.
 * @param rel   [min, max] terrain height relative to the water level where points may stand (e.g. [-0.5, 0.4] = shallows and wet bank; [0.35,1.5] under water: use depth)
 * @param depth alternatively [min, max] water depth (m) (positive = under water); wins over `rel` when given
 * @param accept optional (x, z) => 0..1 extra probability (clumping noise, exclusions)
 */
export function placeShore({ water, count, minDist, rel = null, depth = null, accept = null, seed = 1, tries = 60000 }) {
  const b = water.bounds, level = water.level;
  return scatter({
    seed, count, minDist, maxTries: tries, region: { x0: b.x0, z0: b.z0, x1: b.x1, z1: b.z1 },
    accept: (x, z) => {
      const h = water.heightFn(x, z), d = level - h;
      if (water.mask && !water.mask(x, z)) return 0;
      if (depth) { if (d < depth[0] || d > depth[1]) return 0; } else if (h - level < rel[0] || h - level > rel[1]) return 0;
      return accept ? accept(x, z) : 1;
    },
  });
}

// ---------------------------------------------------------------------------------------------------------------- reeds
function reedGeometry(seed = 7) {
  const rng = mulberry32(seed), pos = [], col = [], uv = [], idx = [];
  const blades = 9, rows = 6;
  for (let b = 0; b < blades; b++) {
    const ang = rng() * Math.PI * 2, rad = 0.05 + rng() * 0.20, ox = Math.cos(ang) * rad, oz = Math.sin(ang) * rad;
    const h = 1.05 + rng() * 1.05, lean = (rng() - 0.5) * 0.7, yaw = rng() * Math.PI, cy = Math.cos(yaw), sy = Math.sin(yaw), w0 = 0.028 + rng() * 0.018;
    const base = pos.length / 3, tall = b < 2;
    for (let r = 0; r <= rows; r++) {
      const t = r / rows, y = t * h, bend = lean * t * t, w = w0 * (1 - Math.pow(t, 0.85) * 0.92);
      for (const side of [-1, 1]) {
        pos.push(ox + (bend + side * w) * cy, y, oz + (bend + side * w) * sy);
        const g = 0.5 + 0.5 * t; col.push(0.22 + 0.18 * g, 0.34 + 0.2 * g, 0.10 + 0.05 * g); uv.push(0, t);
      }
      if (r > 0) { const k = base + (r - 1) * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
    }
    if (tall) {                                                                 // cattail head on a stem: a brown capsule near the tip
      const hb = pos.length / 3, hy = h * 0.82, hx = ox + lean * 0.672 * cy, hz = oz + lean * 0.672 * sy, hh = 0.30, R = 0.045;
      for (let r = 0; r <= 3; r++) for (let a = 0; a < 7; a++) {
        const t = r / 3, rr = R * (1 - Math.pow(Math.abs(t - 0.5) * 2, 2) * 0.55), an = a / 7 * Math.PI * 2;
        pos.push(hx + Math.cos(an) * rr, hy + t * hh, hz + Math.sin(an) * rr); col.push(0.27, 0.15, 0.07); uv.push(1, 1.5);
      }
      for (let r = 0; r < 3; r++) for (let a = 0; a < 7; a++) { const a0 = hb + r * 7 + a, a1 = hb + r * 7 + (a + 1) % 7, b0 = a0 + 7, b1 = a1 + 7; idx.push(a0, b0, a1, a1, b0, b1); }
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
}

export class ReedField {
  /** @param points [{x, z, r1, r2, r3}] (from placeShore)  @param U grass uniforms (wind + season)  @param heightAt (x,z) => terrain height */
  constructor({ scene, points, heightAt, uniforms: U }) {
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.75, side: THREE.DoubleSide });
    mat.onBeforeCompile = shader => {
      Object.assign(shader.uniforms, U);
      shader.vertexShader = `
        uniform float uTime, uWind, uWindSpeed, uSeasonSat, uSeasonHeight, uSeasonKeep; uniform vec2 uWindDir; uniform vec3 uSeasonTint; varying vec3 vReedTint;
      ` + shader.vertexShader.replace('#include <begin_vertex>', `
        vec3 transformed = vec3(position);
        vec3 ip = instanceMatrix[3].xyz;
        float seed = fract(sin(dot(ip.xz, vec2(12.9898, 78.233))) * 43758.5453);
        float alive = step(seed, uSeasonKeep + 0.15);                                    // winter die-back: some bundles collapse
        float tt = clamp(position.y / 2.0, 0.0, 1.0);
        vec2 wd = normalize(uWindDir);
        float gust = 0.55 + 0.45 * sin(uTime * (0.9 + uWindSpeed * 0.5) + dot(ip.xz, wd) * 0.35 + seed * 6.0);
        float flutter = sin(uTime * 2.4 + seed * 31.0 + position.y * 2.0) * 0.25;
        transformed.xz += wd * (gust + flutter) * uWind * 0.55 * tt * tt;
        transformed.y *= uSeasonHeight * alive;
        vec3 rt = vec3(1.0);
        { vec3 gtc = uSeasonTint; rt = mix(vec3(dot(gtc, vec3(0.2126, 0.7152, 0.0722))), gtc, uSeasonSat); }
        vReedTint = mix(rt, vec3(1.0), uv.x);                                            // cattail heads (uv.x = 1) keep their brown
      `);
      shader.fragmentShader = 'varying vec3 vReedTint;\n' + shader.fragmentShader.replace('#include <color_fragment>', '#include <color_fragment>\n diffuseColor.rgb *= vReedTint;');
    };
    const key = mat.customProgramCacheKey(); mat.customProgramCacheKey = () => key + '|reeds';
    const geo = reedGeometry();
    const im = new THREE.InstancedMesh(geo, mat, points.length), m = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), p = new THREE.Vector3(), s = new THREE.Vector3();
    points.forEach((pt, i) => {
      e.set(0, pt.r1 * Math.PI * 2, 0); q.setFromEuler(e); const sc = 0.8 + pt.r2 * 0.6; s.set(sc, sc * (0.85 + pt.r3 * 0.35), sc);
      p.set(pt.x, heightAt(pt.x, pt.z) - 0.05, pt.z); m.compose(p, q, s); im.setMatrixAt(i, m);
    });
    im.castShadow = false; im.receiveShadow = true; im.frustumCulled = false; im.name = 'reeds';
    scene.add(im); this.mesh = im; this.count = points.length;
  }
}

// ---------------------------------------------------------------------------------------------------------------- lily pads + lotus
function padGeometry() {
  const seg = 22, pos = [0, 0.012, 0], col = [0.18, 0.42, 0.14], idx = [], notch = 0.13;
  for (let i = 0; i <= seg; i++) {
    const a = notch + (i / seg) * (Math.PI * 2 - notch * 2);
    pos.push(Math.cos(a), 0.012, Math.sin(a)); col.push(0.12, 0.34, 0.10);
    if (i > 0) idx.push(0, i, i + 1);
  }
  for (let i = 1; i <= seg + 1; i++) pos[i * 3 + 1] = 0.045;                           // slightly cupped: the rim lifts
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx); g.computeVertexNormals(); return g;
}
function lotusGeometry() {
  const petals = 9, pos = [], col = [], idx = [];
  for (let layer = 0; layer < 2; layer++) for (let p = 0; p < petals; p++) {
    const a = (p / petals + layer * 0.5 / petals) * Math.PI * 2, r0 = 0.03, h = 0.16 - layer * 0.03, spread = 0.16 - layer * 0.07, w = 0.05, base = pos.length / 3;
    const ca = Math.cos(a), sa = Math.sin(a), tx = -sa, tz = ca;
    pos.push(ca * r0 + tx * w, 0.02, sa * r0 + tz * w, ca * r0 - tx * w, 0.02, sa * r0 - tz * w, ca * (r0 + spread) , 0.02 + h, sa * (r0 + spread));
    const pk = layer ? [1.0, 0.78, 0.86] : [0.98, 0.9, 0.94];
    col.push(1, 0.95, 0.9, 1, 0.95, 0.9, pk[0], pk[1], pk[2]); idx.push(base, base + 1, base + 2);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3)); g.setIndex(idx); g.computeVertexNormals(); return g;
}

export class LilyPads {
  /** @param points [{x, z, r1, r2, r3}] in 0.35..1.6 m of water (placeShore) */
  constructor({ scene, water, points, flowerShare = 0.16 }) {
    this.water = water; this.pts = points.map(p => ({ ax: p.x, az: p.z, ph: p.r1 * 6.28, size: 0.26 + p.r2 * 0.3, yaw: p.r3 * 6.28, flower: p.r2 > 1 - flowerShare, tone: p.r1 }));
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, side: THREE.DoubleSide });
    this.pads = new THREE.InstancedMesh(padGeometry(), mat, points.length);
    const fm = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, side: THREE.DoubleSide });
    this.flowers = new THREE.InstancedMesh(lotusGeometry(), fm, this.pts.filter(p => p.flower).length || 1);
    for (const m of [this.pads, this.flowers]) { m.frustumCulled = false; m.receiveShadow = true; m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); scene.add(m); }
    this.pads.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(points.length * 3), 3); this.pads.name = 'lily_pads'; this.flowers.name = 'lotus';
    this._n = new THREE.Vector3(); this._q = new THREE.Quaternion(); this._m = new THREE.Matrix4(); this._p = new THREE.Vector3(); this._s = new THREE.Vector3(); this._c = new THREE.Color(); this._qy = new THREE.Quaternion(); this._up = new THREE.Vector3(0, 1, 0);
  }

  /** @param t seconds  @param season season state ({ water: { pads, lotus } }) */
  update(t, season) {
    const w = this.water, scale = season.water?.pads ?? 1, bloom = season.water?.lotus ?? 0;
    let fi = 0;
    for (let i = 0; i < this.pts.length; i++) {
      const p = this.pts[i], x = p.ax + Math.sin(t * 0.06 + p.ph) * 0.35, z = p.az + Math.cos(t * 0.047 + p.ph * 1.3) * 0.35;
      const y = w.heightAt(x, z) + 0.012; w.normalAt(x, z, this._n);
      this._q.setFromUnitVectors(this._up, this._n); this._qy.setFromAxisAngle(this._up, p.yaw + Math.sin(t * 0.05 + p.ph) * 0.2); this._q.multiply(this._qy);
      const sc = p.size * scale * (0.9 + 0.1 * Math.sin(p.ph)); this._p.set(x, y, z); this._s.set(sc, sc, sc);
      this._m.compose(this._p, this._q, this._s); this.pads.setMatrixAt(i, this._m);
      // colour: green in the growing seasons, yellow-brown as it dies back
      const die = Math.min(1, Math.max(0, 1.1 - scale)), g = 0.8 + 0.4 * (p.tone - 0.5);
      this.pads.setColorAt(i, this._c.setRGB(g * (0.9 + 0.8 * die), g * (1.0 - 0.28 * die), g * (0.85 - 0.45 * die)));
      if (p.flower) {
        const fs = 0.55 + bloom * 0.8; this._s.set(fs, fs * (bloom > 0.05 ? 1 : 0.001), fs); this._p.y = y + 0.03;
        this._m.compose(this._p, this._q, this._s); this.flowers.setMatrixAt(fi++, this._m);
      }
    }
    for (const m of [this.pads, this.flowers]) m.instanceMatrix.needsUpdate = true; this.pads.instanceColor.needsUpdate = true; this.flowers.count = fi || 0;
  }
}

// ---------------------------------------------------------------------------------------------------------------- floating petals / leaves
export class Flotsam {
  constructor({ scene, water, count = 160, seed = 3 }) {
    this.water = water; this.n = count; this.rng = mulberry32(seed);
    const g = new THREE.CircleGeometry(0.5, 7); g.rotateX(-Math.PI / 2);
    this.mesh = new THREE.InstancedMesh(g, new THREE.MeshStandardMaterial({ roughness: 0.6, side: THREE.DoubleSide }), count);
    this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3); this.mesh.frustumCulled = false; this.mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.mesh.name = 'flotsam'; scene.add(this.mesh);
    this.items = Array.from({ length: count }, () => ({ x: 0, z: 0, yaw: 0, size: 0, tone: this.rng(), alive: false }));
    this._q = new THREE.Quaternion(); this._qy = new THREE.Quaternion(); this._n = new THREE.Vector3(); this._m = new THREE.Matrix4(); this._p = new THREE.Vector3(); this._s = new THREE.Vector3(); this._c = new THREE.Color(); this._up = new THREE.Vector3(0, 1, 0);
  }
  _spawn(it) {
    const b = this.water.bounds;
    for (let k = 0; k < 40; k++) { const x = b.x0 + this.rng() * (b.x1 - b.x0), z = b.z0 + this.rng() * (b.z1 - b.z0); if (this.water.isWater(x, z, 0.25)) { it.x = x; it.z = z; it.alive = true; it.yaw = this.rng() * 6.28; it.size = 0.09 + this.rng() * 0.1; return; } }
  }
  /** @param amount 0..1 how many pieces are on the water  @param palette [[r,g,b],[r,g,b]] petal / leaf colours */
  update(dt, t, amount, palette) {
    const w = this.water, live = Math.round(this.n * amount);
    for (let i = 0; i < this.n; i++) {
      const it = this.items[i];
      if (i >= live) { this._s.setScalar(0.0001); this._p.set(0, -50, 0); this._m.compose(this._p, this._q.identity(), this._s); this.mesh.setMatrixAt(i, this._m); continue; }
      if (!it.alive) this._spawn(it);
      // pushed along by the wind, wobbling a little; a piece that reaches the shore is recycled upwind
      it.x += (w.wind.x * 0.16 + Math.sin(t * 0.7 + i) * 0.03) * dt; it.z += (w.wind.z * 0.16 + Math.cos(t * 0.6 + i * 1.7) * 0.03) * dt;
      if (!w.isWater(it.x, it.z, 0.1)) { it.alive = false; this._spawn(it); }
      const y = w.heightAt(it.x, it.z) + 0.006; w.normalAt(it.x, it.z, this._n);
      this._q.setFromUnitVectors(this._up, this._n); this._qy.setFromAxisAngle(this._up, it.yaw + t * 0.05 * (i % 2 ? 1 : -1)); this._q.multiply(this._qy);
      this._p.set(it.x, y, it.z); this._s.set(it.size, it.size, it.size * 1.4); this._m.compose(this._p, this._q, this._s); this.mesh.setMatrixAt(i, this._m);
      const a = palette[0], b = palette[1], k = it.tone; this.mesh.setColorAt(i, this._c.setRGB(a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k));
    }
    this.mesh.instanceMatrix.needsUpdate = true; this.mesh.instanceColor.needsUpdate = true;
  }
}

// ---------------------------------------------------------------------------------------------------------------- shore rocks
function rockGeometry(seed) {
  const g = new THREE.IcosahedronGeometry(1, 2), pos = g.attributes.position, col = [];
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i), n = 0.78 + 0.34 * (Math.sin(x * 3.1 + seed) * Math.cos(z * 2.7 + seed * 1.3) * 0.5 + 0.5) + 0.12 * Math.sin(y * 5.0 + x * 2.0 + seed);
    pos.setXYZ(i, x * n * 1.1, Math.max(y * n * 0.62, -0.25), z * n);
    const v = 0.34 + 0.18 * (Math.sin(x * 9 + z * 7 + seed) * 0.5 + 0.5) + 0.1 * (y > 0.3 ? 1 : 0); col.push(v, v * 0.96, v * 0.9);
  }
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3)); g.deleteAttribute('uv'); g.computeVertexNormals(); return g;
}
export class ShoreRocks {
  constructor({ scene, points, heightAt }) {
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92 }), geos = [rockGeometry(3), rockGeometry(11)];
    this.meshes = geos.map(g => { const m = new THREE.InstancedMesh(g, mat, points.length); m.castShadow = true; m.receiveShadow = true; m.frustumCulled = false; m.count = 0; m.name = 'shore_rocks'; scene.add(m); return m; });
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), p = new THREE.Vector3(), s = new THREE.Vector3(), cnt = [0, 0];
    for (const pt of points) {
      const k = pt.r3 > 0.5 ? 1 : 0, sc = 0.28 + pt.r2 * pt.r2 * 0.75;
      e.set((pt.r1 - 0.5) * 0.3, pt.r1 * 6.28, (pt.r3 - 0.5) * 0.3); q.setFromEuler(e); s.set(sc * (1 + pt.r1 * 0.4), sc, sc * (1 + pt.r3 * 0.3));
      p.set(pt.x, heightAt(pt.x, pt.z) + sc * 0.12, pt.z); m4.compose(p, q, s); this.meshes[k].setMatrixAt(cnt[k]++, m4);
    }
    this.meshes.forEach((m, i) => { m.count = cnt[i]; m.instanceMatrix.needsUpdate = true; });
  }
}
