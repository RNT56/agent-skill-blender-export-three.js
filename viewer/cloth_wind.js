// Reference runtime for the character asset's WIND contract (docs/character.md, "Cloth").
//
// The clips are baked DRY: the flag, the pole and the obi tails carry only the motion their own inertia, gravity and collisions give them (cloth.py). This module adds the
// engine's wind on top, per frame, AFTER the AnimationMixer has written the keys:
//   air velocity relative to the unit (world wind - the unit's own velocity, rotated into the unit's frame)
//     -> per chain a damped second-order spring per bone toward a wind-driven target + a travelling flutter
//     -> a small rotation per bone, composed onto the animated local quaternion.
// `<asset>.cloth.json` (cloth.py `runtime_descriptor`) lists the chains: kind, bones, parent, rest direction and length of each segment in the glTF UNIT frame
// (x right, y up, z forward). No dependency: the core is plain maths (node-testable); `ClothWindRig` takes the THREE namespace as an argument.
//
// CORE ------------------------------------------------------------------------------------------------------------------------------------------------
export const WIND_MS = 3.5;                     // metres per second of air for 1.0 of the game's wind strength
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

/** a gust multiplier (about 0.7..1.3) that rolls across the field with the wind, so a formation shows a wave of gusts instead of every flag flapping in step */
export function gustAt(t, x, z, dirX, dirZ) {
  const d = x * dirX + z * dirZ;
  return 1 + 0.18 * Math.sin(Math.PI * 2 * (t * 0.35 - d / 23)) + 0.12 * Math.sin(Math.PI * 2 * (t * 0.9 - d / 11 + 0.37));
}

/** the air blowing past the unit, in the unit's frame. dirX / dirZ: unit vector the wind blows TOWARD (world x, z); strength: the game's wind strength; gust: multiplier;
 *  vel: the unit's world velocity (x, z) in m/s; yaw: the unit's rotation about +Y (three.js convention). Returns { x, z } in m/s. */
export function relativeAir(dirX, dirZ, strength, gust, vel, yaw) {
  const sp = WIND_MS * strength * gust;
  const wx = dirX * sp - vel.x, wz = dirZ * sp - vel.z;
  const c = Math.cos(yaw), s = Math.sin(yaw);
  return { x: c * wx - s * wz, z: s * wx + c * wz };
}

const FRACTION = { flag: [0.30, 0.70, 1.0], ribbon: [0.55, 1.0], pole: [0.4, 1.0] };
const W0 = { flag: 2.8, ribbon: 5.5, pole: 8.0 };          // air speed (m/s) at which the response is 63% of its full value

/** One chain's dynamic state. `step` fills `rot` with, per bone, TWO axis-angle rotations in the unit frame: [ax, ay, az, angle, bx, by, bz, angle2]. */
export class ChainState {
  constructor(desc, seed = 0) {
    this.desc = desc; this.kind = desc.kind; this.n = desc.segments.length;
    this.th = new Float64Array(this.n); this.vel = new Float64Array(this.n);      // primary angle (rad) and its rate per bone
    this.tw = new Float64Array(this.n); this.twv = new Float64Array(this.n);      // secondary angle (roll / twist) and its rate
    this.rot = new Float64Array(this.n * 8);
    this.ph = (seed * 0.6180339887) % 1 * Math.PI * 2;
    this.max = (desc.max_deg ?? 60) * Math.PI / 180;
    this.gain = desc.gain ?? 1; this.omega = desc.omega ?? 8; this.zeta = desc.zeta ?? 0.4;
    this.flut = desc.flutter ?? 1; this.flutHz = desc.flutter_hz ?? 1;           // a small light cloth (a spear's pennant) flutters wider and faster than a head band's tail
    this.frac = FRACTION[this.kind] || FRACTION.ribbon;
    this.speed = 0; this.s = 0;
  }

  /** forget everything (a pooled rig is given to another unit) */
  reset() { this.th.fill(0); this.vel.fill(0); this.tw.fill(0); this.twv.fill(0); this.rot.fill(0); this.speed = 0; this.s = 0; }

