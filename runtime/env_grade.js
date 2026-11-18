// Colour grading pass (display-referred, after tone mapping): white balance, lift / gain / gamma, contrast around a pivot, saturation + vibrance,
// shadow / highlight split toning, faded blacks, radial chromatic aberration, vignette and animated film grain. Every parameter is a uniform
// driven by the atmosphere state, so the grade follows the time of day, the season and the weather.
import * as THREE from 'three';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';

const FRAG = `
  varying vec2 vUv;
  uniform sampler2D tDiffuse; uniform vec2 uRes;
  uniform float uTime, uSat, uVibrance, uContrast, uPivot, uTemp, uTint, uGamma, uSplit, uFade, uVignette, uGrain, uAberration;
  uniform vec3 uLift, uGain, uShadowTint, uHighlightTint;
  float h12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
  void main(){
    vec2 q = vUv - 0.5; vec2 qa = q * vec2(uRes.x / uRes.y, 1.0); float r2 = dot(qa, qa);
    vec2 off = q * uAberration * r2 * 6.0;                                       // radial chromatic aberration: zero in the centre
    vec3 c = vec3(texture2D(tDiffuse, vUv + off).r, texture2D(tDiffuse, vUv).g, texture2D(tDiffuse, vUv - off).b);
    // white balance: temperature (blue <-> orange) and tint (green <-> magenta)
    c *= vec3(1.0 + 0.45 * uTemp, 1.0 - 0.25 * uTint - 0.06 * abs(uTemp), 1.0 - 0.45 * uTemp);
    // lift (blacks), gain (whites), gamma (mids)
    c = pow(max(c * uGain + uLift, 0.0), vec3(1.0 / uGamma));
    // contrast around a pivot, then a soft shoulder so highlights do not clip harshly
    c = (c - uPivot) * uContrast + uPivot; c = max(c, 0.0);
    c = c / (1.0 + max(c - 0.92, 0.0) * 0.6);
    // saturation + vibrance (vibrance lifts the dull colours more than the vivid ones)
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)), sat = (mx - mn) / (mx + 1e-4);
    c = mix(vec3(l), c, uSat + uVibrance * (1.0 - sat));
    // split toning: tint the shadows and the highlights independently
    float ws = 1.0 - smoothstep(0.12, 0.55, l), wh = smoothstep(0.42, 0.9, l);
    c = mix(c, c * uShadowTint, ws * uSplit); c = mix(c, c * uHighlightTint, wh * uSplit);
    // faded blacks, vignette (slightly cooler and darker at the corners), film grain (stronger in the shadows)
    c = c * (1.0 - uFade) + uFade * 0.5 * (1.0 - l);
    float v = 1.0 - uVignette * smoothstep(0.22, 0.85, sqrt(r2) * 1.25);
    c *= v; c = mix(c, c * vec3(0.94, 0.98, 1.06), (1.0 - v) * 1.2);
    c += (h12(vUv * uRes + fract(uTime) * 91.7) - 0.5) * uGrain * (1.0 - l * 0.55);
    gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
  }`;

export function createGradePass() {
  const U = {
    tDiffuse: { value: null }, uRes: { value: new THREE.Vector2(1280, 800) }, uTime: { value: 0 },
    uSat: { value: 1.1 }, uVibrance: { value: 0.2 }, uContrast: { value: 1.05 }, uPivot: { value: 0.46 }, uTemp: { value: 0 }, uTint: { value: 0 }, uGamma: { value: 1.0 },
    uSplit: { value: 0.6 }, uFade: { value: 0.01 }, uVignette: { value: 0.3 }, uGrain: { value: 0.02 }, uAberration: { value: 0.0007 },
    uLift: { value: new THREE.Vector3(0.005, 0.004, 0.003) }, uGain: { value: new THREE.Vector3(1.03, 1, 0.97) },
    uShadowTint: { value: new THREE.Vector3(0.88, 0.95, 1.1) }, uHighlightTint: { value: new THREE.Vector3(1.08, 1, 0.9) },
  };
  const material = new THREE.ShaderMaterial({ uniforms: U, vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }', fragmentShader: FRAG });
  const pass = new ShaderPass(material);
  return {
    pass, uniforms: U,
    /** @param g atmosphere grade: { sat, contrast, temp, tint, lift, gain, shadow, highlight, split, vignette, grain, fade, aberration, vibrance } */
    apply(g) {
      U.uSat.value = g.sat; U.uContrast.value = g.contrast; U.uTemp.value = g.temp; U.uTint.value = g.tint ?? 0; U.uSplit.value = g.split;
      U.uVignette.value = g.vignette; U.uGrain.value = g.grain; U.uFade.value = g.fade; U.uAberration.value = g.aberration; U.uVibrance.value = g.vibrance;
      U.uLift.value.fromArray(g.lift); U.uGain.value.fromArray(g.gain); U.uShadowTint.value.fromArray(g.shadow); U.uHighlightTint.value.fromArray(g.highlight);
    },
    setSize(w, h) { U.uRes.value.set(w, h); },
    update(t) { U.uTime.value = t; },
  };
}
