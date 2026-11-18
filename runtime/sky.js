// Procedural autumn sky: 3-stop gradient with a warm sun-side horizon glow, sun disc + halo, two cloud decks (lit cumulus with sun-facing
// rims and orange undersides, high cirrus streaks). Follows the camera; values are scene-linear HDR so bloom can pick up the sun.
import * as THREE from 'three';

export function createSky(look, sunDir) {
  const c = a => new THREE.Color(a[0], a[1], a[2]);
  const cl = look.clouds ?? { cover: 0.48, lit: [1.0, 0.8, 0.6], shadow: [0.35, 0.36, 0.5], speed: 0.004 };
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: {
      uSunDir: { value: sunDir.clone() }, uSunColor: { value: c(look.sun.color) }, uTime: { value: 0 },
      uTop: { value: c(look.sky.top ?? [0.03, 0.09, 0.34]) }, uMid: { value: c(look.sky.mid ?? [0.1, 0.26, 0.5]) },
      uHorizon: { value: c(look.sky.color) }, uGlow: { value: c(look.sky.glow ?? look.sun.color) },
      uGround: { value: c(look.fog ?? look.sky.color) },
      uCover: { value: cl.cover }, uCloudLit: { value: c(cl.lit) }, uCloudShadow: { value: c(cl.shadow) }, uSpeed: { value: cl.speed },
    },
    vertexShader: `varying vec3 vDir; void main(){ vDir = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); gl_Position.z = gl_Position.w; }`,
    fragmentShader: `
      varying vec3 vDir; uniform vec3 uSunDir, uSunColor, uTop, uMid, uHorizon, uGlow, uGround, uCloudLit, uCloudShadow; uniform float uTime, uCover, uSpeed;
      float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float vn(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
        return mix(mix(h21(i),h21(i+vec2(1,0)),f.x), mix(h21(i+vec2(0,1)),h21(i+vec2(1,1)),f.x), f.y); }
      float fb(vec2 p){ float s=0., a=.5; for(int i=0;i<6;i++){ s+=a*vn(p); p=p*2.03+vec2(7.1,3.7); a*=.5; } return s; }
      void main(){
        vec3 d = normalize(vDir); float h = d.y;
        float s = max(dot(d, uSunDir), 0.);
        // gradient: horizon -> mid -> top, horizon warmed toward the sun
        vec3 hor = mix(uHorizon, uGlow, pow(s, 2.2) * 0.85);
        vec3 col = mix(hor, uMid, smoothstep(0.0, 0.32, h));
        col = mix(col, uTop, smoothstep(0.25, 0.9, h));
        col = mix(col, uGround, smoothstep(0.0, -0.22, h));
        // sun disc, halo, and a broad scattering lobe
        col += uSunColor * (pow(s, 1800.) * 22. + pow(s, 90.) * 1.6 + pow(s, 14.) * 0.5 + pow(s, 3.) * 0.10);
        if (h > 0.004) {
          vec2 wind = vec2(uTime * uSpeed, uTime * uSpeed * 0.4);
          // cumulus deck
          vec2 uv = d.xz / (h + 0.16) * 0.55 + wind;
          float dens = fb(uv * 2.2);
          float cov = smoothstep(uCover, uCover + 0.22, dens);
          vec2 sdir = normalize(uSunDir.xz + 1e-4);
          float lit = fb(uv * 2.2 + sdir * 0.09);                          // density toward the sun: thinner there = this point is a lit rim
          float shade = clamp(0.55 + (dens - lit) * 4.0, 0., 1.);
          vec3 cc = mix(uCloudShadow, uCloudLit, shade);
          cc += uSunColor * pow(s, 4.) * 0.35 * (1.0 - cov * 0.4);         // silver/gold lining toward the sun
          cc = mix(cc, uCloudShadow * 0.8, smoothstep(0.55, 1.0, cov) * (1.0 - shade) * 0.5);
          float vis = cov * smoothstep(0.004, 0.2, h) * 0.9;
          col = mix(col, cc, vis);
          // high cirrus streaks
          vec2 uv2 = d.xz / (h + 0.35) * vec2(0.22, 1.1) + wind * 0.5;
          float ci = smoothstep(0.5, 0.95, fb(uv2 * 3.0)) * 0.38 * smoothstep(0.05, 0.4, h);
          col = mix(col, mix(uCloudLit, vec3(1.0), 0.3), ci * (0.6 + 0.8 * pow(s, 2.)));
        }
        gl_FragColor = vec4(col, 1.0);
      }`,
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), mat);
  mesh.scale.setScalar(900);
  mesh.frustumCulled = false;
  mesh.renderOrder = -1;
  return {
    mesh, material: mat,
    update(camera, t) { mesh.position.copy(camera.position); mat.uniforms.uTime.value = t; },
  };
}
