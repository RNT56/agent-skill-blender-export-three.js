// Lake fauna, all procedural and instanced:
//   KoiSchool    fish that swim in the shallows in a loose school (body undulation in the vertex shader), steer around the shore, rise to the surface now and then
//   DuckFlock    ducks that float on the wave surface (CPU wave model), paddle with wake ripples, and flee from approaching units
//   Dragonflies  red darters (akatonbo) that hover and dash over the water and meadows, wings flapping in the vertex shader
// Every creature is hidden (scaled to nothing) when its position is outside the player's sight (ctx.visible) and fades with the season / daylight.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { mulberry32 } from './noise.js';

const TAU = Math.PI * 2;
const wrap = a => { while (a > Math.PI) a -= TAU; while (a < -Math.PI) a += TAU; return a; };
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);

/** a coloured, transformed copy of a geometry (position-only attributes + vertex colours) */
function part(geo, color, pos = [0, 0, 0], rot = [0, 0, 0], scale = [1, 1, 1], wing = 0) {
  const g = geo.index ? geo.toNonIndexed() : geo.clone();
  g.applyMatrix4(new THREE.Matrix4().compose(new THREE.Vector3(...pos), new THREE.Quaternion().setFromEuler(new THREE.Euler(...rot)), new THREE.Vector3(...scale)));
  const n = g.attributes.position.count, c = new THREE.Color(color), arr = new Float32Array(n * 3), uv = new Float32Array(n * 2);
  for (let i = 0; i < n; i++) { arr.set([c.r, c.g, c.b], i * 3); uv[i * 2] = wing; }
  g.setAttribute('color', new THREE.BufferAttribute(arr, 3)); g.setAttribute('uv', new THREE.BufferAttribute(uv, 2)); g.deleteAttribute('normal');
  g.computeVertexNormals();
  return g;
}
const merge = list => mergeGeometries(list, false);

function instanced(scene, geo, mat, count, name) {
  const m = new THREE.InstancedMesh(geo, mat, count); m.frustumCulled = false; m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); m.castShadow = false; m.name = name; scene.add(m); return m;
}

/** fade factor: 1 when the creature may be seen, easing to 0 when it may not */
function fadeTo(c, target, dt) { c.fade += (target - c.fade) * Math.min(1, dt * 5); return c.fade; }

// ---------------------------------------------------------------------------------------------------------------- koi
function koiGeometry(pattern, seed) {
  const rng = mulberry32(seed), tex = (x, z) => Math.sin(x * 38 + seed) * Math.cos(z * 17 + seed * 2) + 0.6 * Math.sin(z * 31 + x * 11);
  const body = new THREE.SphereGeometry(1, 12, 9).toNonIndexed(); body.scale(0.062, 0.058, 0.27);
  const pos = body.attributes.position, col = new Float32Array(pos.count * 3);
  const orange = new THREE.Color(1.0, 0.36, 0.08), white = new THREE.Color(0.97, 0.94, 0.9), black = new THREE.Color(0.08, 0.07, 0.07), gold = new THREE.Color(0.95, 0.68, 0.18);
  for (let i = 0; i < pos.count; i++) {
    const t = tex(pos.getX(i) * 3, pos.getZ(i) * 3), belly = pos.getY(i) < -0.02;
    let c = pattern === 'ogon' ? gold : pattern === 'kohaku' ? (t > 0.25 ? orange : white) : (t > 0.5 ? orange : t < -0.55 ? black : white);
    if (belly) c = c.clone().lerp(white, 0.6);
    col.set([c.r, c.g, c.b], i * 3);
  }
  body.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const u = new Float32Array(pos.count * 2); body.setAttribute('uv', new THREE.BufferAttribute(u, 2)); body.deleteAttribute('normal'); body.computeVertexNormals();
  const fin = (x, y, z, w, h, rz, ry = 0) => part(new THREE.PlaneGeometry(w, h), pattern === 'ogon' ? '#e8b84a' : '#f4e6d4', [x, y, z], [0, ry, rz]);
  void rng;
  return merge([body, fin(0, 0, -0.34, 0.17, 0.2, 0, Math.PI / 2), fin(0, 0.07, -0.02, 0.02, 0.11, 0, 0), fin(0.07, -0.03, 0.08, 0.1, 0.045, 0.4), fin(-0.07, -0.03, 0.08, 0.1, 0.045, -0.4)]);
}

