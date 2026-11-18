// Tree wind + leaf translucency, injected into the glTF materials with onBeforeCompile (works with InstancedMesh).
// glTF cannot carry translucency or wind, so they live here, in the engine.
import * as THREE from 'three';

export function createFoliageUniforms(look) {
  const c = a => new THREE.Color(a[0], a[1], a[2]);
  return {
    uTime: { value: 0 }, uWindDir: { value: new THREE.Vector2(1.0, 0.35) }, uWindStr: { value: 1.0 },
    uLightDirView: { value: new THREE.Vector3(0, 1, 0) }, uSunColor: { value: c(look.sun.color) },
    uTrans: { value: look.foliage?.translucency ?? 0.9 }, uPow: { value: look.foliage?.translucency_power ?? 3.0 },
  };
}

/** leaf: adds flutter + translucency (alpha-cut cards). Bark/trunk: sway only. treeHeight: metres (sway scales with (y/height)^2). */
export function patchTreeMaterial(mat, U, { leaf = false, treeHeight = 8.0, amplitude = 0.42 } = {}) {
  const prev = mat.onBeforeCompile;
  mat.onBeforeCompile = (shader, renderer) => {
    prev?.(shader, renderer);
    Object.assign(shader.uniforms, U);
    shader.uniforms.uTreeH = { value: treeHeight };
    shader.uniforms.uAmp = { value: amplitude };
    shader.uniforms.uLeaf = { value: leaf ? 1.0 : 0.0 };
    shader.vertexShader = `
      uniform float uTime, uWindStr, uTreeH, uAmp, uLeaf; uniform vec2 uWindDir;
    ` + shader.vertexShader.replace('#include <begin_vertex>', `
      #include <begin_vertex>
      {
        float hgt = max(position.y, 0.0);
        float kk = clamp(hgt / uTreeH, 0.0, 1.2); kk *= kk;
        #ifdef USE_INSTANCING
          mat3 im = mat3(instanceMatrix);
          vec3 ip = instanceMatrix[3].xyz;
          vec3 wl = transpose(im) * vec3(uWindDir.x, 0.0, uWindDir.y) / max(dot(im[0], im[0]), 1e-4);   // world wind in tree-local space
        #else
          vec3 ip = vec3(0.0); vec3 wl = vec3(uWindDir.x, 0.0, uWindDir.y);
        #endif
        float ph = ip.x * 0.21 + ip.z * 0.17;
        float slow = 0.55 + 0.45 * sin(uTime * 0.8 + ph + hgt * 0.10);
        float fast = sin(uTime * 2.1 + ph * 1.7 + hgt * 0.35) * 0.35;
        transformed += wl * uAmp * uWindStr * (slow + fast) * kk;
        transformed += uLeaf * 0.045 * uWindStr * kk * vec3(sin(uTime * 6.3 + dot(position, vec3(7.1, 3.3, 5.2))),
                                                      sin(uTime * 5.1 + dot(position, vec3(2.9, 6.1, 4.3))),
                                                      sin(uTime * 7.7 + dot(position, vec3(5.3, 1.7, 8.1))));
      }`);
    if (leaf) {
      shader.fragmentShader = 'uniform vec3 uLightDirView, uSunColor; uniform float uTrans, uPow;\n' +
        shader.fragmentShader.replace('#include <opaque_fragment>', `
          float lback = pow(clamp(-dot(normalize(vViewPosition), uLightDirView), 0.0, 1.0), uPow);
          outgoingLight += diffuseColor.rgb * uSunColor * lback * uTrans;
          #include <opaque_fragment>`);
    }
  };
  mat.needsUpdate = true;
}
