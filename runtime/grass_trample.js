// Grass trampling as a PERSISTENT lean field: a small world-space grid around the view focus that remembers where things have walked.
// Pure (no three.js): the grass vertex shader reads it as a 2-channel byte texture, tests read it directly.
//
// Why a field instead of "push every blade away from every unit" in the shader:
//   * a blade is pushed ONE way, decided at its root, so it bends as a whole (no per-vertex direction flips, no hooked tips or starbursts near a unit's centre)
//   * walkers leave a TRAIL: the grass they pressed stays down and springs back over a few seconds, like real tall grass
//   * the direction is physical: grass beside the path is parted sideways, grass under and ahead of the walker is pressed along its heading
//   * cost does not grow with the number of units (no per-vertex loop), so every visible unit can trample
//
// Each cell holds a lean vector L (|L| <= 1) in world xz: the direction the blades there lean, and (by magnitude) how far they are pressed down.
export class TrampleMap {
  /**
   * @param size    cells per side
   * @param texel   metres per cell
   * @param radius  default pusher radius (m)
   * @param recover seconds for the pressed grass to relax by a factor e (plus a slow linear spring so it fully recovers)
   */
  constructor({ size = 256, texel = 0.5, radius = 1.15, recover = 6.5, spring = 0.03 } = {}) {
    this.N = size; this.texel = texel; this.radius = radius; this.recover = recover; this.spring = spring;
    this.lean = new Float32Array(size * size * 2); this._tmp = new Float32Array(size * size * 2);
    this.data = new Uint8Array(size * size * 2).fill(128);                 // 128 = zero lean (the GPU texture)
    this.ox = 0; this.oz = 0;                                              // integer cell coordinates of cell (0,0)
    this.box = { i0: 1, i1: 0, j0: 1, j1: 0 };                             // cells that may be non-zero (empty when i0 > i1)
    this.version = 0; this._prev = new Map();
  }

  /** world x of the map's left edge / z of its top edge, and its extent in metres (the shader's uTrOrigin / uTrExtent) */
  get originX() { return this.ox * this.texel; }
  get originZ() { return this.oz * this.texel; }
  get extent() { return this.N * this.texel; }

  /** centre the map on a world point (snapped to whole cells, so nothing swims); the remembered trail scrolls with the world */
  setCenter(x, z) {
    const N = this.N, nx = Math.round(x / this.texel) - (N >> 1), nz = Math.round(z / this.texel) - (N >> 1);
    if (nx === this.ox && nz === this.oz) return;
    const di = nx - this.ox, dj = nz - this.oz;
    if (this.box.i0 <= this.box.i1) {
      if (Math.abs(di) >= N || Math.abs(dj) >= N) { this.lean.fill(0); this.data.fill(128); this.box = { i0: 1, i1: 0, j0: 1, j1: 0 }; }
      else {
        const src = this.lean, dst = this._tmp; dst.fill(0);
        const i0 = Math.max(0, -di), i1 = Math.min(N, N - di), j0 = Math.max(0, -dj), j1 = Math.min(N, N - dj);
        for (let j = j0; j < j1; j++) for (let i = i0; i < i1; i++) { const d = (j * N + i) * 2, s = ((j + dj) * N + i + di) * 2; dst[d] = src[s]; dst[d + 1] = src[s + 1]; }
        this.lean = dst; this._tmp = src;
        this.box = { i0: Math.max(0, this.box.i0 - di), i1: Math.min(N - 1, this.box.i1 - di), j0: Math.max(0, this.box.j0 - dj), j1: Math.min(N - 1, this.box.j1 - dj) };
        this._encodeAll();
      }
    }
    this.ox = nx; this.oz = nz; this.version++;                            // pusher sweeps are in world space, so they stay valid across a scroll
  }

  /**
   * advance the field: relax the pressed grass, then stamp every pusher (swept along its movement since the last call, so a fast walker leaves a continuous trail)
   * @param dt real seconds  @param pushers [{id?, x, z, r?, s?}] s = strength 0..1
   */
  step(dt, pushers = []) {
    dt = Math.min(Math.max(dt, 0), 0.1);
    const wasActive = this.box.i0 <= this.box.i1;
    this._relax(dt);
    const next = new Map();
    for (let n = 0; n < pushers.length; n++) {
      const p = pushers[n], key = p.id ?? ('#' + n), prev = this._prev.get(key);
      this._stamp(p, prev, dt); next.set(key, { x: p.x, z: p.z });
    }
    this._prev = next;
    if (wasActive || this.box.i0 <= this.box.i1) { this._encode(); this.version++; }   // only a changing field needs a new GPU upload
  }

  _relax(dt) {
    const b = this.box; if (b.i0 > b.i1) return;
    const N = this.N, f = Math.exp(-dt / this.recover), lr = this.spring * dt, L = this.lean;
    let i0 = N, i1 = -1, j0 = N, j1 = -1;
    for (let j = b.j0; j <= b.j1; j++) for (let i = b.i0; i <= b.i1; i++) {
      const k = (j * N + i) * 2; let x = L[k] * f, z = L[k + 1] * f;
      const m = Math.sqrt(x * x + z * z);
      if (m <= lr + 0.004) { if (L[k] !== 0 || L[k + 1] !== 0) { L[k] = 0; L[k + 1] = 0; this._zeroed(k); } continue; }
      const s = (m - lr) / m; L[k] = x * s; L[k + 1] = z * s;
      if (i < i0) i0 = i; if (i > i1) i1 = i; if (j < j0) j0 = j; if (j > j1) j1 = j;
    }
    this.box = i1 < 0 ? { i0: 1, i1: 0, j0: 1, j1: 0 } : { i0, i1, j0, j1 };
  }
  _zeroed(k) { this.data[k] = 128; this.data[k + 1] = 128; }

