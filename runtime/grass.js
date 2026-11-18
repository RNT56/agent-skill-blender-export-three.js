// GPU-instanced grass with wind, in two flavours that share one shader:
//   * blades  GLB blade meshes from the `grass` recipe (specs/grass_blades.json): nodes named <asset>_<Variant>_LOD<n>; uv.y = height along the blade.
//   * clumps  procedural tall-field clumps (grass_clump.js): arching blades with seed heads, three levels of detail. Pass `clumps: true`.
// Chunks around the view focus are built on demand in three distance tiers, one draw call per (chunk, variant). Everything that moves runs in the vertex shader:
//   - wind: slow gust cells (noise texture), rolling bands that travel downwind across the field, per-blade flutter, seed heads that lag and bob
//   - trampling: a persistent lean field (grass_trample.js) remembers where units walked: grass is parted sideways and pressed along the heading, then springs back
//   - seasons: colour multiplier + saturation, height, die-back, frost, ripeness of the seed heads (golden rice in autumn)
import * as THREE from 'three';
import { mulberry32 } from './noise.js';
import { createNoiseTexture } from './noisetex.js';
import { createClumpLods } from './grass_clump.js';
import { TrampleMap } from './grass_trample.js';

const DEFAULT_TIERS = [
  { r: 26, density: 34, lod: 0, wScale: 1.0, hScale: 1.0 },
  { r: 62, density: 12, lod: 1, wScale: 1.3, hScale: 1.0 },
  { r: 108, density: 3.2, lod: 1, wScale: 2.4, hScale: 1.1 },
];
/** clump tiers: density is clumps per square metre (one clump = a bouquet of 3..8 blades) */
export const CLUMP_TIERS = [
  { r: 15, density: 7.0, lod: 0, wScale: 1.0, hScale: 1.0 },
  { r: 40, density: 3.8, lod: 1, wScale: 1.3, hScale: 1.0 },
  { r: 100, density: 1.0, lod: 2, wScale: 1.8, hScale: 1.0 },
];

/** detail levels (the quantised zoom scale) and the cross-fade durations of a chunk growing in / out, in seconds */
const LEVELS = [0.8, 1, 1.4, 2, 3];
const levelOf = x => (x < 0.9 ? 0 : x < 1.2 ? 1 : x < 1.7 ? 2 : x < 2.5 ? 3 : 4);
const FADE_IN = 0.9, FADE_OUT = 0.9, LEAD_SECONDS = 0.8;

export class GrassField {
  /**
   * @param bladeScene  gltf.scene from grass_blades.glb (ignored with clumps: true)
   * @param heightAt    (x,z) => y
   * @param styleAt     (x,z,out) => void   set out.density (0..1), out.r/g/b (tip colour, display values) and optionally out.height (multiplier)
   * @param uniforms    shared wind/light uniforms (see createGrassUniforms)
   * @param clumps      true: procedural tall-field clumps instead of GLB blades
   */
  constructor({ scene, bladeScene = null, heightAt, styleAt, uniforms, clumps = false, tiers = clumps ? CLUMP_TIERS : DEFAULT_TIERS, chunk = clumps ? 14 : 12, maxBuildsPerFrame = 40, heightRange = clumps ? [1.05, 1.7] : [0.35, 0.85] }) {
    this.scene = scene; this.heightAt = heightAt; this.styleAt = styleAt; this.U = uniforms; this.clump = clumps;
    this.tiers = tiers; this.chunk = chunk; this.maxBuilds = maxBuildsPerFrame; this.hr = heightRange;
    this.maxR = tiers[tiers.length - 1].r;
    this.qi = 1; this.scale = 1;                      // detail level (zoom): tier radii x scale, density / scale^2; one of LEVELS
    this.U.uFar.value = this.maxR;
    // streaming: chunks live in `chunks` (this level's grid) and are replaced / retired with a cross-fade (see update()); nothing ever pops
    this.chunks = new Map(); this.legacy = []; this.later = []; this.dying = [];
    this.budgetMs = 2.2; this._tUpd = null; this._frame = 0; this._now = 0; this._lastBirth = -1e9; this.pending = 0;
    this._lastC = new THREE.Vector3(); this._haveC = false; this._vel = new THREE.Vector2(); this._lead = new THREE.Vector2(); this._born = null;
    this.group = new THREE.Group(); this.group.name = 'grass'; scene.add(this.group);
    this.frustum = new THREE.Frustum(); this._pv = new THREE.Matrix4(); this._sph = new THREE.Sphere();
    if (clumps) this.variants = [createClumpLods()];                // variants[v][lod]
    else {
      const found = {};
      bladeScene.traverse(o => {
        const m = /_([A-Za-z0-9]+)_LOD(\d+)$/.exec(o.name);
        if (o.isMesh && m) (found[m[1]] ??= {})[+m[2]] = o.geometry;
      });
      this.variants = Object.keys(found).sort().map(k => found[k]);
      if (!this.variants.length) throw new Error('GrassField: no blade meshes named *_<Variant>_LOD<n> found');
    }
    this.trample = new TrampleMap(); this._lt = null; this._pushers = [];
    this._trTex = new THREE.DataTexture(this.trample.data, this.trample.N, this.trample.N, THREE.RGFormat, THREE.UnsignedByteType);
    this._trTex.minFilter = this._trTex.magFilter = THREE.LinearFilter; this._trTex.wrapS = this._trTex.wrapT = THREE.ClampToEdgeWrapping; this._trTex.generateMipmaps = false; this._trTex.unpackAlignment = 1; this._trTex.needsUpdate = true;
    this.U.tTrample.value = this._trTex; this.U.uTrExtent.value = this.trample.extent; this._trVer = -1;
    this.material = makeGrassMaterial(uniforms, clumps);
    this.stats = { chunks: 0, instances: 0, visible: 0, pending: 0, dying: 0 };
  }

