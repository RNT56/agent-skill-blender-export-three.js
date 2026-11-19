"""Golden checks of the light archer (run on the built fixture):  blender -b fixtures/archer_unit.blend -P tests/test_archer_golden.py
Numbers, measured on the BAKED Actions with Blender's own pose evaluation: the string keeps its length while the bow is drawn, the arrow lies on the string hand and
across the arrow rest, the string never comes near the war hat, the release is one frame, planted feet move at the clip's stride speed. Prints ok / FAIL lines and a
final 'ARCHER GOLDEN: ...' line (blender -b swallows exceptions: parse stdout)."""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "generators"))
sys.path.insert(0, os.path.join(ROOT, "gamepipe"))
from archer import anim, clips, cloth, consts as K, gear, rig as R  # noqa: E402
import gp_character  # noqa: E402

V = Vector
res = []


def check(name, ok, info=""):
    res.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""))


arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
sc = bpy.context.scene
bones = arm.data.bones
spec = json.load(open(os.path.join(ROOT, "specs", "archer_unit_01.json")))
tris = {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in bpy.data.objects if o.type == "MESH"}

# ---------------------------------------------------------------------------------------------------------------- asset shape
check("59 bones, inside the 64-bone budget", len(bones) == 59, len(bones))
check("nodes: three body LODs and the bare-headed far mesh, the war hat, the bow, the nocked arrow, the banner", sorted(tris) == ["Archer_Far_Bare", "Archer_LOD0", "Archer_LOD1", "Archer_LOD2", "Arrow_Nocked", "Helmet", "Sashimono", "Yumi"], sorted(tris))
check("triangle budgets: body 24,000 / 8,000 / 2,500, the bare far mesh 2,500, the hat 2,000", tris["Archer_LOD0"] <= 24000 and tris["Archer_LOD1"] <= 8000 and tris["Archer_LOD2"] <= 2500 and tris["Archer_Far_Bare"] <= 2500 and tris["Helmet"] <= 2000, tris)


def _zmax(name, bone=None):
    o = bpy.data.objects[name]
    gi = o.vertex_groups[bone].index if bone else None
    return max(v.co.z for v in o.data.vertices if gi is None or any(g.group == gi and g.weight > 0.5 for g in v.groups))


check("the war hat is its own piece on the head bone; the body is whole without it (the bare crown is under 1.78 m, the hat reaches over 1.78 m)",
      {g.name for g in bpy.data.objects["Helmet"].vertex_groups if any(any(x.group == g.index and x.weight > 0.3 for x in v.groups) for v in bpy.data.objects["Helmet"].data.vertices)} == {"head"}
      and _zmax("Archer_LOD0", "head") < 1.780 and _zmax("Helmet") > 1.78 and _zmax("Archer_LOD2", "head") > 1.78 and _zmax("Archer_Far_Bare", "head") < 1.780,
      f"crown {_zmax('Archer_LOD0', 'head'):.3f}, hat {_zmax('Helmet'):.3f}, far with hat {_zmax('Archer_LOD2', 'head'):.3f}, far bare {_zmax('Archer_Far_Bare', 'head'):.3f} m")
ws = {o.name: gp_character.weight_stats(o, {b.name for b in bones}) for o in bpy.data.objects if o.type == "MESH"}
check("every vertex weighted, at most 4 influences, no stray groups", all(w[1] == 0 and w[2] <= 4 and not w[3] for w in ws.values()), {k: w[1:] for k, w in ws.items()})
for n in ("Archer_LOD1", "Archer_LOD2"):
    o = bpy.data.objects[n]
    gi = {g.name: g.index for g in o.vertex_groups}
    used = {g.group for v in o.data.vertices for g in v.groups if g.weight > 0.3}
    check(f"{n} carries the bow (limb and nock bones are weighted) and the flag", all(gi.get(b) in used for b in ("bow_u2", "bow_l2", "bow_nock")) and any(gi.get(b) in used for b in ("flag_1", "flag_2", "flag_3")),
          [b for b in ("bow_u2", "bow_l2", "bow_nock", "flag_1", "flag_2", "flag_3") if gi.get(b) not in used])