export class KoiSchool {
  constructor({ scene, water, count = 9, seed = 5 }) {
    this.water = water; this.rng = mulberry32(seed); this.t = 0;
    this.patterns = ['kohaku', 'sanke', 'ogon'];
    this.U = { uTime: { value: 0 } };
    const mat = () => { const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.4, side: THREE.DoubleSide }); m.onBeforeCompile = sh => { Object.assign(sh.uniforms, this.U); sh.vertexShader = 'uniform float uTime;\n' + sh.vertexShader.replace('#include <begin_vertex>', `
        #include <begin_vertex>
        float ph = instanceMatrix[3].x * 3.1 + instanceMatrix[3].z * 2.3;
        float tailAmt = (1.0 - smoothstep(-0.34, 0.02, position.z));
        transformed.x += sin(uTime * 7.5 - position.z * 11.0 + ph) * (0.012 + 0.07 * tailAmt * tailAmt);`); }; const k = m.customProgramCacheKey(); m.customProgramCacheKey = () => k + '|koi'; return m; };
    this.meshes = this.patterns.map((p, i) => instanced(scene, koiGeometry(p, 3 + i * 7), mat(), count, 'koi_' + p));
    this.fish = Array.from({ length: count }, (_, i) => this._spawn(i));
    this.fish.forEach((f, i) => { f.mesh = i % 3; f.slot = Math.floor(i / 3); });
    this.meshes.forEach((m, i) => { m.count = 0; });
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._p = new THREE.Vector3(); this._s = new THREE.Vector3(); this._e = new THREE.Euler();
  }
  _spawn() {
    const b = this.water.bounds;
    for (let k = 0; k < 200; k++) { const x = b.x0 + this.rng() * (b.x1 - b.x0), z = b.z0 + this.rng() * (b.z1 - b.z0); if (this.water.depthAt(x, z) > 0.9) return { x, z, yaw: this.rng() * TAU, speed: 0.5, turn: 0, phase: this.rng() * 9, fade: 0, rise: 0, riseT: 8 + this.rng() * 20, size: 0.9 + this.rng() * 0.45 }; }
    const c = { x: (b.x0 + b.x1) / 2, z: (b.z0 + b.z1) / 2 }; return { ...c, yaw: 0, speed: 0.5, turn: 0, phase: 0, fade: 0, rise: 0, riseT: 10, size: 1 };
  }
  /** ctx: { visible(x,z), amount 0..1, daylight 0..1 } */
  update(dt, t, ctx) {
    const w = this.water; this.U.uTime.value = t;
    let cx = 0, cz = 0; for (const f of this.fish) { cx += f.x; cz += f.z; } cx /= this.fish.length; cz /= this.fish.length;
    const live = Math.round(this.fish.length * (ctx.amount ?? 1)), counts = [0, 0, 0];
    this.fish.forEach((f, i) => {
      // steering: wander, drift toward the school, keep to water that is deep enough, avoid the very deepest centre (fish like the margins)
      f.turn += (this.rng() - 0.5) * 2.2 * dt; f.turn = clamp(f.turn, -0.9, 0.9);
      let want = f.yaw + f.turn * dt * 2.0;
      const toC = Math.atan2(cz - f.z, cx - f.x), dc = Math.hypot(cx - f.x, cz - f.z); if (dc > 3) want += wrap(toC - f.yaw) * 0.6 * dt;
      const ahead = (a, r) => w.depthAt(f.x + Math.cos(f.yaw + a) * r, f.z + Math.sin(f.yaw + a) * r);
      if (ahead(0, 1.8) < 0.7) { const l = ahead(0.9, 1.8), r = ahead(-0.9, 1.8); want += (l > r ? 1 : -1) * 3.2 * dt; f.turn *= 0.8; }
      f.yaw += wrap(want - f.yaw) * Math.min(1, dt * 4);
      f.speed += ((0.45 + 0.35 * (0.5 + 0.5 * Math.sin(t * 0.3 + f.phase))) - f.speed) * dt;
      const nx = f.x + Math.cos(f.yaw) * f.speed * dt, nz = f.z + Math.sin(f.yaw) * f.speed * dt;
      if (w.depthAt(nx, nz) > 0.55) { f.x = nx; f.z = nz; } else f.yaw += 2.0 * dt;
      // now and then a fish rises and rings the surface
      f.riseT -= dt; if (f.riseT <= 0) { f.rise = 1; f.riseT = 14 + this.rng() * 30; w.addRipple(f.x, f.z, 0.55); }
      f.rise = Math.max(0, f.rise - dt * 0.7);
      const d = w.depthAt(f.x, f.z), depthY = clamp(d * 0.4, 0.28, 0.95), y = w.level - depthY * (1 - f.rise) - 0.03 * f.rise + Math.sin(t * 1.3 + f.phase) * 0.02;
      const vis = i < live && ctx.visible(f.x, f.z) ? 1 : 0, s = fadeTo(f, vis, dt) * f.size;
      this._e.set(Math.sin(t * 3 + f.phase) * 0.04, -f.yaw + Math.PI / 2, 0); this._q.setFromEuler(this._e);
      this._p.set(f.x, y, f.z); this._s.setScalar(Math.max(s, 0.0001));
      this._m.compose(this._p, this._q, this._s);
      this.meshes[f.mesh].setMatrixAt(f.slot, this._m); counts[f.mesh] = Math.max(counts[f.mesh], f.slot + 1);
    });
    this.meshes.forEach((m, i) => { m.count = counts[i]; m.instanceMatrix.needsUpdate = true; });
  }
}

