"""Cloth: offline physics, baked into bone chains.

The free cloth of the samurai (the two obi tails, the sashimono pole and its flag) is simulated per clip, once, at build time, and the result is written as ordinary
bone keys: nothing runs in the game except the skeleton. Each chain is a short Verlet particle chain (rigid segments, a weak pull back toward its rest shape in the
parent bone's frame, gravity, air drag with a unit-local wind, collisions) pinned to the parent bone's REAL animated motion, so the cloth lags, swings and settles
because the body did. The pure-python pose evaluator (pose.py) supplies the body motion; nothing here touches Blender meshes.

What this is NOT: the robe and the trousers (skinned, folds are a baked normal map), the lamellar skirt / shoulder plates (rigid plates, analytic follow-through in
anim.py) and collisions that were not baked.

WIND IS NOT BAKED. The clips are baked DRY (BAKED_WIND = False): inertia, gravity, collisions and still-air drag only. The engine adds the world's wind at runtime on top
of the keys (`<asset>.cloth.json` describes the chains: kind, bones, rest directions; viewer/cloth_wind.js is the reference implementation), so the cloth reacts to the
game's wind direction, strength, gusts and to the unit's own velocity relative to the air. A baked, unit-local wind would stream every flag the same way whatever the weather.

Loops: the cycle is simulated several times and the last one is recorded; the residual mismatch between its end and its start is removed with a linear ramp (so the
first and last keys are identical and the gate's loop check passes). One-shots: the chain is settled on the clip's first pose before the recording starts.
"""
import math

from mathutils import Matrix, Quaternion, Vector

V = Vector
FPS = 30
DT = 1.0 / FPS
SUBSTEPS = 8
ITERATIONS = 8
CYCLES = 4                    # loop clips: simulated cycles (the last is recorded)
PRE_ROLL = 45                 # one-shot clips: frames the first pose is held before the recording (the chain settles)
GRAVITY = V((0.0, 0.0, -9.81))
GROUND = 0.010
BAKED_WIND = False             # clips are baked dry: the engine supplies the wind (see the module docstring and runtime_descriptor)

# ------------------------------------------------------------------------------------------------------------- geometry (single source for rig / body / skin)
SASH = {"a": (0.045, 0.26), "b": (0.105, 0.32)}          # x of the tail on the obi, drop (m)
SASH_Z = 1.02


def sash_joints(key):
    """Root, middle and tip of an obi tail (armature rest space): two bones."""
    sx, drop = SASH[key]
    return [V((sx, -0.158, SASH_Z)), V((sx + 0.010, -0.176, SASH_Z - drop * 0.5)), V((sx + 0.020, -0.180, SASH_Z - drop))]


POLE = [V((0.0, 0.185, 1.32)), V((0.0, 0.217, 1.95)), V((0.0, 0.222, 2.50))]          # banner_1 (on the chest), banner_2


def flag_joints():
    from .consts import CLOTH_H, CLOTH_W, TOP, X0, YC
    z = TOP - 0.004 - CLOTH_H * 0.5
    return [V((X0 + CLOTH_W * i / 3.0, YC + 0.003, z)) for i in range(4)]           # flag_1..3 along the cloth, at mid height


class Chain:
    def __init__(self, name, bones, parent, joints, **kw):
        self.name, self.bones, self.parent, self.joints = name, list(bones), parent, [V(j) for j in joints]
        self.k_shape = kw.get("k_shape", 0.01)         # pull toward the rest shape per substep (0 = free, 1 = rigid)
        self.damp = kw.get("damp", 0.985)              # velocity kept per substep
        self.gravity = kw.get("gravity", True)
        self.c_n = kw.get("c_n", 4.0)                  # air drag normal to the cloth (1 / s)
        self.c_t = kw.get("c_t", 0.5)                  # along the cloth
        self.planar = kw.get("planar", False)          # motion confined to the plane through the root with the parent's +Z as normal (the flag hangs from its top edge)
        self.nref = V(kw.get("nref", (0.0, 1.0, 0.0)))  # face normal of a ribbon in the parent's rest frame
        self.wind_gain = kw.get("wind", 1.0)
        self.run_gain = kw.get("run", 1.0)             # share of the locomotion headwind the chain feels
        self.gust = kw.get("gust", 0.5)                # gust amplitude (m/s)
        self.collide = kw.get("collide", ())
        self.half = kw.get("half", 0.006)              # collision half thickness: a ribbon that swings sideways presents its WIDTH to the armour, so tails use their half width
        self.max_angle = math.radians(kw.get("max_deg", 85.0))   # a segment may not turn further than this from its rest direction in the parent frame
        self.kind = kw.get("kind", "ribbon")           # runtime wind model: "ribbon" (hangs, tilts downwind), "flag" (streams downwind in a plane), "pole" (stiff, leans slightly)
        self.rt = kw.get("rt", {})                     # runtime parameters shipped in cloth.json (gain, omega, zeta, max_deg)