  /** @param dt seconds, @param t absolute time, @param air { x, z } relative air in the unit frame (m/s) */
  step(dt, t, air) {
    const k = this.kind, n = this.n, sp = Math.hypot(air.x, air.z);
    const s = 1 - Math.exp(-sp / W0[k]); this.speed = sp; this.s = s;
    const inc = (i) => this.frac[Math.min(i, this.frac.length - 1)] - (i > 0 ? this.frac[Math.min(i - 1, this.frac.length - 1)] : 0);
    let axis = [0, 1, 0], total = 0, flutAmp = 0, flutHz = 1, axis2 = [1, 0, 0], twAmp = 0;
    if (k === 'flag') {
      // the flag lies along +x and streams downwind in the horizontal plane: a yaw about +Y of -phi turns +x toward the air's direction (x', z') = (cos phi, sin phi)
      const phi = Math.atan2(air.z, air.x);
      const wdir = smooth(Math.PI * 0.88, Math.PI * 0.60, Math.abs(phi));     // wind blowing from the tip toward the pole cannot stream the flag: it hangs and flutters
      total = -clamp(phi, -this.max, this.max) * s * wdir * this.gain;
      flutAmp = 0.42 * Math.pow(s, 0.8) * this.gain; flutHz = clamp(1.4 + 0.75 * sp, 1.4, 7);
      axis = [0, 1, 0]; axis2 = [1, 0, 0]; twAmp = 0.30;
    } else if (k === 'ribbon') {
      // a ribbon hangs along -y and tilts toward the air's direction; the tails rest on the front of the body, so a push INTO it (-z) is clamped
      let px = 0, pz = 0;
      if (sp > 1e-4) { const a = Math.min(this.max, 0.62) * s * this.gain; px = air.x / sp * a; pz = air.z / sp * a; }
      if ((this.desc.body_z ?? -1) > 0) pz = Math.min(pz, 0.012);                // `body_z: 1` in the descriptor: the body is in FRONT of the ribbon (tails that hang behind a head)
      else if ((this.desc.body_z ?? -1) < 0) pz = Math.max(pz, -0.012);            // (`body_z: 0`: nothing to rest against: a spear's pennant swings both ways) 0.7 degrees: the baked tails already rest on the kusazuri, a tip 26 cm below its root moves 3 mm per 0.7 degrees
      total = Math.hypot(px, pz);
      axis = total > 1e-6 ? [-pz / total, 0, px / total] : [1, 0, 0];
      flutAmp = 0.12 * s * this.gain; flutHz = clamp(0.8 + 0.35 * sp, 0.8, 3.5); axis2 = [0, 1, 0]; twAmp = 0.5;     // the twist about its own length
    } else {                                                                      // pole: a slight lean downwind
      let px = 0, pz = 0;
      if (sp > 1e-4) { const a = Math.min(this.max, 0.045) * s * this.gain; px = air.x / sp * a; pz = air.z / sp * a; }
      total = Math.hypot(px, pz);
      axis = total > 1e-6 ? [pz / total, 0, -px / total] : [1, 0, 0];
    }
    flutAmp *= this.flut; flutHz *= this.flutHz;
    const omega = Math.PI * 2 * flutHz, h = Math.min(dt, 0.1), sub = h > 0.02 ? 4 : h > 0.008 ? 2 : 1, hs = h / sub;
    for (let q = 0; q < sub; q++) {
      const tt = t - h + hs * (q + 1);
      for (let i = 0; i < n; i++) {
        const w = this.omega * (1 + 0.15 * i), z = this.zeta;
        const wave = Math.sin(omega * tt - 1.3 * i + this.ph) + 0.35 * Math.sin(1.7 * omega * tt - 2.1 * i + this.ph * 1.7);
        const target = total * inc(i) + flutAmp * (0.4 + 0.6 * (i + 1) / n) * wave * (k === 'pole' ? 0 : 1);
        this.vel[i] += (w * w * (target - this.th[i]) - 2 * z * w * this.vel[i]) * hs; this.th[i] += this.vel[i] * hs;
        const wt = 5.0, tgt2 = twAmp * flutAmp * Math.sin(1.3 * omega * tt - 1.0 * i + this.ph * 0.5);
        this.twv[i] += (wt * wt * (tgt2 - this.tw[i]) - 2 * 0.5 * wt * this.twv[i]) * hs; this.tw[i] += this.twv[i] * hs;
      }
    }
    let cum = 0;
    for (let i = 0; i < n; i++) {                                                 // keep the CUMULATIVE bend of the chain inside the limit
      cum += this.th[i]; if (Math.abs(cum) > this.max) { const over = cum - Math.sign(cum) * this.max; this.th[i] -= over; cum -= over; }
      const o = i * 8; this.rot[o] = axis[0]; this.rot[o + 1] = axis[1]; this.rot[o + 2] = axis[2]; this.rot[o + 3] = this.th[i];
      this.rot[o + 4] = axis2[0]; this.rot[o + 5] = axis2[1]; this.rot[o + 6] = axis2[2]; this.rot[o + 7] = this.tw[i];
    }
    return this.rot;
  }
}

