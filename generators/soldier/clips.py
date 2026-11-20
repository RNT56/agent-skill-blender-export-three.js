"""Stage `clips`: the ashigaru's clips (ashigaru.clips: written for the procedural v1 body) RE-FITTED to the reconstructed man, then baked as plain FK keys.

The clips are functions t -> character parameters in metres for the v1 skeleton (0.81 m legs, 0.55 m arms, shoulders at 1.405 m). The reconstructed man has
his own joints (legs 0.74 m, arms 0.46 m as the auto-rig placed them, shoulders at 1.35 m). Nothing is re-authored: every frame is solved TWICE.
  1. on a v1 skeleton built here only for that (the REFERENCE): where its shoulders are, how its chest is turned;
  2. on the man: hips and feet scaled by the leg ratio (a stride, a crouch and so a clip's ground speed scale with it), the planted ankle at HIS ankle height;
     the spear, the hand that is free and every other point in space carried over RELATIVE TO THE CHEST (the reference's shoulder line put on his, distances
     scaled by the arm ratio), so a hand that reached is still at the end of an arm that reaches. A spear that stood on the ground still does (the hand slides
     on the shaft to make it so). Spine and head angles are his as they were.
The thrusts stay on the simulation's clock (the impact frame is the same frame). Cloth chains (pennant, banner pole, flag) are simulated dry on the man's own
motion (samurai.cloth), as before.

    blender -b --factory-startup -P generators/soldier_unit.py -- --unit ashigaru --stage clips [--only idle,thrust_high] --work <dir>   -> <work>/<unit>/anim.blend, qa/
"""
import json
import math
import os

import bpy
from mathutils import Matrix, Quaternion, Vector

from ashigaru import anim as AA, clips as AC, rig as AR
from samurai import cloth as SC
from samurai.pose import Pose, Rig, key_pose
from villager import qa, rig as VR

V = Vector
FPS = 30
AZ_REF = AC.AZ                 # the planted ankle height the clips are written with


SWING_POLE = (0.5, 0.6, -0.5)             # the elbow hint ashigaru.clips.locomotion gives the swinging arm: how that arm is recognised


def swing_arm(p, rig, side, sw, bend, reach, sink=0.0):
    """A free arm in a gait. sw: the clip's fore-aft swing (metres of wrist travel on the v1 body, + = back), bend: 0 a walk (the arm hangs nearly
    straight and swings like a pendulum), 1 a run (the elbow at a right angle, the fist pumping past the hip). Returns a hand target in armature space."""
    sx = 1.0 if side == "L" else -1.0
    sh = p.head(f"upper_arm.{side}")
    T = p.matrices()["hips"].to_3x3() @ rig.rest["hips"].to_3x3().inverted()
    phi = math.radians(-6.0 - 22.0 * bend) + (sw / 0.18) * math.radians(19.0 + 6.0 * bend)        # + = back; a run carries the fists ahead of the hips
    dist = reach * (0.965 - 0.245 * bend - 0.03 * max(0.0, -sw) / 0.18 - 0.5 * sink)             # the elbow closes a little on the forward swing
    d = V((0.06 * sx, math.sin(phi), -math.cos(phi))).normalized()
    pole = V((0.04 * sx, 1.0, -0.25 - 0.45 * (1.0 - bend)))                                       # the elbow points back
    return dict(pos=sh + T @ (d * dist), pole=T @ pole, space="world")


GUARD_ELBOW = (-0.45, 0.75, -0.55)
EASE_DROP = 0.10
STANCE = 0.128                 # half the least distance between the feet's tracks (m)
CARRY_PALM = (0.86, -0.48, 0.12)      # from the palm toward the shaft when a spear is carried upright
FREE_ELBOW, CARRY_ELBOW = 0.75, 0.80        # how far a free arm's / an upright spear arm's elbow hint goes toward a hanging elbow