def chains():
    a, b = sash_joints("a"), sash_joints("b")
    return [
        Chain("sash_a", ("sash_a1", "sash_a2"), "hips", a, k_shape=0.006, damp=0.975, c_n=6.0, c_t=0.8, gust=0.30, run=0.6, max_deg=70.0, half=0.016, collide=("skirt", "thigh", "ground"),
              kind="ribbon", rt=dict(gain=1.0, omega=7.0, zeta=0.45, max_deg=38.0)),
        Chain("sash_b", ("sash_b1", "sash_b2"), "hips", b, k_shape=0.006, damp=0.975, c_n=6.0, c_t=0.8, gust=0.30, run=0.6, max_deg=70.0, half=0.016, collide=("skirt", "thigh", "ground"),
              kind="ribbon", rt=dict(gain=1.15, omega=6.2, zeta=0.45, max_deg=42.0)),
        Chain("pole", ("banner_1", "banner_2"), "chest", POLE, k_shape=0.08, damp=0.97, gravity=False, wind=0.0, run=0.0, max_deg=12.0,
              kind="pole", rt=dict(gain=0.25, omega=9.0, zeta=0.6, max_deg=2.5)),
        Chain("flag", ("flag_1", "flag_2", "flag_3"), "banner_2", flag_joints(), k_shape=0.010, damp=0.982, gravity=False, planar=True, c_n=9.0, c_t=1.2,
              gust=1.1, run=1.0, max_deg=70.0, kind="flag", rt=dict(gain=1.0, omega=9.0, zeta=0.32, max_deg=75.0)),
    ]


def runtime_descriptor():
    """What the engine needs to add wind on top of the baked keys: per chain its kind, bones, parent, and the rest direction / length of each bone segment in the glTF UNIT frame
    (+Y up, +Z forward, x right, metres: Blender (x, y, z) -> (x, z, -y)). Written next to the GLB as <asset>.cloth.json; viewer/cloth_wind.js is the reference implementation."""
    def g(v):
        return [round(v.x, 5), round(v.z, 5), round(-v.y, 5)]

    out = []
    for ch in chains():
        segs = []
        for i, bone in enumerate(ch.bones):
            d = ch.joints[i + 1] - ch.joints[i]
            n = d.normalized()
            segs.append({"bone": bone, "dir": g(n), "length": round(d.length, 5)})
        out.append({"name": ch.name, "kind": ch.kind, "parent": ch.parent, "segments": segs, **{k: ch.rt[k] for k in sorted(ch.rt)}})
    return {"version": 1, "baked_wind": BAKED_WIND, "frame": "glTF unit frame: x right, y up, z forward; metres; unit-local (the engine rotates the world wind into it)",
            "chains": out}


def write_runtime(out_dir, base):
    """Write <base>_cloth.json into out_dir."""
    import json
    import os
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{base}_cloth.json")
    with open(path, "w") as fh:
        json.dump(runtime_descriptor(), fh, indent=2)
    return path


CHAIN_BONES = [b for c in chains() for b in c.bones]


# ------------------------------------------------------------------------------------------------------------- rigid transforms
def _rt(M):
    """(rotation quaternion, translation) of a 4x4 matrix."""
    return M.to_quaternion(), M.translation.copy()


def _lerp_rt(A, B, t):
    return A[0].slerp(B[0], t), A[1].lerp(B[1], t)


def _apply(T, p):
    return T[0] @ p + T[1]


def _inv_apply(T, p):
    return T[0].inverted() @ (p - T[1])


# ------------------------------------------------------------------------------------------------------------- colliders (armature space, from the pose)
SKIRT_TOP, SKIRT_BOTTOM = 0.985, 0.70


