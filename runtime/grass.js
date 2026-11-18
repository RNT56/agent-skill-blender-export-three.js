// GPU-instanced grass with wind. Blade meshes come from the `grass` recipe (specs/grass_blades.json):
// nodes named <asset>_<Variant>_LOD<n>; uv.y = height along the blade (0 base .. 1 tip).
// Chunks around the camera are built on demand in three distance tiers (LOD0 blade / LOD1 blade / sparse wide tufts),
// one draw call per (chunk, variant). Wind, player push-through, translucency and distance fade all run in the vertex/fragment shader.
import * as THREE from 'three';
import { mulberry32 } from './noise.js';

const DEFAULT_TIERS = [
  { r: 26, density: 34, lod: 0, wScale: 1.0, hScale: 1.0 },
  { r: 62, density: 12, lod: 1, wScale: 1.3, hScale: 1.0 },
  { r: 108, density: 3.2, lod: 1, wScale: 2.4, hScale: 1.1 },
];

export class GrassField {
  /**
   * @param bladeScene  gltf.scene from grass_blades.glb
   * @param heightAt    (x,z) => y
   * @param styleAt     (x,z,out) => void   set out.density (0..1) and out.r/g/b (tip colour, linear-ish display values)
   * @param uniforms    shared wind/light uniforms (see createGrassUniforms)
   */
  constructor({ scene, bladeScene, heightAt, styleAt, uniforms, tiers = DEFAULT_TIERS, chunk = 12, maxBuildsPerFrame = 3, heightRange = [0.35, 0.85] }) {
    this.scene = scene; this.heightAt = heightAt; this.styleAt = styleAt; this.U = uniforms;
    this.tiers = tiers; this.chunk = chunk; this.maxBuilds = maxBuildsPerFrame; this.hr = heightRange;
    this.maxR = tiers[tiers.length - 1].r;
    this.U.uFar.value = this.maxR;
    this.chunks = new Map();
    this.group = new THREE.Group(); this.group.name = 'grass'; scene.add(this.group);
    this.frustum = new THREE.Frustum(); this._pv = new THREE.Matrix4(); this._sph = new THREE.Sphere();
    // blade geometries: variants[v][lod]
    const found = {};
    bladeScene.traverse(o => {
      const m = /_([A-Za-z0-9]+)_LOD(\d+)$/.exec(o.name);
      if (o.isMesh && m) (found[m[1]] ??= {})[+m[2]] = o.geometry;
    });
    this.variants = Object.keys(found).sort().map(k => found[k]);
    if (!this.variants.length) throw new Error('GrassField: no blade meshes named *_<Variant>_LOD<n> found');
    this.material = makeGrassMaterial(uniforms);
    this.stats = { chunks: 0, instances: 0, visible: 0 };
  }

