// Lighting rig driven by the atmosphere: hemisphere ambient, one shadow-casting KEY light (the sun by day, the moon by night, blended so its
// direction never jumps), a cool no-shadow fill opposite the key, optional flickering lamp lights (lanterns / braziers that come on at dusk),
// plus exposure, fog and background. Shadow frustum helpers follow the view focus (texel-snapped, so shadows do not shimmer).
import * as THREE from 'three';

export class LightingRig {
  constructor(scene, renderer, { shadowSize = 4096, shadowRadius = 60, lampCount = 4 } = {}) {
    this.scene = scene; this.renderer = renderer; this.shadowSize = shadowSize; this.curR = shadowRadius;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    scene.background = new THREE.Color(); scene.fog = new THREE.FogExp2(0x888888, 0.006);
    this.hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 1); scene.add(this.hemi);
    this.key = new THREE.DirectionalLight(0xffffff, 1);
    this.key.castShadow = true; this.key.shadow.mapSize.set(shadowSize, shadowSize);
    Object.assign(this.key.shadow.camera, { left: -shadowRadius, right: shadowRadius, top: shadowRadius, bottom: -shadowRadius, near: 1, far: 260 });
    this.key.shadow.bias = -0.0008; this.key.shadow.normalBias = 0.08;
    scene.add(this.key, this.key.target);
    this.fill = new THREE.DirectionalLight(0xffffff, 0); scene.add(this.fill);
    // lamps stay in the light list permanently (only their intensity changes): toggling visibility would recompile every lit material at dusk
    this.lamps = Array.from({ length: lampCount }, () => { const l = new THREE.PointLight(0xff8a3a, 0, 24, 1.7); scene.add(l); return l; });
    this.lampBase = this.lamps.map(() => 0);
    this.dir = new THREE.Vector3(0, 1, 0);                                   // direction toward the key light (sun or moon), slew-limited
    this._t = 0; this._init = false; this._want = new THREE.Vector3(); this._right = new THREE.Vector3(); this._upL = new THREE.Vector3(); this._c = new THREE.Vector3();
  }

  /** @param S Atmosphere state  @param dt real seconds since the last call (the key light may turn at most ~26 degrees per second: no shadow snaps at dusk and dawn) */
  apply(S, dt = 1) {
    const r = this.renderer, sc = this.scene;
    r.toneMappingExposure = S.exposure;
    sc.background.copy(S.sky.horizon);
    sc.fog.color.copy(S.fog.color); sc.fog.density = S.fog.density;
    this.hemi.color.copy(S.hemi.sky); this.hemi.groundColor.copy(S.hemi.ground); this.hemi.intensity = S.hemi.intensity;
    const want = this._want.copy(S.keyDir); if (want.y < 0.1) { want.y = 0.1; want.normalize(); }                    // never light from below the horizon
    const ang = this.dir.angleTo(want), step = 0.45 * dt;
    if (!this._init || ang <= step) { this.dir.copy(want); this._init = true; } else this.dir.lerp(want, step / ang).normalize();
    this.key.color.copy(S.keyColor); this.key.intensity = S.keyIntensity;
    this.fill.color.copy(S.fill.color); this.fill.intensity = S.fill.intensity;
    this.fill.position.set(-this.dir.x * 80, 60, -this.dir.z * 80);
    this._lamp = S.lamps;
  }

  /** lamp positions: [{x, y, z, intensity?}]; they glow in proportion to atmosphere.lamps (dusk -> dawn) */
  setLamps(list) { list.forEach((p, i) => { if (this.lamps[i]) { this.lamps[i].position.set(p.x, p.y, p.z); this.lampBase[i] = p.intensity ?? 14; } }); }
  /** flicker; call once per frame */
  updateLamps(t) {
    this._t = t;
    this.lamps.forEach((l, i) => { const f = 0.88 + 0.07 * Math.sin(t * 7.3 + i * 2.1) + 0.05 * Math.sin(t * 13.1 + i); l.intensity = (this._lamp ?? 0) * this.lampBase[i] * f; });
  }

  setShadowRadius(rad) {
    if (Math.abs(rad - this.curR) < 0.5) return;
    this.curR = rad;
    Object.assign(this.key.shadow.camera, { left: -rad, right: rad, top: rad, bottom: -rad }); this.key.shadow.camera.updateProjectionMatrix();
  }
  /** keep the shadow frustum centred on the view focus, snapped to whole shadow texels IN LIGHT SPACE (so shadows do not shimmer as the view pans) */
  followShadow(center) {
    const d = this.dir, right = this._right.set(0, 1, 0).cross(d).normalize(), upL = this._upL.crossVectors(d, right), texel = 2 * this.curR / this.shadowSize;
    const pr = center.x * right.x + center.y * right.y + center.z * right.z, pu = center.x * upL.x + center.y * upL.y + center.z * upL.z;
    const c = this._c.copy(center).addScaledVector(right, Math.round(pr / texel) * texel - pr).addScaledVector(upL, Math.round(pu / texel) * texel - pu);
    this.key.target.position.copy(c);
    this.key.position.copy(c).addScaledVector(d, 130);
    this.key.target.updateMatrixWorld();
  }
}