  /** the chunk edge in metres: grows with the detail scale in clump mode so the draw-call count stays bounded when zoomed out */
  get C() { return this.clump ? this.chunk * Math.sqrt(this.scale) : this.chunk; }

  /** trampling: [{id?, x, z, r?, s?}] everything that currently walks through the grass (any number); strength s 0..1, footprint radius r metres. Applied in update(). */
  setPushers(list) { this._pushers = list; }

  _build(cx, cz, tier, born) {
    const t = this.tiers[tier], C = this.C;
    const x0 = cx * C, z0 = cz * C;
    const nv = this.variants.length;
    const target = Math.ceil(C * C * t.density / (this.scale * this.scale));
    const rng = mulberry32((cx * 73856093) ^ (cz * 19349663) ^ 0x9e3779b9);
    const buf = this.variants.map(() => []);
    const style = { density: 1, r: 0.3, g: 0.5, b: 0.1, height: 1 };
    let minY = 1e9, maxY = -1e9, count = 0;
    for (let k = 0; k < target; k++) {
      const x = x0 + rng() * C, z = z0 + rng() * C;
      const rv = rng(), ryaw = rng() * Math.PI * 2, rh = rng(), rw = rng(), rt = rng(), rvar = rng();
      style.height = 1; this.styleAt(x, z, style);
      if (rv > style.density) continue;
      const y = this.heightAt(x, z);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y + this.hr[1] * 1.5);
      const h = (this.hr[0] + (this.hr[1] - this.hr[0]) * rh) * t.hScale * (0.75 + 0.5 * style.density) * style.height;
      const w = (0.8 + 0.5 * rw) * t.wScale * Math.sqrt(this.scale);
      const v = Math.min(nv - 1, Math.floor(rvar * nv));
      const tint = 0.85 + 0.3 * rt;
      buf[v].push(x, y - 0.02, z, ryaw, h, w, rt, 0, style.r * tint, style.g * tint, style.b * tint);
      count++;
    }
    const e = { meshes: [], life: [], tier, qi: this.qi, count, box: null, born, dieAt: 1e12, seen: -1, since: null };
    if (!count) return e;
    for (let v = 0; v < nv; v++) {
      const a = buf[v];
      if (!a.length) continue;
      const n = a.length / 11;
      const src = this.variants[v][Math.min(t.lod, this.variants[v].length - 1)] ?? this.variants[v][0];
      const g = new THREE.InstancedBufferGeometry();
      g.index = new THREE.BufferAttribute(src.index.array, 1);                  // a chunk's own index: dispose() must not delete a buffer shared by every chunk
      for (const name of ['position', 'normal', 'uv', 'aBlade', 'aHead']) { const at = src.getAttribute(name); if (at) g.setAttribute(name, new THREE.BufferAttribute(at.array, at.itemSize)); }
      const off = new Float32Array(n * 3), par = new Float32Array(n * 4), tin = new Float32Array(n * 3), life = new Float32Array(n * 2);
      for (let i = 0; i < n; i++) {
        const o = i * 11;
        off.set([a[o], a[o + 1], a[o + 2]], i * 3);
        par.set([a[o + 3], a[o + 4], a[o + 5], a[o + 6]], i * 4);
        tin.set([a[o + 8], a[o + 9], a[o + 10]], i * 3);
        life[i * 2] = born; life[i * 2 + 1] = 1e12;                             // (born, dies): the shader grows the blade in after `born` and out after `dies`
      }
      const lifeAttr = new THREE.InstancedBufferAttribute(life, 2);
      g.setAttribute('iOffset', new THREE.InstancedBufferAttribute(off, 3));
      g.setAttribute('iParams', new THREE.InstancedBufferAttribute(par, 4));
      g.setAttribute('iTint', new THREE.InstancedBufferAttribute(tin, 3));
      g.setAttribute('iLife', lifeAttr);
      g.instanceCount = n;
      const m = new THREE.Mesh(g, this.material);
      m.frustumCulled = false; m.receiveShadow = true; m.castShadow = false;
      this.group.add(m);
      e.meshes.push(m); e.life.push(lifeAttr);
    }
    e.box = new THREE.Sphere(new THREE.Vector3(x0 + C / 2, (minY + maxY) / 2, z0 + C / 2), Math.hypot(C / 2, (maxY - minY) / 2) + 2.5);
    return e;
  }

  _drop(e) {
    for (const m of e.meshes) { this.group.remove(m); m.geometry.dispose(); }
    e.meshes.length = 0;
  }

  /** start the fade-out of a chunk; it is removed when the fade has finished */
  _retire(e, now) {
    if (e.dieAt < 1e11) return;
    e.dieAt = now;
    for (const a of e.life) { const arr = a.array; for (let i = 1; i < arr.length; i += 2) arr[i] = now; a.needsUpdate = true; }
    this.dying.push(e);
  }

  /** advance the trample field and upload it when it changed */
  _trample(time, cp) {
    const T = this.trample, dt = this._lt == null ? 0 : time - this._lt; this._lt = time;
    T.setCenter(cp.x, cp.z); T.step(dt, this._pushers);
    this.U.uTrOrigin.value.set(T.originX, T.originZ);
    if (T.version !== this._trVer) { this._trVer = T.version; this._trTex.needsUpdate = true; }
  }

  /**
   * Stream chunks around the view focus. Nothing pops:
   *  - new chunks GROW in (blade height from 0, in the vertex shader) and the chunk they replace fades out underneath them
   *  - a change of zoom level does not flush the field: the old level keeps drawing until the new one is complete, then fades
   *  - chunks are built ahead of the camera (the focus' velocity is extrapolated 0.8 s), nearest first, within a per-frame time budget
   *  - a chunk is only removed or coarsened after it has been unwanted for a while, so panning back and forth does not thrash
   * @param center  world point the detail is centred on (default: the camera). RTS/top-down cameras pass their ground focus.
   * @param scale   detail scale (>=1 as you zoom out): tier radii x scale, density / scale^2. Quantised to LEVELS to avoid rebuild churn.
   * @param fade    0..1 global fade (blades sink into the ground as it falls; the whole field is hidden below 0.02)
   * @param opts    { instant: true } builds everything wanted right now, already grown (used while a loading screen is up)
   */
  update(camera, time, player, center = null, scale = 1, fade = 1, opts = null) {
    const U = this.U, instant = !!opts?.instant;
    U.uTime.value = time; this._frame++;
    // streaming runs on the wall clock, not the game clock: fades and retirements must finish in real time even when the frame rate (and with it the clamped game time) drops
    const clock = performance.now() / 1000; U.uStreamT.value = clock; this._now = clock;
    if (player) U.uPlayer.value.copy(player);
    const cp = center ?? camera.position;
    this._trample(time, cp);
    const qi = levelOf(scale);
    if (qi !== this.qi) {                                                          // the whole grid changes: keep drawing the old level until the new one has grown in
      for (const e of this.chunks.values()) this.legacy.push(e);
      this.chunks = new Map(); this.qi = qi; this.scale = LEVELS[qi];
      if (this.legacy.length > 450) for (const e of this.legacy.splice(0, this.legacy.length - 450)) this._drop(e);
    }
    U.uCenter.value.copy(cp); U.uFar.value = this.maxR * this.scale; U.uFade.value = fade;
    this.group.visible = fade > 0.02;
    if (fade <= 0.02) {                                                            // hidden (zoomed far out): nothing is drawn, so nothing lingers either
      for (const e of this.legacy) this._drop(e); for (const l of this.later) this._drop(l.e); for (const e of this.dying) this._drop(e);
      this.legacy.length = 0; this.later.length = 0; this.dying.length = 0; this.pending = 0;
      this.stats.chunks = this.chunks.size; this.stats.visible = 0; this.stats.pending = 0; this.stats.dying = 0; return;
    }

    // the focus' velocity (smoothed), so chunks are wanted where the camera is GOING as well as where it is
    if (this._haveC) { const dt = Math.max(1e-3, Math.min(0.2, clock - (this._tLast ?? clock))); this._vel.x += ((cp.x - this._lastC.x) / dt - this._vel.x) * 0.15; this._vel.y += ((cp.z - this._lastC.z) / dt - this._vel.y) * 0.15; }
    this._lastC.copy(cp); this._tLast = clock; this._haveC = true;
    const vl = Math.hypot(this._vel.x, this._vel.y), k = vl > 3 ? Math.min(40, vl * LEAD_SECONDS) / vl : 0;
    const lx = cp.x + this._vel.x * k, lz = cp.z + this._vel.y * k;

    const C = this.C, reach = this.maxR * this.scale, rr = Math.ceil(reach / C) + 1, frame = this._frame;
    const ci0 = Math.floor(Math.min(cp.x, lx) / C) - rr, ci1 = Math.floor(Math.max(cp.x, lx) / C) + rr, cj0 = Math.floor(Math.min(cp.z, lz) / C) - rr, cj1 = Math.floor(Math.max(cp.z, lz) / C) + rr;
    const want = [], T = this.tiers, base = this.qi * 4194304;
    for (let j = cj0; j <= cj1; j++) {
      for (let i = ci0; i <= ci1; i++) {
        const mx = (i + 0.5) * C, mz = (j + 0.5) * C;
        const dc = Math.hypot(mx - cp.x, mz - cp.z), dl = Math.hypot(mx - lx, mz - lz), d = Math.min(dc, dl) - C * 0.7;
        let tier = -1;
        for (let t = 0; t < T.length; t++) if (d < T[t].r * this.scale) { tier = t; break; }
        if (tier < 0) continue;
        const key = base + (i + 1024) * 2048 + j + 1024, e = this.chunks.get(key);
        if (!e) { want.push({ i, j, tier, key, d }); continue; }
        e.seen = frame;
        if (tier < e.tier) want.push({ i, j, tier, key, d });                      // finer detail is needed now
        else if (tier > e.tier) { if (e.since == null) e.since = clock; else if (clock - e.since > 1.5) want.push({ i, j, tier, key, d }); }   // coarser only after it has been wanted for a while
        else e.since = null;
      }
    }
    for (const [key, e] of this.chunks) {                                          // out of range: fade out after a grace period
      if (e.seen === frame) continue;
      if (e.since == null) e.since = clock;
      if (instant || clock - e.since > 1.5) { this._retire(e, instant ? clock - FADE_OUT : clock); this.chunks.delete(key); }
    }

    // build, nearest first, within a time budget (always at least one per frame). A slow frame is GPU-bound and leaves the CPU idle, so the budget grows with the
    // frame time (a quarter of it, up to 8 ms): the queue then drains in about the same wall time at 15 fps as at 60
    const frameMs = this._tUpd == null ? 16 : Math.min(250, (clock - this._tUpd) * 1000); this._tUpd = clock;
    const budget = Math.min(8, Math.max(this.budgetMs, frameMs * 0.25));
    want.sort((a, b) => a.d - b.d);
    const t0 = performance.now(), born = instant ? clock - FADE_IN * 2 : clock;
    let built = 0;
    for (const w of want) {
      if (!instant && built > 0 && (built >= this.maxBuilds || performance.now() - t0 > budget)) break;
      const old = this.chunks.get(w.key), e = this._build(w.i, w.j, w.tier, born); e.seen = frame;
      if (old) { if (instant) this._drop(old); else this.later.push({ e: old, at: clock + FADE_IN * 0.5 }); }     // the replaced chunk fades out under the growing one
      this.chunks.set(w.key, e); built++; this._lastBirth = clock;
    }
    this.pending = want.length - built;

    // retirements
    if (this.legacy.length && this.pending === 0 && (instant || clock - this._lastBirth > FADE_IN * 0.6)) { for (const e of this.legacy) instant ? this._drop(e) : this._retire(e, clock); this.legacy.length = 0; }
    for (let i = this.later.length - 1; i >= 0; i--) { const l = this.later[i]; if (clock >= l.at) { this._retire(l.e, clock); this.later.splice(i, 1); } }
    for (let i = this.dying.length - 1; i >= 0; i--) { const e = this.dying[i]; if (clock > e.dieAt + FADE_OUT + 0.15) { this._drop(e); this.dying.splice(i, 1); } }

    // frustum cull per chunk (everything that may still be drawn)
    this._pv.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    this.frustum.setFromProjectionMatrix(this._pv);
    let inst = 0, vis = 0;
    const cull = e => {
      const v = e.box ? this.frustum.intersectsSphere(e.box) : false;
      for (const m of e.meshes) m.visible = v;
      inst += e.count; if (v) vis += e.count;
    };
    for (const e of this.chunks.values()) cull(e);
    for (const e of this.legacy) cull(e);
    for (const l of this.later) cull(l.e);
    for (const e of this.dying) cull(e);
    this.stats.chunks = this.chunks.size; this.stats.instances = inst; this.stats.visible = vis; this.stats.pending = this.pending; this.stats.dying = this.legacy.length + this.later.length + this.dying.length;
  }

  /** build everything the current view needs, already grown in (call repeatedly with a loading screen up); true when nothing is pending */
  prime(camera, time, center, scale, fade = 1) {
    this.update(camera, time, null, center, scale, fade, { instant: true });
    return this.pending === 0;
  }
}

