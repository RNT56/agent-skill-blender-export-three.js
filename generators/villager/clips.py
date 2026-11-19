"""Stage 5: the villager's clips.

Two sources, one result (plain FK keys on the deform bones, one Action per clip, 30 fps, in place):

  MOCAP    idle / walk / run come from motion capture retargeted onto this skeleton (Meshy's animation library through Higgsfield, applied by
           the same auto-rig, so the joints coincide): read per frame as armature-aligned rotation deltas (they do not depend on bone rolls),
           cut to a loop, the root motion taken out, the loop closed. The variants a labourer needs are built ON TOP of those cycles by
           re-solving the arms: a long tool carried at the trail, a load on the shoulder, a basket held in front.
  AUTHORED the trades (chop, mine, hoe, hammer, chisel, saw, cut, fish, craft) are written here: planted feet (two-bone IK), a keyed
           torso, and the tool driven through a swing model in the CHEST's frame, so every pose stays inside the arms' reach; the second
           hand takes the handle where props.SECOND_GRIP says.

Frames: metres, the figure faces -Y, left = +X. `samurai.pose` (blend-up's evaluator, generic over any armature) does the FK / IK.
"""
import json
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from samurai import pose as PO

from . import props as P, props_bpy, qa, rig as R

FPS = 30
V = Vector
MOCAP = {"idle": "idle_3.glb", "walk": "casual_walk.glb", "run": "run_02.glb", "carry": "carry_heavy_walk.glb", "pick": "bend_pick_up.glb"}


# ---------------------------------------------------------------------------------------------------- mocap in
def load_mocap(path):
    """-> list of frames; a frame is {bone: Quaternion (armature-aligned delta), '_loc': Vector (hips translation, metres)}."""
    sc = bpy.context.scene
    b_obj, b_act = set(bpy.data.objects), set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in b_obj]
    arm = next(o for o in new if o.type == "ARMATURE")
    for o in new:
        if o.type == "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    act = next(a for a in bpy.data.actions if a not in b_act)
    f0, f1 = (int(round(x)) for x in act.frame_range)
    scale = arm.matrix_world.to_scale().x
    rq = {b.name: b.matrix_local.to_3x3().to_quaternion() for b in arm.data.bones}
    rm = {b.name: b.matrix_local.to_3x3() for b in arm.data.bones}
    frames = []
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        fr = {}
        for pb in arm.pose.bones:
            n = R.MAP.get(pb.name)
            if n is None or pb.name in ("head_end", "headfront"):
                continue
            B = pb.matrix_basis
            fr[n] = rq[pb.name] @ B.to_quaternion() @ rq[pb.name].inverted()
            if n == "hips":
                fr["_loc"] = (rm[pb.name] @ B.to_translation()) * scale
        frames.append(fr)
    for o in [o for o in bpy.data.objects if o not in b_obj]:
        bpy.data.objects.remove(o, do_unlink=True)
    for a in [a for a in bpy.data.actions if a not in b_act]:
        bpy.data.actions.remove(a)
    bpy.context.view_layer.update()
    sc.frame_set(1)
    return frames


def fdist(a, b):
    d = 0.0
    for k, q in a.items():
        if k == "_loc":
            continue
        d += 1.0 - abs(q.dot(b[k]))
    return d


def detrend(frames, axes=(0, 1)):
    """take the root's travel out (linear trend of the hips over the clip), keep its sway."""
    n = len(frames) - 1
    d = frames[-1]["_loc"] - frames[0]["_loc"]
    out = []
    for i, fr in enumerate(frames):
        g = dict(fr)
        l = fr["_loc"].copy()
        for ax in axes:
            l[ax] -= d[ax] * i / max(n, 1)
        g["_loc"] = l
        out.append(g)
    return out, V((d.x, d.y, 0)).length


def close_loop(frames, tail=0.34):
    """bend the last part of the clip so that its last frame IS its first (rotations by slerp, the hips by a ramp)."""
    n = len(frames) - 1
    k0 = int(round(n * (1 - tail)))
    out = [dict(f) for f in frames]
    for i in range(k0, n + 1):
        w = (i - k0) / max(n - k0, 1)
        w = w * w * (3 - 2 * w)
        for key in frames[0]:
            if key == "_loc":
                out[i][key] = frames[i][key] + (frames[0][key] - frames[n][key]) * w
            else:
                corr = frames[0][key] @ frames[n][key].inverted()
                out[i][key] = Quaternion().slerp(corr, w) @ frames[i][key]
    out[n] = {k: (v.copy()) for k, v in out[0].items()}
    return out


def best_loop(frames, lo, hi, step=1):
    """the window [a, b] (lo <= b - a <= hi frames) whose two ends are the most alike."""
    best = None
    n = len(frames)
    for a in range(0, n - lo, step):
        for b in range(a + lo, min(n, a + hi + 1), step):
            d = fdist(frames[a], frames[b]) + (frames[a]["_loc"] - frames[b]["_loc"]).z ** 2 * 50
            if best is None or d < best[0]:
                best = (d, a, b)
    return best


def resample(frames, n_out):
    """n_out + 1 frames spread over the same motion (slerp between neighbours)."""
    n = len(frames) - 1
    out = []
    for i in range(n_out + 1):
        x = i * n / n_out
        a = min(int(x), n - 1)
        t = x - a
        fr = {}
        for k in frames[a]:
            fr[k] = frames[a][k].lerp(frames[a + 1][k], t) if k == "_loc" else frames[a][k].slerp(frames[a + 1][k], t)
        out.append(fr)
    return out


