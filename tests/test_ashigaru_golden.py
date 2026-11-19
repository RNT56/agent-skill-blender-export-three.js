"""Golden checks of the ashigaru (run on the built fixture):  blender -b fixtures/ashigaru_unit.blend -P tests/test_ashigaru_golden.py
Numbers. The model: one skeleton, a whole body, every piece of kit its own node, six ready-made far meshes. Measured on the BAKED Actions with Blender's own pose
evaluation: both hands stay on the shaft, the spear stands on the ground at ease, the point arrives on the impact frame and ends where the unit's reach says (the
pike half a metre beyond the short spear), planted feet move at the clip's stride speed.
Prints ok / FAIL lines and a final 'ASHIGARU GOLDEN: ...' line (blender -b swallows exceptions: parse stdout)."""
import json
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "generators"))
sys.path.insert(0, os.path.join(ROOT, "gamepipe"))
from ashigaru import clips, cloth, finalize as F, rig as R  # noqa: E402
from archer import consts as K  # noqa: E402
import gp_character  # noqa: E402

V = Vector
res = []


def check(name, ok, info=""):
    res.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""))


arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
sc = bpy.context.scene
base = "ashigaru_unit_01"
bones = arm.data.bones
spec = json.load(open(os.path.join(ROOT, "specs", f"{base}.json")))
tris = {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in bpy.data.objects if o.type == "MESH"}

# ---------------------------------------------------------------------------------------------------------------- asset shape
check("62 bones (one skeleton for every piece of kit), inside the 64-bone budget", len(bones) == 62, len(bones))
KIT = ["Armour_HaraAte", "Armour_Okegawa", "Helmet_Jingasa", "Helmet_Tetsu", "Yari", "Yari_Long", "Side_Tanto", "Sashimono"]
FAR = [F.far_name(a, h) for a, _ in F.ARMOURS for h, _ in F.HEADS]
nodes = ["Ashigaru_LOD0", "Ashigaru_LOD1", "Armour_HaraAte_Low", "Armour_Okegawa_Low"] + KIT + FAR
check("nodes: the body at two levels, eight pieces of kit, two low armours, six far meshes (2 armours x jingasa / tetsu / bare)", sorted(tris) == sorted(nodes), sorted(tris))
check("no far mesh is named like a body LOD (an engine finds body LODs by the _LOD<n> ending)", not any(n[-5:-1] == "_LOD" for n in FAR + KIT))
check("triangle budgets: body 14,000 / 5,600, a far mesh 2,500, a spear 400, a hat 2,000, the side arm 200", tris["Ashigaru_LOD0"] <= 14000 and tris["Ashigaru_LOD1"] <= 5600
      and all(tris[n] <= 2500 for n in FAR) and tris["Yari"] <= 400 and tris["Yari_Long"] <= 400 and tris["Helmet_Jingasa"] <= 2000 and tris["Helmet_Tetsu"] <= 2000 and tris["Side_Tanto"] <= 200, tris)
drawn = {"levy, near": tris["Ashigaru_LOD0"] + tris["Armour_HaraAte"] + tris["Helmet_Jingasa"] + tris["Yari"] + tris["Side_Tanto"],
         "lent armour, near": tris["Ashigaru_LOD0"] + tris["Armour_Okegawa"] + tris["Helmet_Tetsu"] + tris["Yari_Long"] + tris["Side_Tanto"] + tris["Sashimono"],
         "lent armour, mid": tris["Ashigaru_LOD1"] + tris["Armour_Okegawa_Low"] + tris["Helmet_Tetsu"] + tris["Yari_Long"],
         "lent armour, far": tris[F.far_name("Okegawa", "Tetsu")] + tris["Yari_Long"]}
check("what one man costs to draw: under 25,000 triangles near, 10,500 at mid distance, 2,800 far", drawn["lent armour, near"] <= 25000 and drawn["levy, near"] <= 25000 and drawn["lent armour, mid"] <= 10500
      and drawn["lent armour, far"] <= 2800, drawn)