// ---------------------------------------------------------------------------------------------------------------- ducks
function duckGeometry(drake) {
  const sph = (r, w = 10, h = 8) => new THREE.SphereGeometry(r, w, h), body = drake ? '#7a5a44' : '#8a6a4c', head = drake ? '#1d6b4a' : '#8a6a4c', breast = drake ? '#5d4636' : '#9a7a58';
  return merge([
    part(sph(1, 12, 9), body, [0, 0.085, -0.02], [0, 0, 0], [0.105, 0.095, 0.2]), part(sph(1, 10, 8), breast, [0, 0.1, 0.1], [0, 0, 0], [0.095, 0.095, 0.11]),
    part(new THREE.CylinderGeometry(0.03, 0.04, 0.13, 8), head, [0, 0.19, 0.17], [0.25, 0, 0]), part(sph(0.052), head, [0, 0.265, 0.21]),
    part(new THREE.BoxGeometry(0.045, 0.018, 0.07), '#e6a21c', [0, 0.255, 0.27]), part(new THREE.ConeGeometry(0.05, 0.12, 6), drake ? '#2b2a2c' : '#6a5238', [0, 0.11, -0.2], [-Math.PI / 2 - 0.3, 0, 0]),
    part(new THREE.SphereGeometry(0.1, 8, 6), '#f2efe6', [0, 0.19, 0.19], [0, 0, 0], [0.5, 0.22, 0.5]),                  // white neck ring / cheek
  ]);
}
export class DuckFlock {
  constructor({ scene, water, count = 6, seed = 9 }) {
    this.water = water; this.rng = mulberry32(seed);
    const mat = () => new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6 });
    this.drakes = instanced(scene, duckGeometry(true), mat(), Math.ceil(count / 2), 'drakes'); this.hens = instanced(scene, duckGeometry(false), mat(), Math.floor(count / 2), 'hens');
    for (const m of [this.drakes, this.hens]) m.castShadow = true;
    this.ducks = Array.from({ length: count }, (_, i) => { const d = this._spawn(); d.mesh = i % 2 ? this.hens : this.drakes; d.slot = i >> 1; return d; });
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._qy = new THREE.Quaternion(); this._n = new THREE.Vector3(); this._p = new THREE.Vector3(); this._s = new THREE.Vector3(); this._up = new THREE.Vector3(0, 1, 0);
  }
  _spawn() {
    const b = this.water.bounds;
    for (let k = 0; k < 300; k++) { const x = b.x0 + this.rng() * (b.x1 - b.x0), z = b.z0 + this.rng() * (b.z1 - b.z0); if (this.water.depthAt(x, z) > 0.8) return { x, z, yaw: this.rng() * TAU, speed: 0, goalT: 0, gx: x, gz: z, fade: 0, wake: 0, scared: 0 }; }
    return { x: 0, z: 0, yaw: 0, speed: 0, goalT: 0, gx: 0, gz: 0, fade: 0, wake: 0, scared: 0 };
  }
  /** ctx: { visible(x,z), threats: [{x,z}], amount 0..1, daylight 0..1 } */
  update(dt, t, ctx) {
    const w = this.water, live = Math.round(this.ducks.length * (ctx.amount ?? 1));
    this.ducks.forEach((d, i) => {
      // threats: units that come close frighten them; they swim directly away at twice the speed
      let fx = 0, fz = 0, near = 0; for (const th of ctx.threats ?? []) { const dx = d.x - th.x, dz = d.z - th.z, r = Math.hypot(dx, dz); if (r < 9) { fx += dx / (r + 0.1) * (9 - r); fz += dz / (r + 0.1) * (9 - r); near++; } }
      d.scared = near ? 1 : Math.max(0, d.scared - dt * 0.5);
      d.goalT -= dt;
      if (near) { d.gx = d.x + fx; d.gz = d.z + fz; d.goalT = 1; }
      else if (d.goalT <= 0 || Math.hypot(d.gx - d.x, d.gz - d.z) < 1) {                       // a new place to dabble
        const b = w.bounds; for (let k = 0; k < 40; k++) { const x = b.x0 + this.rng() * (b.x1 - b.x0), z = b.z0 + this.rng() * (b.z1 - b.z0); if (w.depthAt(x, z) > 0.7) { d.gx = x; d.gz = z; break; } }
        d.goalT = 5 + this.rng() * 12; d.pause = this.rng() < 0.35 ? 2 + this.rng() * 5 : 0;
      }
      if (d.pause > 0) d.pause -= dt;
      const want = Math.atan2(d.gz - d.z, d.gx - d.x), target = (d.pause > 0 && !near) ? 0 : (near ? 1.4 : 0.38);
      d.yaw += wrap(want - d.yaw) * Math.min(1, dt * (near ? 5 : 1.6)); d.speed += (target - d.speed) * Math.min(1, dt * 2);
      const nx = d.x + Math.cos(d.yaw) * d.speed * dt, nz = d.z + Math.sin(d.yaw) * d.speed * dt;
      if (w.depthAt(nx, nz) > 0.4) { d.x = nx; d.z = nz; } else { d.yaw += 2.5 * dt; d.gx = d.x - (nx - d.x) * 20; d.gz = d.z - (nz - d.z) * 20; }
      d.wake += d.speed * dt; if (d.wake > 0.9) { d.wake = 0; w.addRipple(d.x, d.z, 0.16 + 0.1 * d.speed); }
      // float on the exact wave surface, level with the normal
      const y = w.heightAt(d.x, d.z) - 0.025; w.normalAt(d.x, d.z, this._n);
      this._q.setFromUnitVectors(this._up, this._n); this._qy.setFromAxisAngle(this._up, -d.yaw + Math.PI / 2); this._q.multiply(this._qy);
      const vis = i < live && ctx.visible(d.x, d.z) ? 1 : 0, s = fadeTo(d, vis, dt);
      this._p.set(d.x, y, d.z); this._s.setScalar(Math.max(s, 0.0001) * 1.15);
      this._m.compose(this._p, this._q, this._s); d.mesh.setMatrixAt(d.slot, this._m);
    });
    this.drakes.instanceMatrix.needsUpdate = true; this.hens.instanceMatrix.needsUpdate = true;
  }
}