def amplify(frames, legs=1.0, arms=1.0, trunk=1.0, bounce=1.0):
    """scale a cycle's motion about its own mean pose: a shorter or longer stride from the same capture (a jog out of a run, a brisk walk out of a stroll)."""
    keys = [k for k in frames[0] if k != "_loc"]
    n = len(frames) - 1
    mean = {}
    for k in keys:
        ref = frames[0][k]
        acc = [0.0, 0.0, 0.0, 0.0]
        for fr in frames[:n]:
            q = fr[k] if fr[k].dot(ref) >= 0 else -fr[k]
            for i in range(4):
                acc[i] += q[i]
        m = Quaternion(acc)
        m.normalize()
        mean[k] = m
    lm = sum((fr["_loc"] for fr in frames[:n]), V()) / n

    def gain(k):
        if k.startswith(("thigh", "shin", "foot", "toe")):
            return legs
        if k.startswith(("upper_arm", "forearm", "hand", "shoulder")):
            return arms
        return trunk
    out = []
    for fr in frames:
        g = {}
        for k in keys:
            d = mean[k].inverted() @ fr[k]
            if d.w < 0:
                d.negate()
            ax, ang = d.to_axis_angle()
            g[k] = mean[k] @ Quaternion(ax, ang * gain(k))
        g["_loc"] = lm + (fr["_loc"] - lm) * bounce
        out.append(g)
    return out


def start_on_left_reach(B, frames):
    """rotate a closed cycle so that it starts where the LEFT foot is furthest forward: every gait then starts on the same footfall, and an engine that
    carries the stride phase over from one gait to another (walk <-> run) does not swap feet in the cross-fade."""
    n = len(frames) - 1
    ys = [(B.pose(f).head("toe.L") - B.pose(f).head("toe.R")).y for f in frames[:n]]
    k = int(np.argmin(ys))                                     # -y is forward
    return frames[k:n] + frames[:k] + [dict(frames[k])], k


def ground(B, frames, target=None):
    """shift the hips so the lowest point the toes reach in the cycle is the height they rest at (scaling a stride lifts or sinks the feet)."""
    target = B.rig.head["toe.L"].z + 0.006 if target is None else target
    low = min(min(B.pose(f).head("toe.L").z, B.pose(f).head("toe.R").z) for f in frames)
    dz = target - low
    out = []
    for fr in frames:
        g = dict(fr)
        g["_loc"] = fr["_loc"] + V((0, 0, dz))
        out.append(g)
    return out, dz


# ---------------------------------------------------------------------------------------------------- the body
class Body:
    def __init__(self, arm, hands, cfg=None):
        self.arm = arm
        self.rig = PO.Rig(arm)
        self.hands = hands
        self.rest = self.rig.rest
        self.tool_rest = {"R": R.tool_matrix(arm, "tool_r"), "L": R.tool_matrix(arm, "tool_l")}
        self.ankle = {s: self.rig.head[f"foot.{s}"].copy() for s in "LR"}
        self.sh = {s: self.rig.head[f"upper_arm.{s}"].copy() for s in "LR"}
        self.reach = {s: self.rig.length[f"upper_arm.{s}"] + self.rig.length[f"forearm.{s}"] for s in "LR"}
        self.load = {b: self.rig.head[b].copy() for b in ("load_shoulder", "load_front")}
        # The work clips are written in the REFERENCE body's coordinates (hands a certain way in front of ITS shoulders). Another body gets them
        # through a map that puts the reference's shoulder line on its own and scales by its arm's reach; its legs scale the squat depths.
        from . import variants
        ref = variants.REF
        if cfg is None or cfg.get("reference"):
            self.k, self.kl, self.fit = 1.0, 1.0, Matrix.Identity(4)
        else:
            mid = (self.sh["L"] + self.sh["R"]) * 0.5
            self.k = (self.reach["L"] + self.reach["R"]) * 0.5 / ref["arm"]
            leg = sum(self.rig.length[f"{b}.{s}"] for s in "LR" for b in ("thigh", "shin")) * 0.5
            self.kl = leg / ref["leg"]
            self.fit = Matrix.Translation(mid) @ Matrix.Diagonal((self.k, self.k, self.k, 1.0)) @ Matrix.Translation(-V(ref["shoulder_mid"]))

    def pose(self, fr=None):
        p = PO.Pose(self.rig)
        if fr:
            for k, q in fr.items():
                if k == "_loc":
                    p.move("hips", q)
                else:
                    p.rot(k, q)
        return p

    def chest(self, p):
        """the chest's motion from rest: takes a point given in THIS body's rest coordinates along with the chest"""
        return p.matrices()["chest"] @ self.rest["chest"].inverted()

    def chest_ref(self, p):
        """the same for a point given in the REFERENCE body's rest coordinates (the authored clips): fitted to this body first"""
        return self.chest(p) @ self.fit

    @staticmethod
    def frame(G, h, b):
        """tool matrix from the grip point, the handle direction (toward the working end) and the strike direction."""
        z = V(h).normalized()
        x = V(b) - z * V(b).dot(z)
        if x.length < 1e-5:
            x = V((0, 0, -1)) - z * z.z * -1
        x.normalize()
        y = z.cross(x)
        T = Matrix.Identity(4)
        for i in range(3):
            T[i][0], T[i][1], T[i][2], T[i][3] = x[i], y[i], z[i], V(G)[i]
        return T

    def grip_frame(self, side, G, fingers, palm):
        """a free hand: where the middle of the palm is, where the fingers point, where the palm faces."""
        y = V(palm).normalized() * (1.0 if side == "R" else -1.0)
        x = V(fingers) - y * V(fingers).dot(y)
        x.normalize()
        z = x.cross(y)
        T = Matrix.Identity(4)
        for i in range(3):
            T[i][0], T[i][1], T[i][2], T[i][3] = x[i], y[i], z[i], V(G)[i]
        return T

    def place_hand(self, p, side, T, pole=None, twist=0.55):
        """put the hand so that its grip frame is T (armature space). Returns (reach ratio, miss in metres)."""
        s = side
        T = T.copy()
        R3 = T.to_3x3()
        for c in range(3):                                    # a fitted frame (chest_ref) carries the fit's scale: a hand is not scaled
            col = R3.col[c].normalized()
            for i in range(3):
                T[i][c] = col[i]
        H = T @ self.tool_rest[s].inverted() @ self.rest[f"hand.{s}"]
        sx = 1.0 if s == "L" else -1.0
        pole = V(pole) if pole is not None else V((0.55 * sx, 0.70, -0.55))
        reach = p.limb(f"upper_arm.{s}", f"forearm.{s}", None, H.translation, pole, -1.0)
        H3 = H.to_3x3()
        p._place(f"hand.{s}", H3)
        # share the hand's roll about the forearm with the forearm itself (pronation), or the wrist wrings like a towel
        M = p.matrices()
        F = M[f"forearm.{s}"].to_3x3()
        rel0 = self.rest[f"forearm.{s}"].to_3x3().inverted() @ self.rest[f"hand.{s}"].to_3x3()
        d = (F.inverted() @ H3 @ rel0.inverted()).to_quaternion()
        tw = Quaternion((d.w, 0.0, d.y, 0.0))
        if tw.magnitude > 1e-6:
            tw.normalize()
            part = Quaternion().slerp(tw, twist)
            p._place(f"forearm.{s}", F @ part.to_matrix())
            p._place(f"hand.{s}", H3)
        tb = "tool_l" if s == "L" else "tool_r"
        miss = (p.matrices()[tb].translation - T.translation).length
        return reach, miss

    def plant(self, p, side, d=(0, 0, 0), yaw=0.0, pitch=0.0):
        """the ankle at rest + d, the sole level but turned by yaw (degrees, + = toes to the figure's left) and tipped by pitch (+ = heel up)."""
        s = side
        sx = 1.0 if s == "L" else -1.0
        tgt = self.ankle[s] + V(d)
        ya = math.radians(yaw)
        fwd = V((math.sin(ya), -math.cos(ya), 0.0))
        p.limb(f"thigh.{s}", f"shin.{s}", None, tgt, fwd + V((0.22 * sx, 0, 0.1)), 1.0)
        Rw = Matrix.Rotation(ya, 3, "Z") @ Matrix.Rotation(math.radians(pitch), 3, "X")
        p._place(f"foot.{s}", Rw @ self.rig.rest_rot[f"foot.{s}"])
        p._place(f"toe.{s}", Matrix.Rotation(ya, 3, "Z") @ self.rig.rest_rot[f"toe.{s}"])

    def spine(self, p, bend=0.0, lean=0.0, twist=0.0, add=False):
        for n, w in (("spine", 0.30), ("spine1", 0.35), ("chest", 0.35)):
            r = (bend * w, lean * w, twist * w)
            (p.mul if add else p.rot)(n, r)

    def curl(self, p, side, amount, thumb=None):
        R.curl(p, self.rig, side, amount, self.hands, thumb)

    def relax_arm(self, p, side, swing=0.0, out=8.0, bend=18.0):
        """an arm hanging at the side (the rest pose is an A-pose: bring it in)."""
        sx = 1.0 if side == "L" else -1.0
        p.rot(f"upper_arm.{side}", (swing, sx * (28.0 - out), 0))
        p.rot(f"forearm.{side}", (-bend, 0, 0))
        p.rot(f"hand.{side}", (0, 0, 0))


