// Shared look (looks/*.json): sun, ambient, fog, exposure. The same JSON drives the Blender preview.
import * as THREE from 'three';

const col = a => new THREE.Color(a[0], a[1], a[2]);

export function applyLook(scene, renderer, look, { shadowSize = 4096, shadowRadius = 46 } = {}) {
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = look.exposure.three;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const horizon = col(look.sky.color);
  scene.background = horizon.clone();
  const fogCol = look.fog ? col(look.fog) : horizon.clone().lerp(new THREE.Color(1, 1, 1), 0.08);
  scene.fog = new THREE.FogExp2(fogCol, look.fogDensity ?? 0.0105);
  const hemi = new THREE.HemisphereLight(col(look.sky.ambient_sky), col(look.sky.ambient_ground), look.sky.three_ambient);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(col(look.sun.color), look.sun.three_intensity);
  const el = THREE.MathUtils.degToRad(look.sun.elevation_deg), az = THREE.MathUtils.degToRad(look.sun.azimuth_deg);
  const dir = new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el)).normalize();   // toward the sun
  sun.castShadow = true;
  sun.shadow.mapSize.set(shadowSize, shadowSize);
  const r = shadowRadius;
  Object.assign(sun.shadow.camera, { left: -r, right: r, top: r, bottom: -r, near: 1, far: 220 });
  sun.shadow.bias = -0.0008;
  sun.shadow.normalBias = 0.08;
  scene.add(sun, sun.target);
  if (look.fill) {                                   // cool skylight fill from the side opposite the sun (no shadows): keeps the shade readable
    const fill = new THREE.DirectionalLight(col(look.fill.color), look.fill.intensity);
    fill.position.set(-dir.x * 80, 60, -dir.z * 80);
    scene.add(fill);
  }
  const snap = shadowRadius * 2 / shadowSize;
  return {
    sun, hemi, dir, horizon,
    /** Keep the shadow frustum centred on the viewer (texel-snapped to avoid shimmer). */
    followShadow(center) {
      const cx = Math.round(center.x / (snap * 8)) * snap * 8, cz = Math.round(center.z / (snap * 8)) * snap * 8;
      sun.target.position.set(cx, center.y, cz);
      sun.position.set(cx, center.y, cz).addScaledVector(dir, 120);
      sun.target.updateMatrixWorld();
    },
  };
}
