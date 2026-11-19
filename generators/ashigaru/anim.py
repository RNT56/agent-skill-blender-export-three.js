"""Animation solver of the ashigaru: character-level parameters -> a full pose. Clips (clips.py) are functions t -> params.

What is special here is the SPEAR. A clip says where the shaft is (the point the right hand holds, the direction to the head) and how far from the butt each hand
holds it; the solver then
  * puts the right hand on the shaft (grip centre on the line, thumb toward the head, turned about the shaft as the clip asks) and the arm on it by IK,
  * slides the spear through that hand (a location key on the weapon bone: the hand's place on the shaft changes between the guard, the carry and standing at ease),
  * puts the left hand on the same line, further up the shaft (in a thrust the shaft runs forward through it), or lets it hang / swing when the clip leaves it free,
  * holds the long pike a little further up than the short spear where the clip says so (`pike_up`): its own weapon bone, the same hands.
Every clip ends up as plain FK keys (plus location keys on hips and the two weapon bones). Space: armature space, +Z up, the character faces -Y, left = +X.
"""
import json
import math

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from samurai.pose import Pose, Rig, key_pose

from . import cloth as cloth_mod, rig as R

V = Vector
FPS = 30


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def frame3(a, b):
    """orthonormal 3x3 with columns (a, b made perpendicular to a, a x b)"""
    a = V(a).normalized()
    b = V(b) - a * V(b).dot(a)
    b.normalize()
    M = Matrix.Identity(3)
    M.col[0], M.col[1], M.col[2] = a, b, a.cross(b)
    return M