# ---------------------------------------------------------------------------------------------------- curves
class Curve:
    """Monotone cubic (no overshoot) through keys [(t, value)], periodic when `period` is given. Values are floats or tuples."""

    def __init__(self, keys, period=None):
        ts = np.array([k[0] for k in keys], dtype=float)
        ys = np.array([np.atleast_1d(np.array(k[1], dtype=float)) for k in keys])
        self.period = period
        if period:
            ts = np.concatenate([ts, [ts[0] + period]])
            ys = np.vstack([ys, ys[:1]])
        h = np.diff(ts)
        d = np.diff(ys, axis=0) / h[:, None]
        n = len(ts)
        m = np.zeros_like(ys)
        for i in range(n):
            if period:
                il, ir = (i - 1) % (n - 1), i % (n - 1)
            else:
                if i == 0 or i == n - 1:
                    continue
                il, ir = i - 1, i
            dl, dr, hl, hr = d[il], d[ir], h[il], h[ir]
            same = dl * dr > 0
            w1, w2 = 2 * hr + hl, hr + 2 * hl
            with np.errstate(divide="ignore", invalid="ignore"):
                m[i] = np.where(same, (w1 + w2) / (w1 / np.where(same, dl, 1) + w2 / np.where(same, dr, 1)), 0.0)
        self.ts, self.ys, self.m, self.h = ts, ys, m, h

    def __call__(self, t):
        ts = self.ts
        if self.period:
            t = ts[0] + (t - ts[0]) % self.period
        t = min(max(t, ts[0]), ts[-1])
        i = min(int(np.searchsorted(ts, t, side="right")) - 1, len(ts) - 2)
        u = (t - ts[i]) / self.h[i]
        h00, h10, h01, h11 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
        y = h00 * self.ys[i] + h10 * self.h[i] * self.m[i] + h01 * self.ys[i + 1] + h11 * self.h[i] * self.m[i + 1]
        return float(y[0]) if len(y) == 1 else y


def swing(C, rho, u, v, theta):
    """the two-handed swing model: the handle turns in the plane (u, v) by theta (degrees, 0 = along u); the hands ride a small arc about C.
    Returns (grip, handle direction, the way the working end travels when theta DEcreases)."""
    u, v = V(u).normalized(), V(v).normalized()
    a = math.radians(theta)
    h = u * math.cos(a) + v * math.sin(a)
    b = u * math.sin(a) - v * math.cos(a)
    return V(C) + h * rho, h, b


# ---------------------------------------------------------------------------------------------------- variants on a mocap cycle
def relaxed_hands(B, p, r=0.30, l=0.30):
    B.curl(p, "R", r)
    B.curl(p, "L", l)


