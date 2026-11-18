// Tree wind + leaf translucency, injected into the glTF materials with onBeforeCompile (works with InstancedMesh).
// glTF cannot carry translucency or wind, so they live here, in the engine.
import * as THREE from 'three';

export function createFoliageUniforms(look) {
  const c = a => new THREE.Color(a[0], a[1], a[2]);
  return {
    uTime: { value: 0 }, uWindDir: { value: new THREE.Vector2(1.0, 0.35) }, uWindStr: { value: 1.0 },
    uLightDirView: { value: new THREE.Vector3(0, 1, 0) }, uSunColor: { value: c(look.sun.color) },
    uTrans: { value: look.foliage?.translucency ?? 0.9 }, uPow: { value: look.foliage?.translucency_power ?? 3.0 },
    kinds: {},                                                              // per tree kind seasonal uniforms (see leafKind)
  };
}

/** Seasonal uniforms for one kind of tree (maple, ginkgo, sakura, evergreen...): leaf recolour mix + colour, and the fraction of leaves still on the tree.
 *  The objects are shared with every material patched with that kind, so writing .value updates the whole species at once. */
export function leafKind(U, kind) {
  return (U.kinds[kind] ??= { uLeafMix: { value: 0 }, uLeafColor: { value: new THREE.Vector3(1, 1, 1) }, uLeafKeep: { value: 1 } });
}

/** the shared vertex sway of a tree (also used by its shadow depth pass); expects uTime, uWindStr, uTreeH, uAmp, uLeaf, uWindDir and declares vLeafWorld's value */
const WIND_VERTEX = `
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
        #ifdef USE_INSTANCING
          vLeafWorld = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;
        #else
          vLeafWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
        #endif
      }
`;

/** leaf fall: clumps of leaves vanish as the season turns (fragment; needs vLeafWorld, uLeafKeep) */
const LEAF_FALL = `
  vec3 lcell = floor(vLeafWorld * 2.4);
  if (fract(sin(dot(lcell, vec3(12.9898, 78.233, 37.719))) * 43758.5453) > uLeafKeep) discard;
`;

/** leaf: adds flutter + translucency (alpha-cut cards). Bark/trunk: sway only. treeHeight: metres (sway scales with (y/height)^2). */
export function patchTreeMaterial(mat, U, { leaf = false, treeHeight = 8.0, amplitude = 0.42, seasonKind = null } = {}) {
  const prev = mat.onBeforeCompile, K = seasonKind ? leafKind(U, seasonKind) : null;
  const prevKey = mat.customProgramCacheKey();
  mat.customProgramCacheKey = () => prevKey + '|tree' + (leaf ? 'L' : 'B') + (K ? 's' : '');                  // a unique program key per patch variant (three keys on onBeforeCompile.toString())
  mat.onBeforeCompile = (shader, renderer) => {
    prev?.(shader, renderer);
    Object.assign(shader.uniforms, U);
    shader.uniforms.uTreeH = { value: treeHeight };
    shader.uniforms.uAmp = { value: amplitude };
    shader.uniforms.uLeaf = { value: leaf ? 1.0 : 0.0 };
    if (K) Object.assign(shader.uniforms, K);
    shader.vertexShader = `
      uniform float uTime, uWindStr, uTreeH, uAmp, uLeaf; uniform vec2 uWindDir; varying vec3 vLeafWorld;
    ` + shader.vertexShader.replace('#include <begin_vertex>', `
      #include <begin_vertex>
      ${WIND_VERTEX}`);
    if (leaf) {
      shader.fragmentShader = 'uniform vec3 uLightDirView, uSunColor; uniform float uTrans, uPow;' + (K ? ' uniform float uLeafMix, uLeafKeep; uniform vec3 uLeafColor; varying vec3 vLeafWorld;' : '') + '\n' +
        shader.fragmentShader.replace('#include <color_fragment>', K ? `
          #include <color_fragment>
          {
            float ll = dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722));                  // recolour the leaves toward the season's colour, keeping their shading
            diffuseColor.rgb = mix(diffuseColor.rgb, vec3(ll) * uLeafColor * 1.9, uLeafMix);
            ${LEAF_FALL}                                                                          // leaf fall: clumps of leaves disappear as the season turns
          }` : '#include <color_fragment>').replace('#include <opaque_fragment>', `
          float lback = pow(clamp(-dot(normalize(vViewPosition), uLightDirView), 0.0, 1.0), uPow);
          outgoingLight += diffuseColor.rgb * uSunColor * lback * uTrans;
          #include <opaque_fragment>`);
    }
  };
  // the shadow pass gets the same sway and leaf fall (the stock depth material would cast a full, motionless canopy: bare winter trees would still shade the ground)
  const depth = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, side: THREE.DoubleSide });
  depth.map = mat.map; depth.alphaTest = mat.alphaTest;
  const dk = depth.customProgramCacheKey(); depth.customProgramCacheKey = () => dk + '|treeDepth' + (leaf ? 'L' : 'B') + (K ? 's' : '');
  depth.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, U);
    shader.uniforms.uTreeH = { value: treeHeight }; shader.uniforms.uAmp = { value: amplitude }; shader.uniforms.uLeaf = { value: leaf ? 1.0 : 0.0 };
    if (K) Object.assign(shader.uniforms, K);
    shader.vertexShader = `
      uniform float uTime, uWindStr, uTreeH, uAmp, uLeaf; uniform vec2 uWindDir; varying vec3 vLeafWorld;
    ` + shader.vertexShader.replace('#include <begin_vertex>', `
      #include <begin_vertex>
      ${WIND_VERTEX}`);
    if (leaf && K) shader.fragmentShader = 'uniform float uLeafKeep; varying vec3 vLeafWorld;\n' + shader.fragmentShader.replace('#include <map_fragment>', `#include <map_fragment>\n${LEAF_FALL}`);
  };
  mat.customDepthMaterial = depth;
  mat.needsUpdate = true;
}