def skirt_front_y(x, z, extra=0.0):
    """Outer surface of the front kusazuri at (x, z) in the panel's REST frame (the armour.skirt_parts ellipse cone + plate thickness + relief), or None outside it."""
    if z > SKIRT_TOP or z < SKIRT_BOTTOM:
        return None
    f = max(0.0, (0.979 - z) / 0.30)
    tier = min(3, max(0, int((0.979 - z) / 0.060)))
    off = 0.018 + 0.0045 * tier + 0.0045 + 0.0026 + extra
    rx, ry = 0.170 + 0.130 * f + off, 0.126 + 0.010 * f + off
    t = (abs(x) / rx) ** 2.4
    if t >= 1.0:
        return None
    return -0.004 - ry * (1.0 - t) ** (1.0 / 2.4)


def frame_colliders(rig, pose, kinds):
    """Everything a chain may touch in this pose: front skirt panel transforms (rest -> pose), thigh / shin capsules."""
    M = pose.matrices()
    out = {}
    if "skirt" in kinds:
        out["skirt"] = {s: _rt(M[f"skirt_front.{s}"] @ rig.rest[f"skirt_front.{s}"].inverted()) for s in "LR"}
    if "thigh" in kinds:
        caps = [(M["hips"].translation.copy(), pose.tail("chest"), 0.145)]          # the trunk (only gross interpenetration, e.g. a fall onto the tails)
        for s in "LR":
            caps.append((M[f"thigh.{s}"].translation.copy(), pose.tail(f"thigh.{s}"), 0.135))
            caps.append((M[f"shin.{s}"].translation.copy(), pose.tail(f"shin.{s}"), 0.085))
            caps.append((M[f"forearm.{s}"].translation.copy(), pose.tail(f"forearm.{s}"), 0.075))      # kote + sleeve: a fallen arm lies across the hips
            caps.append((M[f"hand.{s}"].translation.copy(), pose.tail(f"hand.{s}"), 0.06))
        out["caps"] = caps
    return out


def _lerp_colliders(A, B, t):
    if A is None:
        return None
    out = {}
    if "skirt" in A:
        out["skirt"] = {s: _lerp_rt(A["skirt"][s], B["skirt"][s], t) for s in "LR"}
    if "caps" in A:
        out["caps"] = [(a0.lerp(b0, t), a1.lerp(b1, t), r) for (a0, a1, r), (b0, b1, _) in zip(A["caps"], B["caps"])]
    return out


def _push_out(x, col, kinds, half):
    """Move a particle out of the colliders (half = half thickness of the cloth)."""
    if "ground" in kinds and x.z < GROUND:
        x.z = GROUND
    if col is None:
        return
    if "skirt" in kinds and "skirt" in col:
        T = col["skirt"]["L" if x.x >= 0.0 else "R"]
        q = _inv_apply(T, x)                              # into the panel's rest frame
        ys = skirt_front_y(q.x, q.z, half + 0.002)
        if ys is not None and q.y > ys:                   # inside the skirt: back out through the front
            q.y = ys
            x.x, x.y, x.z = _apply(T, q)
    if "thigh" in kinds and "caps" in col:
        for a, b, r in col["caps"]:
            ab = b - a
            t = max(0.0, min(1.0, (x - a).dot(ab) / max(ab.length_squared, 1e-9)))
            c = a + ab * t
            d = x - c
            dl = d.length
            if dl < r + half:
                nv = c + d / max(dl, 1e-6) * (r + half)
                x.x, x.y, x.z = nv.x, nv.y, nv.z


# ------------------------------------------------------------------------------------------------------------- wind
class Wind:
    """Unit-local air velocity: a weak steady breeze + periodic gusts (integer cycles per loop) + the headwind of the clip's own locomotion (character faces -Y)."""

    def __init__(self, name, duration, loop, speed):
        self.speed, self.loop, self.duration = speed, loop, duration
        base = sum(ord(c) for c in name)
        ph = [((base * (k + 3) * 0.37) % 1.0) * math.tau for k in range(6)]
        if loop:
            ms = [max(1, round(f * duration)) for f in (0.7, 1.3, 2.1)]
            self.freq = [m / duration for m in ms]
        else:
            self.freq = [0.8, 1.4, 2.3]
        self.ph = ph

    def at(self, t, gust, gain, run_gain):
        if not BAKED_WIND:
            return V((0.0, 0.0, 0.0))
        w = V((0.15, 0.30, 0.0)) * gain
        g = 0.0
        for k, f in enumerate(self.freq):
            amp = (1.0, 0.6, 0.35)[k]
            g += amp * math.sin(math.tau * f * t + self.ph[k])
        w += V((0.45 * math.sin(math.tau * self.freq[1] * t + self.ph[3]), 1.0 * g, 0.25 * math.sin(math.tau * self.freq[0] * t + self.ph[4]))) * (gust * gain)
        w += V((0.0, self.speed * run_gain, 0.0))
        return w