def tool_trail(B, p, w_mean, w_now):
    """a long tool carried at the trail in the right hand: the arm hangs, the head of the tool leads, the swing of the arm is damped."""
    C = B.chest_ref(p)
    sway = (V(w_now) - V(w_mean)) * 0.28
    G = V((-0.262, -0.035, 0.835)) + V((0.0, sway.y, sway.z * 0.5))
    T = C @ B.frame(G, (0.03, -0.955, 0.295), (0, -0.2, -1))
    r, m = B.place_hand(p, "R", T, pole=(-0.45, 0.85, -0.25))
    B.curl(p, "R", 1.0)
    B.curl(p, "L", 0.30)
    return r, m


def shoulder_load(B, p):
    """a load riding on the right shoulder, the right hand cupped under its front end; the body leans a little away from it."""
    B.spine(p, lean=3.5, add=True)
    p.mul("head", (0, 5.0, 4.0))
    p.rot("load_shoulder", (7.0, 0, -3.0))
    C = B.chest(p)
    Lb = B.load["load_shoulder"]
    G = Lb + V((-0.035, -0.235, -0.040))
    T = C @ B.grip_frame("R", G, (0.30, 0.86, 0.22), (0.10, -0.12, 1.0))
    r, m = B.place_hand(p, "R", T, pole=(-0.45, 0.15, -0.9))
    B.curl(p, "R", 0.42, thumb=0.2)
    for n in ("upper_arm.L", "forearm.L"):                    # the free arm swings less: it balances
        p.rot(n, Quaternion().slerp(p.D.get(n, Quaternion()), 0.72))
    B.curl(p, "L", 0.35)
    return r, m


def front_load(B, p):
    """a basket carried in front in both hands"""
    B.spine(p, bend=-5.0, add=True)
    p.mul("head", (4.0, 0, 0))
    C = B.chest(p)
    Lb = B.load["load_front"]
    rs, ms = 0.0, 0.0
    for s, sx in (("L", 1.0), ("R", -1.0)):
        G = Lb + V((sx * (P.BASKET_GRIP[0] + 0.012), -0.01, P.BASKET_GRIP[2] - 0.035))
        T = C @ B.grip_frame(s, G, (-0.18 * sx, -0.86, -0.42), (-sx, 0.05, 0.25))
        r, m = B.place_hand(p, s, T, pole=(0.75 * sx, 0.55, -0.45))
        rs, ms = max(rs, r), max(ms, m)
        B.curl(p, s, 0.55, thumb=0.1)
    return rs, ms


# ---------------------------------------------------------------------------------------------------- authored work
def _stance(B, p, hips=(0, 0, -0.05), hrot=(0, 0, 0), L=((0.02, -0.16, 0), 12, 0), Rr=((-0.02, 0.10, 0), -22, 0)):
    p.move("hips", (hips[0], hips[1], hips[2] * B.kl))
    p.rot("hips", hrot)
    B.plant(p, "L", *L)
    B.plant(p, "R", *Rr)


def _two_hands(B, p, tool, G, h, b, roll=0.0, poleR=None, poleL=None, curl=1.0):
    C = B.chest_ref(p)
    T = C @ B.frame(G, h, b)
    r1, m1 = B.place_hand(p, "R", T, pole=poleR)
    M = p.matrices()
    Tt = M["tool_r"]
    # the tool now sits where the hand really is: take the left hand to the handle
    X = Matrix.Identity(4)
    Rt = Tt.to_3x3()
    xb, yb, zb = Rt.col[2], Rt.col[0], Rt.col[1]
    for i in range(3):
        X[i][0], X[i][1], X[i][2], X[i][3] = xb[i], yb[i], zb[i], Tt[i][3]
    d = P.SECOND_GRIP[tool]
    TL = X @ Matrix.Translation((0, 0, d)) @ Matrix.Rotation(math.radians(roll), 4, "Z")
    r2, m2 = B.place_hand(p, "L", TL, pole=poleL)
    B.curl(p, "R", curl)
    B.curl(p, "L", curl)
    return max(r1, r2), max(m1, m2), X


def clip_chop(B, T=1.5):
    """felling: a batter's stance side-on to the tree, the axe swung from over the right shoulder into the trunk in front"""
    th = Curve([(0.00, 18), (0.34, 128), (0.46, 122), (0.60, 6), (0.74, 2), (0.86, 12)], T)
    tw = Curve([(0.00, 12), (0.34, -30), (0.46, -26), (0.60, 34), (0.74, 36), (0.86, 22)], T)       # torso twist (+ = to the left, into the cut)
    bd = Curve([(0.00, 12), (0.34, 2), (0.60, 27), (0.74, 28), (0.86, 18)], T)
    hy = Curve([(0.00, 0.0), (0.34, 0.035), (0.60, -0.05), (0.74, -0.05)], T)                          # weight from the back foot to the front
    hz = Curve([(0.00, -0.08), (0.34, -0.05), (0.60, -0.14), (0.74, -0.14)], T)

    def fn(t):
        p = B.pose()
        _stance(B, p, hips=(0.0, hy(t), hz(t)), hrot=(0, 0, -38 + tw(t) * 0.25), L=((0.05, -0.20, 0), -18, 0), Rr=((-0.10, 0.17, 0), -62, 0))
        B.spine(p, bend=bd(t), twist=tw(t), lean=-3)
        p.rot("neck", (4, 0, 8))
        p.rot("head", (8, 0, 26 - tw(t) * 0.5))
        G, h, b = swing((-0.035, -0.215, 1.205), 0.125, (0.34, -0.93, -0.10), (-0.80, 0.25, 0.55), th(t))
        r, m, X = _two_hands(B, p, "ono", G, h, b, poleR=(-0.6, 0.6, -0.5), poleL=(0.35, 0.3, -0.9))
        return p, r, m
    return fn, T, {"impact": 0.60}


