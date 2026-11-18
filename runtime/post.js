// Post-processing: MSAA HDR render target -> bloom (sun, glitter, bright sky) -> ACES tonemap + sRGB -> full colour grade (env_grade.js: white
// balance, lift/gain/gamma, contrast, saturation/vibrance, split toning, aberration, vignette, grain). Everything before the OutputPass is scene-linear HDR, so the water/sky shaders can exceed 1.0.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { createGradePass } from './env_grade.js';

export function createPost(renderer, scene, camera, { bloom = 0.32, radius = 0.55, threshold = 1.05, samples = 4, bloomScale = 0.5, depthTexture = false, grade = {} } = {}) {
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const rt = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples, depthTexture: depthTexture ? new THREE.DepthTexture(size.x, size.y) : null });
  const composer = new EffectComposer(renderer, rt);
  composer.addPass(new RenderPass(scene, camera));
  const bloomPass = new UnrealBloomPass(new THREE.Vector2(size.x / 2, size.y / 2), bloom, radius, threshold);
  // the bloom blur chain is the most expensive part of the stack and is intentionally soft: run it at (bloomScale x) the usual half-res
  const baseSetSize = bloomPass.setSize.bind(bloomPass);
  bloomPass.setSize = (w, h) => baseSetSize(Math.max(8, Math.round(w * bloomScale)), Math.max(8, Math.round(h * bloomScale)));
  bloomPass.setSize(size.x, size.y);
  composer.addPass(bloomPass);
  composer.addPass(new OutputPass());
  const gradeFx = createGradePass(), gradePass = gradeFx.pass;
  Object.entries(grade).forEach(([k, v]) => { if (gradeFx.uniforms[k]) gradeFx.uniforms[k].value = v; });       // legacy {uSat, uContrast, uVignette} options still work
  gradeFx.setSize(size.x, size.y);
  composer.addPass(gradePass);
  const dbs = new THREE.Vector2(), syncGrade = () => { renderer.getDrawingBufferSize(dbs); gradeFx.setSize(dbs.x, dbs.y); };
  return {
    composer, bloomPass, gradePass, grade: gradeFx,
    /** Insert a pass right after the scene render (index 1). The pass sees the scene depth as readBuffer.depthTexture when depthTexture:true. */
    insertPass(pass, index = 1) { composer.insertPass(pass, index); },
    render(dt) { gradeFx.update(performance.now() / 1000); composer.render(dt); },
    setPixelRatio(r) { composer.setPixelRatio(r); syncGrade(); },
    setSize(w, h) { composer.setSize(w, h); syncGrade(); },
  };
}