acts = {a.name: a for a in bpy.data.actions}
want = spec["character"]["clips"]
check(f"{len(want)} clips, every one in the spec", len(want) == 14 and sorted(acts) == sorted(want), sorted(acts))
check("equip (taking up a piece of kit): 1.6 s, the hand closes on it at 0.85 s", int(acts["equip"].frame_range[1] - acts["equip"].frame_range[0]) == 48 and json.loads(acts["equip"]["gp_events"]) == {"take": 0.85})
check("shot clips: 35 frames, the arrow appears at 0.133 s, leaves at 0.80 s", all(int(acts[k].frame_range[1] - acts[k].frame_range[0]) == 35 and json.loads(acts[k]["gp_events"]) == {"arrow": 0.1333, "release": 0.8} for k in ("shoot", "crouch_shoot")))
check("the grip never opens: the bow is pulled in by < 20 mm in every clip, the string hand is ON the nock (0.0 mm) whenever it should be", all(a["gp_bow_shift_mm"] < 20.0 and a["gp_string_gap_mm"] < 0.5 for a in acts.values()),
      {k: (a["gp_bow_shift_mm"], a["gp_string_gap_mm"]) for k, a in acts.items() if a["gp_bow_shift_mm"] > 0})


# ---------------------------------------------------------------------------------------------------------------- measured on the baked Actions
def play(name):
    arm.animation_data_create()
    act = acts[name]
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and len(getattr(act, "slots", [])):
        arm.animation_data.action_slot = act.slots[0]
    return int(act.frame_range[0]), int(act.frame_range[1])


def posed(bone, rest_pt):
    """a point given in armature REST space, carried by a bone, in the current pose"""
    return arm.pose.bones[bone].matrix @ bones[bone].matrix_local.inverted() @ V(rest_pt)


b = R.bow_rest()
TU = R.bp(R.bow_f(R.BOW_UP - 0.012) - 0.0065, R.BOW_UP - 0.012)
TL = R.bp(R.bow_f(-R.BOW_DN + 0.012) - 0.0065, -R.BOW_DN + 0.012)
N0, REST0 = R.nock0(), R.arrow_rest()
L0 = (TU - N0).length + (TL - N0).length
HAT = [gear.hat_matrix() @ V((math.cos(math.tau * j / 48) * r, math.sin(math.tau * j / 48) * r, h)) for r, h in gear.HAT_PROF for j in range(48)]


def measure(name):
    f0, f1 = play(name)
    out = dict(dl=0.0, arrow_on_hand=0.0, arrow_off_rest=0.0, hat=9.0, hat_f=0, pull=[])
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        tu, tl, n = posed("bow_u2", TU), posed("bow_l2", TL), posed("bow_nock", N0)
        out["dl"] = max(out["dl"], abs((tu - n).length + (tl - n).length - L0))
        g, n_rest = posed("weapon_l", b["G"]), posed("weapon_l", N0)
        out["pull"].append((n - n_rest).length)
        t = (f - f0) / 30.0
        if clips.arrow_at(name, t) and t >= 0.34:                      # nocked: the arrow starts at the nock and lies across the arrow rest
            ah = arm.pose.bones["arrow"].head.copy()
            ad = (arm.pose.bones["arrow"].tail - ah).normalized()
            rest = posed("weapon_l", REST0)
            out["arrow_on_hand"] = max(out["arrow_on_hand"], (ah - n).length)
            out["arrow_off_rest"] = max(out["arrow_off_rest"], ((rest - ah) - ad * (rest - ah).dot(ad)).length)
        Mh = arm.pose.bones["head"].matrix @ bones["head"].matrix_local.inverted()
        hat = [Mh @ p for p in HAT]
        for a_, c_ in ((n, tu), (n, tl)):                              # both strands against the war hat's surface
            for k in range(41):
                p = a_.lerp(c_, k / 40.0)
                d = min((p - h).length for h in hat)
                if d < out["hat"]:
                    out["hat"], out["hat_f"] = d, f - f0
    return out