class Solver:
    def __init__(self, arm_obj):
        self.rig = r = Rig(arm_obj)
        self.D0 = R.spear_rest()["D"].copy()
        self.grip0, self.F0, self.wr_rest, self.R_h = {}, {}, {}, {}
        for s in "LR":
            G, D, N, wr = R.grip_rest(s)
            self.grip0[s] = G
            self.F0[s] = frame3(D, N)                                    # the rest hand's grip frame: shaft axis toward the thumb, palm-to-shaft normal
            self.wr_rest[s] = r.head[f"hand.{s}"].copy()
            self.R_h[s] = r.rest_rot[f"hand.{s}"].copy()
        self.foot_rest_dir = (r.tail["foot.L"] - r.head["foot.L"]).normalized()
        self.thigh_dir = {s: (r.tail[f"thigh.{s}"] - r.head[f"thigh.{s}"]).normalized() for s in "LR"}
        self.skirt = [n for n in r.names if n.startswith("skirt_")]
        self.reach = {s: 0.992 * (r.length[f"upper_arm.{s}"] + r.length[f"forearm.{s}"]) for s in "LR"}
        self.last_shift = 0.0            # how far the spear had to come in for the right hand to reach it (m)
        self.last_gap = 0.0              # how far the left hand's grip is from where the clip put it on the shaft (m): it slid toward the right hand to reach

    # -------------------------------------------------------------------------------------------------- pieces
    def spine(self, p, P):
        sp = P.get("spine", (0, 0, 0))
        for n, w in (("spine", 0.28), ("spine1", 0.36), ("chest", 0.36)):
            p.rot(n, tuple(a * w for a in sp))
        nk = P.get("neck", (0, 0, 0))
        p.rot("neck", tuple(a * 0.45 for a in nk))
        p.rot("head", tuple(a * 0.55 for a in nk))

    def leg(self, p, side, F):
        if F is None:
            return
        sx = 1.0 if side == "L" else -1.0
        yaw, pitch = math.radians(F.get("yaw", 0.0)), math.radians(F.get("pitch", 0.0))
        Rz = Euler((0, 0, math.radians(F.get("knee", F.get("yaw", 0.0)))), "XYZ").to_matrix()
        pole = V(F["kpole"]) if "kpole" in F else Rz @ V((0.10 * sx, -1.0, 0.1))
        p.limb(f"thigh.{side}", f"shin.{side}", f"foot.{side}", V(F["pos"]), pole, 1)
        d = Euler((pitch, 0, 0), "XYZ").to_matrix() @ self.foot_rest_dir
        d = Euler((0, 0, yaw), "XYZ").to_matrix() @ d
        up = V((0, 0, 1))
        if F.get("instep"):                 # the foot turns rigidly by its pitch (an instep on the ground): past ~70 deg the up hint would roll it 180 deg and wring the ankle
            up = Euler((pitch, 0, 0), "XYZ").to_matrix() @ up
        p.aim(f"foot.{side}", d, Euler((0, 0, yaw), "XYZ").to_matrix() @ up)
        p.rot(f"toe.{side}", (F.get("toe", 0.0), 0, 0))

    def arm_ik(self, p, side, wrist, pole=None):
        sx = 1.0 if side == "L" else -1.0
        pole = V(pole) if pole is not None else V((0.55 * sx, 0.45, -0.7))
        return p.limb(f"upper_arm.{side}", f"forearm.{side}", f"hand.{side}", V(wrist), pole, -1)

    def grip(self, p, side, C, D, N, pole):
        """Put a hand's grip centre at C with the shaft along D and the palm-to-shaft normal toward N. Returns the grip centre it reached."""
        Q = frame3(D, N) @ self.F0[side].inverted()
        off = Q @ (self.wr_rest[side] - self.grip0[side])
        self.arm_ik(p, side, C + off, pole)
        p._place(f"hand.{side}", Q @ self.R_h[side])
        return p.matrices()[f"hand.{side}"].translation - off

    def fingers(self, p, P):
        for side, sx in (("L", 1.0), ("R", -1.0)):
            c = P.get(f"curl_{side}", 0.18)
            for fn, k in (("index", 1.0), ("middle", 1.05), ("ring", 1.0), ("pinky", 0.95)):
                p.rot(f"{fn}_01.{side}", (0, sx * 62.0 * c * k, 0))
                p.rot(f"{fn}_02.{side}", (0, sx * 80.0 * c * k, 0))
            p.rot(f"thumb_01.{side}", (0, sx * 25.0 * c, 0))
            p.rot(f"thumb_02.{side}", (0, sx * 38.0 * c, 0))

    def secondary(self, p):
        """the tassets swing with the thighs (the samurai's rule)"""
        if not self.skirt:
            return
        for s in "LR":
            td = (p.tail(f"thigh.{s}") - p.head(f"thigh.{s}")).normalized()
            f = math.atan2(td.y, -td.z) - math.atan2(self.thigh_dir[s].y, -self.thigh_dir[s].z)       # + = the leg swings back
            fw = min(f, 0.0) * 0.55 + max(f, 0.0) * 0.12
            bk = max(f, 0.0) * 0.55 + min(f, 0.0) * 0.12
            for n, a in ((f"skirt_front.{s}", fw), (f"skirt_back.{s}", bk), (f"skirt_side.{s}", 0.5 * (fw + bk))):
                if n in self.rig.parent:
                    p.D[n] = Euler((a, 0, 0), "XYZ").to_quaternion()
        p._M = None

    # -------------------------------------------------------------------------------------------------- main entry
    def solve(self, P):
        p = Pose(self.rig)
        p.move("hips", V(P.get("hips_pos", (0, 0, 0))))
        p.rot("hips", P.get("hips_rot", (0, 0, 0)))
        self.spine(p, P)
        self.leg(p, "L", P.get("footL"))
        self.leg(p, "R", P.get("footR"))
        S = P["spear"]
        D = V(S["D"]).normalized()
        B = V(S["B"])
        gR = float(P.get("gripR", R.GRIP0))
        # ---- the right hand on the shaft; out of reach: bring the spear in toward the shoulder, never open the grip
        Q = frame3(D, V(S["nR"])) @ self.F0["R"].inverted()
        off = Q @ (self.wr_rest["R"] - self.grip0["R"])
        sh = p.head("upper_arm.R")
        B0 = B.copy()
        for _ in range(8):
            d = (B + off) - sh
            if d.length <= self.reach["R"]:
                break
            B = B - d.normalized() * (d.length - self.reach["R"]) * 0.9
        self.last_shift = (B - B0).length
        self.grip(p, "R", B, D, V(S["nR"]), S.get("poleR", (-0.55, 0.50, -0.65)))
        p.move("weapon_r", -self.D0 * (gR - R.GRIP0))
        p.move("weapon_r2", -self.D0 * (gR + float(P.get("pike_up", 0.0)) - R.GRIP0))
        # ---- the left hand: on the shaft `slide` metres ahead of the right, or free
        self.last_gap = 0.0
        sl = P.get("slide")
        w = smooth(float(P.get("lhand", 1.0 if sl is not None else 0.0)))                 # 1 = on the shaft, 0 = free
        M = p.matrices()
        T = M["hips"] @ self.rig.rest["hips"].inverted()
        H = P.get("handL") or dict(pos=V((0.330, -0.030, 0.872)), pole=V((0.55, 0.45, -0.7)))
        hp = H.get("space", "hips") == "hips"
        wf = (T @ V(H["pos"])) if hp else V(H["pos"])
        polef = V(H.get("pole", (0.55, 0.45, -0.7)))
        if w < 1e-4 or sl is None:
            self.arm_ik(p, "L", wf, polef)
        else:
            nL = V(S.get("nL", (0.0, 0.0, 1.0)))
            QL = frame3(D, nL) @ self.F0["L"].inverted()
            offL = QL @ (self.wr_rest["L"] - self.grip0["L"])
            shL = p.head("upper_arm.L")
            s = float(sl)
            for _ in range(10):                                                           # out of reach: the hand comes down the shaft toward the other
                d = (B + D * s + offL) - shL
                if d.length <= self.reach["L"] or s <= 0.12:
                    break
                s = max(0.12, s - (d.length - self.reach["L"]) * 1.1)
            self.last_gap = abs(float(sl) - s) if w > 0.999 else 0.0
            ws = B + D * s + offL
            poleL = V(S.get("poleL", (0.55, 0.30, -0.75)))
            if w > 0.999:
                self.arm_ik(p, "L", ws, poleL)
                p._place("hand.L", QL @ self.R_h["L"])
            else:
                self.arm_ik(p, "L", wf, polef)
                Ff = p.matrices()["hand.L"].to_3x3()
                F = Ff.to_quaternion().slerp((QL @ self.R_h["L"]).to_quaternion(), w).to_matrix()
                self.arm_ik(p, "L", wf.lerp(ws, w), polef.lerp(poleL, w))
                p._place("hand.L", F)
        self.fingers(p, P)
        self.secondary(p)
        return p


def bake(arm_obj, solver, name, fn, duration, loop=True, fps=FPS, speed=0.0, cloth=True):
    """Solve every frame of the clip, simulate the cloth chains on that body motion, then write one Action of FK keys. Looping clips repeat frame 0 at the end."""
    arm_obj.animation_data_create()
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm_obj.animation_data.action = act
    for pb in arm_obj.pose.bones:
        pb.rotation_mode = "QUATERNION"
    n = int(round(duration * fps))
    poses, shift, gap = [], 0.0, 0.0
    for f in range(n + 1):
        t = duration * f / n
        if loop and f == n:
            t = 0.0
        poses.append(solver.solve(fn(t)))
        shift, gap = max(shift, solver.last_shift), max(gap, solver.last_gap)
    if cloth:
        act["gp_cloth"] = json.dumps(cloth_mod.simulate(solver.rig, poses, loop, duration, speed, name))
    for f, pose in enumerate(poses):
        key_pose(arm_obj, pose, 1 + f)
    act.frame_range = (1, 1 + n)
    act["gp_spear_shift_mm"] = round(shift * 1000.0, 1)
    act["gp_hand_slip_mm"] = round(gap * 1000.0, 1)
    return act
