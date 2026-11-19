"""Stage `clips` for a unit with a bow: the v1 archer's clips (archer.clips) RE-FITTED to the reconstructed man, as soldier.clips does for the spearman.

Every frame is solved on a v1 archer skeleton built only for that, then carried over: hips and feet by the leg ratio; the bow's grip and the string hand's
free targets each relative to THEIR OWN shoulder, scaled by the arm ratio (so an extended bow arm is still extended); directions (toward the target, up the
bow, the hand's turn) as they were. The string hand on the string goes where THIS bow's nock point is (archer.anim.Solver does that itself). What hangs on
the body is found on the body: the quiver's nocks are where soldier.bowkit put the quiver, not where the v1 hip was.
The free arm in a walk or a run swings from its shoulder (soldier.clips.swing_arm); elbows hang (soldier.clips.RefitSolver.elbow).
"""
import json
import math
import os

import bpy
from mathutils import Vector

from archer import anim as AAr, clips as ACl, rig as ARg
from samurai import cloth as SC
from samurai.pose import Pose, Rig, key_pose
from villager import qa, rig as VR

from . import clips as K

V = Vector
FPS = 30
smooth = K.smooth
SWING_POLE_R = (-0.5, 0.6, -0.5)


class ArcherRefit(AAr.Solver):
    def __init__(self, arm, hands, bowf, ref):
        self.rig = r = Rig(arm)
        self.ref = ref
        self.hands = hands
        rr = ref.rig
        leg = lambda R_: R_.length["thigh.L"] + R_.length["shin.L"]
        reach = lambda R_: R_.length["upper_arm.L"] + R_.length["forearm.L"]
        self.kl = leg(r) / leg(rr)
        self.ka = reach(r) / reach(rr)
        self.ankle = 0.5 * (r.head["foot.L"].z + r.head["foot.R"].z) + 0.008
        self.hip_x = {"L": r.head["thigh.L"].x, "R": r.head["thigh.R"].x}
        self.hip_x_ref = {"L": rr.head["thigh.L"].x, "R": rr.head["thigh.R"].x}
        self.G0, self.U0, self.W0 = V(bowf["G"]), V(bowf["U"]), V(bowf["W"])
        self.B0 = AAr.frame3(self.U0, self.W0)
        self.kflex = self.U0.cross(self.W0).normalized()
        self.bow = AAr.BowModel()
        self.wr_rest = {s: r.head[f"hand.{s}"].copy() for s in "LR"}
        self.R_h = {s: r.rest_rot[f"hand.{s}"].copy() for s in "LR"}
        self.HR0 = AAr.frame3(V(bowf["string_dir"]), V(bowf["string_palm"]))
        self.pinch0 = V(bowf["pinch0"])
        self.nock0, self.rest0 = V(bowf["nock0"]), V(bowf["arrow_rest"])
        self.arrow_head0 = r.head["arrow"].copy()
        self.foot_rest_dir = (r.tail["foot.L"] - r.head["foot.L"]).normalized()
        self.reach = {s: 0.992 * (r.length[f"upper_arm.{s}"] + r.length[f"forearm.{s}"]) for s in "LR"}
        self.last_shift = self.last_gap = 0.0
        q = bowf.get("quiver")
        self.slot = V(q["slot"]) if q else None                 # the nocks of the arrows in the quiver, hips space (= rest space)
        self.slot_dir = -V(q["axis"]) if q else None            # nock -> head: down into the quiver
        self.slot_ref, self.slot_dir_ref = ARg.quiver_slot(-1)
        self.q_align = self.slot_dir_ref.rotation_difference(self.slot_dir).to_matrix() if q else None

    foot = K.RefitSolver.foot
    leg = K.RefitSolver.leg
    chest = staticmethod(K.RefitSolver.chest)
    elbow = staticmethod(K.RefitSolver.elbow)
    BODY = K.RefitSolver.BODY
    sunk = K.RefitSolver.sunk

    def fingers(self, p, P):
        for side in "LR":
            c = float(P.get(f"curl_{side}", 0.18))
            VR.curl(p, self.rig, side, min(1.0, c * 0.96), self.hands)

    def refit(self, P, lift=0.0):
        ref = self.ref
        pr = ref.solve(P)
        o_r, R_r = self.chest(pr, ref.rig)
        Q = dict(P)
        Q["hips_pos"] = V(P.get("hips_pos", (0, 0, 0))) * self.kl + V((0, 0, lift))
        bent = float(P.get("hips_rot", (0, 0, 0))[0]) + float(P.get("spine", (0, 0, 0))[0])
        if bent > 30.0:
            nk = P.get("neck", (0, 0, 0))
            Q["neck"] = (nk[0] - min(20.0, 0.42 * (bent - 30.0)), nk[1], nk[2])
        Q["footL"], Q["footR"] = self.foot(P.get("footL"), "L"), self.foot(P.get("footR"), "R")
        p0 = Pose(self.rig)
        p0.move("hips", Q["hips_pos"])
        p0.rot("hips", P.get("hips_rot", (0, 0, 0)))
        self.spine(p0, P)
        o_n, R_n = self.chest(p0, self.rig)
        Rr_inv = R_r.inverted()
        sh_r = {s: pr.head(f"upper_arm.{s}") for s in "LR"}
        sh_n = {s: p0.head(f"upper_arm.{s}") for s in "LR"}
        T_r = pr.matrices()["hips"] @ ref.rig.rest["hips"].inverted()
        T_n = p0.matrices()["hips"] @ self.rig.rest["hips"].inverted()

        def pt(x, side):
            return sh_n[side] + R_n @ ((Rr_inv @ (V(x) - sh_r[side])) * self.ka)

        def dr(d):
            return (R_n @ (Rr_inv @ V(d))).normalized()

        def at_quiver(w_r, mapped):
            """a point the clip put at the quiver stays at the quiver"""
            if self.slot is None:
                return mapped
            s_r = T_r @ self.slot_ref
            wq = smooth(0.34, 0.12, (V(w_r) - s_r).length)
            return mapped.lerp(T_n @ self.slot + (V(w_r) - s_r) * self.ka, wq) if wq > 0.0 else mapped

        # ---- the bow in the left hand
        B = P["bow"]
        G = pt(B["G"], "L")
        B2 = dict(B)
        B2["G"], B2["U"], B2["W"] = G, dr(B["U"]), dr(B["W"])
        low = smooth(0.10, 0.45, (sh_n["L"].z - G.z) / self.reach["L"])
        if B.get("pole") is not None and low > 0.0:
            B2["pole"] = self.elbow(V(B["pole"]), "L", 0.75 * low)             # carried at his side the bow arm's elbow hangs
        Q["bow"] = B2
        # ---- the string hand when it is free
        H = P.get("handR")
        if H is not None:
            hp = H.get("space", "hips") == "hips"
            R3 = T_r.to_3x3()
            H2 = dict(H)
            H2["space"] = "world"
            if "pinch" in H:
                w_r = (T_r @ V(H["pinch"])) if hp else V(H["pinch"])
                m = pt(w_r, "R")
                H2["pinch"] = at_quiver(w_r, m)
                H2["dir"] = dr((R3 @ V(H["dir"])) if hp else H["dir"])
                H2["palm"] = dr((R3 @ V(H["palm"])) if hp else H["palm"])
                hang = smooth(0.25, 0.65, (sh_n["R"].z - m.z) / self.reach["R"])
                if hang > 0.0 and (V(w_r) - T_r @ self.slot_ref).length > 0.34:      # a hand that just hangs, hangs under its shoulder (not a hand's width out)
                    H2["pinch"] = m.lerp(V((sh_n["R"].x - 0.035, m.y, m.z)), 0.7 * hang)
                H2["pole"] = self.elbow(V(H.get("pole", (-0.55, 0.45, -0.7))), "R", K.FREE_ELBOW * hang)
            else:
                w_r = (T_r @ V(H["pos"])) if hp else V(H["pos"])
                if hp and (V(H.get("pole", (0, 0, 0))) - V(SWING_POLE_R)).length < 1e-6:
                    hpv = V(H["pos"])                                          # the arm that swings in a walk, a run, a creep
                    H2 = K.swing_arm(p0, self.rig, "R", hpv.y + 0.02, min(1.0, max(0.0, (-0.285 - hpv.x) / 0.02)), self.reach["R"])
                else:
                    H2["pos"] = at_quiver(w_r, pt(w_r, "R"))
                    if "dir" in H:
                        H2["dir"] = dr((R3 @ V(H["dir"])) if hp else H["dir"])
                        if "hint" in H:
                            H2["hint"] = dr((R3 @ V(H["hint"])) if hp else H["hint"])
            Q["handR"] = H2
        # ---- the arrow's free state (in the quiver, on the way to the string)
        A = P.get("arrow")
        if A is not None:
            hp = A.get("space", "hips") == "hips"
            A2 = dict(A)
            A2["space"] = "world"
            d_h = V(A["dir"]) if hp else (T_r.to_3x3().inverted() @ V(A["dir"]))       # in hips space
            if self.q_align is not None:
                d_h = self.q_align @ d_h
            A2["dir"] = (T_n.to_3x3() @ d_h).normalized()
            if "pos" in A:
                w_r = (T_r @ V(A["pos"])) if hp else V(A["pos"])
                A2["pos"] = at_quiver(w_r, pt(w_r, "R"))
            Q["arrow"] = A2
        if "string_pole" in P:
            Q["string_pole"] = dr(P["string_pole"])
        return Q

    def solve(self, P):
        p = AAr.Solver.solve(self, self.refit(P))
        d = self.sunk(p)
        if d > 0.004:
            p = AAr.Solver.solve(self, self.refit(P, lift=d))
            d2 = self.sunk(p)
            if d2 > 0.004:
                p = AAr.Solver.solve(self, self.refit(P, lift=d + d2))
        return p


