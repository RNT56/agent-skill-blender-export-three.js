// Dynamic sky dome driven by the atmosphere state: a 4-stop gradient with a sun-side glow, sun disc and halo, a phased moon, a rotating star
// field with a faint galaxy band, two cloud decks (lit cumulus with sun-facing rims, high cirrus) that follow the wind, and a ground haze.
// Follows the camera. Values are scene-linear HDR so bloom can pick up the sun, the moon and the brightest stars.
import * as THREE from 'three';
import { createNoiseTexture } from './noisetex.js';

const VERT = 'varying vec3 vDir; void main(){ vDir = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); gl_Position.z = gl_Position.w; }';
const FRAG = `
  varying vec3 vDir;
  uniform sampler2D tNoise; uniform mat3 uStarRot;
  uniform vec3 uSunDir, uSunDisc, uMoonDir, uMoonColor, uTop, uMid, uHorizon, uGlow, uGround, uCloudLit, uCloudShadow;
  uniform float uTime, uCover, uSpeed, uStars, uMoonLight, uMoonPhase, uSunVis;
  float h13(vec3 p){ p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
  void main(){
    vec3 d = normalize(vDir); float h = d.y;
    float s = max(dot(d, uSunDir), 0.);
    // gradient: horizon -> mid -> top, the horizon warmed toward the sun
    vec3 hor = mix(uHorizon, uGlow, pow(s, 2.2) * 0.85);
    vec3 col = mix(hor, uMid, smoothstep(0.0, 0.32, h));
    col = mix(col, uTop, smoothstep(0.25, 0.9, h));
    col = mix(col, uGround, (1.0 - smoothstep(-0.22, 0.0, h)));
    // sun: disc, halo, broad scattering lobe
    col += uSunDisc * (pow(s, 1800.) * 1.0 + pow(s, 90.) * 0.075 + pow(s, 14.) * 0.024 + pow(s, 3.) * 0.0045);
    if (h > 0.0) {
      // stars: hashed cells, each with a jittered point, size, brightness and twinkle; fade toward the horizon and behind the moon
      if (uStars > 0.01) {
        vec3 sd = uStarRot * d, p = sd * 85., ip = floor(p), fp = fract(p) - 0.5;
        float hs = h13(ip);
        vec3 off = vec3(h13(ip + 7.1), h13(ip + 13.7), h13(ip + 3.3)) - 0.5;
        float star = step(0.982, hs) * (1.0 - smoothstep(0.0, 0.14 + 0.18 * fract(hs * 13.7), length(fp - off * 0.55)));
        star *= (0.35 + 0.9 * fract(hs * 7.7)) * (0.78 + 0.22 * sin(uTime * (1.6 + 3.0 * fract(hs * 5.3)) + hs * 60.));
        vec4 gn = texture2D(tNoise, sd.xz * 0.6 + sd.y * 0.3);
        float band = exp(-pow(dot(sd, normalize(vec3(0.3, 0.8, 0.5))) * 3.2, 2.)) * (0.35 + 0.9 * gn.r * gn.g);
        col += (vec3(0.8, 0.88, 1.0) * star * 2.4 + vec3(0.35, 0.42, 0.7) * band * 0.06) * uStars * smoothstep(0.0, 0.18, h);
      }
      // moon: a lit sphere seen from the earth; the terminator follows the phase, dark maria from the noise texture
      float md = dot(d, uMoonDir);
      if (uMoonLight > 0.001 && md > 0.9985) {
        vec3 up = abs(uMoonDir.y) > 0.99 ? vec3(1, 0, 0) : vec3(0, 1, 0), mx = normalize(cross(uMoonDir, up)), my = cross(mx, uMoonDir);
        vec2 q = vec2(dot(d, mx), dot(d, my)) / 0.0270;                       // disc radius ~1.5 degrees (a little generous)
        float r2 = dot(q, q);
        if (r2 < 1.0) {
          vec3 nrm = vec3(q, sqrt(1. - r2));
          float ph = 6.28318 * uMoonPhase; vec3 ld = vec3(sin(ph), 0., -cos(ph));
          float lit = smoothstep(-0.05, 0.12, dot(nrm, ld));
          float maria = 0.72 + 0.28 * texture2D(tNoise, q * 0.18 + 0.5).b;
          col = mix(col, uMoonColor * 2.4 * maria, lit * 0.95 + 0.04);
        }
      }
      col += uMoonColor * (pow(max(md, 0.), 220.) * 0.16 + pow(max(md, 0.), 24.) * 0.03) * uMoonLight;          // moon halo
      // clouds: cumulus deck (lit toward the sun) + cirrus
      vec2 wind = vec2(uTime * uSpeed, uTime * uSpeed * 0.4);
      vec2 uv = d.xz / (h + 0.16) * 0.55 + wind;
      float dens = texture2D(tNoise, uv * 0.28).r * 0.66 + texture2D(tNoise, uv * 0.9 + 7.).g * 0.34;
      float cov = smoothstep(uCover, uCover + 0.22, dens);
      vec2 sdir = normalize(uSunDir.xz + 1e-4);
      float litd = texture2D(tNoise, (uv + sdir * 0.09) * 0.28).r * 0.66 + texture2D(tNoise, (uv + sdir * 0.09) * 0.9 + 7.).g * 0.34;
      float shade = clamp(0.55 + (dens - litd) * 4.0, 0., 1.);
      vec3 cc = mix(uCloudShadow, uCloudLit, shade);
      cc += uSunDisc * 0.012 * pow(s, 4.) * (1.0 - cov * 0.4);                // silver / gold lining toward the sun
      cc += uMoonColor * pow(max(md, 0.), 6.) * 0.08 * uMoonLight;
      cc = mix(cc, uCloudShadow * 0.8, smoothstep(0.55, 1.0, cov) * (1.0 - shade) * 0.5);
      col = mix(col, cc, cov * smoothstep(0.004, 0.2, h) * 0.9);
      vec2 uv2 = d.xz / (h + 0.35) * vec2(0.22, 1.1) + wind * 0.5;
      float ci = smoothstep(0.5, 0.95, texture2D(tNoise, uv2 * 0.32 + 3.).b * 0.7 + texture2D(tNoise, uv2 * 1.1).a * 0.3) * 0.38 * smoothstep(0.05, 0.4, h);
      col = mix(col, mix(uCloudLit, vec3(1.0), 0.3), ci * (0.6 + 0.8 * pow(s, 2.)) * (0.2 + 0.8 * uSunVis));
    }
    gl_FragColor = vec4(col, 1.0);
  }`;

