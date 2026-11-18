// First-person walker (WASD + mouse, pointer lock), terrain following, circle colliders, fly-cam toggle, and a scripted tour camera.
import * as THREE from 'three';

export class Player {
  constructor({ camera, dom, heightAt, colliders = [], bounds = 140, eye = 1.72, start = { x: 0, z: 0, yaw: 0 }, blocked = null }) {
    this.blocked = blocked;   // (x,z) => true where the player may not walk (deep water...)
    this.camera = camera; this.dom = dom; this.heightAt = heightAt; this.colliders = colliders; this.bounds = bounds; this.eye = eye;
    this.pos = new THREE.Vector3(start.x, 0, start.z); this.pos.y = heightAt(start.x, start.z);
    this.yaw = start.yaw; this.pitch = -0.05; this.vel = new THREE.Vector3();
    this.keys = new Set(); this.fly = false; this.tour = null; this.locked = false; this.bob = 0;
    addEventListener('keydown', e => { this.keys.add(e.code); if (e.code === 'KeyF') this.fly = !this.fly; });
    addEventListener('keyup', e => this.keys.delete(e.code));
    dom.addEventListener('click', () => { if (!this.tour) dom.requestPointerLock?.(); });
    document.addEventListener('pointerlockchange', () => { this.locked = document.pointerLockElement === dom; });
    addEventListener('mousemove', e => {
      if (!this.locked) return;
      this.yaw -= e.movementX * 0.0022;
      this.pitch = Math.max(-1.45, Math.min(1.45, this.pitch - e.movementY * 0.0022));
    });
  }

  setPose(x, z, yaw, pitch = 0, y = null) {
    this.pos.set(x, y ?? this.heightAt(x, z), z); this.yaw = yaw; this.pitch = pitch;
  }

  /** points: [[x,z,(y)]...] camera path; speed m/s; lookAhead metres. */
  startTour(points, { speed = 5, height = 2.2, lookAhead = 10, loop = true } = {}) {
    const pts = points.map(p => new THREE.Vector3(p[0], p[2] ?? 0, p[1]));
    this.tour = { curve: new THREE.CatmullRomCurve3(pts, loop, 'catmullrom', 0.4), t: 0, speed, height, lookAhead, loop };
    this.tour.len = this.tour.curve.getLength();
  }
  stopTour() { this.tour = null; }

  update(dt) {
    const cam = this.camera;
    if (this.tour) {
      const T = this.tour; T.t = (T.t + dt * T.speed / T.len) % 1;
      const p = T.curve.getPointAt(T.t), a = T.curve.getPointAt((T.t + T.lookAhead / T.len) % 1);
      this.pos.set(p.x, this.heightAt(p.x, p.z), p.z);
      cam.position.set(p.x, this.pos.y + T.height, p.z);
      const ay = this.heightAt(a.x, a.z) + T.height * 0.55;
      cam.lookAt(a.x, ay, a.z);
      return;
    }
    const k = this.keys, sprint = k.has('ShiftLeft') || k.has('ShiftRight');
    const speed = (this.fly ? 22 : sprint ? 7.5 : 3.6);
    const f = (k.has('KeyW') || k.has('ArrowUp') ? 1 : 0) - (k.has('KeyS') || k.has('ArrowDown') ? 1 : 0);
    const s = (k.has('KeyD') || k.has('ArrowRight') ? 1 : 0) - (k.has('KeyA') || k.has('ArrowLeft') ? 1 : 0);
    const sy = Math.sin(this.yaw), cy = Math.cos(this.yaw);
    const wish = new THREE.Vector3(-sy * f + cy * s, 0, -cy * f - sy * s);
    if (wish.lengthSq() > 0) wish.normalize().multiplyScalar(speed);
    this.vel.lerp(wish, 1 - Math.exp(-dt * 10));
    const nx = this.pos.x + this.vel.x * dt, nz = this.pos.z + this.vel.z * dt;
    let x = nx, z = nz;
    if (!this.fly) {
      for (const c of this.colliders) {
        const dx = x - c.x, dz = z - c.z, d = Math.hypot(dx, dz), m = c.r + 0.35;
        if (d < m && d > 1e-4) { x = c.x + dx / d * m; z = c.z + dz / d * m; }
      }
    }
    if (!this.fly && this.blocked && this.blocked(x, z)) {          // slide along: try each axis on its own
      if (!this.blocked(x, this.pos.z)) z = this.pos.z; else if (!this.blocked(this.pos.x, z)) x = this.pos.x; else { x = this.pos.x; z = this.pos.z; }
    }
    const b = this.bounds;
    x = Math.max(-b, Math.min(b, x)); z = Math.max(-b, Math.min(b, z));
    this.pos.x = x; this.pos.z = z;
    const gy = this.heightAt(x, z);
    if (this.fly) {
      if (k.has('Space')) this.pos.y += 14 * dt;
      if (k.has('KeyC')) this.pos.y -= 14 * dt;
      this.pos.y = Math.max(this.pos.y, gy + 0.6);
    } else {
      this.pos.y += (gy - this.pos.y) * (1 - Math.exp(-dt * 14));
      this.bob += this.vel.length() * dt * 2.2;
    }
    const bobY = this.fly ? 0 : Math.sin(this.bob) * 0.035 * Math.min(1, this.vel.length() / 3);
    cam.position.set(this.pos.x, this.pos.y + (this.fly ? 0 : this.eye) + bobY, this.pos.z);
    cam.rotation.order = 'YXZ'; cam.rotation.set(this.pitch, this.yaw, 0);
  }
}