def _overhead(B, tool, T, top, low, bend_top, bend_low, drop, pull=0.0, sink=0.0, C0=(-0.02, -0.225, 1.215), rho=0.12):
    th = Curve([(0.00, low + 22), (0.36, top), (0.47, top - 5), (0.61, low), (0.76, low - 1), (0.88, low + 10)], T)
    bd = Curve([(0.00, bend_low - 12), (0.36, bend_top), (0.47, bend_top + 2), (0.61, bend_low), (0.76, bend_low + 1), (0.88, bend_low - 5)], T)
    hz = Curve([(0.00, -drop * 0.6), (0.36, -0.035), (0.61, -drop), (0.76, -drop)], T)
    hy = Curve([(0.00, 0.01), (0.36, 0.03), (0.61, -0.02), (0.76, -0.02 + pull * 0.25)], T)
    cy = Curve([(0.00, pull * 0.6), (0.36, 0.0), (0.61, 0.0), (0.80, pull), (0.94, pull * 0.8)], T)     # the hoe is drawn back through the soil
    cz = Curve([(0.00, -sink * 0.6), (0.36, 0.0), (0.47, 0.0), (0.61, -sink), (0.76, -sink), (0.88, -sink * 0.8)], T)   # the hands come down in front of the belly with the blow

    def fn(t):
        p = B.pose()
        _stance(B, p, hips=(0.0, hy(t), hz(t)), hrot=(bd(t) * 0.30, 0, -8), L=((0.03, -0.20, 0), 6, 0), Rr=((-0.04, 0.13, 0), -30, 0))
        B.spine(p, bend=bd(t) * 0.70, twist=4)
        p.rot("neck", (-bd(t) * 0.18, 0, 0))
        p.rot("head", (-bd(t) * 0.20 + 6, 0, 0))
        C = V(C0) + V((0, cy(t), cz(t)))
        G, h, b = swing(C, rho, (0.06, -1.0, 0.0), (-0.10, 0.0, 1.0), th(t))
        r, m, X = _two_hands(B, p, tool, G, h, b, poleR=(-0.75, 0.45, -0.5), poleL=(0.75, 0.45, -0.5))
        return p, r, m
    return fn, T, {"impact": round(0.61, 3)}


def clip_mine(B, T=1.6):
    """the pick: up over the head, down into the ground in front"""
    fn, T, ev = _overhead(B, "tsuruhashi", T, top=120, low=-5, bend_top=-6, bend_low=52, drop=0.29, sink=0.10)
    return fn, T, ev


def clip_hoe(B, T=1.9):
    """the hoe: a lower stroke than the pick, then drawn back through the soil"""
    fn, T, ev = _overhead(B, "kuwa", T, top=88, low=-8, bend_top=2, bend_low=44, drop=0.22, pull=0.085, sink=0.09)
    return fn, T, ev


def clip_hammer(B, T=1.2):
    """one-handed: two blows a loop on something at bench height, the left hand steadying the work"""
    th = Curve([(0.00, 30), (0.20, 96), (0.34, 4), (0.42, 8), (0.62, 104), (0.78, 2), (0.88, 6)], T)
    bd = Curve([(0.00, 12), (0.20, 8), (0.34, 17), (0.62, 7), (0.78, 18), (0.88, 16)], T)

    def fn(t):
        p = B.pose()
        _stance(B, p, hips=(0, -0.01, -0.06), hrot=(4, 0, -6), L=((0.02, -0.15, 0), 10, 0), Rr=((-0.03, 0.10, 0), -24, 0))
        B.spine(p, bend=bd(t), twist=6 - th(t) * 0.05)
        p.rot("head", (16, 0, 4))
        C = B.chest_ref(p)
        G, h, b = swing((-0.165, -0.255, 1.115), 0.085, (0.10, -1.0, -0.06), (0.0, 0.10, 1.0), th(t))
        r1, m1 = B.place_hand(p, "R", C @ B.frame(G, h, b), pole=(-0.8, 0.35, -0.45))
        B.curl(p, "R", 1.0)
        TL = C @ B.grip_frame("L", (0.085, -0.385, 1.00), (-0.35, -0.90, -0.10), (0.1, 0.1, -1.0))
        r2, m2 = B.place_hand(p, "L", TL, pole=(0.8, 0.35, -0.45))
        B.curl(p, "L", 0.45)
        return p, max(r1, r2), m1
    return fn, T, {"impact": 0.34, "impacts": [0.34, 0.78]}


def clip_chisel(B, T=1.6):
    """the stonecutter: down on his haunches, the chisel set against the stone with the left hand, three taps of the hammer"""
    taps = [0.22, 0.62, 1.02]
    keys = [(0.0, 0.55)]
    for tp in taps:
        keys += [(tp - 0.16, 1.0), (tp, 0.0), (tp + 0.06, 0.08)]
    keys += [(1.30, 0.4)]
    up = Curve(keys, T)

    def fn(t):
        p = B.pose()
        u = up(t)
        p.move("hips", (0, 0.13, -0.44 * B.kl))
        p.rot("hips", (20, 0, 0))
        B.plant(p, "L", (0.05, -0.10, 0.045), 14, 26)
        B.plant(p, "R", (-0.06, 0.03, 0.045), -22, 26)
        B.spine(p, bend=22 + (1 - u) * 2.0, twist=5)
        p.rot("neck", (-6, 0, 0))
        p.rot("head", (-4, 0, 3))
        C = B.chest_ref(p)
        # the chisel: its butt up and back toward the right shoulder, its edge on the stone
        zl = V((-0.20, 0.42, 0.88)).normalized()
        GL = V((0.060, -0.275, 1.055))
        TL = C @ B.frame(GL, zl, (0.25, -0.9, 0.35))
        r2, m2 = B.place_hand(p, "L", TL, pole=(0.8, 0.3, -0.5))
        B.curl(p, "L", 1.0)
        butt = GL + zl * 0.125
        hR = V((0.62, -0.74, 0.22)).normalized()
        strike = -zl
        Gs = butt - hR * P.HEAD_Z["tsuchi"] + zl * 0.024
        # the wind-up: the hammer lifts along the chisel's axis and cocks back
        G = Gs + zl * (0.17 * u) + V((-0.03, 0.03, 0.02)) * u
        h = (hR + V((-0.15, 0.25, 0.75)) * u).normalized()
        r1, m1 = B.place_hand(p, "R", C @ B.frame(G, h, strike), pole=(-0.8, 0.3, -0.5))
        B.curl(p, "R", 1.0)
        return p, max(r1, r2), max(m1, m2)
    return fn, T, {"impact": taps[0], "impacts": taps}