/** a 1x1 'nothing is trampled' texture (byte 128 = zero lean), used until a GrassField installs its own */
function neutralTrample() {
  const t = new THREE.DataTexture(new Uint8Array([128, 128]), 1, 1, THREE.RGFormat, THREE.UnsignedByteType); t.unpackAlignment = 1; t.needsUpdate = true; return t;
}

export function createGrassUniforms(look, noise = createNoiseTexture(256, 17)) {
  const c = a => new THREE.Color(a[0], a[1], a[2]);
  return {
    uTime: { value: 0 }, uStreamT: { value: 0 }, uWindDir: { value: new THREE.Vector2(1.0, 0.35) }, uWind: { value: 0.55 }, uWindSpeed: { value: 1.1 },
    uPlayer: { value: new THREE.Vector3(1e5, 0, 1e5) }, uFar: { value: 100 }, uCenter: { value: new THREE.Vector3() }, uFade: { value: 1 },
    uLightDirView: { value: new THREE.Vector3(0, 1, 0) }, uSunColor: { value: c(look.sun.color) },
    uTrans: { value: (look.foliage?.translucency ?? 0.9) * 0.8 }, uPow: { value: look.foliage?.translucency_power ?? 3.0 },
    // seasons (env_seasons.js): blade colour multiplier + saturation, blade height multiplier, fraction of blades kept, frost on the tips, ripeness of the seed heads
    uSeasonTint: { value: new THREE.Vector3(1, 1, 1) }, uSeasonSat: { value: 1 }, uSeasonHeight: { value: 1 }, uSeasonKeep: { value: 1 }, uFrost: { value: 0 }, uRipe: { value: 1 },
    // trampling (GrassField owns the TrampleMap and swaps in its texture) and the wind noise
    tTrample: { value: neutralTrample() }, uTrOrigin: { value: new THREE.Vector2(1e6, 1e6) }, uTrExtent: { value: 128 }, tGNoise: { value: noise },
  };
}