def smooth(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


class RefitSolver(AA.Solver):
    def __init__(self, arm, hands, spear, ref):
        self.rig = r = Rig(arm)
        self.ref = ref
        self.hands = hands
        rr = ref.rig
        leg = lambda R_: R_.length["thigh.L"] + R_.length["shin.L"]
        reach = lambda R_: R_.length["upper_arm.L"] + R_.length["forearm.L"]
        self.kl = leg(r) / leg(rr)
        self.ka = reach(r) / reach(rr)
        self.ankle = 0.5 * (r.head["foot.L"].z + r.head["foot.R"].z) + 0.008        # (a planted, turned-out foot sat 1 cm in the ground at the rest height)
        self.hip_x = {"L": r.head["thigh.L"].x, "R": r.head["thigh.R"].x}
        self.hip_x_ref = {"L": rr.head["thigh.L"].x, "R": rr.head["thigh.R"].x}
        self.D0 = V(spear["D"]).normalized()
        self.grip0, self.F0, self.wr_rest, self.R_h = {}, {}, {}, {}
        for s in "LR":
            H = hands[s]
            D = V(H["c"]).normalized()
            N = V(H["n"])
            N = (N - D * N.dot(D)).normalized()
            self.grip0[s] = V(H["grip"])
            self.F0[s] = AA.frame3(D, N)
            self.wr_rest[s] = r.head[f"hand.{s}"].copy()
            self.R_h[s] = r.rest_rot[f"hand.{s}"].copy()
        a0 = (r.tail["hand.L"] - r.head["hand.L"]).normalized()
        n0 = V(hands["L"]["n"])
        self.free0 = AA.frame3(a0, n0 - a0 * n0.dot(a0))                # the rest hand: along its bone, out of the palm
        self.foot_rest_dir = (r.tail["foot.L"] - r.head["foot.L"]).normalized()
        self.thigh_dir = {s: (r.tail[f"thigh.{s}"] - r.head[f"thigh.{s}"]).normalized() for s in "LR"}
        self.skirt = []
        self.reach = {s: 0.992 * (r.length[f"upper_arm.{s}"] + r.length[f"forearm.{s}"]) for s in "LR"}
        self.last_shift = self.last_gap = 0.0
        self.grounded = 0.0

    def leg(self, p, side, F):
        """ashigaru.anim.Solver.leg with THIS foot's own rest direction (an auto-rig's two feet are not mirror images: one sole's pitch on the other foot
        put its toes 3 cm in the ground)"""
        if F is None:
            return
        from mathutils import Euler
        sx = 1.0 if side == "L" else -1.0
        r = self.rig
        yaw, pitch = math.radians(F.get("yaw", 0.0)), math.radians(F.get("pitch", 0.0))
        Rz = Euler((0, 0, math.radians(F.get("knee", F.get("yaw", 0.0)))), "XYZ").to_matrix()
        pole = V(F["kpole"]) if "kpole" in F else Rz @ V((0.10 * sx, -1.0, 0.1))
        p.limb(f"thigh.{side}", f"shin.{side}", f"foot.{side}", V(F["pos"]), pole, 1)
        d0 = (r.tail[f"foot.{side}"] - r.head[f"foot.{side}"]).normalized()
        d0 = V((0.0, d0.y, d0.z)).normalized()                       # (its turn-out is the clip's yaw)
        d = Euler((0, 0, yaw), "XYZ").to_matrix() @ (Euler((pitch, 0, 0), "XYZ").to_matrix() @ d0)
        up = V((0, 0, 1))
        if F.get("instep"):
            up = Euler((pitch, 0, 0), "XYZ").to_matrix() @ up
        p.aim(f"foot.{side}", d, Euler((0, 0, yaw), "XYZ").to_matrix() @ up)
        p.rot(f"toe.{side}", (F.get("toe", 0.0), 0, 0))

    # the man's hand is three bones (the four fingers close together): a fist around a shaft
    def fingers(self, p, P):
        for side in "LR":
            c = float(P.get(f"curl_{side}", 0.18))
            VR.curl(p, self.rig, side, min(1.0, c * 0.96), self.hands)

    @staticmethod
    def chest(p, rig):
        """the shoulder line's middle and the chest's turn (an armature-space rotation off its rest) of a pose"""
        o = (p.head("upper_arm.L") + p.head("upper_arm.R")) * 0.5
        R = p.matrices()["chest"].to_3x3() @ rig.rest_rot["chest"].inverted()
        return o, R

    def foot(self, F, side):
        if F is None:
            return None
        G = dict(F)
        x, y, z = F["pos"]
        xn = self.hip_x[side] + (x - self.hip_x_ref[side]) * self.kl
        # this man was reconstructed standing wide in baggy breeches: feet set down on one line (the v1 gait's 8.5 cm) wring the cloth and read as crossed legs
        sx = 1.0 if side == "L" else -1.0
        a = sx * xn
        if a < STANCE:
            xn = sx * (a + 0.65 * (STANCE - a))
        G["pos"] = V((xn, y * self.kl, self.ankle + (z - AZ_REF) * self.kl))
        return G

    def refit(self, P, lift=0.0):
        """the clip's parameters (v1 metres) -> the same pose on this man"""
        ref = self.ref
        pr = ref.solve(P)                                     # the frame on the reference skeleton
        o_r, R_r = self.chest(pr, ref.rig)
        Q = dict(P)
        Q["hips_pos"] = V(P.get("hips_pos", (0, 0, 0))) * self.kl + V((0, 0, lift))
        bent = float(P.get("hips_rot", (0, 0, 0))[0]) + float(P.get("spine", (0, 0, 0))[0])
        if bent > 30.0 and not P.get("_fall"):                                     # bent well forward (a creep, a kneel) he still looks ahead, not at his feet
            nk = P.get("neck", (0, 0, 0))
            Q["neck"] = (nk[0] - min(20.0, 0.42 * (bent - 30.0)), nk[1], nk[2])
        Q["footL"], Q["footR"] = self.foot(P.get("footL"), "L"), self.foot(P.get("footR"), "R")
        p0 = Pose(self.rig)
        p0.move("hips", Q["hips_pos"])
        p0.rot("hips", P.get("hips_rot", (0, 0, 0)))
        self.spine(p0, P)
        o_n, R_n = self.chest(p0, self.rig)
        Rr_inv = R_r.inverted()

        # (2026-11-19, owner: "fix arm and hand positions ... make it natural": points were carried over relative to the MIDDLE of the shoulder line, so on
        #  narrower shoulders every hand target came in toward the trunk and the elbows had to stick out. Each hand's points now hang on ITS OWN shoulder.)
        sh_r = {s: pr.head(f"upper_arm.{s}") for s in "LR"}
        sh_n = {s: p0.head(f"upper_arm.{s}") for s in "LR"}

        def pt(x, side="R"):
            return sh_n[side] + R_n @ ((Rr_inv @ (V(x) - sh_r[side])) * self.ka)

        def dr(d):
            return (R_n @ (Rr_inv @ V(d))).normalized()

        S = P["spear"]
        D_r = V(S["D"]).normalized()
        B_r = V(S["B"])
        gR = float(P.get("gripR", AR.GRIP0))
        B, D = pt(B_r), dr(D_r)
        # a spear that stood (or lay) on the ground still does
        butt_r = B_r - D_r * gR
        wg = 1.0 - smooth(0.03, 0.14, butt_r.z)
        self.grounded = wg
        if wg > 0.0:
            if D.z > 0.25:
                B = B + V((0.0, -0.035, -EASE_DROP)) * wg                          # at ease the hand is lower on the shaft and a little ahead: the arm nearly hangs
                gR = gR + ((B.z - butt_r.z) / D.z - gR) * wg          # upright: the hand's place on the shaft makes up the difference
            else:
                B = B + V((0, 0, (butt_r.z - (B - D * gR).z) * wg))    # lying: the spear comes down with the hand
        # a LEVELLED spear keeps its point where the clip put it (the simulation's reach is measured to it): shorter arms hold it nearer the butt
        wl = (1.0 - wg) * smooth(0.60, 0.35, abs(D.z))
        if wl > 0.0:
            gR = max(0.22, gR + max(-0.22, min(0.0, (B - B_r).dot(D))) * wl)
        S2 = dict(S)
        S2["B"], S2["D"] = B, D
        # an UPRIGHT spear (at ease, on the march) is held with the elbow hanging under the hand, not winged out
        up = smooth(0.55, 0.85, D.z)
        low = smooth(0.15, 0.50, (sh_n["R"].z - B.z) / self.reach["R"]) * (1.0 - min(1.0, float(P.get("lhand", 0.0)) * 2.0))    # ... nor when one hand trails it low
        if max(up, low) > 0.0 and "poleR" in S:
            S2["poleR"] = self.elbow(V(S["poleR"]), "R", CARRY_ELBOW * max(up, low))
        two = min(1.0, float(P.get("lhand", 0.0)) * 2.0) * (1.0 - up)
        if two > 0.0 and "poleR" in S:                                             # both hands on a levelled spear: the rear elbow back and LOW, not lifted over the shoulder
            S2["poleR"] = V(S2.get("poleR", S["poleR"])).normalized().lerp(R_n @ V(GUARD_ELBOW).normalized(), 0.7 * two)
        # ... and CARRIED on the march, the hand is on the shaft's outer side, thumb up, the forearm coming from behind (the clip's hand cupped it from the
        # front with the elbow winged out: with the elbow down that broke the wrist at a right angle)
        for k in ("nR", "nL"):
            if k in S:
                S2[k] = dr(S[k])
        wc = up * (1.0 - wg)
        if wc > 0.0:
            S2["nR"] = V(S2["nR"]).normalized().lerp(R_n @ V(CARRY_PALM).normalized(), wc).normalized()
            S2["B"] = B = B + R_n @ V((0.045, 0.0, 0.0)) * wc                                 # and nearer the hip
        Q["spear"] = S2
        Q["gripR"] = gR
        if P.get("slide") is not None:
            Q["slide"] = float(P["slide"]) * self.ka
        H = P.get("handL")
        if H is not None:
            if H.get("space", "hips") == "hips":
                T = pr.matrices()["hips"] @ ref.rig.rest["hips"].inverted()
                w_r = T @ V(H["pos"])
            else:
                w_r = V(H["pos"])
            Q["handL"] = dict(pos=pt(w_r, "L"), pole=self.elbow(V(H.get("pole", (0.55, 0.45, -0.7))), "L", FREE_ELBOW), space="world")
            kn_r = pr.head("shin.L")
            wk = smooth(0.24, 0.13, (w_r - kn_r).length)
            if wk > 0.0:                                                           # a hand that rested on the knee still does (his knee is where HIS legs put it)
                self.leg(p0, "L", Q["footL"])
                kn = p0.head("shin.L")
                Q["handL"]["pos"] = Q["handL"]["pos"].lerp(kn + (w_r - kn_r) * 0.8 + V((0.0, 0.0, 0.035)), wk)
                Q["handL"]["pole"] = self.elbow(V(H.get("pole", (0.55, 0.45, -0.7))), "L", 0.5)
            if H.get("space", "hips") == "hips" and (V(H.get("pole", (0, 0, 0))) - V(SWING_POLE)).length < 1e-6:
                # the arm that SWINGS in a walk or a run (ashigaru.clips.locomotion): not a point carried over but an arm that swings from its shoulder
                hp = V(H["pos"])
                Q["handL"] = swing_arm(p0, self.rig, "L", hp.y + 0.02, min(1.0, max(0.0, (hp.x - 0.285) / 0.02)), self.reach["L"])
        return Q

    @staticmethod
    def elbow(pole, side, w):
        """a clip's elbow hint blended toward a hanging elbow (down, a little back, hardly out)"""
        sx = 1.0 if side == "L" else -1.0
        return V(pole).normalized().lerp(V((0.10 * sx, 0.42, -0.90)).normalized(), w)

    def free_hand(self, p, P):
        """The hand that holds nothing hangs as a hand does: along the forearm, the palm toward the thigh, the wrist a little bent (it kept the A-pose's turn:
        the palm faced the ground behind him)."""
        w = 1.0 - min(1.0, max(0.0, float(P.get("lhand", 0.0)) * 2.0))
        if w <= 0.0:
            return
        f = (p.head("hand.L") - p.head("forearm.L")).normalized()
        down = smooth(0.2, 0.8, -f.z)                                   # only an arm that hangs: a raised or reaching one keeps the solver's hand
        w *= down
        if w <= 0.0:
            return
        T = p.matrices()["hips"].to_3x3() @ self.rig.rest["hips"].to_3x3().inverted()
        d = (f + T @ V((-0.10, -0.10, 0.0))).normalized()                # the wrist breaks a little in and forward
        n = T @ V((-0.92, 0.38, 0.0))                                    # out of the palm: toward the thigh, a little back
        F1 = AA.frame3(d, n) @ self.free0.inverted() @ self.R_h["L"]
        F0 = p.matrices()["hand.L"].to_3x3()
        p._place("hand.L", F0.to_quaternion().slerp(F1.to_quaternion(), w).to_matrix())

    BODY = (("hips", 0.0, 0.105), ("chest", 1.0, 0.115), ("spine1", 0.0, 0.11), ("head", 0.45, 0.095), ("upper_arm.L", 0.0, 0.06), ("upper_arm.R", 0.0, 0.06))

    def sunk(self, p):
        """how far the trunk or the head is in the ground (spheres on the spine: a man lying down is as thick as he is, whatever his legs measure)"""
        d = 0.0
        for n, u, r in self.BODY:
            z = p.head(n).z + (p.tail(n).z - p.head(n).z) * u
            d = max(d, r - z)
        return d

    def solve(self, P):
        p = AA.Solver.solve(self, self.refit(P))
        d = self.sunk(p)
        if d > 0.004:                                          # (a fall: the hips' drop was scaled with the legs, the trunk's thickness is not)
            p = AA.Solver.solve(self, self.refit(P, lift=d))
            d2 = self.sunk(p)
            if d2 > 0.004:
                p = AA.Solver.solve(self, self.refit(P, lift=d + d2))
        self.free_hand(p, P)
        if getattr(self, "body", None) is not None:
            from samurai import armfix
            on_shaft = {"R": True, "L": float(P.get("lhand", 0.0)) > 0.999}        # the hands closed on the spear may turn about it (armfix.grip_roll)
            for s in "LR":
                if on_shaft[s]:
                    H = self.hands[s]
                    armfix.grip_roll(p, s, self.body, H["grip"], H["c"], keep=("weapon_r", "weapon_r2"))
            for s in "LR":
                armfix.fix_arm(p, s, self.body, keep=("weapon_r", "weapon_r2") if s == "R" else ())
        # a free hand that comes down to the ground lies ON it (it kept the forearm's line and went in to the knuckles)
        if float(P.get("lhand", 0.0)) < 0.5:
            w = 1.0 - smooth(0.05, 0.17, p.head("hand.L").z)
            if w > 0.0:
                d = p.axis("hand.L")
                flat = V((d.x, d.y, 0.0))
                flat = flat.normalized() if flat.length > 1e-3 else V((0.0, -1.0, 0.0))
                p.aim("hand.L", d.lerp(flat + V((0.0, 0.0, 0.06)), w).normalized(), V((0.0, 0.0, 1.0)))
        return p


# --------------------------------------------------------------------------------------------------------------------- cloth
def chains(facts):
    C = SC.Chain
    sp, ban = facts["spear"], facts["banner"]
    return [
        C("pennant", ("pennant_1", "pennant_2"), "weapon_r", sp["pennant"], k_shape=0.0, damp=0.972, c_n=7.0, c_t=0.9, max_deg=170.0, half=0.012, collide=("ground",), nref=tuple(sp["N"]),
          kind="ribbon", rt=dict(gain=1.8, omega=12.0, zeta=0.45, max_deg=60.0, body_z=0.0, flutter=1.7, flutter_hz=1.4)),
        C("pole", ("banner_1", "banner_2"), "chest", ban["pole"], k_shape=0.08, damp=0.97, gravity=False, wind=0.0, run=0.0, max_deg=12.0,
          kind="pole", rt=dict(gain=0.25, omega=9.0, zeta=0.6, max_deg=2.5)),
        C("flag", ("flag_1", "flag_2", "flag_3"), "banner_2", ban["flag"], k_shape=0.010, damp=0.982, gravity=False, planar=True, c_n=9.0, c_t=1.2,
          max_deg=70.0, kind="flag", rt=dict(gain=1.0, omega=9.5, zeta=0.32, max_deg=75.0)),
    ]


def simulate(rig, poses, loop, duration, speed, name, all_chains):
    """ashigaru.cloth.simulate with this unit's chains"""
    n = len(poses) - 1
    wind = SC.Wind(name, duration, loop, speed)
    diag = {}
    for stage in (("pennant", "pole"), ("flag",)):
        for ch in [c for c in all_chains if c.name in stage]:
            Ts = SC._chain_frames(rig, poses, ch)
            cols = [None for _ in poses]
            rec = SC._simulate(ch, Ts, cols, wind, loop, n)
            if loop:
                rec = SC._close_loop(ch, rec, Ts, n, cols)
            qs = [SC.place_chain(rig, p, ch, SC._directions(rec[f])) for f, p in enumerate(poses)]
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
            ang = max(math.degrees(qs[f][j].angle) for f in range(n + 1) for j in range(len(ch.bones)))
            diag[ch.name] = {"max_deg": round(ang, 1)}
    return diag


def cloth_descriptor(all_chains):
    def gl(v):
        return [round(v.x, 5), round(v.z, 5), round(-v.y, 5)]

    out = []
    for ch in all_chains:
        segs = []
        for i, bone in enumerate(ch.bones):
            d = ch.joints[i + 1] - ch.joints[i]
            segs.append({"bone": bone, "dir": gl(d.normalized()), "length": round(d.length, 5)})
        out.append({"name": ch.name, "kind": ch.kind, "parent": ch.parent, "segments": segs, **{k: ch.rt[k] for k in sorted(ch.rt)}})
    return {"version": 1, "baked_wind": SC.BAKED_WIND, "frame": "glTF unit frame: x right, y up, z forward; metres; unit-local (the engine rotates the world wind into it)", "chains": out}


# --------------------------------------------------------------------------------------------------------------------- bake
def bake(arm, solver, name, c, all_chains, log=print):
    fn, duration, loop = c["fn"], c["duration"], c["loop"]
    speed = float(c.get("speed", 0.0)) * solver.kl
    arm.animation_data_create()
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data.action = act
    n = int(round(duration * FPS))
    poses, shift, gap = [], 0.0, 0.0
    for f in range(n + 1):
        t = duration * f / n
        if loop and f == n:
            t = 0.0
        poses.append(solver.solve(fn(t)))
        shift, gap = max(shift, solver.last_shift), max(gap, solver.last_gap)
    diag = simulate(solver.rig, poses, loop, duration, speed, name, all_chains)
    for f, pose in enumerate(poses):
        key_pose(arm, pose, 1 + f)
    act.frame_range = (1, 1 + n)
    act["gp_loop"] = int(loop)
    act["gp_weapon"] = c["weapon"]
    act["gp_weapon_end"] = c.get("weapon_end", c["weapon"])
    act["gp_events"] = json.dumps(c.get("events", {}))
    act["gp_fps"] = FPS
    act["gp_speed"] = round(speed, 4)
    act["gp_cloth"] = json.dumps(diag)
    log(f"  clip {name}: {n} frames, speed {speed:.2f} m/s, spear pulled in {shift * 1000:.0f} mm, left hand slipped {gap * 1000:.0f} mm")
    return act, poses


def measure(arm, meshes, poses, frames):
    """lowest and highest point of the given skinned meshes over some frames of the current action (evaluated)"""
    sc = bpy.context.scene
    lo, hi = 9.0, -9.0
    for f in frames:
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        for o in meshes:
            ev = o.evaluated_get(dg)
            me = ev.to_mesh()
            zs = [v.co.z for v in me.vertices]
            lo, hi = min(lo, min(zs)), max(hi, max(zs))
            ev.to_mesh_clear()
    return lo, hi


def run(cfg, work, A=None, rel=lambda p: p, log=print):
    if cfg.get("weapon") == "bow":                             # the archer: its own clips and solver (soldier.clips_archer)
        from . import clips_archer
        return clips_archer.run(cfg, work, A, rel, log)
    A = A or {}
    unit = cfg["unit"]
    U = unit.capitalize()
    bpy.ops.wm.open_mainfile(filepath=os.path.join(work, unit, "assembled.blend"))
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.render.fps_base = 1.0
    arm = bpy.data.objects[f"{U}Rig"]
    with open(os.path.join(work, unit, "hands.json")) as fh:
        hands = json.load(fh)
    with open(os.path.join(work, unit, "assembled.json")) as fh:
        facts = json.load(fh)
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    # the reference: the v1 skeleton the clips were written on (never exported)
    ref_arm = AR.build_armature(sc.collection)
    ref_arm.name = ref_arm.data.name = "_RefRig"
    ref = AA.Solver(ref_arm)
    solver = RefitSolver(arm, hands, facts["spear"], ref)
    from samurai import armfix
    solver.body = armfix.Body(solver.rig, [bpy.data.objects[n] for n in facts["bodies"].values()], log=log)      # arms keep out of the trunk (armfix.py)
    log(f"  refit: legs x{solver.kl:.3f}, arms x{solver.ka:.3f}, planted ankle {solver.ankle:.3f} m (the clips': {AZ_REF})")
    all_chains = chains(facts)
    only = A["only"].split(",") if "only" in A else None
    for a in list(bpy.data.actions):
        if only is None or a.name in only:
            bpy.data.actions.remove(a)
    bodies = [bpy.data.objects[n] for n in facts["bodies"].values()]
    kit = {n: bpy.data.objects[n] for n in facts["kit"]}
    report = {}
    keep = {}
    for name, c in AC.CLIPS.items():
        if only and name not in only:
            continue
        act, poses = bake(arm, solver, name, c, all_chains, log)
        keep[name] = act
        n = int(act.frame_range[1] - act.frame_range[0])
        r = {"frames": n, "speed": act["gp_speed"]}
        ev = c.get("events", {})
        if "impact" in ev:                                     # where the points are at the impact frame (the sim's reach: 1.9 m, with the pike 2.4 m)
            sc.frame_set(1 + int(round(ev["impact"] * FPS)))
            dg = bpy.context.evaluated_depsgraph_get()
            for node in ("Yari", "Yari_Long"):
                me = kit[node].evaluated_get(dg).to_mesh()
                r[f"{node}_point_ahead"] = round(-min(v.co.y for v in me.vertices), 3)
                kit[node].evaluated_get(dg).to_mesh_clear()
        if name in ("crouch_idle", "sneak"):
            lo, hi = measure(arm, [bodies[0]], poses, range(1, n + 2, max(1, n // 12)))
            r["head_top_max"] = round(hi, 3)
        if name in ("idle", "walk", "run", "combat_idle", "crouch_idle", "sneak", "death"):
            lo, hi = measure(arm, [bodies[0]], poses, range(1, n + 2, max(1, n // 10)))
            r["lowest"] = round(lo, 3)
        report[name] = r
        log("    " + json.dumps(r))
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    # ---- QA strips: every clip at five moments, the levy with the short spear / the lent armour with the pike
    qd = os.path.join(work, unit, "qa")
    names = list(keep)
    rows = []
    tk = arm.pose.bones["topknot"]
    for i, name in enumerate(names):
        act = keep[name]
        arm.animation_data.action = act
        n = int(act.frame_range[1] - act.frame_range[0])
        armoured = i % 2 == 1
        obs = ([bodies[2], kit["Helmet_Tetsu"], kit["Yari_Long"], kit["Sashimono"], kit["Side_Tanto"]] if armoured and len(bodies) > 2 else [bodies[min(1, len(bodies) - 1)], kit["Helmet_Jingasa"], kit["Yari"], kit["Side_Tanto"]])
        tk.scale = (1e-4, 1e-4, 1e-4)
        ev = AC.CLIPS[name].get("events", {})
        ts = [0.0, 0.25, 0.5, 0.75, 1.0] if "impact" not in ev else [0.0, ev["impact"] * FPS / n * 0.6, ev["impact"] * FPS / n, 0.75, 1.0]
        for k, u in enumerate(ts):
            sc.frame_set(1 + int(round(u * n)))
            bpy.context.view_layer.update()
            rows += qa.shots(obs, os.path.join(qd, f"clip_{name}_{k}"), views=("q",), size=600, focus=(0, -0.2, 0.95), span=2.35)
    tk.scale = (1, 1, 1)
    arm.animation_data.action = None
    sc.frame_set(1)
    half = (len(names) + 1) // 2
    qa.sheet(rows[:half * 5], os.path.join(qd, "clips_a.jpg"), cols=5)
    if rows[half * 5:]:
        qa.sheet(rows[half * 5:], os.path.join(qd, "clips_b.jpg"), cols=5)
    for p in rows:
        os.remove(p)
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    d = ref_arm.data
    bpy.data.objects.remove(ref_arm, do_unlink=True)
    bpy.data.armatures.remove(d)
    tex = os.path.join(work, unit, "tex")
    with open(os.path.join(tex, f"{unit}_cloth.json"), "w") as fh:
        json.dump(cloth_descriptor(all_chains), fh, indent=2)
    with open(os.path.join(work, unit, "clips.json"), "w") as fh:
        json.dump({"refit": {"legs": round(solver.kl, 4), "arms": round(solver.ka, 4), "ankle": round(solver.ankle, 4)}, "clips": report, "order": names}, fh, indent=1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, unit, "anim.blend"), compress=True)
    log("CLIPS " + json.dumps(report))
    return report
