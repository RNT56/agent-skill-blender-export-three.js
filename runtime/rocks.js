// Rocks: procedural boulders and outcrops that break up the silhouette of cliffs, steep hills and mountains, sit in scree at the foot of escarpments and ring building yards.
// A terrain with a good rock texture still has a smooth outline; real cliffs are made of blocks. Each rock is a low-poly, angular, noise-displaced body (several variants, two
// levels of detail) drawn as instances and shaded with the SAME biplanar rock materials as the terrain (world-space projection), so a rock never looks pasted on: its texture
// continues into the ground's. The base of every rock is darkened (contact occlusion) and sunk into the ground by the placement.
import * as THREE from 'three';
import { mulberry32 } from './noise.js';
import { ROCK_SAMPLE_GLSL } from './terrain.js';

const hash3 = (x, y, z, s) => { let h = (Math.imul(x | 0, 73856093) ^ Math.imul(y | 0, 19349663) ^ Math.imul(z | 0, 83492791) ^ Math.imul(s | 0, 2654435761)) >>> 0; h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0; return (h ^ (h >>> 16)) / 4294967296; };
function noise3(x, y, z, s) {
  const ix = Math.floor(x), iy = Math.floor(y), iz = Math.floor(z), fx = x - ix, fy = y - iy, fz = z - iz, u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy), w = fz * fz * (3 - 2 * fz);
  const l = (a, b, t) => a + (b - a) * t;
  return l(l(l(hash3(ix, iy, iz, s), hash3(ix + 1, iy, iz, s), u), l(hash3(ix, iy + 1, iz, s), hash3(ix + 1, iy + 1, iz, s), u), v), l(l(hash3(ix, iy, iz + 1, s), hash3(ix + 1, iy, iz + 1, s), u), l(hash3(ix, iy + 1, iz + 1, s), hash3(ix + 1, iy + 1, iz + 1, s), u), v), w);
}

/**
 * One rock body: an icosphere pushed out by 3D noise, chiselled into planes (vertices snap toward a few random plane directions), flattened underneath. Flat shaded.
 * @param seed variant seed   @param detail icosphere subdivision (2 = 320 faces, 1 = 80)   @returns THREE.BufferGeometry (unit size, origin at the centre)
 */
export function createRockGeometry(seed = 1, detail = 2) {
  const rng = mulberry32(seed * 977 + 13), g = new THREE.IcosahedronGeometry(1, detail), pos = g.attributes.position;
  const planes = Array.from({ length: 5 }, () => new THREE.Vector3(rng() - 0.5, rng() - 0.5, rng() - 0.5).normalize());
  const stretch = [0.85 + rng() * 0.5, 0.65 + rng() * 0.35, 0.85 + rng() * 0.5], v = new THREE.Vector3(), s0 = seed * 7.1;
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).normalize();
    let r = 1 + (noise3(v.x * 1.6 + s0, v.y * 1.6, v.z * 1.6, seed) - 0.5) * 0.55 + (noise3(v.x * 4.1, v.y * 4.1 + s0, v.z * 4.1, seed + 5) - 0.5) * 0.16;
    for (const p of planes) { const d = v.dot(p); if (d > 0.62) r = Math.min(r, 0.86 / d); }                   // chisel: a flat facet where the direction nears a plane normal
    v.multiplyScalar(r).multiply(new THREE.Vector3(stretch[0], stretch[1], stretch[2]));
    if (v.y < -0.35) v.y = -0.35 - (v.y + 0.35) * 0.15;                                                         // flat-ish underside, so it sits on the ground
    pos.setXYZ(i, v.x, v.y, v.z);
  }
  g.computeVertexNormals();
  g.deleteAttribute('uv');
  return g;
}

/**
 * @param scene     the scene
 * @param rocks     [{x, y, z, rot, scale, sx, sy, sz, nx, ny, nz, mat, variant, tint}] (n = the up direction the rock leans toward, mat = index of the six rock materials, tint = brightness multiplier)
 * @param uniforms  the terrain's uniforms (they carry the rock texture arrays, layer and tile tables): the rocks share them by reference
 * @param lodDist   distances (m, x lodScale) where LOD1 takes over and where rocks stop being drawn
 */
export class RockField {
  constructor({ scene, rocks, uniforms, lodDist = [60, 170], variants = 5, castShadowLod0 = true }) {
    this.rocks = rocks; this.lodDist = lodDist; this.nv = variants;
    this.material = rockMaterial(uniforms);
    this.geoms = [0, 1].map(lod => Array.from({ length: variants }, (_, k) => createRockGeometry(k + 1, lod === 0 ? 2 : 1)));
    this.meshes = this.geoms.map((row, lod) => row.map((g, k) => {
      const im = new THREE.InstancedMesh(g, this.material, rocks.length);
      im.count = 0; im.frustumCulled = false; im.castShadow = lod === 0 && castShadowLod0; im.receiveShadow = true; im.name = `rocks_lod${lod}_${k}`;
      im.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      const mat = new THREE.InstancedBufferAttribute(new Float32Array(rocks.length), 1), tint = new THREE.InstancedBufferAttribute(new Float32Array(rocks.length), 1);
      mat.setUsage(THREE.DynamicDrawUsage); tint.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute('aMat', mat); g.setAttribute('aTint', tint);
      scene.add(im); return im;
    }));
    this.frustum = new THREE.Frustum(); this._pv = new THREE.Matrix4(); this._sph = new THREE.Sphere();
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._qy = new THREE.Quaternion(); this._p = new THREE.Vector3(); this._s = new THREE.Vector3(); this._n = new THREE.Vector3(); this._up = new THREE.Vector3(0, 1, 0); this._ay = new THREE.Vector3(0, 1, 0);
    this._t = 0; this._last = new THREE.Vector3(1e9, 0, 1e9); this._ls = 1; this.counts = [0, 0];
  }