def clip_saw(B, T=1.0):
    """sawing a baulk: the left hand bears down on the timber, the right drives the saw along its own length"""
    def fn(t):
        ph = 2 * math.pi * t / T
        s = math.sin(ph)
        p = B.pose()
        _stance(B, p, hips=(0, -0.02 - 0.012 * s, -0.10), hrot=(10, 0, -10), L=((0.02, -0.22, 0), 8, 0), Rr=((-0.05, 0.14, 0), -32, 0))
        B.spine(p, bend=27 + 3.0 * s, twist=8 - 5.0 * s)
        p.rot("head", (10, 0, 6))
        C = B.chest_ref(p)
        h = V((0.16, -0.985, 0.06)).normalized()
        G = V((-0.185, -0.205, 1.035)) + h * (0.105 * s)
        r1, m1 = B.place_hand(p, "R", C @ B.frame(G, h, (0, -0.25, -1)), pole=(-0.7, 0.6, -0.3))
        B.curl(p, "R", 1.0)
        TL = C @ B.grip_frame("L", (0.10, -0.33, 0.975), (-0.25, -0.95, -0.10), (0.0, 0.25, -1.0))
        r2, m2 = B.place_hand(p, "L", TL, pole=(0.8, 0.4, -0.4))
        B.curl(p, "L", 0.30)
        return p, max(r1, r2), m1
    return fn, T, {"impact": 0.25}


def clip_cut(B, T=1.5):
    """the sickle: bent to the crop, the left hand gathers a sheaf, the right draws the blade through it toward the body"""
    sw = Curve([(0.00, 0.0), (0.38, 0.0), (0.62, 1.0), (0.80, 1.0), (1.10, 0.3)], T)                 # 0 = reached out to the right, 1 = drawn through
    rise = Curve([(0.00, 0.0), (0.62, 0.0), (0.80, 0.25), (1.05, 1.0), (1.30, 0.35)], T)               # the cut sheaf is lifted, then down to the next

    def fn(t):
        p = B.pose()
        k, u = sw(t), rise(t)
        bend = 56 - 30 * u
        _stance(B, p, hips=(0, 0.035, -0.20 + 0.10 * u), hrot=(bend * 0.36, 0, -6 + 8 * k), L=((0.03, -0.19, 0), 8, 0), Rr=((-0.05, 0.14, 0), -30, 0))
        B.spine(p, bend=bend * 0.64, twist=-24 + 40 * k)
        p.rot("neck", (-10, 0, 0))
        p.rot("head", (-12, 0, 0))
        C = B.chest_ref(p)
        TL = C @ B.grip_frame("L", (0.075, -0.345, 1.02 + 0.03 * u), (-0.45, -0.75, -0.48), (-0.9, 0.2, -0.3))
        r2, m2 = B.place_hand(p, "L", TL, pole=(0.85, 0.3, -0.4))
        B.curl(p, "L", 0.85)
        G = V((-0.330, -0.235, 1.060)).lerp(V((-0.060, -0.225, 1.03)), k)
        h = V((0.45, -0.82, -0.34)).lerp(V((0.92, -0.05, -0.38)), k).normalized()
        r1, m1 = B.place_hand(p, "R", C @ B.frame(G, h, (0.3, 0.9, -0.2)), pole=(-0.8, 0.45, -0.35))
        B.curl(p, "R", 1.0)
        return p, max(r1, r2), m1
    return fn, T, {"impact": 0.5}


def clip_fish(B, T=5.0):
    """waiting on a bite: the rod held out over the water in both hands, a lift now and then; the line hangs plumb from the tip"""
    lift = Curve([(0.0, 0.0), (2.9, 0.0), (3.25, 1.0), (3.6, 0.25), (4.2, 0.0)], T)

    def fn(t):
        ph = 2 * math.pi * t / T
        p = B.pose()
        u = lift(t)
        _stance(B, p, hips=(0.012 * math.sin(ph), 0.0, -0.035), hrot=(0, 0, -10), L=((0.01, -0.10, 0), 8, 0), Rr=((-0.02, 0.07, 0), -24, 0))
        B.spine(p, bend=3 - 5 * u + 1.0 * math.sin(2 * ph), twist=6)
        p.rot("head", (6, 0, 4 + 3 * math.sin(ph)))
        pitch = math.radians(27 + 15 * u + 1.5 * math.sin(2 * ph))
        h = V((0.06, -math.cos(pitch), math.sin(pitch)))
        G = V((-0.105, -0.285, 1.055 + 0.05 * u))
        r, m, X = _two_hands(B, p, "tsurizao", G, h, (0, -0.3, -1.0), poleR=(-0.8, 0.4, -0.45), poleL=(0.7, 0.5, -0.5), curl=0.95)
        # the line: plumb from the tip, swinging a little behind the rod's motion
        sway = V((0.035 * math.sin(ph + 0.6), 0.05 * math.sin(2 * ph + 1.0) - 0.10 * u, -1.0))
        p.aim("line", sway, (0, -1, 0))
        return p, r, m
    return fn, T, {}