ws = {o.name: gp_character.weight_stats(o, {b.name for b in bones}) for o in bpy.data.objects if o.type == "MESH"}
check("every vertex weighted, at most 4 influences, no stray groups", all(w[1] == 0 and w[2] <= 4 and not w[3] for w in ws.values()), {k: w[1:] for k, w in ws.items() if w[1] or w[2] > 4 or w[3]})


def groups_used(name, thr=0.3):
    o = bpy.data.objects[name]
    idx = {g.index: g.name for g in o.vertex_groups}
    return {idx[g.group] for v in o.data.vertices for g in v.groups if g.weight > thr}


def zmax(name, bone=None):
    o = bpy.data.objects[name]
    gi = o.vertex_groups[bone].index if bone else None
    return max(v.co.z for v in o.data.vertices if gi is None or any(g.group == gi and g.weight > 0.5 for g in v.groups))


check("each spear hangs on its own weapon bone; the pennant on its chain", groups_used("Yari") >= {"weapon_r", "pennant_1", "pennant_2"} and groups_used("Yari_Long") == {"weapon_r2"},
      (sorted(groups_used("Yari")), sorted(groups_used("Yari_Long"))))
SKIRT = {f"skirt_{p}.{s}" for p in ("front", "side", "back") for s in "LR"}
check("the lent armour's six tassets ride the six skirt bones; the hara-ate's two the front ones only", groups_used("Armour_Okegawa") >= SKIRT and groups_used("Armour_HaraAte") & SKIRT == {"skirt_front.L", "skirt_front.R"},
      sorted(groups_used("Armour_HaraAte") & SKIRT))
check("the body is whole on its own: it carries no armour, hat, spear or banner bone, and its head band's tails ride their chains",
      not groups_used("Ashigaru_LOD0") & (SKIRT | {"weapon_r", "weapon_r2", "banner_1", "banner_2", "flag_1", "flag_2", "flag_3"}) and groups_used("Ashigaru_LOD0") >= {"tail_a2", "tail_b2"})
check("both hats sit on the head bone alone (the iron one's neck curtain also hangs on the neck and the shoulders)", groups_used("Helmet_Jingasa") == {"head"} and "head" in groups_used("Helmet_Tetsu"),
      (sorted(groups_used("Helmet_Jingasa")), sorted(groups_used("Helmet_Tetsu"))))
check("the bare crown (hair and its knot) clears both hats' brims: it is under 1.78 m, the hats reach over 1.80 m", zmax("Ashigaru_LOD0", "head") < 1.780 and zmax("Helmet_Jingasa") > 1.80 and zmax("Helmet_Tetsu") > 1.78,
      f"crown {zmax('Ashigaru_LOD0', 'head'):.3f}, rawhide {zmax('Helmet_Jingasa'):.3f}, iron {zmax('Helmet_Tetsu'):.3f} m")
BAN = {"banner_1", "banner_2"}
check("the banner goes with the lent armour: in its low mesh and in its far meshes, in none of the hara-ate's", all(groups_used(n) & BAN for n in ["Armour_Okegawa_Low"] + [x for x in FAR if "Okegawa" in x])
      and not any(groups_used(n) & BAN for n in ["Armour_HaraAte_Low"] + [x for x in FAR if "HaraAte" in x]))
TL = {"tail_a1", "tail_a2", "tail_b1", "tail_b2"}
check("under the iron hat's neck curtain the head band's tails are left out of the far meshes; the other far meshes keep them", not any(groups_used(n, 0.5) & TL for n in FAR if n.endswith("Tetsu"))
      and all(groups_used(n, 0.5) & TL for n in FAR if not n.endswith("Tetsu")), {n: sorted(groups_used(n, 0.5) & TL) for n in FAR})