worst_dl, worst_hat, hat_at = 0.0, 9.0, {}
for name in ("shoot", "crouch_shoot", "aim", "ready", "combat_idle", "hit"):
    m = measure(name)
    worst_dl, worst_hat = max(worst_dl, m["dl"]), min(worst_hat, m["hat"])
    hat_at[name] = (round(m["hat"] * 1000), m["hat_f"])
    if name in ("shoot", "crouch_shoot"):
        check(f"{name}: full draw is held on the release frame, the string is home one frame later", m["pull"][24] > 0.97 * R.PULL and m["pull"][25] < 0.06, f"{m['pull'][24]:.3f} m -> {m['pull'][25]:.3f} m")
        check(f"{name}: the nocked arrow starts on the string's nock point", m["arrow_on_hand"] < 0.003, f"{m['arrow_on_hand'] * 1000:.2f} mm")
        check(f"{name}: and lies across the arrow rest on the bow hand", m["arrow_off_rest"] < 0.003, f"{m['arrow_off_rest'] * 1000:.2f} mm")
        check(f"{name}: the arrow is longer than the draw (it never falls off the bow)", R.ARROW_LEN > R.BRACE + max(m["pull"]) + 0.05, f"{R.BRACE + max(m['pull']):.3f} m of {R.ARROW_LEN} m")
check("the string keeps its length while the limbs flex (every frame of every stance clip)", worst_dl < 0.002, f"worst {worst_dl * 1000:.2f} mm of {L0:.3f} m")
check("the string never comes near the war hat (draw to the shoulder, bow canted)", worst_hat > 0.020, f"closest {worst_hat * 1000:.0f} mm; per clip (mm, frame): {hat_at}")
bm = anim.BowModel()
check("negative: a bow that did not flex would stretch the string by centimetres", abs(bm.length(0.0, R.PULL) - bm.L0) > 0.05, f"{(bm.length(0.0, R.PULL) - bm.L0) * 1000:.0f} mm")

for name in ("walk", "run", "sneak"):                                  # planted feet: while a foot is on the ground it moves back at the clip's stride speed
    f0, f1 = play(name)
    pts = []
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        pts.append(arm.pose.bones["foot.L"].head.copy())
    zmin = min(p.z for p in pts)
    v = [(pts[i + 1].y - pts[i].y) * 30.0 for i in range(len(pts) - 1) if pts[i].z < zmin + 0.004 and pts[i + 1].z < zmin + 0.004 and pts[i + 1].y > pts[i].y]
    sp = sum(v) / max(len(v), 1)
    check(f"{name}: the planted foot moves at the clip's stride speed", len(v) >= 3 and abs(sp - acts[name]["gp_speed"]) < 0.04 * acts[name]["gp_speed"], f"{sp:.3f} vs {acts[name]['gp_speed']:.3f} m/s over {len(v)} frames")
    check(f"{name}: a loop (first key == last key on every bone)", all((pts[0] - pts[-1]).length < 1e-5 for _ in (0,)))

# the kneeling (right) foot in the crouch clips: the shin lies on the ground and the foot goes on in line with it, the instep down and the sole up. A foot aimed with a fixed
# world-up hint past ~70 deg of pitch rolls over (sole down, the toes pointing back: a wrung ankle) or, steeper, is driven into the ground. Measured on the baked Actions:
# the foot bone's top axis (z) points down, and the lowest skinned vertex of the foot and toes (LOD0) is on the ground (-10 .. +40 mm).
import numpy as np  # noqa: E402

_body = bpy.data.objects["Archer_LOD0"]
_fg = {g.index for g in _body.vertex_groups if g.name in ("foot.R", "toe.R")}
_fv = np.array([sum(g.weight for g in v.groups if g.group in _fg) > 0.5 for v in _body.data.vertices])


