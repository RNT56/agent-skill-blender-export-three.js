// Water: a wind-driven lake surface with real physics hooks.
//
//   * waves      a shared model (water_waves.js): the longest waves displace the mesh, all of them bend the normal; the CPU samples the same model,
//                so floating things (lily pads, ducks, petals) sit exactly on the drawn surface
//   * shoreline  the bed is baked into a texture (bed height relative to the still level), so the waterline is exact per pixel, breathes with the
//                waves (swash), fades softly, and carries foam; shallow water is transparent and the real lake bed shows through
//   * body       depth absorption per colour channel (red dies first), caustics on the bed, subsurface-tinted crests, ambient from the atmosphere
//   * reflection planar mirror render (oblique clip plane) distorted by the surface normal, Fresnel-weighted, with sun / moon glints
//   * ripples    up to 24 live rings (units wading, arrows landing, ducks paddling, fish surfacing) from addRipple(x, z, strength)
//
// Output is premultiplied (CustomBlending) so reflections, glints and caustics add light without needing opacity.
import * as THREE from 'three';
import { waveSample, waveGLSL, DISPLACING, WAVES } from './water_waves.js';
import { createNoiseTexture } from './noisetex.js';

const MAX_RIPPLES = 24;

export class Water {
  /**
   * @param level      world Y of the still water surface
   * @param bounds     {x0,z0,x1,z1} area to cover (must contain the whole basin; square works best)
   * @param heightAt   (x,z) => terrain height (the carved basin)
   * @param mask       optional (x,z) => bool; places outside the mask are never water (keeps natural dips inside `bounds` dry)
   */
  constructor({ scene, level, bounds, heightAt, mask = null, cell = 1.0, reflectionWidth = 768, noise = createNoiseTexture(256, 11), bedRes = 256 }) {
    this.level = level; this.scene = scene; this.bounds = bounds; this.heightFn = heightAt; this.mask = mask; this.time = 0;
    const W = bounds.x1 - bounds.x0, H = bounds.z1 - bounds.z0;
    this.wind = { x: 1, z: 0.35, amp: 1 };

    // --- bed texture: (terrain height - level) as half floats
    const bed = new Uint16Array(bedRes * bedRes);
    for (let j = 0; j < bedRes; j++) for (let i = 0; i < bedRes; i++) {
      const x = bounds.x0 + (i + 0.5) / bedRes * W, z = bounds.z0 + (j + 0.5) / bedRes * H;
      bed[j * bedRes + i] = THREE.DataUtils.toHalfFloat((mask && !mask(x, z)) ? 9 : Math.max(-9, Math.min(9, heightAt(x, z) - level)));
    }
    const bedTex = new THREE.DataTexture(bed, bedRes, bedRes, THREE.RedFormat, THREE.HalfFloatType);
    bedTex.minFilter = bedTex.magFilter = THREE.LinearFilter; bedTex.wrapS = bedTex.wrapT = THREE.ClampToEdgeWrapping; bedTex.generateMipmaps = false; bedTex.needsUpdate = true;

    // --- mesh: a grid over the bounds; cells that are dry everywhere are dropped (less overdraw, no z-fighting with the terrain)
    const nx = Math.ceil(W / cell), nz = Math.ceil(H / cell);
    const g = new THREE.PlaneGeometry(W, H, nx, nz); g.rotateX(-Math.PI / 2); g.translate((bounds.x0 + bounds.x1) / 2, level, (bounds.z0 + bounds.z1) / 2);
    const pos = g.attributes.position, dry = new Uint8Array(pos.count);
    for (let i = 0; i < pos.count; i++) { const x = pos.getX(i), z = pos.getZ(i); dry[i] = ((mask && !mask(x, z)) || heightAt(x, z) - level > 0.9) ? 1 : 0; }
    const idx = g.index.array, keep = [];
    for (let t = 0; t < idx.length; t += 3) if (!(dry[idx[t]] && dry[idx[t + 1]] && dry[idx[t + 2]])) keep.push(idx[t], idx[t + 1], idx[t + 2]);
    g.setIndex(keep);

    this.rt = new THREE.WebGLRenderTarget(reflectionWidth, Math.round(reflectionWidth * 0.62), { type: THREE.HalfFloatType, samples: 2 });
    this.mirror = new THREE.PerspectiveCamera(); this.texMatrix = new THREE.Matrix4();
    this.ripples = Array.from({ length: MAX_RIPPLES }, () => new THREE.Vector4(0, 0, -100, 0)); this._rip = 0;
    const c = (r, g2, b) => new THREE.Color(r, g2, b);
    // NOTE: uniform objects are built by hand (never UniformsUtils.merge/clone, which copies matrices and nulls render-target textures)
    this.uniforms = {
      uTime: { value: 0 }, uAmp: { value: 1 }, uWindDir: { value: new THREE.Vector2(1, 0.35).normalize() }, uLevel: { value: level },
      uBedOrigin: { value: new THREE.Vector2(bounds.x0, bounds.z0) }, uBedSize: { value: new THREE.Vector2(W, H) },
      tRefl: { value: this.rt.texture }, uTexMatrix: { value: this.texMatrix }, tBed: { value: bedTex }, tNoise: { value: noise },
      uSunDir: { value: new THREE.Vector3(0.4, 0.7, 0.2) }, uSunColor: { value: c(1, 0.8, 0.6) }, uBodyLight: { value: c(0.7, 0.75, 0.85) },
      uDeep: { value: c(0.012, 0.075, 0.085) }, uShallow: { value: c(0.12, 0.27, 0.22) }, uAbsorb: { value: new THREE.Vector3(0.62, 0.17, 0.12) },
      uFoam: { value: c(0.93, 0.96, 0.98) }, uRipples: { value: this.ripples },
      fogColor: { value: new THREE.Color() }, fogDensity: { value: 0.006 }, fogNear: { value: 1 }, fogFar: { value: 2000 },
    };
    const mat = new THREE.ShaderMaterial({
      uniforms: this.uniforms, transparent: true, depthWrite: true, fog: false, blending: THREE.CustomBlending,
      blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
      vertexShader: `
        uniform float uTime, uAmp, uLevel; uniform vec2 uWindDir, uBedOrigin, uBedSize; uniform mat4 uTexMatrix; uniform sampler2D tBed;
        varying vec3 vWorld; varying vec4 vRefl; varying float vFogDepth;
        ${waveGLSL()}
        void main(){
          vec3 wp = (modelMatrix * vec4(position, 1.0)).xyz;
          float bedRel = textureLod(tBed, (wp.xz - uBedOrigin) / uBedSize, 0.0).r;
          wp.y += waveGrad(wp.xz, ${DISPLACING}).x * smoothstep(0.0, 0.9, -bedRel);       // waves die out toward the shore
          vWorld = wp; vRefl = uTexMatrix * vec4(wp, 1.0);
          vec4 mv = viewMatrix * vec4(wp, 1.0); vFogDepth = -mv.z;
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `
        uniform float uTime, uAmp, uLevel; uniform vec2 uWindDir, uBedOrigin, uBedSize;
        uniform sampler2D tRefl, tBed, tNoise;
        uniform vec3 uSunDir, uSunColor, uBodyLight, uDeep, uShallow, uAbsorb, uFoam; uniform vec4 uRipples[${MAX_RIPPLES}];
        uniform vec3 fogColor; uniform float fogDensity;
        varying vec3 vWorld; varying vec4 vRefl; varying float vFogDepth;
        ${waveGLSL()}
        void main(){
          vec2 p = vWorld.xz;
          float bedRel = texture2D(tBed, (p - uBedOrigin) / uBedSize).r;
          float depth = (vWorld.y - uLevel) - bedRel;                                   // water depth right here, including the wave
          if (depth < -0.03) discard;
          // ---- surface normal: waves + capillary ripples + live ripple rings, all calmer near the shore
          vec3 g = waveGrad(p, ${WAVES.length});
          float calm = smoothstep(0.02, 0.8, depth);
          vec2 cap = (texture2D(tNoise, p * 0.55 + uTime * 0.030 * uWindDir).rg - 0.5) + (texture2D(tNoise, p * 1.35 - uTime * 0.045 * uWindDir.yx).gb - 0.5);
          vec2 slope = g.yz * (0.4 + 0.6 * calm) + cap * (0.10 + 0.07 * uAmp) * calm;
          float ripFoam = 0.0;
          for (int i = 0; i < ${MAX_RIPPLES}; i++) {
            vec4 r = uRipples[i]; float age = uTime - r.z;
            if (age > 0.0 && age < 5.0) {
              vec2 d = p - r.xy; float rr = length(d) + 1e-4, R = 0.15 + age * 1.5, w = exp(-pow((rr - R) / 0.34, 2.0)), decay = exp(-age * 0.75) * r.w;
              slope += (d / rr) * (-sin((rr - R) * 9.0) * w * 0.22 * decay); ripFoam += w * decay * (1.0 - smoothstep(0.0, 0.7, age)) * 0.7;
            }
          }
          vec3 N = normalize(vec3(-slope.x, 1.0, -slope.y));
          vec3 V = normalize(cameraPosition - vWorld);
          float cosT = max(dot(N, V), 0.0), F = 0.02 + 0.98 * pow(1.0 - cosT, 5.0);
          // ---- reflection (planar mirror, bent by the normal)
          vec3 refl = texture2D(tRefl, clamp(vRefl.xy / vRefl.w + N.xz * 0.045, 0.001, 0.999)).rgb;
          // ---- body: per-channel absorption, ambient from the sky / key light
          float d = max(depth, 0.0);
          vec3 T = exp(-uAbsorb * d * 1.5);
          float cover = 1.0 - T.g;
          vec3 scatter = mix(uShallow, uDeep, clamp(1.0 - T.g * 1.15, 0.0, 1.0)) * uBodyLight;
          // translucent crests: light through thin wave tops tints them green
          scatter += vec3(0.05, 0.17, 0.10) * uBodyLight * smoothstep(0.02, 0.1, g.x * uAmp) * (0.4 + 0.6 * max(dot(normalize(vec3(uSunDir.x, 0.0, uSunDir.z)), normalize(vec3(-V.x, 0.0, -V.z))), 0.0));
          // ---- caustics on the bed (only where the bed is close enough to matter)
          float c1 = texture2D(tNoise, p * 0.46 + vec2(uTime * 0.050, uTime * 0.030)).r, c2 = texture2D(tNoise, p * 0.63 - vec2(uTime * 0.040, uTime * 0.060)).g;
          float caus = pow(clamp(1.0 - abs(c1 - c2) * 3.2, 0.0, 1.0), 6.0) * (1.0 - smoothstep(0.15, 2.6, d)) * T.g;
          // ---- foam: breathing shoreline band, wind-whipped crests, ripple rings
          float fn = texture2D(tNoise, p * 0.85 + uTime * 0.035).b;
          float shore = (1.0 - smoothstep(0.0, 0.30 + 0.08 * sin(uTime * 1.1 + p.x * 0.6 + p.y * 0.4), d + (fn - 0.5) * 0.30)) * smoothstep(-0.02, 0.05, d) * (0.55 + 0.45 * fn);
          float crest = smoothstep(0.05, 0.12, g.x) * smoothstep(0.3, 1.2, uAmp) * (0.3 + 0.7 * fn);
          float foam = clamp(shore * 0.8 + crest * 0.55 + ripFoam, 0.0, 1.0);
          // ---- sun / moon glints
          vec3 H = normalize(uSunDir + V); float nh = max(dot(N, H), 0.0);
          vec3 spec = uSunColor * (pow(nh, 1100.0) * 16.0 + pow(nh, 80.0) * 0.55) * (0.3 + 0.7 * F);
          // ---- compose (premultiplied)
          float edge = smoothstep(0.0, 0.07, depth);
          float a = clamp(cover * 0.97 + 0.03, 0.0, 1.0) * edge;
          vec3 rgb = scatter * a + refl * F * edge + (spec + uSunColor * caus * 0.5 * (1.0 - F)) * edge;
          float A = clamp(a + F * edge * (1.0 - a), 0.0, 1.0);
          vec3 foamC = uFoam * uBodyLight * 1.3;
          rgb = mix(rgb, foamC * max(A, 0.6), foam * 0.7); A = max(A, foam * 0.75);
          if (A < 0.025) discard;
          // fog (exp2), premultiplied: fade toward the fog colour and keep the coverage
          float ff = 1.0 - exp(-fogDensity * fogDensity * vFogDepth * vFogDepth);
          rgb = mix(rgb, fogColor * A, ff);
          gl_FragColor = vec4(rgb, A);
        }`,
    });
    this.mesh = new THREE.Mesh(g, mat); this.mesh.renderOrder = 2; this.mesh.frustumCulled = false; this.mesh.name = 'water';
    scene.add(this.mesh);
    this._plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -level);
    this._clip = new THREE.Plane(); this._clip4 = new THREE.Vector4(); this._q = new THREE.Vector4();
    this._fwd = new THREE.Vector3(); this._tgt = new THREE.Vector3(); this._up = new THREE.Vector3(); this._tmp = { h: 0, dx: 0, dz: 0 };
    this.onReflect = null;                                       // optional { begin(mirrorCamera), end() }: swap camera-dependent uniforms (cloud shadows, light direction) for the mirror pass
    this._frame = 0; this._lastPos = new THREE.Vector3(1e9, 0, 0); this._lastQuat = new THREE.Quaternion(); this.stillEvery = 3;
  }

  // ---------------------------------------------------------------------------------------------------- physics queries (CPU, same model as the GPU)
  /** terrain depth under still water at (x, z) in metres (0 on land) */
  depthAt(x, z) { const b = this.bounds; if (x < b.x0 || x > b.x1 || z < b.z0 || z > b.z1 || (this.mask && !this.mask(x, z))) return 0; return Math.max(0, this.level - this.heightFn(x, z)); }
  isWater(x, z, minDepth = 0.05) { return this.depthAt(x, z) > minDepth; }
  /** surface height at (x, z) right now (still level + waves, damped near the shore); equals the drawn mesh */
  heightAt(x, z) {
    const d = this.depthAt(x, z), s = waveSample(x, z, this.time, this.wind.x, this.wind.z, this.wind.amp, DISPLACING, this._tmp);
    const k = Math.min(1, Math.max(0, d / 0.9)); return this.level + s.h * k * k * (3 - 2 * k);
  }
  /** surface normal into `out` (a THREE.Vector3) from all wave components */
  normalAt(x, z, out) {
    const s = waveSample(x, z, this.time, this.wind.x, this.wind.z, this.wind.amp, WAVES.length, this._tmp);
    return out.set(-s.dx, 1, -s.dz).normalize();
  }
  /** a ring spreading from (x, z); strength ~ 0.3 (a paddle) .. 1.5 (a splash) */
  addRipple(x, z, strength = 1) { this.ripples[this._rip].set(x, z, this.time, strength); this._rip = (this._rip + 1) % MAX_RIPPLES; }

  // ---------------------------------------------------------------------------------------------------- per frame
  /** wind: unit direction {x, y} (THREE.Vector2) and a 0..2 strength */
  setWind(dir, strength) {
    this.wind.x = dir.x; this.wind.z = dir.y; this.wind.amp = 0.4 + 0.75 * strength;
    this.uniforms.uWindDir.value.set(dir.x, dir.y); this.uniforms.uAmp.value = this.wind.amp;
  }
  /** colours and light from the atmosphere state */
  setAtmosphere(S) {
    const u = this.uniforms, k = Math.min(1, S.keyIntensity / 4.5);
    u.uSunDir.value.copy(S.keyDir); u.uSunColor.value.copy(S.keyColor).multiplyScalar(k);
    // body light: sky ambient plus a share of the key light, normalised so a bright day is ~0.8
    u.uBodyLight.value.setRGB(
      S.hemi.sky.r * S.hemi.intensity * 0.35 + S.keyColor.r * S.keyIntensity * 0.075,
      S.hemi.sky.g * S.hemi.intensity * 0.35 + S.keyColor.g * S.keyIntensity * 0.075,
      S.hemi.sky.b * S.hemi.intensity * 0.35 + S.keyColor.b * S.keyIntensity * 0.075);
    u.fogColor.value.copy(this.scene.fog.color); u.fogDensity.value = this.scene.fog.density;
  }

  /** Render the mirrored scene into the reflection target. `hide` = objects to skip in the reflection (grass, particles, ground markers). */
  update(renderer, scene, camera, time, hide = []) {
    this.time = time; this.uniforms.uTime.value = time;
    this.uniforms.fogColor.value.copy(scene.fog.color); this.uniforms.fogDensity.value = scene.fog.density;
    const cp = camera.position;
    if (cp.y <= this.level + 0.05) return;                       // underwater: keep the last reflection
    // a motionless view only needs a fresh reflection every few frames (units and trees still move, but the mirror image barely changes)
    const still = this._lastPos.distanceToSquared(cp) < 1e-6 && this._lastQuat.angleTo(camera.quaternion) < 1e-5;
    this._lastPos.copy(cp); this._lastQuat.copy(camera.quaternion);
    if (still && (this._frame++ % this.stillEvery) !== 0) return;
    const m = this.mirror, L = this.level;
    camera.getWorldDirection(this._fwd);
    this._up.set(0, 1, 0).applyQuaternion(camera.quaternion);
    m.position.set(cp.x, 2 * L - cp.y, cp.z);
    m.up.set(this._up.x, -this._up.y, this._up.z);
    this._tgt.set(cp.x + this._fwd.x, 2 * L - (cp.y + this._fwd.y), cp.z + this._fwd.z);
    m.lookAt(this._tgt);
    m.projectionMatrix.copy(camera.projectionMatrix);
    m.updateMatrixWorld(); m.matrixWorldInverse.copy(m.matrixWorld).invert();
    this.texMatrix.set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1).multiply(m.projectionMatrix).multiply(m.matrixWorldInverse);
    // oblique near plane = the water plane, so nothing below the surface leaks into the reflection
    this._clip.copy(this._plane).applyMatrix4(m.matrixWorldInverse);
    this._clip4.set(this._clip.normal.x, this._clip.normal.y, this._clip.normal.z, this._clip.constant);
    const e = m.projectionMatrix.elements;
    this._q.set((Math.sign(this._clip4.x) + e[8]) / e[0], (Math.sign(this._clip4.y) + e[9]) / e[5], -1.0, (1.0 + e[10]) / e[14]);
    this._clip4.multiplyScalar(2.0 / this._clip4.dot(this._q));
    e[2] = this._clip4.x; e[6] = this._clip4.y; e[10] = this._clip4.z + 1.0 - 0.003; e[14] = this._clip4.w;

    const vis = hide.map(o => o.visible); hide.forEach(o => { o.visible = false; });
    this.mesh.visible = false; this.onReflect?.begin(m);
    const shadowAuto = renderer.shadowMap.autoUpdate; renderer.shadowMap.autoUpdate = false;
    const prevRT = renderer.getRenderTarget();
    renderer.setRenderTarget(this.rt);
    renderer.state.buffers.depth.setMask(true);
    renderer.clear();
    renderer.render(scene, m);
    renderer.setRenderTarget(prevRT);
    renderer.shadowMap.autoUpdate = shadowAuto;
    this.onReflect?.end(); this.mesh.visible = true;
    hide.forEach((o, i) => { o.visible = vis[i]; });
  }

  setSize(width) { this.rt.setSize(width, Math.round(width * 0.62)); }
}
