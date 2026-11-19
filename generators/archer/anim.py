"""Animation solver of the archer: character-level parameters -> a full pose. Clips (clips.py) are functions t -> params.

What is special here is the BOW. A clip says where the bow is (grip position, the direction to the target, the direction up the bow) and how far the string is drawn;
the solver then
  * puts the bow hand rigidly on the grip (the bow is a child of hand.L, modelled in its grip) and the arm on it by IK,
  * moves the nock point back along the bow's own draw axis and flexes the two bones of each limb by the angle that keeps the string's length constant,
  * blends the string hand between a free target (quiver, rest) and its place on the string,
  * lays the arrow from the string hand's pinch point to the arrow rest on the bow hand.
Every clip ends up as plain FK keys (plus location keys on hips, bow_nock and arrow). Space: armature space, +Z up, the character faces -Y, left = +X.
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


def _rot2(p, a):
    c, s = math.cos(a), math.sin(a)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


class BowModel:
    """The strung bow in its own plane (u toward the target, w up): how far the limbs must bend for a given pull so the string keeps its length."""

    def __init__(self):
        u1, u2, l1, l2 = R.BOW_J
        self.J = [(R.bow_f(w), w) for w in (u1, u2, l1, l2)]
        tu, tl = R.BOW_UP - 0.012, -R.BOW_DN + 0.012
        self.T = [(R.bow_f(tu) - 0.0065, tu), (R.bow_f(tl) - 0.0065, tl)]                 # where the string is tied (as modelled in bow.py)
        self.L0 = self.length(0.0, 0.0)

    def tips(self, a):
        (j1, j2, k1, k2), (tu, tl) = self.J, self.T
        d1, d2 = (j2[0] - j1[0], j2[1] - j1[1]), (tu[0] - j2[0], tu[1] - j2[1])
        r1, r2 = _rot2(d1, a), _rot2(d2, 2 * a)
        up = (j1[0] + r1[0] + r2[0], j1[1] + r1[1] + r2[1])
        e1, e2 = (k2[0] - k1[0], k2[1] - k1[1]), (tl[0] - k2[0], tl[1] - k2[1])
        s1, s2 = _rot2(e1, -a), _rot2(e2, -2 * a)
        lo = (k1[0] + s1[0] + s2[0], k1[1] + s1[1] + s2[1])
        return up, lo

    def length(self, a, pull):
        up, lo = self.tips(a)
        n = (-R.BRACE - pull, R.NOCK_H)
        return math.hypot(up[0] - n[0], up[1] - n[1]) + math.hypot(lo[0] - n[0], lo[1] - n[1])

    def flex(self, pull):
        """limb joint angle (radians, each of the two joints of a limb) for a pull of the nock point (metres)"""
        lo, hi = -0.12, 0.60
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if self.length(mid, pull) > self.L0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)


class Solver:
    def __init__(self, arm_obj):
        self.rig = r = Rig(arm_obj)
        b = R.bow_rest()
        self.G0, self.U0, self.W0 = b["G"].copy(), b["U"].copy(), b["W"].copy()
        self.B0 = frame3(self.U0, self.W0)
        self.kflex = self.U0.cross(self.W0).normalized()                 # the limbs bend about this axis: + turns the upper limb toward the string
        self.bow = BowModel()
        self.wr_rest = {s: r.head[f"hand.{s}"].copy() for s in "LR"}
        self.R_h = {s: r.rest_rot[f"hand.{s}"].copy() for s in "LR"}
        wr, d, n, th = R.hand_frame("R")
        self.HR0 = frame3(d, n)                                          # string hand: fingers, palm normal
        self.pinch0 = R.pinch_rest("R")
        self.nock0, self.rest0 = R.nock0(), R.arrow_rest()
        self.arrow_head0 = r.head["arrow"].copy()
        self.foot_rest_dir = (r.tail["foot.L"] - r.head["foot.L"]).normalized()
        self.last_shift = 0.0            # how far the bow had to be pulled in for the bow hand to reach it (m)
        self.last_gap = 0.0              # distance between the string hand's pinch point and the nock when it should be on the string (m)

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

    def bow_hand(self, p, B):
        """Place the bow (G, U, W) and the bow hand on it. Returns (Q, G): the rotation from the rest bow to the posed bow and the grip actually used."""
        Bw = frame3(B["U"], B["W"])
        Q = Bw @ self.B0.inverted()
        G = V(B["G"])
        sh = p.head("upper_arm.L")
        lim = 0.992 * (p.rig.length["upper_arm.L"] + p.rig.length["forearm.L"])
        off = Q @ (self.wr_rest["L"] - self.G0)
        for _ in range(8):                                   # out of reach: bring the bow in toward the shoulder, never open the grip
            d = (G + off) - sh
            if d.length <= lim:
                break
            G = G - d.normalized() * (d.length - lim) * 0.9
        self.last_shift = (G - V(B["G"])).length
        self.arm_ik(p, "L", G + off, B.get("pole"))
        p._place("hand.L", Q @ self.R_h["L"])
        return Q, G

    def fingers(self, p, P):
        for side, sx in (("L", 1.0), ("R", -1.0)):
            c = P.get(f"curl_{side}", 0.18)
            for fn, k in (("index", 1.0), ("middle", 1.05), ("ring", 1.0), ("pinky", 0.95)):
                p.rot(f"{fn}_01.{side}", (0, sx * 62.0 * c * k, 0))
                p.rot(f"{fn}_02.{side}", (0, sx * 80.0 * c * k, 0))
            p.rot(f"thumb_01.{side}", (0, sx * 25.0 * c, 0))
            p.rot(f"thumb_02.{side}", (0, sx * 38.0 * c, 0))

    # -------------------------------------------------------------------------------------------------- main entry
    def solve(self, P):
        p = Pose(self.rig)
        p.move("hips", V(P.get("hips_pos", (0, 0, 0))))
        p.rot("hips", P.get("hips_rot", (0, 0, 0)))
        self.spine(p, P)
        self.leg(p, "L", P.get("footL"))
        self.leg(p, "R", P.get("footR"))
        # ---- the bow and the bow hand
        Q, G = self.bow_hand(p, P["bow"])
        Uw, Ww = Q @ self.U0, Q @ self.W0
        pull = float(P.get("draw", 0.0)) * R.PULL
        a = self.bow.flex(pull)
        qa = Quaternion(self.kflex, a)
        p.D["bow_u1"], p.D["bow_u2"] = qa.copy(), qa.copy()
        qb = Quaternion(self.kflex, -a)
        p.D["bow_l1"], p.D["bow_l2"] = qb.copy(), qb.copy()
        p.move("bow_nock", -self.U0 * pull)
        N = G + Q @ (self.nock0 - self.G0) - Uw * pull                    # the nock point of the string
        rest = G + Q @ (self.rest0 - self.G0)                             # where the shaft lies on the bow hand
        # ---- the string hand: free target first, then blended onto the string
        M = p.matrices()
        T = M["hips"] @ self.rig.rest["hips"].inverted()
        H = P.get("handR")
        if H is None:
            wf = M["chest"] @ self.rig.rest["chest"].inverted() @ (self.wr_rest["R"] + V((0.0, -0.03, 0.02)))
            polef = V((-0.55, 0.45, -0.7))
            self.arm_ik(p, "R", wf, polef)
        elif "pinch" in H:                                               # the pinch point (thumb and fingers) at a place, the hand turned by (fingers, palm normal)
            hp = H.get("space", "hips") == "hips"
            R3 = T.to_3x3() if hp else Matrix.Identity(3)
            Qf = frame3(R3 @ V(H["dir"]), R3 @ V(H["palm"])) @ self.HR0.inverted()
            wf = ((T @ V(H["pinch"])) if hp else V(H["pinch"])) - Qf @ (self.pinch0 - self.wr_rest["R"])
            polef = V(H.get("pole", (-0.55, 0.45, -0.7)))
            self.arm_ik(p, "R", wf, polef)
            p._place("hand.R", Qf @ self.R_h["R"])
        else:
            hp = H.get("space", "hips") == "hips"
            wf = (T @ V(H["pos"])) if hp else V(H["pos"])
            polef = V(H.get("pole", (-0.55, 0.45, -0.7)))
            self.arm_ik(p, "R", wf, polef)
            if "dir" in H:
                d = (T.to_3x3() @ V(H["dir"])) if hp else V(H["dir"])
                z = (T.to_3x3() @ V(H.get("hint", (0, 0, 1)))) if hp else V(H.get("hint", (0, 0, 1)))
                p.aim("hand.R", d, z)
        w = smooth(float(P.get("nockw", 0.0)))
        if w > 1e-4:
            Ff = p.matrices()["hand.R"].to_3x3()
            tilt = math.radians(P.get("string_tilt", 18.0))               # the back of the string hand is turned up and a little outward
            nS = -Ww * math.cos(tilt) + Uw.cross(Ww) * math.sin(tilt)
            Qr = frame3(Uw, nS) @ self.HR0.inverted()
            Fs = Qr @ self.R_h["R"]
            ws = N - Qr @ (self.pinch0 - self.wr_rest["R"])
            F = Ff.to_quaternion().slerp(Fs.to_quaternion(), w).to_matrix()
            pole = polef.lerp(V(P.get("string_pole", (0.25, 1.0, 0.10))), w)
            self.arm_ik(p, "R", wf.lerp(ws, w), pole)
            p._place("hand.R", F)
        self.fingers(p, P)
        # ---- the arrow: from the string hand's pinch point toward the arrow rest (nocked) or along a free direction (in the quiver, on the way)
        Mh = p.matrices()["hand.R"]
        Qh = Mh.to_3x3() @ self.R_h["R"].inverted()
        pinch = Mh.translation + Qh @ (self.pinch0 - self.wr_rest["R"])
        self.last_gap = (pinch - N).length if float(P.get("nockw", 0.0)) > 0.999 else 0.0
        wa = smooth(float(P.get("arrow_w", P.get("nockw", 0.0))))
        A = P.get("arrow")
        if A is not None:
            hp = A.get("space", "hips") == "hips"
            df = ((T.to_3x3() @ V(A["dir"])) if hp else V(A["dir"])).normalized()
            o = (T @ V(A["pos"])) if (hp and "pos" in A) else (V(A["pos"]) if "pos" in A else pinch)
            o = o.lerp(pinch, smooth(float(A.get("grab", 1.0))))
        else:
            df, o = Qh @ V((0.0, -1.0, 0.0)), pinch
        dn = rest - o
        dn = dn.normalized() if dn.length > 1e-6 else Uw
        ad = df.lerp(dn, wa)
        ad = ad.normalized() if ad.length > 1e-6 else dn
        p.move("arrow", o - self.arrow_head0)
        p.aim("arrow", ad, Ww)
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
    act["gp_bow_shift_mm"] = round(shift * 1000.0, 1)
    act["gp_string_gap_mm"] = round(gap * 1000.0, 1)
    return act