acts = {a.name: a for a in bpy.data.actions}
want = spec["character"]["clips"]
check(f"{len(want)} clips, every one in the spec, loops as the spec says", len(want) >= 12 and sorted(acts) == sorted(want) and all(bool(acts[k]["gp_loop"]) == want[k]["loop"] for k in want), sorted(acts))
eq = acts["equip"]
check("equip (taking up a piece of kit): 1.6 s, the hand closes on it at 0.85 s, and he ends as he stands at ease", int(eq.frame_range[1] - eq.frame_range[0]) == 48 and json.loads(eq["gp_events"]) == {"take": 0.85} and not eq["gp_loop"])
check("thrusts: 29 frames, the point arrives at 0.45 s", all(int(acts[k].frame_range[1] - acts[k].frame_range[0]) == 29 and json.loads(acts[k]["gp_events"]) == {"impact": 0.45} for k in ("thrust_high", "thrust_low")))
check("the grip never opens: the spear is never pulled in, the leading hand never slips down the shaft (0.0 mm in every clip)", all(a["gp_spear_shift_mm"] < 0.5 and a["gp_hand_slip_mm"] < 0.5 for a in acts.values()),
      {k: (a["gp_spear_shift_mm"], a["gp_hand_slip_mm"]) for k, a in acts.items() if a["gp_spear_shift_mm"] > 0 or a["gp_hand_slip_mm"] > 0})


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


SPEARS = (("weapon_r", R.YARI_LEN), ("weapon_r2", R.NAGAE_LEN))
GL, DL, NL, _ = R.grip_rest("L")
GR, DR, NR, _ = R.grip_rest("R")


def frames(name):
    f0, f1 = play(name)
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        yield f - f0


def line_dist(p, a, b):
    d = (b - a).normalized()
    return ((p - a) - d * (p - a).dot(d)).length


# both hands on the shaft: the grip centre of each hand lies on the spear's axis (both spears share the axis: they differ only in where along it they are held)
worst_r, worst_l = 0.0, 0.0
for name in ("combat_idle", "thrust_high", "thrust_low", "run_ready", "hit"):
    for _ in frames(name):
        a, b = posed("weapon_r", R.sp(0.0)), posed("weapon_r", R.sp(R.YARI_LEN))
        worst_r = max(worst_r, line_dist(posed("hand.R", GR), a, b))
        worst_l = max(worst_l, line_dist(posed("hand.L", GL), a, b))
check("guard, thrusts, charge, hit: the right hand's grip is on the shaft's axis every frame", worst_r < 0.0015, f"worst {worst_r * 1000:.2f} mm")
check("and the left hand's (the shaft runs through it in the thrust)", worst_l < 0.0015, f"worst {worst_l * 1000:.2f} mm")
worst_a, worst_b = 0.0, 0.0
for _ in frames("combat_idle"):
    a, b = posed("weapon_r", R.sp(0.0)), posed("weapon_r", R.sp(R.YARI_LEN))
    a2, b2 = posed("weapon_r2", R.sp(0.0)), posed("weapon_r2", R.sp(R.NAGAE_LEN))
    worst_a = max(worst_a, line_dist(a2, a, b), line_dist(b2, a, b))
    worst_b = max(worst_b, abs((a - a2).length - clips.PIKE_UP))
check("the pike lies on the same axis as the short spear, held 0.60 m further up", worst_a < 0.001 and worst_b < 0.002, f"off axis {worst_a * 1000:.2f} mm, offset error {worst_b * 1000:.2f} mm")

# at ease the spear stands on the ground (both spears: the hand holds them at the same height)
butt = {b: [] for b, _ in SPEARS}
for _ in frames("idle"):
    for b, ln in SPEARS:
        butt[b].append(posed(b, R.sp(0.0)).z)
check("idle: the butt of either spear stands on the ground the whole clip", all(max(abs(z) for z in zs) < 0.012 for zs in butt.values()), {b: f"{min(zs) * 1000:.1f} .. {max(zs) * 1000:.1f} mm" for b, zs in butt.items()})

# the thrust: where the point is, frame by frame
reach = {}
for name in ("thrust_high", "thrust_low"):
    tip = {b: [] for b, _ in SPEARS}
    for _ in frames(name):
        for b, ln in SPEARS:
            tip[b].append(posed(b, R.sp(ln)).copy())
    for b, ln in SPEARS:
        ys = [-p.y for p in tip[b]]
        fmax = max(range(len(ys)), key=lambda i: ys[i])
        reach[(name, b)] = (max(ys), fmax, ys[0])
    y, f, y0 = reach[(name, "weapon_r")]
    check(f"{name}: the point is furthest out on the impact frame (13 or 14 of 29) and travels over 0.6 m", f in (13, 14) and y - y0 > 0.60, f"frame {f}, {y0:.2f} -> {y:.2f} m")