  _build(cx, cz, tier) {
    const t = this.tiers[tier], C = this.chunk;
    const x0 = cx * C, z0 = cz * C;
    const nv = this.variants.length;
    const target = Math.ceil(C * C * t.density);
    const rng = mulberry32((cx * 73856093) ^ (cz * 19349663) ^ 0x9e3779b9);
    const buf = this.variants.map(() => []);
    const style = { density: 1, r: 0.3, g: 0.5, b: 0.1 };
    let minY = 1e9, maxY = -1e9, count = 0;
    for (let k = 0; k < target; k++) {
      const x = x0 + rng() * C, z = z0 + rng() * C;
      const rv = rng(), ryaw = rng() * Math.PI * 2, rh = rng(), rw = rng(), rt = rng(), rvar = rng();
      this.styleAt(x, z, style);
      if (rv > style.density) continue;
      const y = this.heightAt(x, z);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y + 1.2);
      const h = (this.hr[0] + (this.hr[1] - this.hr[0]) * rh) * t.hScale * (0.75 + 0.5 * style.density);
      const w = (0.8 + 0.5 * rw) * t.wScale;
      const v = Math.min(nv - 1, Math.floor(rvar * nv));
      const tint = 0.85 + 0.3 * rt;
      buf[v].push(x, y - 0.02, z, ryaw, h, w, rt, 0, style.r * tint, style.g * tint, style.b * tint);
      count++;
    }
    if (!count) return { meshes: [], tier, count: 0, box: null };
    const meshes = [];
    for (let v = 0; v < nv; v++) {
      const a = buf[v];
      if (!a.length) continue;
      const n = a.length / 11;
      const src = this.variants[v][Math.min(t.lod, this.variants[v].length - 1)] ?? this.variants[v][0];
      const g = new THREE.InstancedBufferGeometry();
      g.index = src.index;
      for (const name of ['position', 'normal', 'uv']) g.setAttribute(name, new THREE.BufferAttribute(src.getAttribute(name).array, src.getAttribute(name).itemSize));
      const off = new Float32Array(n * 3), par = new Float32Array(n * 4), tin = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        const o = i * 11;
        off.set([a[o], a[o + 1], a[o + 2]], i * 3);
        par.set([a[o + 3], a[o + 4], a[o + 5], a[o + 6]], i * 4);
        tin.set([a[o + 8], a[o + 9], a[o + 10]], i * 3);
      }
      g.setAttribute('iOffset', new THREE.InstancedBufferAttribute(off, 3));
      g.setAttribute('iParams', new THREE.InstancedBufferAttribute(par, 4));
      g.setAttribute('iTint', new THREE.InstancedBufferAttribute(tin, 3));
      g.instanceCount = n;
      const m = new THREE.Mesh(g, this.material);
      m.frustumCulled = false; m.receiveShadow = true; m.castShadow = false;
      this.group.add(m);
      meshes.push(m);
    }
    const box = new THREE.Sphere(new THREE.Vector3(x0 + C / 2, (minY + maxY) / 2, z0 + C / 2), Math.hypot(C / 2, (maxY - minY) / 2) + 1.5);
    return { meshes, tier, count, box };
  }

  _drop(e) {
    for (const m of e.meshes) { this.group.remove(m); m.geometry.dispose(); }
  }

  update(camera, time, player) {
    const U = this.U;
    U.uTime.value = time;
    if (player) U.uPlayer.value.copy(player);
    const C = this.chunk, cp = camera.position;
    const ci = Math.floor(cp.x / C), cj = Math.floor(cp.z / C), rr = Math.ceil(this.maxR / C) + 1;
    const want = [];
    const seen = new Set();
    for (let j = cj - rr; j <= cj + rr; j++) {
      for (let i = ci - rr; i <= ci + rr; i++) {
        const dx = (i + 0.5) * C - cp.x, dz = (j + 0.5) * C - cp.z;
        const d = Math.hypot(dx, dz) - C * 0.7;
        let tier = -1;
        for (let k = 0; k < this.tiers.length; k++) if (d < this.tiers[k].r) { tier = k; break; }
        const key = i + ',' + j;
        const e = this.chunks.get(key);
        if (tier < 0) continue;
        seen.add(key);
        if (!e || e.tier !== tier) want.push({ i, j, tier, key, d });
      }
    }
    for (const [key, e] of this.chunks) if (!seen.has(key)) { this._drop(e); this.chunks.delete(key); }
    want.sort((a, b) => a.d - b.d);
    for (let n = 0; n < Math.min(this.maxBuilds, want.length); n++) {
      const w = want[n];
      const old = this.chunks.get(w.key);
      if (old) this._drop(old);
      this.chunks.set(w.key, this._build(w.i, w.j, w.tier));
    }
    // frustum cull per chunk
    this._pv.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    this.frustum.setFromProjectionMatrix(this._pv);
    let inst = 0, vis = 0;
    for (const e of this.chunks.values()) {
      const v = e.box ? this.frustum.intersectsSphere(e.box) : false;
      for (const m of e.meshes) m.visible = v;
      inst += e.count; if (v) vis += e.count;
    }
    this.stats.chunks = this.chunks.size; this.stats.instances = inst; this.stats.visible = vis;
  }
}

export function createGrassUniforms(look) {
  const c = a => new THREE.Color(a[0], a[1], a[2]);
  return {
    uTime: { value: 0 }, uWindDir: { value: new THREE.Vector2(1.0, 0.35) }, uWind: { value: 0.55 }, uWindSpeed: { value: 1.1 },
    uPlayer: { value: new THREE.Vector3(1e5, 0, 1e5) }, uFar: { value: 100 },
    uLightDirView: { value: new THREE.Vector3(0, 1, 0) }, uSunColor: { value: c(look.sun.color) },
    uTrans: { value: (look.foliage?.translucency ?? 0.9) * 0.8 }, uPow: { value: look.foliage?.translucency_power ?? 3.0 },
  };
}