// ---------------------------------------------------------------------------------------------------------------- dragonflies
export class Dragonflies {
  constructor({ scene, water, heightAt, count = 16, seed = 13, scale = 2.6 }) {
    this.water = water; this.heightAt = heightAt; this.rng = mulberry32(seed); this.scale = scale; this.U = { uTime: { value: 0 } };
    const body = merge([part(new THREE.CylinderGeometry(0.011, 0.007, 0.15, 6), '#c7321c', [0, 0, 0], [Math.PI / 2, 0, 0]), part(new THREE.SphereGeometry(0.018, 7, 6), '#a82a18', [0, 0, 0.085]), part(new THREE.SphereGeometry(0.015, 7, 6), '#b82e1b', [0, 0, 0.045])]);
    const wing = (x, z, rz, len = 0.1) => part(new THREE.PlaneGeometry(len, 0.03), '#dfe9f0', [x, 0.004, z], [-Math.PI / 2, 0, rz], [1, 1, 1], 1);
    const wings = merge([wing(0.06, 0.035, 0.05), wing(-0.06, 0.035, -0.05), wing(0.06, 0.02, -0.05), wing(-0.06, 0.02, 0.05)]);
    const wm = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.3, transparent: true, opacity: 0.5, side: THREE.DoubleSide, depthWrite: false });
    wm.onBeforeCompile = sh => { Object.assign(sh.uniforms, this.U); sh.vertexShader = 'uniform float uTime;\n' + sh.vertexShader.replace('#include <begin_vertex>', `
      #include <begin_vertex>
      float fp = instanceMatrix[3].x * 5.0 + instanceMatrix[3].z * 3.0;
      transformed.y += sin(uTime * 62.0 + fp) * abs(position.x) * 0.9;`); };
    const k = wm.customProgramCacheKey(); wm.customProgramCacheKey = () => k + '|dragonfly_wings';
    this.body = instanced(scene, body, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.45 }), count, 'dragonfly_bodies');
    this.wings = instanced(scene, wings, wm, count, 'dragonfly_wings');
    this.flies = Array.from({ length: count }, () => this._spawn());
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._e = new THREE.Euler(); this._p = new THREE.Vector3(); this._s = new THREE.Vector3();
  }
  _spawn() {
    const b = this.water.bounds, x = b.x0 + this.rng() * (b.x1 - b.x0), z = b.z0 + this.rng() * (b.z1 - b.z0);
    return { x, z, y: 1.2, yaw: this.rng() * TAU, tx: x, tz: z, ty: 1.2, speed: 0, hover: this.rng() * 2, fade: 0 };
  }
  update(dt, t, ctx) {
    this.U.uTime.value = t; const w = this.water, b = w.bounds, live = Math.round(this.flies.length * (ctx.amount ?? 1)) * (ctx.daylight > 0.25 ? 1 : 0);
    this.flies.forEach((f, i) => {
      f.hover -= dt;
      if (f.hover <= 0) {                                                        // dash to a new perch / hover spot near the water
        f.tx = clamp(f.x + (this.rng() - 0.5) * 16, b.x0 - 10, b.x1 + 10); f.tz = clamp(f.z + (this.rng() - 0.5) * 16, b.z0 - 10, b.z1 + 10);
        const ground = Math.max(this.heightAt(f.tx, f.tz), w.level); f.ty = ground + 0.6 + this.rng() * 1.4; f.hover = 0.6 + this.rng() * 2.6;
      }
      const dx = f.tx - f.x, dz = f.tz - f.z, d = Math.hypot(dx, dz);
      const want = d > 0.4 ? Math.min(3.6, d * 3.0) : 0; f.speed += (want - f.speed) * Math.min(1, dt * 6);
      if (d > 0.05) { f.yaw += wrap(Math.atan2(dz, dx) - f.yaw) * Math.min(1, dt * 10); f.x += Math.cos(f.yaw) * f.speed * dt; f.z += Math.sin(f.yaw) * f.speed * dt; }
      f.y += (f.ty - f.y) * Math.min(1, dt * 3) + Math.sin(t * 9 + i) * 0.004;
      const vis = i < live && ctx.visible(f.x, f.z) ? 1 : 0, s = fadeTo(f, vis, dt) * this.scale;
      this._e.set(0, -f.yaw + Math.PI / 2, 0); this._q.setFromEuler(this._e); this._p.set(f.x, f.y, f.z); this._s.setScalar(Math.max(s, 0.0001));
      this._m.compose(this._p, this._q, this._s); this.body.setMatrixAt(i, this._m); this.wings.setMatrixAt(i, this._m);
    });
    this.body.instanceMatrix.needsUpdate = true; this.wings.instanceMatrix.needsUpdate = true;
  }
}