ys, yl = reach[("thrust_high", "weapon_r")][0], reach[("thrust_high", "weapon_r2")][0]
check("the short spear's point ends at the unit's reach (sim range 1.9 m, centre to centre): between 1.75 and 2.05 m ahead", 1.75 < ys < 2.05, f"{ys:.3f} m")
check("the pike's point ends half a metre beyond it (the nagae-yari technique adds 0.5 m of reach)", 0.45 < yl - ys < 0.75 and 2.25 < yl < 2.75, f"{yl:.3f} m, +{yl - ys:.3f} m")
zt = max(posed("weapon_r", R.sp(R.YARI_LEN)).z for _ in frames("thrust_low") if _ == 13)
check("the low thrust is aimed under the guard (the point below 0.9 m at impact), the high one at the chest", zt < 0.90, f"{zt:.2f} m")
check("negative: held at the same place as the short spear the pike would overreach the unit's range by over a metre", (R.NAGAE_LEN - R.YARI_LEN) - clips.PIKE_UP > 0.4, f"{R.NAGAE_LEN - R.YARI_LEN:.2f} m longer, held {clips.PIKE_UP:.2f} m further up")

for name in ("walk", "run", "run_ready"):                               # planted feet: while a foot is on the ground it moves back at the clip's stride speed
    pts = []
    for _ in frames(name):
        pts.append(arm.pose.bones["foot.L"].head.copy())
    zmin = min(p.z for p in pts)
    v = [(pts[i + 1].y - pts[i].y) * 30.0 for i in range(len(pts) - 1) if pts[i].z < zmin + 0.004 and pts[i + 1].z < zmin + 0.004 and pts[i + 1].y > pts[i].y]
    spd = sum(v) / max(len(v), 1)
    check(f"{name}: the planted foot moves at the clip's stride speed", len(v) >= 3 and abs(spd - acts[name]["gp_speed"]) < 0.04 * acts[name]["gp_speed"], f"{spd:.3f} vs {acts[name]['gp_speed']:.3f} m/s over {len(v)} frames")
    check(f"{name}: a loop (the first frame is the last)", (pts[0] - pts[-1]).length < 1e-5)
dead = [None]
for f in frames("death"):
    dead[0] = (arm.pose.bones["hips"].head.z, arm.pose.bones["head"].head.z, posed("weapon_r2", R.sp(R.NAGAE_LEN)).z, posed("weapon_r", R.sp(0.0)).z)
check("death ends on the ground: hips and head under 0.35 m, neither spear end below the ground", dead[0][0] < 0.35 and dead[0][1] < 0.35 and dead[0][2] > -0.01 and dead[0][3] > -0.01, [round(x, 3) for x in dead[0]])

# ---------------------------------------------------------------------------------------------------------------- hidden in the grass: crouch_idle, sneak
# The sim draws a crouched man 0.95 m tall. Measured on the EVALUATED (skinned) meshes over every frame: the bare-headed body's highest point (crown), every vertex of
# both spears (the pennant included, as the cloth bake left it), the shaft's clearance from the body (the right hand that holds it excluded).
import math  # noqa: E402

import numpy as np  # noqa: E402

OLD = {"idle": (240, 8.0), "walk": (30, 1.0), "run": (21, 0.7), "ready": (24, 0.8), "stand_down": (24, 0.8), "combat_idle": (120, 4.0), "run_ready": (21, 0.7),
       "thrust_high": (29, 0.9667), "thrust_low": (29, 0.9667), "hit": (18, 0.6), "death": (38, 1.2667), "equip": (48, 1.6)}
cj = json.load(open(os.path.join(ROOT, "out", base, "clips.json")))
check("every clip but the two crouch clips (the eleven before them and equip) keeps its frames and duration (Actions and clips.json)", all(k in acts and int(acts[k].frame_range[1] - acts[k].frame_range[0]) == n
      and cj[k]["frames"] == n and abs(cj[k]["duration"] - d) < 1e-4 for k, (n, d) in OLD.items()), {k: cj.get(k, {}).get("frames") for k in OLD})