def foot_low():
    e = _body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = e.to_mesh()
    a = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", a)
    e.to_mesh_clear()
    return float((a.reshape(-1, 3)[_fv] @ np.array(_body.matrix_world)[:3, :3].T + np.array(_body.matrix_world)[:3, 3])[:, 2].min())


for name in ("crouch_idle", "crouch_shoot"):
    f0, f1 = play(name)
    top, low = [], []
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        top.append((arm.matrix_world.to_3x3() @ arm.pose.bones["foot.R"].matrix.to_3x3().col[2]).z)
        low.append(foot_low())
    check(f"{name}: the kneeling foot lies on its instep, the sole up (the foot's top axis points down every frame) and on the ground (lowest foot vertex -10 .. +40 mm)",
          max(top) < -0.8 and -0.010 < min(low) and max(low) < 0.040, f"top axis z {min(top):+.2f} .. {max(top):+.2f}, lowest vertex {min(low) * 1000:.0f} .. {max(low) * 1000:.0f} mm")
_sv = anim.Solver(arm)
_P = clips.crouch_idle(0.0)
_P["footR"] = {k: v for k, v in _P["footR"].items() if k != "instep"}
_tz = _sv.solve(_P).matrices()["foot.R"].to_3x3().col[2].z
check("negative: the same kneeling foot solved without `instep` (fixed world-up hint) rolls over: its top faces up, the sole down", _tz > 0.5, f"top axis z {_tz:+.2f}")
arm.animation_data.action = None

# ---------------------------------------------------------------------------------------------------------------- shipped side files
out = os.path.join(ROOT, "out", "archer_unit_01")
cl = json.load(open(os.path.join(out, "archer_unit_01.cloth.json")))
check("cloth.json: tails (ribbons behind the head, body_z = 1), pole, flag; baked dry", [c["name"] for c in cl["chains"]] == ["tail_a", "tail_b", "pole", "flag"] and cl["baked_wind"] is False
      and all(c.get("body_z") == 1.0 for c in cl["chains"] if c["kind"] == "ribbon") and [c.name for c in cloth.chains()] == [c["name"] for c in cl["chains"]])
em = json.load(open(os.path.join(out, "archer_unit_01.emblems.json")))["banner"]["blender"]
fl = bpy.data.objects["Sashimono"]
cv = [v.co for v in fl.data.vertices if v.co.x > K.X0 - 1e-4 and v.co.z <= K.TOP - 0.0039 and K.YC + 0.0012 <= v.co.y <= K.YC + 0.0048]
check("the crest region is the banner cloth (all 64 cloth vertices inside it, 3 mm margins)", len(cv) == 64 and all(em["x0"] - 0.003 <= c.x <= em["x0"] + em["w"] + 0.003 and em["y_min"] <= c.y <= em["y_max"] and em["z_top"] - em["h"] - 0.003 <= c.z <= em["z_top"] + 0.003 for c in cv), len(cv))
img = bpy.data.images.load(os.path.join(out, "archer_unit_01.team.png"))
px = list(img.pixels[0::4])
cov = sum(1 for p in px if p > 0.5) / len(px)
check("team mask coverage (hat band, hachimaki, tasuki, lacing, glove cord, banner) between 3% and 30%", 0.03 < cov < 0.30, f"{cov * 100:.1f}%")
man = json.load(open(os.path.join(out, "manifest.json")))
check("the gate passed and the GLB is under 12 MB", man.get("passed") is True and os.path.getsize(os.path.join(out, "archer_unit_01.glb")) < 12e6, f"{os.path.getsize(os.path.join(out, 'archer_unit_01.glb')) / 1e6:.2f} MB")
print(f"ARCHER GOLDEN: {'ALL PASSED' if all(res) else 'FAILED'} ({sum(res)} of {len(res)} checks)")