  /** @param center the view focus  @param lodScale >= 1 when zoomed out (distances x lodScale) */
  update(camera, dt, force = false, center = null, lodScale = 1) {
    this._t += dt;
    const cp = center ?? camera.position;
    if (!force && this._t < 0.15 && cp.distanceToSquared(this._last) < 1 && Math.abs(lodScale - this._ls) < 0.02) return;
    this._t = 0; this._last.copy(cp); this._ls = lodScale;
    this._pv.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse); this.frustum.setFromProjectionMatrix(this._pv);
    const cnt = [new Array(this.nv).fill(0), new Array(this.nv).fill(0)], far = this.lodDist[1] * lodScale, mid = this.lodDist[0] * lodScale;
    for (let i = 0; i < this.rocks.length; i++) {
      const r = this.rocks[i], dx = r.x - cp.x, dz = r.z - cp.z, d = Math.hypot(dx, dz);
      if (d > far) continue;
      this._sph.center.set(r.x, r.y, r.z); this._sph.radius = r.scale * 1.7 * Math.max(r.sx, r.sy, r.sz);
      if (d > 40 * lodScale && !this.frustum.intersectsSphere(this._sph)) continue;
      const lod = d > mid ? 1 : 0, v = r.variant % this.nv, k = cnt[lod][v]++;
      this._qy.setFromAxisAngle(this._ay, r.rot); this._q.setFromUnitVectors(this._up, this._n.set(r.nx, r.ny, r.nz)).multiply(this._qy);       // spin about its own axis, then lean with the slope
      this._p.set(r.x, r.y, r.z); this._s.set(r.scale * r.sx, r.scale * r.sy, r.scale * r.sz); this._m.compose(this._p, this._q, this._s);
      const im = this.meshes[lod][v], g = this.geoms[lod][v];
      im.setMatrixAt(k, this._m); g.attributes.aMat.array[k] = r.mat; g.attributes.aTint.array[k] = r.tint;
    }
    for (let lod = 0; lod < 2; lod++) for (let v = 0; v < this.nv; v++) {
      const im = this.meshes[lod][v], g = this.geoms[lod][v]; im.count = cnt[lod][v]; im.instanceMatrix.needsUpdate = true; g.attributes.aMat.needsUpdate = true; g.attributes.aTint.needsUpdate = true;
    }
    this.counts = [cnt[0].reduce((a, b) => a + b, 0), cnt[1].reduce((a, b) => a + b, 0)];
  }
}

/** the rock material: standard PBR lighting, albedo / roughness / AO / normal from the terrain's biplanar rock arrays in WORLD space */
function rockMaterial(U) {
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, metalness: 0 });
  mat.onBeforeCompile = shader => {
    for (const k of ['uRAlb', 'uRNor', 'uROrm', 'uRLayer', 'uRTile', 'uRockAlt', 'uSnow']) shader.uniforms[k] = U[k];                  // shared with the terrain: the winter's snow settles on rocks too
    shader.vertexShader = `attribute float aMat; attribute float aTint; varying float vMat; varying float vTint; varying vec3 vRP; varying vec3 vRN; varying float vRY;\n` + shader.vertexShader
      .replace('#include <defaultnormal_vertex>', '#include <defaultnormal_vertex>\n vRN = transpose(mat3(viewMatrix)) * transformedNormal;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vMat = aMat; vTint = aTint; vRY = position.y;
        vec4 rp4 = vec4(transformed, 1.0);
        #ifdef USE_INSTANCING
          rp4 = instanceMatrix * rp4;
        #endif
        vRP = (modelMatrix * rp4).xyz;`);
    shader.fragmentShader = `
      precision highp sampler2DArray;
      varying float vMat; varying float vTint; varying vec3 vRP; varying vec3 vRN; varying float vRY; uniform float uSnow;
      ${ROCK_SAMPLE_GLSL}
    ` + shader.fragmentShader
      .replace('#include <map_fragment>', `
        vec3 rWN = normalize(vRN);
        rockSample(int(vMat + 0.5), vRP, rWN, dFdx(vRP), dFdy(vRP));
        float baseAO = smoothstep(-0.35, 0.25, vRY);                                          // contact occlusion where the rock meets the ground
        diffuseColor.rgb *= rockAlb * vTint * mix(0.55, 1.0, baseAO);
        float rockSnow = uSnow * smoothstep(0.35, 0.8, rWN.y) * (0.8 + 0.2 * baseAO);                    // snow lies on the tops of rocks
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.8, 0.84, 0.92), rockSnow);`)
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = roughness * clamp(rockOrm.g, 0.2, 1.0);')
      .replace('#include <normal_fragment_maps>', 'normal = normalize((viewMatrix * vec4(rockNrm, 0.0)).xyz);')
      .replace('#include <aomap_fragment>', 'reflectedLight.indirectDiffuse *= mix(1.0, rockOrm.r, 0.95) * mix(0.6, 1.0, baseAO);');
  };
  mat.customProgramCacheKey = () => 'rocks_biplanar';
  return mat;
}