function makeGrassMaterial(U) {
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.62, metalness: 0, side: THREE.DoubleSide });
  mat.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, U);
    shader.vertexShader = `
      attribute vec3 iOffset; attribute vec4 iParams; attribute vec3 iTint;
      uniform float uTime, uWind, uWindSpeed, uFar; uniform vec2 uWindDir; uniform vec3 uPlayer;
      varying vec3 vTint; varying float vT;
      float gh(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float gn(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
        return mix(mix(gh(i),gh(i+vec2(1,0)),f.x), mix(gh(i+vec2(0,1)),gh(i+vec2(1,1)),f.x), f.y); }
    ` + shader.vertexShader
      .replace('#include <beginnormal_vertex>', `
        float gyaw = iParams.x; float gcy = cos(gyaw), gsy = sin(gyaw);
        mat3 gRot = mat3(gcy, 0.0, -gsy, 0.0, 1.0, 0.0, gsy, 0.0, gcy);
        vec3 objectNormal = normalize(mix(vec3(0.0, 1.0, 0.0), gRot * normal, 0.32));
        #ifdef USE_TANGENT
          vec3 objectTangent = vec3(tangent.xyz);
        #endif`)
      .replace('#include <begin_vertex>', `
        vT = uv.y; vTint = iTint * iTint;   // tints are authored as display colours
        float gh_ = iParams.y, gw_ = iParams.z;
        vec3 glp = vec3(position.x * gw_, position.y * gh_, position.z * gh_);
        vec3 gwp = iOffset + gRot * glp;
        float gdist = distance(gwp, cameraPosition);
        float gfade = 1.0 - smoothstep(uFar * 0.78, uFar, gdist);
        vec2 gwd = normalize(uWindDir);
        float ggust = gn(gwp.xz * 0.045 - gwd * uTime * uWindSpeed);
        float gflut = gn(gwp.xz * 0.95 - gwd * uTime * 2.9 + iParams.w * 7.0);
        float gsway = (0.22 + 1.15 * ggust) * uWind + (gflut - 0.5) * 0.45 * uWind;
        float gbend = vT * vT;
        gwp.xz += gwd * gsway * gbend * gh_ * 0.62;
        gwp.y  -= abs(gsway) * gbend * gh_ * 0.20;
        vec2 gdp = gwp.xz - uPlayer.xz; float gpd = length(gdp);
        float gpf = smoothstep(1.7, 0.0, gpd) * gbend;
        gwp.xz += (gdp / max(gpd, 0.05)) * gpf * 0.6 * gh_;
        gwp.y  -= gpf * 0.28 * gh_;
        gwp.y = mix(iOffset.y, gwp.y, gfade);
        vec3 transformed = gwp;`);
    shader.fragmentShader = `
      uniform vec3 uLightDirView, uSunColor; uniform float uTrans, uPow;
      varying vec3 vTint; varying float vT;
    ` + shader.fragmentShader
      .replace('#include <color_fragment>', `
        #include <color_fragment>
        vec3 gcol = mix(vTint * 0.30, vTint * 1.20, smoothstep(0.0, 0.85, vT));
        gcol = mix(gcol, gcol * vec3(1.18, 1.06, 0.72), smoothstep(0.72, 1.0, vT) * 0.45);
        diffuseColor.rgb *= gcol;`)
      .replace('#include <normal_fragment_begin>', `
        #include <normal_fragment_begin>
        #ifdef DOUBLE_SIDED
          normal *= faceDirection;
        #endif`)
      .replace('#include <opaque_fragment>', `
        float gback = pow(clamp(-dot(normalize(vViewPosition), uLightDirView), 0.0, 1.0), uPow);
        outgoingLight += diffuseColor.rgb * uSunColor * gback * uTrans * smoothstep(0.1, 0.9, vT);
        outgoingLight *= mix(0.55, 1.0, smoothstep(0.0, 0.5, vT));
        #include <opaque_fragment>`);
  };
  return mat;
}