def clip_craft(B, T=2.4):
    """hands busy at waist height: tying, kneading, weaving. For the trades that have no tool in the hand."""
    def fn(t):
        ph = 2 * math.pi * t / T
        p = B.pose()
        _stance(B, p, hips=(0.008 * math.sin(ph), -0.01, -0.045), hrot=(3, 0, 0), L=((0.0, -0.06, 0), 8, 0), Rr=((0.0, 0.04, 0), -12, 0))
        B.spine(p, bend=13 + 1.5 * math.sin(2 * ph), twist=3 * math.sin(ph))
        p.rot("neck", (8, 0, 0))
        p.rot("head", (14, 0, 3 * math.sin(ph)))
        C = B.chest_ref(p)
        rs = 0.0
        for s, sx, o in (("L", 1.0, 0.0), ("R", -1.0, math.pi)):
            a = 2 * ph + o
            G = V((sx * 0.105 + 0.02 * math.sin(a) * sx, -0.335 + 0.035 * math.cos(a), 1.015 + 0.04 * math.sin(a)))
            T_ = C @ B.grip_frame(s, G, (-0.50 * sx, -0.82, -0.22), (-sx * 0.75, 0.15, -0.6))
            r, m = B.place_hand(p, s, T_, pole=(0.8 * sx, 0.4, -0.45))
            rs = max(rs, r)
            B.curl(p, s, 0.55 + 0.25 * math.sin(a + 1.0))
        return p, rs, 0.0
    return fn, T, {}


WORK = {"chop": clip_chop, "mine": clip_mine, "hoe": clip_hoe, "hammer": clip_hammer, "chisel": clip_chisel, "saw": clip_saw, "cut": clip_cut, "fish": clip_fish, "craft": clip_craft}
# which props a clip is shown with in the QA strips (the game decides by trade)
SHOW = {"chop": ["Tool_ono"], "mine": ["Tool_tsuruhashi"], "hoe": ["Tool_kuwa"], "hammer": ["Tool_tsuchi"], "chisel": ["Tool_nomi", "Tool_tsuchi"], "saw": ["Tool_nokogiri"],
        "cut": ["Tool_kama"], "fish": ["Tool_tsurizao"], "craft": [], "walk_tool": ["Tool_kuwa"], "run_tool": ["Tool_ono"],
        "carry_shoulder_idle": ["Load_sack"], "carry_shoulder_walk": ["Load_log"], "carry_shoulder_run": ["Load_planks"],
        "carry_front_idle": ["Load_basket"], "carry_front_walk": ["Load_basket"], "carry_front_run": ["Load_basket"], "idle": ["Hat_kasa"], "walk": ["Hat_kasa"], "run": []}


# ---------------------------------------------------------------------------------------------------- out
def stride_speed(B, poses, fps=FPS):
    """the ground speed a locomotion cycle is made for: how fast the planted foot travels back under the body."""
    v = []
    pts = [{s: p.head(f"toe.{s}") for s in "LR"} for p in poses]
    zmin = min(min(q["L"].z, q["R"].z) for q in pts)
    for i in range(len(pts) - 1):
        for s in "LR":
            a, b = pts[i][s], pts[i + 1][s]
            if a.z < zmin + 0.022 and b.z < zmin + 0.022:
                v.append((b.y - a.y) * fps)
    v.sort()
    return float(np.median(v)) if v else 0.0


def write_action(arm, name, poses, loop):
    """one Action of quaternion keys (hemisphere-continuous; a loop's last key equals its first) + hips location."""
    arm.animation_data_create()
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data.action = act
    names = [b.name for b in arm.data.bones]
    n = len(poses) - 1
    prev = {}
    first = {}
    for f, pose in enumerate(poses):
        for bn in names:
            pb = arm.pose.bones[bn]
            Bm = pose.basis(bn)
            q = Bm.to_quaternion()
            if bn in prev and q.dot(prev[bn]) < 0:
                q.negate()
            if loop and f == n:
                q = first[bn][0].copy()
            prev[bn] = q
            pb.rotation_quaternion = q
            pb.keyframe_insert("rotation_quaternion", frame=1 + f)
            if bn == "hips":
                loc = Bm.to_translation()
                if loop and f == n:
                    loc = first[bn][1].copy()
                pb.location = loc
                pb.keyframe_insert("location", frame=1 + f)
            if f == 0:
                first[bn] = (q.copy(), Bm.to_translation())
    act.frame_range = (1, 1 + n)
    return act


def strip(B, low, objs, name, poses, out, show=(), n=8, size=440):
    for o in objs.values():
        o.hide_render = True
    vis = [low] + [objs[k] for k in show if k in objs]
    paths = []
    idx = [int(round(i * (len(poses) - 1) / n)) for i in range(n)]
    for view in ("q", "side_r"):
        for j, i in enumerate(idx):
            PO.show_pose(B.arm, poses[i])
            bpy.context.view_layer.update()
            paths += qa.shots(vis, os.path.join(out, f"_{name}_{view}_{j}"), views=(view,), size=size, focus=(0.0, -0.15, 0.98), span=2.45)
    sheet = os.path.join(out, f"clip_{name}.jpg")
    qa.sheet(paths, sheet, cols=n)
    for pth in paths:
        try:
            os.remove(pth)
        except OSError:
            pass
    return sheet


