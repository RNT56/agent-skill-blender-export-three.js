// InstancedForest: many copies of one tree species, bucketed into LODs every few frames.
// lods: gltf scenes for LOD0..LODn (each with one or more meshes: bark, leaves, ...). One InstancedMesh per (LOD, mesh part).
import * as THREE from 'three';
import { patchTreeMaterial } from './foliage.js';

export class InstancedForest {
  /**
   * @param lodScenes  [gltf.scene] LOD0..LODn
   * @param lodDist    [d1,d2,d3...]  distance at which LOD1, LOD2... take over (length = lods-1)
   * @param trees      [{x,y,z,rot,scale}]
   * @param uniforms   foliage uniforms (createFoliageUniforms)
   */
  constructor({ scene, lodScenes, lodDist = [32, 70, 130], trees, uniforms, treeHeight = 8, radius = 5, alwaysNear = 70, castShadowLods = 3, seasonKind = null }) {
    this.trees = trees; this.lodDist = lodDist; this.radius = radius; this.alwaysNear = alwaysNear; this.treeHeight = treeHeight;
    this.nl = lodScenes.length;
    this.parts = [];                       // parts[lod] = [InstancedMesh...]
    const patched = new Map();
    lodScenes.forEach((root, li) => {
      const list = [];
      root.updateMatrixWorld(true);
      root.traverse(o => {
        if (!o.isMesh) return;
        let mat = o.material;
        if (!patched.has(mat)) {
          const leaf = mat.alphaTest > 0;
          mat.side = THREE.DoubleSide;
          patchTreeMaterial(mat, uniforms, { leaf, treeHeight, amplitude: leaf ? 0.45 : 0.40, seasonKind });
          patched.set(mat, true);
        }
        const im = new THREE.InstancedMesh(o.geometry, mat, trees.length);
        im.count = 0; im.frustumCulled = false;
        im.castShadow = li < castShadowLods; im.receiveShadow = true;
        im.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        im.name = `${o.name}_inst`;
        scene.add(im);
        list.push(im);
      });
      this.parts.push(list);
    });
    this.frustum = new THREE.Frustum(); this._pv = new THREE.Matrix4(); this._sph = new THREE.Sphere();
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._p = new THREE.Vector3(); this._s = new THREE.Vector3();
    this._e = new THREE.Euler(); this._last = new THREE.Vector3(1e9, 0, 1e9); this._t = 0;
    this.counts = new Array(this.nl).fill(0);
  }

  /** @param center focus point for LOD distances (default: camera). @param lodScale >=1 as the view zooms out: LOD distances x lodScale. */
  update(camera, dt, force = false, center = null, lodScale = 1) {
    this._t += dt;
    const cp = center ?? camera.position;
    if (!force && this._t < 0.12 && cp.distanceToSquared(this._last) < 1 && Math.abs(lodScale - (this._ls ?? 1)) < 0.02) return;
    this._t = 0; this._last.copy(cp); this._ls = lodScale;
    this._pv.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    this.frustum.setFromProjectionMatrix(this._pv);
    const cnt = new Array(this.nl).fill(0);
    for (const t of this.trees) {
      const dx = t.x - cp.x, dz = t.z - cp.z, d = Math.hypot(dx, dz);
      if (d > this.alwaysNear * lodScale) {
        this._sph.center.set(t.x, t.y + this.treeHeight * 0.5 * t.scale, t.z);
        this._sph.radius = this.radius * t.scale * 1.6;
        if (!this.frustum.intersectsSphere(this._sph)) continue;
      }
      let lod = 0;
      while (lod < this.lodDist.length && d > this.lodDist[lod] * lodScale) lod++;
      this._e.set(0, t.rot, 0);
      this._q.setFromEuler(this._e);
      this._p.set(t.x, t.y, t.z);
      this._s.set(t.scale, t.scale * (t.yscale ?? 1), t.scale);
      this._m.compose(this._p, this._q, this._s);
      const k = cnt[lod]++;
      for (const im of this.parts[lod]) im.setMatrixAt(k, this._m);
    }
    for (let l = 0; l < this.nl; l++) {
      for (const im of this.parts[l]) { im.count = cnt[l]; im.instanceMatrix.needsUpdate = true; }
    }
    this.counts = cnt;
  }
}