# ------------------------------------------------------------------------------------------------------------- the solver
def _chain_frames(rig, poses, ch):
    return [_rt(p.matrices()[ch.parent] @ rig.rest[ch.parent].inverted()) for p in poses]


def _simulate(ch, Ts, cols, wind, loop, n):
    """Run one chain over the clip. Ts[f] = parent rest->pose rigid transform at frame f (0..n); returns the recorded particle positions per frame (n + 1 lists)."""
    N = len(ch.joints)
    seg = [(ch.joints[i + 1] - ch.joints[i]).length for i in range(N - 1)]
    if loop:
        seq = [k % n for k in range(CYCLES * n)] + [n]
        rec0 = (CYCLES - 1) * n
    else:
        seq = [0] * PRE_ROLL + list(range(n + 1))
        rec0 = PRE_ROLL
    x = [_apply(Ts[seq[0]], j) for j in ch.joints]
    prev = [p.copy() for p in x]
    half = ch.half
    ns = SUBSTEPS
    dts = DT / ns
    rest_dir = [(ch.joints[i + 1] - ch.joints[i]).normalized() for i in range(N - 1)]
    rec = []
    for k in range(len(seq)):
        if k >= rec0:
            rec.append([p.copy() for p in x])
        if k == len(seq) - 1:
            break
        A, B = Ts[seq[k]], Ts[seq[k + 1]]
        CA, CB = cols[seq[k]], cols[seq[k + 1]]
        for s in range(1, ns + 1):
            tau = s / ns
            T = _lerp_rt(A, B, tau)
            col = _lerp_colliders(CA, CB, tau)
            tabs = (k + tau) * DT
            w = wind.at(tabs, ch.gust, ch.wind_gain, ch.run_gain)
            goal = [_apply(T, j) for j in ch.joints]
            x[0] = goal[0].copy()
            prev[0] = x[0].copy()
            nz = T[0] @ V((0.0, 0.0, 1.0))
            nref = T[0] @ ch.nref
            for i in range(1, N):
                v = (x[i] - prev[i]) * ch.damp
                a = V((0.0, 0.0, 0.0))
                if ch.gravity:
                    a += GRAVITY
                d = (x[i] - x[i - 1])
                d = d.normalized() if d.length > 1e-6 else rest_dir[i - 1]
                if ch.planar:
                    n = nz.cross(d)
                    n = n.normalized() if n.length > 1e-6 else nref
                else:
                    n = nref - d * nref.dot(d)
                    n = n.normalized() if n.length > 1e-6 else nref
                rel = w - v / dts
                rn = n * rel.dot(n)
                a += rn * ch.c_n + (rel - rn) * ch.c_t
                prev[i] = x[i].copy()
                x[i] = x[i] + v + a * (dts * dts)
                x[i] += (goal[i] - x[i]) * ch.k_shape
            for _ in range(ITERATIONS):
                for i in range(N - 1):
                    dvec = x[i + 1] - x[i]
                    dl = max(dvec.length, 1e-9)
                    corr = dvec * ((dl - seg[i]) / dl)
                    if i == 0:
                        x[1] -= corr
                    else:
                        x[i] += corr * 0.5
                        x[i + 1] -= corr * 0.5
                if ch.planar:
                    for i in range(1, N):
                        x[i] -= nz * (x[i] - goal[0]).dot(nz)
                for i in range(1, N):
                    _push_out(x[i], col, ch.collide, half)
                x[0] = goal[0].copy()
            # a segment may not turn further than max_angle from its rest direction (in the parent frame): keeps a violent frame from folding the cloth onto itself
            for i in range(N - 1):
                dr = (T[0] @ rest_dir[i])
                dvec = x[i + 1] - x[i]
                dl = max(dvec.length, 1e-9)
                ang = dr.angle(dvec / dl, 0.0)
                if ang > ch.max_angle:
                    axis = dr.cross(dvec)
                    if axis.length > 1e-9:
                        q = Quaternion(axis.normalized(), ch.max_angle)
                        x[i + 1] = x[i] + (q @ dr) * seg[i]
    return rec


