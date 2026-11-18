"""Animation solver: character-level parameters -> a full pose (hips/spine/head, planted-foot leg IK, arm IK, two-handed sword grip,
finger curl, sode / kusazuri secondary motion). Clips (clips.py) are functions t -> params; `solve` turns params into a Pose,
`bake` writes one Action of FK keys per clip. Space: armature space, +Z up, character faces -Y, left = +X.
"""
import math

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import katana as K, rig as R
from .pose import Pose, Rig, key_pose

V = Vector
FPS = 30
MX = Matrix.Diagonal((-1.0, 1.0, 1.0))


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def eul(r):
    return Euler([math.radians(a) for a in r], "XYZ").to_quaternion()


def sword_frame(A, E):
    """3x3 frame (x=edge, y=tip direction, z=flat) like katana.placement."""
    y = V(A).normalized()
    x = (V(E) - y * V(E).dot(y))
    if x.length < 1e-6:
        x = V((0, 0, 1)) - y * y.z
    x.normalize()
    z = x.cross(y).normalized()
    M = Matrix.Identity(3)
    M.col[0], M.col[1], M.col[2] = x, y, z
    return M


class Solver:
    def __init__(self, arm_obj):
        self.rig = Rig(arm_obj)
        r = self.rig
        go, gt = R.grip_origin()
        self.M_hand = K.placement(go, gt, V((0, 0, -1)))
        self.Mh3 = self.M_hand.to_3x3()
        self.go = go
        self.wr_rest = {s: r.head[f"hand.{s}"].copy() for s in "LR"}
        self.R_h_rest = {s: r.rest_rot[f"hand.{s}"].copy() for s in "LR"}
        self.up_dir = {s: (r.tail[f"upper_arm.{s}"] - r.head[f"upper_arm.{s}"]).normalized() for s in "LR"}
        self.thigh_dir = {s: (r.tail[f"thigh.{s}"] - r.head[f"thigh.{s}"]).normalized() for s in "LR"}
        self.foot_rest_dir = (r.tail["foot.L"] - r.head["foot.L"]).normalized()
        self.last_shift = 0.0

    # -------------------------------------------------------------------------------------------------- pieces
    def spine(self, p, P):
        sp = P.get("spine", (0, 0, 0))
        for n, w in (("spine", 0.28), ("spine1", 0.36), ("chest", 0.36)):
            p.rot(n, tuple(a * w for a in sp))
        nk = P.get("neck", (0, 0, 0))
        p.rot("neck", tuple(a * 0.45 for a in nk))
        p.rot("head", tuple(a * 0.55 for a in nk))

    def leg(self, p, side, F):
        sx = 1.0 if side == "L" else -1.0
        if F is None:
            return
        tgt = V(F["pos"])
        p.limb(f"thigh.{side}", f"shin.{side}", f"foot.{side}", tgt, V((0.10 * sx, -1.0, 0.1)), 1)
        yaw, pitch = math.radians(F.get("yaw", 0.0)), math.radians(F.get("pitch", 0.0))
        d = self.foot_rest_dir.copy()
        d = Euler((pitch, 0, 0), "XYZ").to_matrix() @ d
        d = Euler((0, 0, yaw), "XYZ").to_matrix() @ d
        p.aim(f"foot.{side}", d, Euler((0, 0, yaw), "XYZ").to_matrix() @ V((0, 0, 1)))
        p.rot(f"toe.{side}", (F.get("toe", 0.0), 0, 0))

    def arm_ik(self, p, side, wrist, roll_pole=None):
        sx = 1.0 if side == "L" else -1.0
        pole = V(roll_pole) if roll_pole is not None else V((0.55 * sx, 0.45, -0.7))
        return p.limb(f"upper_arm.{side}", f"forearm.{side}", f"hand.{side}", V(wrist), pole, -1)

    def sword(self, p, S, one_hand=False):
        """Two-handed grip. S = dict(O, A, E). The right hand moves rigidly with the sword; the left hand is its mirror image
        across the sword's flat plane, slid 0.125 m toward the pommel. If a hand cannot reach its grip the SWORD is nudged toward
        the shoulders (orientation kept) until both hands can, so the grip never opens up."""
        Fw = sword_frame(S["A"], S["E"])
        Q = Fw @ self.Mh3.inverted()
        n = Fw.col[2].normalized()
        T = Matrix.Identity(3)
        for i in range(3):
            for j in range(3):
                T[i][j] -= 2.0 * n[i] * n[j]
        A = V(S["A"]).normalized()
        shift = S.get("left_shift", 0.125)
        O = V(S["O"])
        sh = {s_: p.head(f"upper_arm.{s_}") for s_ in "LR"}
        lim = 0.985 * (p.rig.length["upper_arm.R"] + p.rig.length["forearm.R"])
        for _ in range(10):
            Wr = O + Q @ (self.wr_rest["R"] - self.go)
            Wl = O + T @ (Wr - O) - A * shift
            push, cnt = V((0, 0, 0)), 0
            for W, s_ in ((Wr, "R"), (Wl, "L")):
                if one_hand and s_ == "L":
                    continue
                d = W - sh[s_]
                if d.length > lim:
                    push += -d.normalized() * (d.length - lim)
                    cnt += 1
            if not cnt:
                break
            O = O + push * 0.8
        self.last_shift = (O - V(S["O"])).length
        self.arm_ik(p, "R", Wr)
        FhR = Q @ self.R_h_rest["R"]
        p._place("hand.R", FhR)
        if one_hand:
            return
        self.arm_ik(p, "L", Wl)
        FhL = T @ FhR @ Matrix.Diagonal((-1.0, 1.0, 1.0))
        p._place("hand.L", FhL)

    def fingers(self, p, P):
        for side, sx in (("L", 1.0), ("R", -1.0)):
            c = P.get(f"curl_{side}", 0.18)
            for fn, k in (("index", 1.0), ("middle", 1.05), ("ring", 1.0), ("pinky", 0.95)):
                p.rot(f"{fn}_01.{side}", (0, sx * 62.0 * c * k, 0))
                p.rot(f"{fn}_02.{side}", (0, sx * 80.0 * c * k, 0))
            p.rot(f"thumb_01.{side}", (0, sx * 25.0 * c, 0))
            p.rot(f"thumb_02.{side}", (0, sx * 38.0 * c, 0))

    def secondary(self, p, P):
        M = p.matrices()
        for s in "LR":
            # sode follows the arm's elevation
            ad = (p.tail(f"upper_arm.{s}") - p.head(f"upper_arm.{s}")).normalized()
            rot = self.up_dir[s].rotation_difference(ad)
            p.D[f"sode.{s}"] = Quaternion().slerp(rot, 0.28)
            # kusazuri panels swing with hip flexion
            td = (p.tail(f"thigh.{s}") - p.head(f"thigh.{s}")).normalized()
            f = math.atan2(td.y, -td.z) - math.atan2(self.thigh_dir[s].y, -self.thigh_dir[s].z)       # + = leg swings back
            fw = min(f, 0.0) * 0.55 + max(f, 0.0) * 0.12
            bk = max(f, 0.0) * 0.55 + min(f, 0.0) * 0.12
            p.D[f"skirt_front.{s}"] = Euler((fw, 0, 0), "XYZ").to_quaternion()
            p.D[f"skirt_back.{s}"] = Euler((bk, 0, 0), "XYZ").to_quaternion()
            p.D[f"skirt_side.{s}"] = Euler((0.5 * (fw + bk), 0, 0), "XYZ").to_quaternion()
        p._M = None

    # -------------------------------------------------------------------------------------------------- main entry
    def solve(self, P):
        p = Pose(self.rig)
        hp = V(P.get("hips_pos", (0, 0, 0)))
        p.move("hips", hp)
        p.rot("hips", P.get("hips_rot", (0, 0, 0)))
        if "root_rot" in P:
            p.rot("root", P["root_rot"])
        self.spine(p, P)
        self.leg(p, "L", P.get("footL"))
        self.leg(p, "R", P.get("footR"))
        sw = P.get("sword")
        one = sw is not None and float(sw.get("one_hand", 0.0)) > 0.5
        if sw is not None:
            self.sword(p, sw, one_hand=one)
        sides = (("L", 1.0), ("R", -1.0)) if sw is None else ((("L", 1.0),) if one else ())
        if sides:
            M = p.matrices()
            T = M["hips"] @ self.rig.rest["hips"].inverted()
            for s, sx in sides:
                H = P.get(f"hand{s}")
                if H is None:                               # relaxed arm hanging from the shoulder
                    rest = self.wr_rest[s] + V((0.0 * sx, -0.03, 0.02))
                    tgt = M["chest"] @ self.rig.rest["chest"].inverted() @ rest
                    self.arm_ik(p, s, tgt)
                else:
                    sp = H.get("space", "hips")
                    tgt = (T @ V(H["pos"])) if sp == "hips" else V(H["pos"])
                    self.arm_ik(p, s, tgt, H.get("pole"))
                    if "dir" in H:
                        d = (T.to_3x3() @ V(H["dir"])) if sp == "hips" else V(H["dir"])
                        z = (T.to_3x3() @ V(H.get("hint", (0, 0, 1)))) if sp == "hips" else V(H.get("hint", (0, 0, 1)))
                        p.aim(f"hand.{s}", d, z)
        self.fingers(p, P)
        self.secondary(p, P)
        return p


def bake(arm_obj, solver, name, fn, duration, loop=True, fps=FPS):
    """Sample params fn(t) (t in seconds) and write one Action of FK keys. Looping clips repeat frame 0 at the end."""
    arm_obj.animation_data_create()
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm_obj.animation_data.action = act
    for pb in arm_obj.pose.bones:
        pb.rotation_mode = "QUATERNION"
    n = int(round(duration * fps))
    for f in range(n + 1):
        t = duration * f / n
        if loop and f == n:
            t = 0.0
        pose = solver.solve(fn(t))
        key_pose(arm_obj, pose, 1 + f)
    act.frame_range = (1, 1 + n)
    # linear-safe: leave Blender's default Bezier (sampled densely, so it is nearly identical to linear)
    return act