  _stamp(p, prev, dt) {
    const T = this.texel, R = p.r ?? this.radius, N = this.N, L = this.lean, strength = p.s ?? 1;
    let mx = 0, mz = 0, speed = 0, steps = 1, px = p.x, pz = p.z;
    if (prev) {
      const dx = p.x - prev.x, dz = p.z - prev.z, d = Math.hypot(dx, dz);
      if (d < 4) {                                                          // a teleport is not a walk
        speed = d / Math.max(dt, 1e-3);
        if (speed > 0.35) { mx = dx / d; mz = dz / d; }
        steps = Math.max(1, Math.ceil(d / 0.3)); px = prev.x; pz = prev.z;
      }
    }
    const moving = speed > 0.35, amount = strength * (moving ? 0.62 + 0.38 * Math.min(1, speed / 3.2) : 0.5), alpha = moving ? 0.55 : 1 - Math.exp(-dt * 5);
    for (let s = 1; s <= steps; s++) {
      const cx = px + (p.x - px) * (s / steps), cz = pz + (p.z - pz) * (s / steps);
      const ci = cx / T - this.ox, cj = cz / T - this.oz, rc = R / T + 1;
      const i0 = Math.max(0, Math.floor(ci - rc)), i1 = Math.min(N - 1, Math.ceil(ci + rc)), j0 = Math.max(0, Math.floor(cj - rc)), j1 = Math.min(N - 1, Math.ceil(cj + rc));
      if (i0 > i1 || j0 > j1) continue;
      for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
        const wx = (i + 0.5 + this.ox) * T - cx, wz = (j + 0.5 + this.oz) * T - cz, d = Math.sqrt(wx * wx + wz * wz);
        if (d >= R) continue;
        const t = 1 - d / R, w = t * t * (3 - 2 * t);                       // smooth falloff to the edge of the footprint
        let tx, tz;
        if (moving) {                                                       // parted sideways AND pressed along the heading
          const rx = d > 0.05 ? wx / d : 0, rz = d > 0.05 ? wz / d : 0;
          tx = rx * 0.75 + mx * 0.95; tz = rz * 0.75 + mz * 0.95;
        } else {
          if (d < 0.22) continue;                                           // directly under a standing unit the lean direction is undefined
          tx = wx / d; tz = wz / d;
        }
        const tn = Math.sqrt(tx * tx + tz * tz) || 1, k = (j * N + i) * 2, a = Math.min(1, w * alpha * 1.6);
        L[k] += (tx / tn * amount - L[k]) * a; L[k + 1] += (tz / tn * amount - L[k + 1]) * a;
      }
      this._grow(i0, i1, j0, j1);
    }
  }
  _grow(i0, i1, j0, j1) {
    const b = this.box;
    if (b.i0 > b.i1) { this.box = { i0, i1, j0, j1 }; return; }
    if (i0 < b.i0) b.i0 = i0; if (i1 > b.i1) b.i1 = i1; if (j0 < b.j0) b.j0 = j0; if (j1 > b.j1) b.j1 = j1;
  }

  _encode() {
    const b = this.box; if (b.i0 > b.i1) return;
    const N = this.N, L = this.lean, D = this.data;
    for (let j = b.j0; j <= b.j1; j++) for (let i = b.i0; i <= b.i1; i++) {
      const k = (j * N + i) * 2;
      D[k] = Math.max(1, Math.min(255, Math.round(L[k] * 127 + 128))); D[k + 1] = Math.max(1, Math.min(255, Math.round(L[k + 1] * 127 + 128)));
    }
  }
  _encodeAll() {
    const L = this.lean, D = this.data;
    for (let k = 0; k < L.length; k++) D[k] = Math.max(1, Math.min(255, Math.round(L[k] * 127 + 128)));
  }

  /** the lean vector at a world point (bilinear), into out {x, z} */
  sample(x, z, out = { x: 0, z: 0 }) {
    const N = this.N, u = x / this.texel - this.ox - 0.5, v = z / this.texel - this.oz - 0.5, i = Math.floor(u), j = Math.floor(v), fu = u - i, fv = v - j;
    out.x = 0; out.z = 0;
    for (let dj = 0; dj < 2; dj++) for (let di = 0; di < 2; di++) {
      const ii = i + di, jj = j + dj; if (ii < 0 || jj < 0 || ii >= N || jj >= N) continue;
      const w = (di ? fu : 1 - fu) * (dj ? fv : 1 - fv), k = (jj * N + ii) * 2;
      out.x += this.lean[k] * w; out.z += this.lean[k + 1] * w;
    }
    return out;
  }
  /** largest lean magnitude anywhere (0 = the field is clean) */
  peak() {
    const b = this.box; let m = 0; if (b.i0 > b.i1) return 0;
    for (let j = b.j0; j <= b.j1; j++) for (let i = b.i0; i <= b.i1; i++) { const k = (j * this.N + i) * 2; m = Math.max(m, Math.hypot(this.lean[k], this.lean[k + 1])); }
    return m;
  }
}
