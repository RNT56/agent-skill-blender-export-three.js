// Water: planar reflection (mirrored camera + oblique clip plane), depth-based shoreline (the lake bed shows through the shallows),
// animated wave normals, fresnel, sun glitter, shore foam. One mesh over a bounding box; the shoreline comes from the terrain depth
// (level - heightAt) stored per vertex, so ANY basin carved into the terrain gets a correct, organic shore.
import * as THREE from 'three';

export class Water {
  /**
   * @param level       world Y of the water surface
   * @param bounds      {x0,z0,x1,z1} area to cover (must contain the whole basin)
   * @param heightAt    (x,z) => terrain height (the carved basin)
   * @param look        looks/*.json (sun + sky colours)
   * @param sunDir      THREE.Vector3 pointing TOWARD the sun
   * @param mask        optional (x,z) => bool; vertices outside are never water (keeps natural dips inside `bounds` dry)
   */
  constructor({ scene, level, bounds, heightAt, look, sunDir, mask = null, cell = 1.0, reflectionWidth = 768, deep = [0.015, 0.075, 0.09], shallow = [0.10, 0.25, 0.22] }) {
    this.level = level; this.scene = scene;
    const W = bounds.x1 - bounds.x0, H = bounds.z1 - bounds.z0;
    const nx = Math.ceil(W / cell), nz = Math.ceil(H / cell);
    const g = new THREE.PlaneGeometry(W, H, nx, nz);
    g.rotateX(-Math.PI / 2);
    g.translate((bounds.x0 + bounds.x1) / 2, level, (bounds.z0 + bounds.z1) / 2);
    const pos = g.attributes.position, depth = new Float32Array(pos.count);
    for (let i = 0; i < pos.count; i++) { const x = pos.getX(i), z = pos.getZ(i); depth[i] = (mask && !mask(x, z)) ? -5 : level - heightAt(x, z); }   // mask: only the carved basin holds water, not any low spot inside the box
    g.setAttribute('aDepth', new THREE.BufferAttribute(depth, 1));
    // drop cells that are entirely dry (cheap: keeps overdraw down and avoids z-fighting with the terrain)
    const idx = g.index.array, keep = [];
    for (let t = 0; t < idx.length; t += 3) if (depth[idx[t]] > -0.4 || depth[idx[t + 1]] > -0.4 || depth[idx[t + 2]] > -0.4) keep.push(idx[t], idx[t + 1], idx[t + 2]);
    g.setIndex(keep);

    this.rt = new THREE.WebGLRenderTarget(reflectionWidth, Math.round(reflectionWidth * 0.62), { type: THREE.HalfFloatType, samples: 2 });
    this.mirror = new THREE.PerspectiveCamera();
    this.texMatrix = new THREE.Matrix4();
    const c = a => new THREE.Color(a[0], a[1], a[2]);
    this.uniforms = THREE.UniformsUtils.merge([THREE.UniformsLib.fog, {
      uTime: { value: 0 }, tRefl: { value: this.rt.texture }, uTexMatrix: { value: this.texMatrix },
      uSunDir: { value: sunDir.clone() }, uSunColor: { value: c(look.sun.color) },
      uSkyHorizon: { value: c(look.sky.color) }, uSkyTop: { value: c(look.sky.top ?? [0.05, 0.13, 0.42]) },
      uDeep: { value: c(deep) }, uShallow: { value: c(shallow) }, uWaveScale: { value: 1.0 },
    }]);
    const mat = new THREE.ShaderMaterial({
      uniforms: this.uniforms, transparent: true, depthWrite: false, fog: true,
      vertexShader: `
        attribute float aDepth; varying float vDepth; varying vec3 vWorld; varying vec4 vRefl; uniform mat4 uTexMatrix;
        #include <fog_pars_vertex>
        void main(){
          vDepth = aDepth; vWorld = (modelMatrix * vec4(position, 1.0)).xyz; vRefl = uTexMatrix * vec4(vWorld, 1.0);
          vec4 mvPosition = viewMatrix * vec4(vWorld, 1.0);
          gl_Position = projectionMatrix * mvPosition;
          #include <fog_vertex>
        }`,
      fragmentShader: `
        varying float vDepth; varying vec3 vWorld; varying vec4 vRefl;
        uniform float uTime, uWaveScale; uniform sampler2D tRefl; uniform vec3 uSunDir, uSunColor, uSkyHorizon, uSkyTop, uDeep, uShallow;
        #include <fog_pars_fragment>
        float wh(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
        float wn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
          return mix(mix(wh(i), wh(i + vec2(1, 0)), f.x), mix(wh(i + vec2(0, 1)), wh(i + vec2(1, 1)), f.x), f.y); }
        vec2 wave(vec2 p, vec2 d, float k, float a, float sp){ d = normalize(d); return d * (a * k * cos(dot(d, p) * k + uTime * sp)); }
        void main(){
          if (vDepth < -0.35) discard;
          vec2 p = vWorld.xz;
          vec2 g = wave(p, vec2(1.0, 0.35), 0.55, 0.050, 1.1) + wave(p, vec2(-0.4, 1.0), 0.93, 0.030, 1.5)
                 + wave(p, vec2(0.7, -0.8), 1.7, 0.016, 2.1) + wave(p, vec2(-1.0, -0.2), 2.9, 0.008, 2.9);
          g += (vec2(wn(p * 2.2 + uTime * 0.35), wn(p * 2.2 - uTime * 0.28 + 9.1)) - 0.5) * 0.06;     // fine ripples
          float shore = smoothstep(0.0, 1.2, vDepth);
          vec3 N = normalize(vec3(-g.x, 1.0, -g.y) * vec3(uWaveScale * shore + 0.15, 1.0, uWaveScale * shore + 0.15));
          vec3 V = normalize(cameraPosition - vWorld);
          float cosT = max(dot(N, V), 0.0);
          float F = 0.02 + 0.98 * pow(1.0 - cosT, 5.0);
          vec2 ruv = vRefl.xy / vRefl.w + N.xz * 0.035;
          vec3 refl = texture2D(tRefl, clamp(ruv, 0.001, 0.999)).rgb;
          vec3 body = mix(uShallow, uDeep, 1.0 - exp(-max(vDepth, 0.0) * 0.55));
          // sun glitter + broad sheen
          vec3 H = normalize(uSunDir + V);
          float nh = max(dot(N, H), 0.0);
          vec3 spec = uSunColor * (pow(nh, 520.0) * 9.0 + pow(nh, 70.0) * 0.55);
          // shore foam: thin bands that breathe with the waves
          float fl = wn(p * 3.0 + vec2(uTime * 0.2, 0.0));
          float foam = smoothstep(0.45 + 0.1 * sin(uTime * 0.9 + p.x), 0.0, vDepth + (fl - 0.5) * 0.25) * smoothstep(-0.3, 0.05, vDepth);
          vec3 col = mix(body, refl, clamp(F * 1.1 + 0.08, 0.0, 1.0)) + spec * (0.35 + 0.65 * F);
          col = mix(col, vec3(0.92, 0.95, 0.97), foam * 0.55);
          float alpha = clamp((1.0 - exp(-max(vDepth, 0.0) * 1.7)) * 0.93, 0.0, 1.0);
          alpha = max(alpha, max(F * 0.95, foam * 0.5));
          alpha *= smoothstep(-0.3, 0.12, vDepth);
          gl_FragColor = vec4(col, alpha);
          #include <fog_fragment>
        }`,
    });
    this.mesh = new THREE.Mesh(g, mat);
    this.mesh.renderOrder = 2; this.mesh.frustumCulled = false; this.mesh.name = 'water';
    scene.add(this.mesh);
    this._plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -level);
    this._clip = new THREE.Plane(); this._clip4 = new THREE.Vector4(); this._q = new THREE.Vector4();
    this._fwd = new THREE.Vector3(); this._tgt = new THREE.Vector3(); this._up = new THREE.Vector3();
  }

  /** Render the mirrored scene into the reflection target. `hide` = objects to skip in the reflection (grass, particles). */
  update(renderer, scene, camera, time, hide = []) {
    this.uniforms.uTime.value = time;
    const cp = camera.position;
    if (cp.y <= this.level + 0.05) return;                       // underwater: keep the last reflection
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
    this.mesh.visible = false;
    const shadowAuto = renderer.shadowMap.autoUpdate; renderer.shadowMap.autoUpdate = false;
    const prevRT = renderer.getRenderTarget();
    renderer.setRenderTarget(this.rt);
    renderer.state.buffers.depth.setMask(true);
    renderer.clear();
    renderer.render(scene, m);
    renderer.setRenderTarget(prevRT);
    renderer.shadowMap.autoUpdate = shadowAuto;
    this.mesh.visible = true;
    hide.forEach((o, i) => { o.visible = vis[i]; });
  }

  setSize(width) { this.rt.setSize(width, Math.round(width * 0.62)); }
}