def chains(facts):
    C = SC.Chain
    ban = facts["banner"]
    return [
        C("pole", ("banner_1", "banner_2"), "chest", ban["pole"], k_shape=0.08, damp=0.97, gravity=False, wind=0.0, run=0.0, max_deg=12.0,
          kind="pole", rt=dict(gain=0.25, omega=9.0, zeta=0.6, max_deg=2.5)),
        C("flag", ("flag_1", "flag_2", "flag_3"), "banner_2", ban["flag"], k_shape=0.010, damp=0.982, gravity=False, planar=True, c_n=9.0, c_t=1.2,
          max_deg=70.0, kind="flag", rt=dict(gain=1.0, omega=9.5, zeta=0.32, max_deg=75.0)),
    ]


def simulate(rig, poses, loop, duration, speed, name, all_chains):
    n = len(poses) - 1
    wind = SC.Wind(name, duration, loop, speed)
    diag = {}
    for stage in (("pole",), ("flag",)):
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
            diag[ch.name] = {"max_deg": round(max(math.degrees(qs[f][j].angle) for f in range(n + 1) for j in range(len(ch.bones))), 1)}
    return diag


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
    log(f"  clip {name}: {n} frames, speed {speed:.2f} m/s, bow pulled in {shift * 1000:.0f} mm, string hand off the nock {gap * 1000:.0f} mm")
    return act, poses, {"frames": n, "speed": act["gp_speed"], "bow_shift_mm": round(shift * 1000, 1), "string_gap_mm": round(gap * 1000, 1)}