export function createDynamicSky({ noise = createNoiseTexture(256, 3) } = {}) {
  const U = {
    tNoise: { value: noise }, uStarRot: { value: new THREE.Matrix3() },
    uSunDir: { value: new THREE.Vector3(0, 1, 0) }, uSunDisc: { value: new THREE.Color() }, uMoonDir: { value: new THREE.Vector3(0, -1, 0) }, uMoonColor: { value: new THREE.Color() },
    uTop: { value: new THREE.Color() }, uMid: { value: new THREE.Color() }, uHorizon: { value: new THREE.Color() }, uGlow: { value: new THREE.Color() }, uGround: { value: new THREE.Color() },
    uCloudLit: { value: new THREE.Color() }, uCloudShadow: { value: new THREE.Color() },
    uTime: { value: 0 }, uCover: { value: 0.45 }, uSpeed: { value: 0.0035 }, uStars: { value: 0 }, uMoonLight: { value: 0 }, uMoonPhase: { value: 0.5 }, uSunVis: { value: 1 },
  };
  const mat = new THREE.ShaderMaterial({ side: THREE.BackSide, depthWrite: false, fog: false, uniforms: U, vertexShader: VERT, fragmentShader: FRAG });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), mat);
  mesh.scale.setScalar(900); mesh.frustumCulled = false; mesh.renderOrder = -1; mesh.name = 'sky';
  const axis = new THREE.Vector3(), tmp = new THREE.Matrix4();
  return {
    mesh, material: mat, uniforms: U,
    /** @param S atmosphere state  @param starAngle radians of sidereal rotation  @param latitude degrees */
    setState(S, starAngle = 0, latitude = 35.5) {
      U.uSunDir.value.copy(S.sunDir); U.uMoonDir.value.copy(S.moonDir);
      U.uSunDisc.value.copy(S.sunColor).multiplyScalar(22 * Math.min(1, Math.max(0, (S.sunElev + 1.5) / 3)) * (1 - 0.8 * (S.weather?.cloud ?? 0)));
      U.uMoonColor.value.copy(S.moonColor); U.uMoonLight.value = Math.min(1, S.moonIntensity / 0.9) * Math.min(1, Math.max(0, (S.moonElev + 2) / 6));
      U.uMoonPhase.value = S.moonPhase; U.uSunVis.value = Math.min(1, Math.max(0, (S.sunElev + 6) / 14));
      for (const [k, u] of [['top', 'uTop'], ['mid', 'uMid'], ['horizon', 'uHorizon'], ['glow', 'uGlow'], ['ground', 'uGround']]) U[u].value.copy(S.sky[k]);
      U.uCloudLit.value.copy(S.cloud.lit); U.uCloudShadow.value.copy(S.cloud.shadow); U.uCover.value = S.cloud.cover; U.uSpeed.value = S.cloud.speed; U.uStars.value = S.stars;
      // stars turn about the celestial pole (tilted from the zenith by the latitude); north is -z
      const lat = latitude * Math.PI / 180; axis.set(0, Math.sin(lat), -Math.cos(lat)).normalize();
      U.uStarRot.value.setFromMatrix4(tmp.makeRotationAxis(axis, starAngle));
    },
    update(camera, t) { mesh.position.copy(camera.position); U.uTime.value = t; },
  };
}
