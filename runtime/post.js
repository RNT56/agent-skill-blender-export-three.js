// Post-processing: MSAA HDR render target -> bloom (sun, glitter, bright sky) -> ACES tonemap + sRGB -> colour grade (saturation, contrast,
// warm/cool split tone, vignette). Everything before the OutputPass is scene-linear HDR, so the water/sky shaders can exceed 1.0.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const GRADE = {
  uniforms: { tDiffuse: { value: null }, uSat: { value: 1.12 }, uContrast: { value: 1.05 }, uVignette: { value: 0.3 },
              uWarm: { value: new THREE.Vector3(1.04, 1.0, 0.94) }, uCool: { value: new THREE.Vector3(0.94, 0.99, 1.06) } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `
    varying vec2 vUv; uniform sampler2D tDiffuse; uniform float uSat, uContrast, uVignette; uniform vec3 uWarm, uCool;
    void main(){
      vec3 c = texture2D(tDiffuse, vUv).rgb;
      float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
      c = mix(vec3(l), c, uSat);                                   // saturation
      c = (c - 0.5) * uContrast + 0.5;                              // contrast around mid grey
      c *= mix(uCool, uWarm, smoothstep(0.15, 0.75, l));            // split tone: cool shadows, warm highlights
      vec2 q = vUv - 0.5; float v = 1.0 - uVignette * smoothstep(0.25, 0.85, length(q * vec2(1.15, 1.0)) * 1.25);
      gl_FragColor = vec4(max(c * v, 0.0), 1.0);
    }`,
};

export function createPost(renderer, scene, camera, { bloom = 0.32, radius = 0.55, threshold = 1.05, samples = 4, bloomScale = 0.5, grade = {} } = {}) {
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const rt = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples });
  const composer = new EffectComposer(renderer, rt);
  composer.addPass(new RenderPass(scene, camera));
  const bloomPass = new UnrealBloomPass(new THREE.Vector2(size.x / 2, size.y / 2), bloom, radius, threshold);
  // the bloom blur chain is the most expensive part of the stack and is intentionally soft: run it at (bloomScale x) the usual half-res
  const baseSetSize = bloomPass.setSize.bind(bloomPass);
  bloomPass.setSize = (w, h) => baseSetSize(Math.max(8, Math.round(w * bloomScale)), Math.max(8, Math.round(h * bloomScale)));
  bloomPass.setSize(size.x, size.y);
  composer.addPass(bloomPass);
  composer.addPass(new OutputPass());
  const gradePass = new ShaderPass(GRADE);
  Object.entries(grade).forEach(([k, v]) => { if (gradePass.uniforms[k]) { gradePass.uniforms[k].value = v?.isVector3 ? v : v; } });
  composer.addPass(gradePass);
  return {
    composer, bloomPass, gradePass,
    render(dt) { composer.render(dt); },
    setPixelRatio(r) { composer.setPixelRatio(r); },
    setSize(w, h) { composer.setSize(w, h); },
  };
}