def _close_loop(ch, rec, Ts, n, cols):
    """Remove the residual between the last and the first recorded frame (linear ramp on the offset from the rest shape, in the parent's frame), then resolve the
    collisions again (the ramp moves particles after the solver did): the first and last frames stay identical because their poses and colliders are."""
    N = len(ch.joints)
    off = [[_inv_apply(Ts[f], rec[f][i]) - ch.joints[i] for i in range(N)] for f in range(n + 1)]
    for f in range(n + 1):
        w = f / n
        for i in range(N):
            off[f][i] = off[f][i] - (off[n][i] - off[0][i]) * w
    out = [[_apply(Ts[f], ch.joints[i] + off[f][i]) for i in range(N)] for f in range(n + 1)]
    kinds = set(ch.collide)
    if kinds:
        for f in range(n + 1):
            for _ in range(3):
                for i in range(1, N):
                    _push_out(out[f][i], cols[f], kinds, ch.half)
    return out


def _directions(rec_f):
    out = []
    for i in range(len(rec_f) - 1):
        d = rec_f[i + 1] - rec_f[i]
        out.append(d.normalized() if d.length > 1e-9 else V((0.0, 0.0, -1.0)))
    return out


def place_chain(rig, pose, ch, dirs):
    """Write the pose deltas of the chain bones so that bone j points along dirs[j] (armature space); returns the quaternions.
    Bone orientation = (accumulated parent delta) x q x (rest frame), so q is the shortest arc from the rest axis to the direction seen from the parent's delta."""
    M = pose.matrices()[ch.parent]
    Dp = M.to_3x3() @ rig.rest_rot[ch.parent].inverted()
    out = []
    for bone, d in zip(ch.bones, dirs):
        a = rig.rest_rot[bone] @ V((0.0, 1.0, 0.0))
        q = a.rotation_difference(Dp.inverted() @ d)
        out.append(q)
        Dp = Dp @ q.to_matrix()
    return out


def simulate(rig, poses, loop, duration, speed=0.0, name="clip"):
    """Simulate every chain over the clip's body motion and write the chain bones' deltas into `poses` (n + 1 Pose objects, last == first for loops).
    Returns {chain name: {'max_deg': ..., 'tip_cm_max': ..., 'tip_cm_rms': ...}} diagnostics."""
    n = len(poses) - 1
    wind = Wind(name, duration, loop, speed)
    diag = {}
    for stage in (("sash_a", "sash_b", "pole"), ("flag",)):
        for ch in [c for c in chains() if c.name in stage]:
            Ts = _chain_frames(rig, poses, ch)
            kinds = set(ch.collide)
            cols = [frame_colliders(rig, p, kinds) if kinds - {"ground"} else None for p in poses]
            rec = _simulate(ch, Ts, cols, wind, loop, n)
            if loop:
                rec = _close_loop(ch, rec, Ts, n, cols)
            qs = []
            for f, p in enumerate(poses):
                q = place_chain(rig, p, ch, _directions(rec[f]))
                qs.append(q)
            # hemisphere continuity per bone (Blender interpolates quaternion keys linearly: a sign flip would spin the bone the long way round)
            for j, bone in enumerate(ch.bones):
                prevq = None
                for f in range(n + 1):
                    q = qs[f][j]
                    if prevq is not None and q.dot(prevq) < 0.0:
                        q.negate()
                    prevq = q
                if loop:
                    qs[n][j] = qs[0][j].copy()
                for f, p in enumerate(poses):
                    p.D[bone] = qs[f][j]
            for p in poses:
                p._M = None
            ang = 0.0
            for f in range(n + 1):
                for j in range(len(ch.bones)):
                    ang = max(ang, math.degrees(qs[f][j].angle))
            # tip travel away from its rest shape in the parent's frame (cm): how much the cloth really moves
            tip = [(_inv_apply(Ts[f], rec[f][-1]) - ch.joints[-1]).length * 100.0 for f in range(n + 1)]
            diag[ch.name] = {"max_deg": round(ang, 1), "tip_cm_max": round(max(tip), 1), "tip_cm_rms": round(math.sqrt(sum(t * t for t in tip) / len(tip)), 1)}
    return diag