def run(cfg, work, A=None, rel=lambda p: p, log=print):
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
    ref_arm = ARg.build_armature(sc.collection)
    ref_arm.name = ref_arm.data.name = "_RefRig"
    ref = AAr.Solver(ref_arm)
    solver = ArcherRefit(arm, hands, facts["bow"], ref)
    log(f"  refit: legs x{solver.kl:.3f}, arms x{solver.ka:.3f}, planted ankle {solver.ankle:.3f} m")
    all_chains = chains(facts)
    only = A["only"].split(",") if "only" in A else None
    for a in list(bpy.data.actions):
        if only is None or a.name in only:
            bpy.data.actions.remove(a)
    bodies = [bpy.data.objects[n] for n in facts["bodies"].values()]
    kit = {n: bpy.data.objects[n] for n in facts["kit"]}
    report, keep = {}, {}
    for name, c in ACl.CLIPS.items():
        if only and name not in only:
            continue
        act, poses, r = bake(arm, solver, name, c, all_chains, log)
        keep[name] = act
        if name in ("idle", "walk", "run", "combat_idle", "crouch_idle", "sneak", "death"):
            lo, hi = K.measure(arm, [bodies[0]], poses, range(1, r["frames"] + 2, max(1, r["frames"] // 10)))
            r["lowest"], r["highest"] = round(lo, 3), round(hi, 3)
        report[name] = r
        log("    " + json.dumps(r))
    arm.animation_data.action = None
    K_reset(arm)
    # ---- QA strips: every clip at five moments, front-quarter; the nocked arrow where the clip shows it
    qd = os.path.join(work, unit, "qa")
    names = list(keep)
    rows = []
    tk = arm.pose.bones["topknot"]
    base = [bodies[-1]] + [kit[n] for n in ("Helmet_Jingasa", "Yumi", "Quiver", "Sashimono") if n in kit]
    for name in names:
        act = keep[name]
        arm.animation_data.action = act
        n = int(act.frame_range[1] - act.frame_range[0])
        tk.scale = (1e-4, 1e-4, 1e-4)
        ev = ACl.CLIPS[name].get("events", {})
        ts = [0.0, 0.25, 0.5, 0.75, 1.0] if "release" not in ev else [0.12, 0.30, 0.50, ev["release"] * FPS / n - 0.02, 0.85]
        for k, u in enumerate(ts):
            f = int(round(u * n))
            sc.frame_set(1 + f)
            bpy.context.view_layer.update()
            obs = base + ([kit["Arrow_Nocked"]] if ACl.arrow_at(name, f / FPS) else [])
            rows += qa.shots(obs, os.path.join(qd, f"clip_{name}_{k}"), views=("q",), size=600, focus=(0, -0.2, 0.95), span=2.6)
    tk.scale = (1, 1, 1)
    arm.animation_data.action = None
    sc.frame_set(1)
    half = (len(names) + 1) // 2
    qa.sheet(rows[:half * 5], os.path.join(qd, "clips_a.jpg"), cols=5)
    if rows[half * 5:]:
        qa.sheet(rows[half * 5:], os.path.join(qd, "clips_b.jpg"), cols=5)
    for p in rows:
        os.remove(p)
    K_reset(arm)
    d = ref_arm.data
    bpy.data.objects.remove(ref_arm, do_unlink=True)
    bpy.data.armatures.remove(d)
    tex = os.path.join(work, unit, "tex")
    with open(os.path.join(tex, f"{unit}_cloth.json"), "w") as fh:
        json.dump(K.cloth_descriptor(all_chains), fh, indent=2)
    with open(os.path.join(work, unit, "clips.json"), "w") as fh:
        json.dump({"refit": {"legs": round(solver.kl, 4), "arms": round(solver.ka, 4), "ankle": round(solver.ankle, 4)}, "clips": report, "order": names}, fh, indent=1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, unit, "anim.blend"), compress=True)
    log("CLIPS " + json.dumps(report))
    return report


def K_reset(arm):
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