function makeGrassMaterial(U, clump) {
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: clump ? 0.55 : 0.62, metalness: 0, side: THREE.DoubleSide });
  mat.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, U);
    shader.vertexShader = `
      ${clump ? '#define CLUMP' : ''}
      attribute vec3 iOffset; attribute vec4 iParams; attribute vec3 iTint; attribute vec2 iLife; attribute float aBlade; attribute float aHead;
      uniform float uTime, uStreamT, uWind, uWindSpeed, uFar, uFade, uSeasonSat, uSeasonHeight, uSeasonKeep; uniform vec2 uWindDir; uniform vec3 uPlayer, uCenter, uSeasonTint;
      uniform sampler2D tGNoise, tTrample; uniform vec2 uTrOrigin; uniform float uTrExtent;
      varying vec3 vTint; varying float vT, vBlade, vHead, vPress;
      #ifndef CLUMP
      float gh(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float gn(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
        return mix(mix(gh(i),gh(i+vec2(1,0)),f.x), mix(gh(i+vec2(0,1)),gh(i+vec2(1,1)),f.x), f.y); }
      #endif
    ` + shader.vertexShader
      .replace('#include <beginnormal_vertex>', `
        float gyaw = iParams.x; float gcy = cos(gyaw), gsy = sin(gyaw);
        mat3 gRot = mat3(gcy, 0.0, -gsy, 0.0, 1.0, 0.0, gsy, 0.0, gcy);
        vec3 objectNormal = normalize(mix(vec3(0.0, 1.0, 0.0), gRot * normal, 0.32));
        #ifdef USE_TANGENT
          vec3 objectTangent = vec3(tangent.xyz);
        #endif`)
      .replace('#include <begin_vertex>', `
        vT = uv.y; vBlade = aBlade; vHead = aHead;
        vec3 gtc = iTint * iTint * uSeasonTint;                                   // tints are authored as display colours; the season multiplies them
        vTint = mix(vec3(dot(gtc, vec3(0.2126, 0.7152, 0.0722))), gtc, uSeasonSat);
        float gkeep = step(iParams.w, uSeasonKeep);                               // seasonal die-back: a fraction of the plants collapses
        // streaming: a chunk's blades grow in after iLife.x and out after iLife.y (the field never pops); smoothstep of the elapsed fraction
        float glife = smoothstep(0.0, 1.0, (uStreamT - iLife.x) / ${FADE_IN.toFixed(2)}) * (1.0 - smoothstep(0.0, 1.0, (uStreamT - iLife.y) / ${FADE_OUT.toFixed(2)}));
        float gh_ = iParams.y * uSeasonHeight * gkeep * glife, gw_ = iParams.z;
        #ifdef CLUMP
          vec3 glp = vec3(position.x * gw_, position.y * gh_, position.z * gw_);
        #else
          vec3 glp = vec3(position.x * gw_, position.y * gh_, position.z * gh_);
        #endif
        vec3 gwp = iOffset + gRot * glp;
        float gdist = distance(gwp, uCenter);
        float gfade = (1.0 - smoothstep(uFar * 0.78, uFar, gdist)) * uFade;
        vec2 gwd = normalize(uWindDir), gpd = vec2(-gwd.y, gwd.x);
        float gbend = vT * vT;
        #ifdef CLUMP
          // ---- wind over a field: gust cells from the noise texture, bands rolling downwind, per-blade flutter; seed heads lag and bob
          float along = dot(gwp.xz, gwd), across = dot(gwp.xz, gpd);
          vec4 gn = textureLod(tGNoise, gwp.xz * 0.011 - gwd * uTime * 0.022, 0.0);
          float roll1 = sin(along * 0.42 - uTime * 3.1 + across * 0.10 + gn.r * 4.0), roll2 = sin(along * 0.97 - uTime * 4.7 + gn.g * 6.0 + 1.7);
          float gust = 0.35 + 1.05 * gn.b;
          float push = (gust + 0.55 * (0.5 + 0.5 * roll1) + 0.22 * (0.5 + 0.5 * roll2)) * uWind;
          float flut = sin(uTime * (4.6 + aBlade * 3.2) + aBlade * 31.0 + vT * 4.0 + gn.a * 9.0);
          float lean = push * gbend * gh_ * 0.58;
          gwp.xz += gwd * (lean + flut * 0.03 * uWind * gbend * gh_) + gpd * flut * 0.05 * uWind * gbend * gh_ * (0.5 + 0.5 * gust);
          gwp.y -= abs(lean) * 0.34 * gbend;
          gwp.xz += gwd * aHead * push * gh_ * (0.05 + 0.07 * (0.5 + 0.5 * sin(uTime * 2.6 + aBlade * 19.0)));
          gwp.y -= aHead * (0.03 + 0.05 * push) * gh_;
        #else
          float ggust = gn(gwp.xz * 0.045 - gwd * uTime * uWindSpeed), gflut = gn(gwp.xz * 0.95 - gwd * uTime * 2.9 + iParams.w * 7.0);
          float gsway = (0.22 + 1.15 * ggust) * uWind + (gflut - 0.5) * 0.45 * uWind;
          gwp.xz += gwd * gsway * gbend * gh_ * 0.62;
          gwp.y  -= abs(gsway) * gbend * gh_ * 0.20;
        #endif
        // ---- trampling: the lean field (grass_trample.js) is read at the blade's ROOT, so the whole blade bends one way. Pressed grass stops swaying, then
        //      the blade is rotated about its root by an angle that grows toward the tip (length is preserved, so it arcs over instead of stretching)
        vec2 gtu = (iOffset.xz - uTrOrigin) / uTrExtent;
        vec2 gL = (textureLod(tTrample, gtu, 0.0).rg * 255.0 - 128.0) / 127.0 * step(0.0, min(gtu.x, gtu.y)) * step(max(gtu.x, gtu.y), 1.0);
        float gtl = length(gL);
        vPress = gtl;
        if (gtl > 0.012) {
          gwp = mix(gwp, iOffset + gRot * glp, min(1.0, gtl * 0.85));
          float ga = gtl * 1.4 * pow(vT, 1.12), ghh = glp.y;
          gwp.xz += (gL / gtl) * ghh * sin(ga);
          gwp.y  += ghh * (cos(ga) - 1.0);
        }
        vec2 gdp = gwp.xz - uPlayer.xz; float gpl = length(gdp);
        float gpf = (1.0 - smoothstep(0.0, 1.7, gpl)) * gbend;
        gwp.xz += (gdp / max(gpl, 0.05)) * gpf * 0.6 * gh_;
        gwp.y  -= gpf * 0.28 * gh_;
        gwp.y = mix(iOffset.y, gwp.y, gfade);
        vec3 transformed = gwp;`);
    shader.fragmentShader = `
      ${clump ? '#define CLUMP' : ''}
      uniform vec3 uLightDirView, uSunColor; uniform float uTrans, uPow, uFrost, uRipe;
      varying vec3 vTint; varying float vT, vBlade, vHead, vPress;
    ` + shader.fragmentShader
      .replace('#include <color_fragment>', `
        #include <color_fragment>
        vec3 gcol = mix(vTint * 0.30, vTint * 1.20, smoothstep(0.0, 0.85, vT));
        gcol = mix(gcol, gcol * vec3(1.18, 1.06, 0.72), smoothstep(0.72, 1.0, vT) * 0.45);
        #ifdef CLUMP
          gcol *= 0.86 + 0.28 * vBlade;                                                     // every blade is a slightly different tone
          vec3 headCol = mix(vec3(0.30, 0.46, 0.10), vec3(0.92, 0.66, 0.20), uRipe) * (0.85 + 0.3 * vBlade);   // seed heads ripen from green to gold
          gcol = mix(gcol, headCol, vHead);
        #endif
        gcol = mix(gcol, vec3(0.78, 0.84, 0.92), uFrost * smoothstep(0.25, 1.0, vT));
        gcol *= 1.0 - 0.16 * vPress;                                                         // pressed grass lies in its own shade
        diffuseColor.rgb *= gcol;`)
      .replace('#include <normal_fragment_begin>', `
        #include <normal_fragment_begin>
        #ifdef DOUBLE_SIDED
          normal *= faceDirection;
        #endif`)
      .replace('#include <opaque_fragment>', `
        float gback = pow(clamp(-dot(normalize(vViewPosition), uLightDirView), 0.0, 1.0), uPow);
        outgoingLight += diffuseColor.rgb * uSunColor * gback * uTrans * smoothstep(0.1, 0.9, vT);
        outgoingLight *= mix(${clump ? '0.42' : '0.55'}, 1.0, smoothstep(0.0, ${clump ? '0.62' : '0.5'}, vT));
        #include <opaque_fragment>`);
  };
  const key = mat.customProgramCacheKey(); mat.customProgramCacheKey = () => key + (clump ? '|grass_clump' : '|grass_blades');
  return mat;
}