// THREE WIRING -------------------------------------------------------------------------------------------------------------------------------------------
/** All the chains of one rig. `THREE` is the namespace (so this file needs no import); `root` the cloned glTF scene of the rig (bones are found by name). */
export class ClothWindRig {
  constructor(THREE, root, descriptor, seed = 0) {
    this.THREE = THREE; this.chains = [];
    const bones = {}; root.traverse(o => { if (o.isBone) bones[o.name] = o; });
    const order = { pole: 0, ribbon: 1, flag: 2 };                                 // the flag hangs off banner_2: the pole's lean must be applied first
    for (const d of [...descriptor.chains].sort((a, b) => order[a.kind] - order[b.kind])) {
      const objs = d.segments.map(sg => bones[sg.bone]);
      if (objs.some(b => !b)) continue;                                            // an asset without that chain: skip it, never throw
      const anc = []; for (let p = objs[0].parent; p && p !== root; p = p.parent) anc.unshift(p);      // from the top bone down to the chain's parent
      this.chains.push({ desc: d, state: new ChainState(d, seed), bones: objs, anc, rest: objs.map(b => b.quaternion.clone()), base: objs.map(b => b.quaternion.clone()), names: d.segments.map(sg => sg.bone) });      // the rest orientation: the exporter drops constant tracks, so an unanimated bone is never rewritten by the mixer
    }
    this._qp = new THREE.Quaternion(); this._qd = new THREE.Quaternion(); this._qd2 = new THREE.Quaternion(); this._qi = new THREE.Quaternion();
    this._ax = new THREE.Vector3(); this.active = this.chains.length > 0;
  }

  reset() { for (const c of this.chains) c.state.reset(); }

  /** call BEFORE the mixer updates: takes last frame's wind off the chain bones.
   *  @param animated a Set of the bone names the CURRENT clip has a rotation track for (clipChainBones below), or nothing.
   *  A bone the clip animates goes back to what the mixer last wrote; a bone it does not goes back to its rest orientation (the exporter drops a track that never
   *  leaves the rest pose). Both are needed because the mixer only writes a value that CHANGED since its last write: put a still-hanging pennant back to its rest
   *  orientation (straight out from the shaft) and on every frame its key did not change it stays there - it flickers between hanging and sticking out.
   *  Without `animated` every bone goes to rest (right for chains whose rest pose is how they hang: tails, a banner). */
  restore(animated) {
    for (const c of this.chains) for (let j = 0; j < c.bones.length; j++) c.bones[j].quaternion.copy(animated && animated.has(c.names[j]) ? c.base[j] : c.rest[j]);
  }

  /** call AFTER the mixer wrote this frame's keys (and only on frames it did: the rotations are composed onto the animated quaternion; restore() before the mixer) */
  update(dt, t, air) {
    const { _qp: qp, _qd: qd, _qd2: qd2, _qi: qi, _ax: ax } = this;
    for (const c of this.chains) {
      const rot = c.state.step(dt, t, air);
      qp.identity(); for (const a of c.anc) qp.multiply(a.quaternion);              // the parent bone's orientation in the rig's frame
      for (let j = 0; j < c.bones.length; j++) {
        const o = j * 8;
        c.base[j].copy(c.bones[j].quaternion);                                          // what the clip says, before the wind: restore() puts it back
        qd.setFromAxisAngle(ax.set(rot[o], rot[o + 1], rot[o + 2]), rot[o + 3]);
        qd2.setFromAxisAngle(ax.set(rot[o + 4], rot[o + 5], rot[o + 6]), rot[o + 7]);   // secondary: a roll / twist, about the bone's own direction
        qd.multiply(qd2);
        qi.copy(qp).invert(); qd.premultiply(qi).multiply(qp);                          // the same rotation seen from the parent's own frame: qp^-1 * qd * qp
        c.bones[j].quaternion.premultiply(qd);
        qp.multiply(c.bones[j].quaternion);
      }
    }
  }
}

/** For restore(): per clip name, the Set of bone names the clip has a rotation track for. @param animations the glTF's AnimationClips */
export function clipChainBones(animations) {
  const out = {};
  for (const clip of animations) {
    const set = out[clip.name] = new Set();
    for (const t of clip.tracks) { const k = t.name.lastIndexOf('.'); if (k > 0 && t.name.slice(k + 1) === 'quaternion') set.add(t.name.slice(0, k)); }
  }
  return out;
}