CR = {"crouch_idle": (150, 5.0, 0.0, 1.00, 1.10), "sneak": (33, 1.1, 1.2, 1.15, 1.10)}      # frames, seconds, speed_mps, crown limit, spear limit
check("crouch_idle (5 s) and sneak (1.1 s at 1.2 m/s) exist, loop, and clips.json says so", all(k in acts and bool(acts[k]["gp_loop"]) and int(acts[k].frame_range[1] - acts[k].frame_range[0]) == n
      and abs(acts[k]["gp_speed"] - v) < 1e-6 and cj[k]["loop"] is True and cj[k]["frames"] == n and abs(cj[k]["duration"] - d) < 1e-4 and abs(cj[k]["speed_mps"] - v) < 1e-6
      for k, (n, d, v, _, _) in CR.items()), {k: (cj.get(k, {}).get("frames"), cj.get(k, {}).get("speed_mps")) for k in CR})
body = bpy.data.objects["Ashigaru_LOD0"]
_HG = {g.index for g in body.vertex_groups if g.name.endswith(".R") and g.name.split("_")[0].split(".")[0] in ("hand", "thumb", "index", "middle", "ring", "pinky")}
_away = np.array([sum(g.weight for g in v.groups if g.group in _HG) < 0.2 for v in body.data.vertices])


def evaluated(name):
    o = bpy.data.objects[name]
    e = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = e.to_mesh()
    a = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", a)
    e.to_mesh_clear()
    M = np.array(o.matrix_world)
    return a.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]


def shaft_clearance(pts, bone, ln, radius=0.017):
    a, b = np.array(posed(bone, R.sp(0.0))), np.array(posed(bone, R.sp(ln)))
    d = b - a
    L = np.linalg.norm(d)
    d /= L
    s = np.clip((pts - a) @ d, 0.0, L)
    return float(np.min(np.linalg.norm(pts - a - s[:, None] * d, axis=1))) - radius


hi = {}
for name, (n, d, v, crown_lim, spear_lim) in CR.items():
    crown, sp_hi, clr, slope, grip = 0.0, {"Yari": 0.0, "Yari_Long": 0.0}, 9.0, 0.0, 0.0
    first = last = None
    ank = {"L": [], "R": []}
    for f in frames(name):
        pb = {b.name: b.matrix.copy() for b in arm.pose.bones}
        first, last = (pb if first is None else first), pb
        P = evaluated("Ashigaru_LOD0")
        crown = max(crown, float(P[:, 2].max()))
        for k in sp_hi:
            sp_hi[k] = max(sp_hi[k], float(evaluated(k)[:, 2].max()))
        for bone, ln in SPEARS:
            clr = min(clr, shaft_clearance(P[_away], bone, ln))
        a, b = posed("weapon_r", R.sp(0.0)), posed("weapon_r", R.sp(R.YARI_LEN))
        slope = max(slope, abs(math.degrees(math.asin((b - a).normalized().z))))
        grip = max(grip, line_dist(posed("hand.R", GR), a, b))
        for s in "LR":
            ank[s].append(arm.pose.bones[f"foot.{s}"].head.copy())
    hi[name] = dict(crown=round(crown, 3), **{k: round(z, 3) for k, z in sp_hi.items()})
    check(f"{name}: the bare head's top stays under {crown_lim:.2f} m every frame (the sim's crouched man is 0.95 m)", crown <= crown_lim, f"max {crown:.3f} m")
    check(f"{name}: no part of either spear (pennant included) above {spear_lim:.2f} m, every frame", max(sp_hi.values()) <= spear_lim, {k: f"{z:.3f} m" for k, z in sp_hi.items()})
    check(f"{name}: the spear is held level (shaft within 5 deg of horizontal), the right hand's grip on its axis", slope < 5.0 and grip < 0.0015, f"slope {slope:.1f} deg, grip {grip * 1000:.2f} mm")
    check(f"{name}: neither shaft passes through the body (clearance > 5 mm every frame; the hand that holds it excluded)", clr > 0.005, f"{clr * 1000:.1f} mm")
    check(f"{name}: a loop (every bone of the first frame is the last)", max(max(abs(x - y) for rx, ry in zip(first[k], last[k]) for x, y in zip(rx, ry)) for k in first) < 1e-4)
    if name == "crouch_idle":
        mv = max((p - q[0]).length for q in ank.values() for p in q)
        check("crouch_idle: both feet stay where they are (he breathes, he does not shuffle)", mv < 0.002, f"{mv * 1000:.2f} mm")
    else:
        worst, used = 0.0, 0
        for s, pts in ank.items():
            zmin = min(p.z for p in pts)
            for i in range(len(pts) - 1):
                if pts[i].z < zmin + 0.004 and pts[i + 1].z < zmin + 0.004 and pts[i + 1].y > pts[i].y:
                    used += 1
                    worst = max(worst, abs((pts[i + 1].y - pts[i].y) * 30.0 - v), abs(pts[i + 1].x - pts[i].x) * 30.0)
        check("sneak: no foot slides: every planted frame of both feet moves back at 1.2 m/s (within 0.05 m/s), and not sideways", used >= 20 and worst < 0.05, f"worst {worst:.4f} m/s over {used} frames")