def run(work, mocap_dir, only=None, cfg=None, log=print):
    bpy.ops.wm.open_mainfile(filepath=os.path.join(work, "villager_skin.blend"))
    sc = bpy.context.scene
    sc.render.fps = FPS
    arm = bpy.data.objects["VillagerRig"]
    low = bpy.data.objects["Villager_LOD0"]
    with open(os.path.join(work, "hands.json")) as fh:
        hands = json.load(fh)
    B = Body(arm, hands, cfg)
    log(f"  body: arm reach x{B.k:.3f}, leg x{B.kl:.3f} of the reference")
    # props (with a preview material: the real strip of the atlas is painted in the finalize stage)
    img = props_bpy.strip_images(1024, "props_preview")
    pm = bpy.data.materials.new("props_preview")
    pm.use_nodes = True
    tn = pm.node_tree.nodes.new("ShaderNodeTexImage")
    tn.image = img
    pm.node_tree.links.new(tn.outputs["Color"], pm.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    objs = props_bpy.build_props(arm, sc.collection, hands, pm, hat_drop=(cfg or {}).get("hat_drop", 0.045))
    want = set(only.split(",")) if only else None
    out = os.path.join(work, "qa", "clips")
    os.makedirs(out, exist_ok=True)
    clips, report = {}, {}

    def keep(name, poses, loop, meta):
        clips[name] = (poses, loop, meta)

    need_mocap = want is None or any(not (w in WORK) for w in want)
    if need_mocap:
        src = {k: load_mocap(os.path.join(mocap_dir, f)) for k, f in MOCAP.items() if k in ("idle", "walk", "run")}
        # ---- idle: the calmest stretch of the take, about five seconds
        d, a, b = best_loop(src["idle"], 135, 190, step=3)
        idle = close_loop(detrend(src["idle"][a:b + 1])[0])
        log(f"  idle: frames {a}-{b} of {len(src['idle'])} (end mismatch {d:.4f})")
        # ---- walk: one full gait cycle (two steps)
        d, a, b = best_loop(src["walk"][8:-8], 26, 44)
        seg, travel = detrend(src["walk"][8 + a:8 + b + 1])
        walk = close_loop(seg)
        log(f"  walk: {b - a} frames (end mismatch {d:.4f}), root travelled {travel:.2f} m")
        # ---- run: the take is one cycle
        seg, travel_r = detrend(src["run"])
        run_ = close_loop(seg, tail=0.25)
        log(f"  run: {len(run_) - 1} frames, root travelled {travel_r:.2f} m")
        # the sim's villagers cover 1 to 2.6 m/s: a stroll (0.7 m/s) and a sprint (4.2 m/s) fit neither end. Same captures, re-pitched:
        # a brisk walk (longer stride, quicker cadence) and a porter's trot (the run with a shorter stride and less bounce)
        walk, dzw = ground(B, resample(amplify(walk, legs=1.28, arms=1.15, trunk=1.1, bounce=1.15), 32))
        run_, dzr = ground(B, resample(amplify(run_, legs=0.69, arms=0.60, trunk=0.7, bounce=0.55), 19))
        walk, kw = start_on_left_reach(B, walk)
        run_, kr = start_on_left_reach(B, run_)
        log(f"  re-pitched: walk 32 frames (hips {dzw * 1000:+.0f} mm), run 19 frames (hips {dzr * 1000:+.0f} mm); cycles rotated by {kw} / {kr} frames to start on the left foot's reach")
        bases = {"idle": idle, "walk": walk, "run": run_}
        for g in ("idle", "walk", "run"):
            fr = bases[g]
            poses = [B.pose(f) for f in fr]
            for p in poses:
                relaxed_hands(B, p)
            sp = abs(stride_speed(B, poses)) if g != "idle" else 0.0
            keep(g, poses, True, {"weapon": "none", "speed": sp})
            # a long tool at the trail
            if g != "idle":
                raw = [B.pose(f) for f in fr]
                ws = [(B.chest(p).inverted() @ p.head("hand.R")) for p in raw]
                wm = sum(ws, V()) / len(ws)
                rr = mm = 0.0
                for p, w in zip(raw, ws):
                    r, m = tool_trail(B, p, wm, w)
                    rr, mm = max(rr, r), max(mm, m)
                keep(f"{g}_tool", raw, True, {"weapon": "tool", "speed": sp, "reach": rr, "miss": mm})
            for kind, fnc in (("shoulder", shoulder_load), ("front", front_load)):
                raw = [B.pose(f) for f in fr]
                rr = mm = 0.0
                for p in raw:
                    r, m = fnc(B, p)
                    rr, mm = max(rr, r), max(mm, m)
                keep(f"carry_{kind}_{g}", raw, True, {"weapon": "load", "speed": sp, "reach": rr, "miss": mm})
    for name, mk in WORK.items():
        if want is not None and name not in want:
            continue
        fn, T, ev = mk(B)
        n = int(round(T * FPS))
        poses, rr, mm = [], 0.0, 0.0
        for f in range(n + 1):
            p, r, m = fn(T * (f % n) / n)
            poses.append(p)
            rr, mm = max(rr, r), max(mm, m)
        keep(name, poses, True, {"weapon": "tool" if name != "craft" else "none", "speed": 0.0, "events": ev, "reach": rr, "miss": mm})
        tool = {"chop": "ono", "mine": "tsuruhashi", "hoe": "kuwa", "hammer": "tsuchi"}.get(name)
        if tool:
            ends = [p.matrices()["tool_r"] @ V((0, P.HEAD_Z[tool], 0)) for p in poses]
            lowp = min(ends, key=lambda e: e.z)
            log(f"  {name}: working end lowest at ({lowp.x:+.2f}, {lowp.y:+.2f}, {lowp.z:+.2f}), highest z {max(e.z for e in ends):.2f}")
    for name, (poses, loop, meta) in clips.items():
        if want is not None and name not in want:
            continue
        low_z = min(min(p.head("toe.L").z, p.head("toe.R").z) for p in poses)
        report[name] = {"frames": len(poses) - 1, "speed_mps": round(meta.get("speed", 0.0), 3), "reach": round(meta.get("reach", 0.0), 3),
                        "miss_mm": round(meta.get("miss", 0.0) * 1000, 1), "toe_min_z": round(low_z, 3)}
        log(f"  clip {name}: " + json.dumps(report[name]))
        strip(B, low, objs, name, poses, out, show=SHOW.get(name, []))
    # ---- Actions
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)
    for name, (poses, loop, meta) in clips.items():
        act = write_action(arm, name, poses, loop)
        act["gp_loop"] = int(loop)
        act["gp_weapon"] = meta["weapon"]
        act["gp_weapon_end"] = meta["weapon"]
        act["gp_events"] = json.dumps(meta.get("events", {}))
        act["gp_fps"] = FPS
        act["gp_speed"] = float(meta.get("speed", 0.0))
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    for o in objs.values():
        o.hide_render = False
    bpy.context.view_layer.update()
    with open(os.path.join(work, "clips_report.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    if want is None:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, "villager_anim.blend"), compress=True)
    return report