for _ in frames("idle"):
    break
neg = float(evaluated("Ashigaru_LOD0")[:, 2].max())
check("negative: the same measure finds a standing man (idle) far above the crouch limit", neg > 1.6, f"{neg:.3f} m")
info = {}
for name in CR:
    top = {k: 0.0 for k in ("Helmet_Jingasa", "Helmet_Tetsu", "Sashimono", F.far_name("Okegawa", "Tetsu"), F.far_name("HaraAte", "Jingasa"))}
    for _ in frames(name):
        for k in top:
            top[k] = max(top[k], float(evaluated(k)[:, 2].max()))
    info[name] = {k: round(z, 3) for k, z in top.items()}
print("info  heights (m), bare body and spears:", hi)
print("info  heights (m) of optional pieces and far meshes in the crouch clips (not gated):", info)
arm.animation_data.action = None

# ---------------------------------------------------------------------------------------------------------------- shipped side files
out = os.path.join(ROOT, "out", base)
cl = json.load(open(os.path.join(out, f"{base}.cloth.json")))
names = ["pennant", "tail_a", "tail_b", "pole", "flag"]
check(f"cloth.json: {', '.join(names)}; baked dry; the pennant is a free ribbon (body_z = 0)", [c["name"] for c in cl["chains"]] == names and cl["baked_wind"] is False
      and cl["chains"][0]["kind"] == "ribbon" and cl["chains"][0].get("body_z") == 0.0 and [c.name for c in cloth.chains()] == names)
em = json.load(open(os.path.join(out, f"{base}.emblems.json")))["banner"]["blender"]
fl = bpy.data.objects["Sashimono"]
cv = [v.co for v in fl.data.vertices if v.co.x > K.X0 - 1e-4 and v.co.z <= K.TOP - 0.0039 and K.YC + 0.0012 <= v.co.y <= K.YC + 0.0048]
check("the crest region is the banner cloth (all 64 cloth vertices inside it, 3 mm margins)", len(cv) == 64 and all(em["x0"] - 0.003 <= c.x <= em["x0"] + em["w"] + 0.003 and em["y_min"] <= c.y <= em["y_max"]
      and em["z_top"] - em["h"] - 0.003 <= c.z <= em["z_top"] + 0.003 for c in cv), len(cv))
img = bpy.data.images.load(os.path.join(out, f"{base}.team.png"))
px = list(img.pixels[0::4])
cov = sum(1 for p in px if p > 0.5) / len(px)
check("team mask coverage (hat bands, sash, pennant, head band, cord, lacing, banner) between 3% and 30%", 0.03 < cov < 0.30, f"{cov * 100:.1f}%")
man = json.load(open(os.path.join(out, "manifest.json")))
check("the gate passed, the manifest carries a build id, the GLB is under 12 MB", man.get("passed") is True and len(man.get("build", "")) == 12 and os.path.getsize(os.path.join(out, f"{base}.glb")) < 12e6,
      f"{os.path.getsize(os.path.join(out, f'{base}.glb')) / 1e6:.2f} MB, build {man.get('build')}")
print(f"ASHIGARU GOLDEN: {'ALL PASSED' if all(res) else 'FAILED'} ({sum(res)} of {len(res)} checks)")
