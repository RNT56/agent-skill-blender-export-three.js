"""Headless:  blender -b fixtures/samurai_unit.blend -P tests/test_character_golden.py
Golden test for the samurai unit (recipe "character"): the gate passes, the exported GLB carries the skin and every clip, the
python pose solver agrees with Blender's own skinning, planted feet match the recorded stride speed, and the new validator codes
fire on broken input (a check that cannot fail proves nothing)."""
import copy
import json
import math
import os
import random
import shutil
import sys
import tempfile

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "gamepipe"))
sys.path.insert(0, os.path.join(ROOT, "generators"))
import gp_character
import gp_cli
import gp_glb
import gp_validate
from samurai import anim, clips
from samurai.pose import Pose, Rig, show_pose

fails = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


spec_path = os.path.join(ROOT, "specs", "samurai_unit_01.json")
spec = json.load(open(spec_path))
arm = bpy.data.objects["SamuraiRig"]
solver = anim.Solver(arm)

# ---- 1. pose math: the python evaluator must equal Blender's skinning matrices
worst = 0.0
for name in ("walk", "attack_overhead", "attack_diagonal", "death"):
    c = clips.CLIPS[name]
    for t in (0.0, 0.37 * c["duration"], 0.71 * c["duration"]):
        pose = solver.solve(c["fn"](t))
        show_pose(arm, pose)
        bpy.context.view_layer.update()
        M = pose.matrices()
        for b in arm.pose.bones:
            d = (b.matrix.translation - M[b.name].translation).length
            worst = max(worst, d)
check("python pose evaluator matches Blender pose bones (max joint error < 0.2 mm)", worst < 2e-4, f"{worst * 1000:.3f} mm")
for pb in arm.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.location = (0, 0, 0)

# ---- 2. IK reaches what is reachable
rng = random.Random(7)
rg = Rig(arm)
miss = 0.0
for _ in range(40):
    p = Pose(rg)
    tgt = Vector((rng.uniform(0.05, 0.4), rng.uniform(-0.45, 0.1), rng.uniform(1.0, 1.6)))
    shoulder = rg.head["upper_arm.L"]
    if (tgt - shoulder).length > 0.5:
        continue
    p.limb("upper_arm.L", "forearm.L", "hand.L", tgt, Vector((0.5, 0.5, -0.5)), -1)
    miss = max(miss, (p.head("hand.L") - tgt).length)
check("arm IK lands the wrist on reachable targets (< 1 mm)", miss < 1e-3, f"{miss * 1000:.2f} mm")

# ---- 3. planted feet: stance foot speed equals the recorded stride speed (no sliding when playback is matched)
for name in ("walk", "run"):
    c = clips.CLIPS[name]
    T = c["duration"]
    dts, speeds = 0.004, []
    for k in range(int(T / dts) - 2):
        t0, t1 = k * dts, (k + 1) * dts
        a, b = c["fn"](t0)["footL"], c["fn"](t1)["footL"]
        # stance = foot moves BACK relative to the hips (+Y, the character faces -Y) while it is on the ground
        if abs(a["pos"].z - 0.092) < 0.002 and abs(b["pos"].z - 0.092) < 0.002 and b["pos"].y - a["pos"].y > 1e-6:
            speeds.append((b["pos"].y - a["pos"].y) / dts)
    mean = sum(speeds) / max(len(speeds), 1)
    check(f"{name}: planted foot moves back at the stride speed ({c['speed']:.3f} m/s)", len(speeds) > 20 and abs(abs(mean) - c["speed"]) < 0.04 * c["speed"], f"measured {abs(mean):.3f}")

# ---- 3b. both hands stay on the hilt: the solver nudges the sword toward the shoulders when a grip is out of reach
for name, c in clips.CLIPS.items():
    if name == "death":
        continue
    worst, has_sword = 0.0, False
    for k in range(91):
        P = c["fn"](c["duration"] * k / 90)
        if P.get("sword") is not None:
            has_sword = True
        solver.solve(P)
        worst = max(worst, solver.last_shift if P.get("sword") is not None else 0.0)
    if has_sword:
        check(f"{name}: sword stays within 6 cm of its authored path (the grip never opens)", worst < 0.06, f"{worst * 1000:.1f} mm")

# ---- 3b2. no skating: a foot that stays near the ground may not travel far (steps lift the foot)
for name in ("attack_overhead", "attack_diagonal", "attack_horizontal", "attack_thrust", "draw", "hit", "block"):
    c = clips.CLIPS[name]
    prev, skate = None, {"footL": 0.0, "footR": 0.0}
    for k in range(int(c["duration"] / 0.02) + 1):
        P = c["fn"](k * 0.02)
        if prev is not None:
            for ft in skate:
                a, b2 = prev[ft]["pos"], P[ft]["pos"]
                if b2.z - 0.092 < 0.015:
                    skate[ft] += Vector((b2.x - a.x, b2.y - a.y, 0)).length
        prev = {ft: {"pos": P[ft]["pos"].copy()} for ft in skate}
    check(f"{name}: planted-height foot travel <= 0.20 m (skating)", max(skate.values()) <= 0.20, f"{max(skate.values()):.3f} m")

# ---- 3b3. LOD1 / LOD2 carry the scabbard (weapon_hip weights) so the engine needs no extra node there
for lod, need in (("Samurai_LOD1", 40), ("Samurai_LOD2", 15)):
    o = bpy.data.objects[lod]
    gi = o.vertex_groups["weapon_hip"].index
    n = sum(1 for v in o.data.vertices if any(g.group == gi and g.weight > 0.5 for g in v.groups))
    check(f"{lod} carries the scabbard ({n} vertices weighted to weapon_hip)", n >= need, str(n))

# ---- 3b3b. helmet and armour are pieces of their own; the body is whole without them
def _tris(n):
    return sum(len(p.vertices) - 2 for p in bpy.data.objects[n].data.polygons)


def _zmax(n, bone=None):
    o = bpy.data.objects[n]
    gi = o.vertex_groups[bone].index if bone else None
    return max(v.co.z for v in o.data.vertices if gi is None or any(g.group == gi and g.weight > 0.5 for g in v.groups))


def _groups(n, thr=0.3):
    o = bpy.data.objects[n]
    idx = {g.index: g.name for g in o.vertex_groups}
    return {idx[g.group] for v in o.data.vertices for g in v.groups if g.weight > thr}


_pieces = ("Armour_Oyoroi", "Armour_Oyoroi_Low", "Helmet", "Helmet_Low", "Samurai_Far_Bare", "Samurai_Far_Robe_Kabuto", "Samurai_Far_Robe_Bare")
check("helmet and armour are nodes of their own, with the armour's low mesh and the bare-headed far mesh", all(n in bpy.data.objects for n in _pieces), str([n for n in _pieces if n not in bpy.data.objects]))
check("the helmet (kabuto and menpo) sits on the head bone alone; the armour rides the body's bones and none of the head's", _groups("Helmet") == {"head"} and "head" not in _groups("Armour_Oyoroi") and len(_groups("Armour_Oyoroi")) > 10,
      str(sorted(_groups("Helmet"))))
check("the body is whole without them: a head with hair under 1.78 m, no armour or helmet bone-only parts, and the helmet reaches above it", _zmax("Samurai_LOD0", "head") < 1.78 and _zmax("Helmet") > 1.82 and _zmax("Helmet_Low") > 1.80,
      f"crown {_zmax('Samurai_LOD0', 'head'):.3f}, helmet {_zmax('Helmet'):.3f}")
check("far away the helmet is in the mesh (Samurai_LOD2); the bare-headed far mesh ends at the crown", _zmax("Samurai_LOD2", "head") > 1.80 and _zmax("Samurai_Far_Bare", "head") < 1.80 and _tris("Samurai_Far_Bare") <= 2500 and _tris("Armour_Oyoroi_Low") <= 3600,
      f"{_zmax('Samurai_LOD2', 'head'):.3f} / {_zmax('Samurai_Far_Bare', 'head'):.3f} m, {_tris('Samurai_Far_Bare')} / {_tris('Armour_Oyoroi_Low')} tris")
check("what one samurai costs to draw: under 36,000 triangles near, 11,000 at mid distance", _tris("Samurai_LOD0") + _tris("Armour_Oyoroi") + _tris("Helmet") + _tris("Katana_Saya") + _tris("Katana_Sheathed") + _tris("Sashimono") <= 36000
      and _tris("Samurai_LOD1") + _tris("Armour_Oyoroi_Low") + _tris("Helmet_Low") <= 11000, str({n: _tris(n) for n in ("Samurai_LOD0", "Armour_Oyoroi", "Helmet", "Samurai_LOD1", "Armour_Oyoroi_Low", "Helmet_Low")}))

_ban = {"banner_1", "banner_2", "flag_1", "flag_2", "flag_3"}
check("a samurai who has taken his armour off carries no banner: none in the bare body levels, none in the robe far meshes; the armoured far meshes have it",
      not any(_groups(n) & _ban for n in ("Samurai_LOD0", "Samurai_LOD1", "Samurai_Far_Robe_Kabuto", "Samurai_Far_Robe_Bare")) and all(_groups(n) & _ban for n in ("Samurai_LOD2", "Samurai_Far_Bare", "Armour_Oyoroi_Low")))
check("the robe far meshes: with the helmet and bare-headed, under 2,000 triangles each", _zmax("Samurai_Far_Robe_Kabuto", "head") > 1.80 and _zmax("Samurai_Far_Robe_Bare", "head") < 1.80 and _tris("Samurai_Far_Robe_Kabuto") <= 2000 and _tris("Samurai_Far_Robe_Bare") <= 2000)

# ---- 3b4. the sashimono banner: its own node (LOD0) and baked into LOD1 / LOD2, weighted to the cloth bones
sash = bpy.data.objects["Sashimono"]
cloth_bones = ("banner_1", "banner_2", "flag_1", "flag_2", "flag_3")
gi_s = {n: sash.vertex_groups[n].index for n in cloth_bones if n in sash.vertex_groups}
nb = sum(1 for v in sash.data.vertices if any(g.group in gi_s.values() and g.weight > 0.3 for g in v.groups))
check(f"Sashimono is weighted to the banner / flag bones ({nb} of {len(sash.data.vertices)} vertices)", nb >= 0.6 * len(sash.data.vertices), str(nb))
for lod, need in (("Armour_Oyoroi_Low", 8), ("Samurai_LOD2", 6)):            # (the banner goes with the armour: at mid distance it is in the armour's low mesh) a flat cloth decimates to its corners: a handful of vertices is the whole banner
    o = bpy.data.objects[lod]
    gis = [o.vertex_groups[n].index for n in cloth_bones if n in o.vertex_groups]
    n = sum(1 for v in o.data.vertices if any(g.group in gis and g.weight > 0.3 for g in v.groups))
    up = [v.co for v in o.data.vertices if v.co.y > 0.15 and v.co.z > 1.8]       # everything behind the back and above the helmet: pole + cloth
    ext = (max(v.z for v in up) - min(v.z for v in up), max(v.x for v in up) - min(v.x for v in up)) if up else (0.0, 0.0)
    check(f"{lod} carries the banner ({n} vertices on the banner bones, {ext[0]:.2f} m tall, {ext[1]:.2f} m wide)", n >= need and ext[0] >= 0.5 and ext[1] >= 0.2, str((n, ext)))

# ---- 3b5. cloth simulation (cloth.py): the chains exist, move with the body, are finite, loop exactly, and are deterministic
_fcurves = gp_character._fcurves
from samurai import cloth as _cloth


def _quat_curves(action, bone):
    fcs = action.fcurves if hasattr(action, "fcurves") else _fcurves(action)
    byi = {f.array_index: f for f in fcs if f.data_path == f'pose.bones["{bone}"].rotation_quaternion'}
    return [[k.co[1] for k in byi[i].keyframe_points] for i in range(4)] if len(byi) == 4 else None


def _swing(action, bone):
    q = _quat_curves(action, bone)
    return max(max(c) - min(c) for c in q[1:]) if q else 0.0


check(f"the rig has the {len(_cloth.CHAIN_BONES)} cloth bones", all(b in arm.data.bones for b in _cloth.CHAIN_BONES), str(_cloth.CHAIN_BONES))
check(f"bone budget: {len(arm.data.bones)} bones <= {spec['character']['max_bones']}", len(arm.data.bones) <= spec["character"]["max_bones"])
sw = {nm: {b: _swing(bpy.data.actions[nm], b) for b in ("sash_a1", "sash_b1", "flag_1", "banner_2")} for nm in ("idle", "run", "attack_horizontal")}
check("the clips are baked DRY (no baked wind): the engine adds the world's wind (cloth.BAKED_WIND is False)", _cloth.BAKED_WIND is False)
check("run: the cloth still follows the body by inertia (tails and flag swing more than at idle, flag swing > 0.01)", sw["run"]["sash_a1"] > sw["idle"]["sash_a1"] + 0.02 and sw["run"]["flag_1"] > max(0.01, sw["idle"]["flag_1"]), str(sw["run"]) + " idle " + str(sw["idle"]))
for nm in ("idle", "walk", "run", "run_drawn", "combat_idle"):
    worst = 0.0
    for b in ("sash_a1", "sash_a2", "sash_b1", "sash_b2", "flag_1", "flag_2", "flag_3", "banner_1", "banner_2"):
        q = _quat_curves(bpy.data.actions[nm], b)
        worst = max(worst, max(abs(c[0] - c[-1]) for c in q))
    check(f"{nm}: cloth bones loop exactly (first and last key identical, worst {worst:.1e})", worst < 1e-6, f"{worst:.2e}")
finite = True
tip_max = {}
for nm, act in bpy.data.actions.items():
    dg = json.loads(act.get("gp_cloth", "{}"))
    for ch, d in dg.items():
        finite = finite and all(math.isfinite(v) for v in d.values()) and d["max_deg"] < 125.0 and d["tip_cm_max"] < 60.0
        tip_max[ch] = max(tip_max.get(ch, 0.0), d["tip_cm_max"])
check("no blow-up: every clip's chains stay finite, bone turn < 125 deg, tip travel < 60 cm", finite and len(tip_max) == 4, str(tip_max))
# determinism: simulating the same poses again gives the same keys
_sv = anim.Solver(arm)
_c = clips.CLIPS["walk"]
_n = int(round(_c["duration"] * 30))


def _run_walk():
    ps = [_sv.solve(_c["fn"](0.0 if f == _n else _c["duration"] * f / _n)) for f in range(_n + 1)]
    _cloth.simulate(_sv.rig, ps, True, _c["duration"], _c.get("speed", 0.0), "walk")
    return [tuple(round(x, 9) for x in ps[f].D["sash_b2"]) for f in range(_n + 1)] + [tuple(round(x, 9) for x in ps[f].D["flag_3"]) for f in range(_n + 1)]


check("the cloth simulation is deterministic (two runs give identical keys)", _run_walk() == _run_walk())
# pose math: a placed chain bone points where the simulation put it
_ps = _sv.solve(_c["fn"](0.3))
_dirs = [Vector((0.2, -0.5, -0.84)).normalized(), Vector((-0.1, -0.3, -0.95)).normalized()]
_ch = next(c for c in _cloth.chains() if c.name == "sash_a")
_qs = _cloth.place_chain(_sv.rig, _ps, _ch, _dirs)
for b, q in zip(_ch.bones, _qs):
    _ps.D[b] = q
_ps._M = None
err = max(math.degrees(_ps.axis(b).angle(d)) for b, d in zip(_ch.bones, _dirs))
check(f"place_chain: chain bones point along the simulated directions (error {err:.3f} deg)", err < 0.05, str(err))
# clearance of the tails over every clip: run the measuring tool (it builds its own model: the tails must be a separate object to be measured)
import subprocess
_chk = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "-P", os.path.join(ROOT, "generators", "samurai_cloth_check.py"), "--", "--clips", "idle,walk,run,attack_horizontal,attack_overhead,attack_thrust,attack_diagonal,hit,death",
                       "--step", "1", "--assert-mm", "6", "--assert-pole-mm", "10"], capture_output=True, text=True, timeout=1200)
_gate = [l for l in _chk.stdout.split("\n") if l.startswith("CLOTHCHECK GATE")]
check("tails stay out of the armour in idle / walk / run / attack / death (worst > -6 mm; the static tails reached -19.7 mm)", any("tails_worst" in l and l.endswith("PASS") for l in _gate), "; ".join(_gate) if _gate else _chk.stdout[-300:])
check("the sashimono pole never goes deeper than 10 mm into the armour (axis sampled between rings; the raised arms touch it in attack_overhead)", any("pole_worst" in l and l.endswith("PASS") for l in _gate), "; ".join(_gate) if _gate else _chk.stdout[-300:])

# ---- 3b5b. the runtime cloth descriptor (the engine adds the wind to these chains): written by the generator, matches the rig
_cj_path = os.path.join(ROOT, "out", "samurai_tex", "samurai_cloth.json")
check("the cloth descriptor exists (the spec declares it)", os.path.exists(_cj_path))
_cj = json.load(open(_cj_path))
check("descriptor: baked_wind is false, four chains (sash_a, sash_b, pole, flag) of kinds ribbon / ribbon / pole / flag", _cj["baked_wind"] is False and [(c["name"], c["kind"]) for c in _cj["chains"]] == [("sash_a", "ribbon"), ("sash_b", "ribbon"), ("pole", "pole"), ("flag", "flag")], str([(c["name"], c["kind"]) for c in _cj["chains"]]))
_bad = []
for _c in _cj["chains"]:
    for _sg in _c["segments"]:
        _b = arm.data.bones.get(_sg["bone"])
        if _b is None:
            _bad.append((_sg["bone"], "missing")); continue
        _v = _b.tail_local - _b.head_local
        _gl = Vector((_v.x, _v.z, -_v.y)).normalized()                      # Blender -> glTF unit frame
        if (_gl - Vector(_sg["dir"])).length > 2e-3 or abs(_b.length - _sg["length"]) > 1e-3:
            _bad.append((_sg["bone"], "dir/length"))
    _p = arm.data.bones.get(_c["parent"])
    if _p is None:
        _bad.append((_c["parent"], "parent missing"))
check(f"descriptor: every segment's bone exists and its rest direction (glTF frame) and length match the armature ({len(_bad)} mismatches)", not _bad, str(_bad))

# ---- 3b6. faction emblems: the sheet ships with the asset, its designs are distinct, the banner region matches the geometry, and only the banner cloth lies in it
from samurai import consts as _consts, emblems as _emb
_epng = os.path.join(ROOT, "out", "samurai_tex", "samurai_emblems.png")
_ejson = os.path.join(ROOT, "out", "samurai_tex", "samurai_emblems.json")
check("the emblem sheet and its json exist (the spec declares them)", os.path.exists(_epng) and os.path.exists(_ejson))
_meta = json.load(open(_ejson))
_raw = open(_epng, "rb").read()
import struct as _struct
import zlib as _zlib
_w, _h = _struct.unpack(">II", _raw[16:24])
_idat = b""
_pos = 8
while _pos < len(_raw):
    _ln = _struct.unpack(">I", _raw[_pos:_pos + 4])[0]
    if _raw[_pos + 4:_pos + 8] == b"IDAT":
        _idat += _raw[_pos + 8:_pos + 8 + _ln]
    _pos += 12 + _ln
_dec = _zlib.decompress(_idat)
_rows = [_dec[r * (_w + 1) + 1:(r + 1) * (_w + 1)] for r in range(_h)]
check(f"emblem sheet is {_meta['cols']}x{_meta['rows']} cells of {_meta['px']} px, 8-bit grey ({_w}x{_h})", (_w, _h) == (_meta["cols"] * _meta["px"], _meta["rows"] * _meta["px"]) and len(_meta["names"]) == 8)
_cells = []
for _i in range(8):
    _c0, _r0 = (_i % _meta["cols"]) * _meta["px"], (_i // _meta["cols"]) * _meta["px"]
    _cells.append([1 if _rows[_r0 + y][_c0 + x] > 127 else 0 for y in range(_meta["px"]) for x in range(_meta["px"])])
_cov = [sum(c) / len(c) for c in _cells]
check("every emblem has a sensible fill (8-45% of its cell)", all(0.08 <= c <= 0.45 for c in _cov), str([round(c, 2) for c in _cov]))
_mind = min(sum(a != b for a, b in zip(_cells[i], _cells[j])) / len(_cells[i]) for i in range(8) for j in range(i + 1, 8))
check(f"the eight emblems are distinct (smallest pairwise difference {_mind:.0%} of a cell)", _mind > 0.08, f"{_mind:.3f}")
_rg = _meta["banner"]["blender"]
check("the json's banner region is the geometry's (constants shared with banner.py)", abs(_rg["x0"] - _consts.X0) < 1e-6 and abs(_rg["w"] - _consts.CLOTH_W) < 1e-6 and abs(_rg["z_top"] - (_consts.TOP - 0.004)) < 1e-6)
def _in_region(co):
    return _rg["x0"] - 0.002 <= co.x <= _rg["x0"] + _rg["w"] + 0.002 and _rg["z_top"] - _rg["h"] - 0.002 <= co.z <= _rg["z_top"] + 0.002 and _rg["y_min"] <= co.y <= _rg["y_max"]
_cloth_v = sum(1 for v in sash.data.vertices if _in_region(v.co))
_other = sum(1 for nm in ("Samurai_LOD0", "Katana_Drawn", "Katana_Sheathed", "Katana_Saya") for v in bpy.data.objects[nm].data.vertices if _in_region(v.co))
check(f"only the banner cloth lies in the emblem region ({_cloth_v} cloth vertices, {_other} others)", _cloth_v >= 40 and _other == 0, str((_cloth_v, _other)))
for lod in ("Armour_Oyoroi_Low", "Samurai_LOD2"):
    _lv = sum(1 for v in bpy.data.objects[lod].data.vertices if _in_region(v.co))
    check(f"{lod} keeps the cloth corners inside the emblem region ({_lv} vertices)", _lv >= 4, str(_lv))

# ---- 3c. draw starts exactly where the sheathed sword sits (pop-free weapon swap)
from samurai import katana as _K
P0 = clips.CLIPS["draw"]["fn"](clips.CLIPS["draw"]["events"]["swap_weapon"])
check("draw: at the swap event the sword is exactly at the hip carry pose", (P0["sword"]["O"] - _K.HIP_ORIGIN).length < 0.03 and P0["sword"]["A"].dot(_K.HIP_DIR) > 0.995,
      f"{(P0['sword']['O'] - _K.HIP_ORIGIN).length * 1000:.1f} mm")

# ---- 3d. hidden in the grass: crouch_idle and sneak. The sim draws a crouched man 0.95 m tall, and a samurai hides only out of his armour (robe, no helmet).
# Measured over every frame of the BAKED Actions on the EVALUATED skinned meshes: the bare body's highest point (the crown), every vertex of the sheathed hilt and
# the scabbard, the hilt's and the scabbard's clearance from the body, the planted feet; LOD1 and the robe far meshes must crouch with him.
import numpy as np  # noqa: E402

_acts = {a.name: a for a in bpy.data.actions}
OLD_CLIPS = {"idle": (240, 8.0), "walk": (30, 1.0), "run": (21, 0.7), "combat_idle": (120, 4.0), "attack_overhead": (30, 1.0), "attack_diagonal": (32, 1.0667),
             "attack_horizontal": (30, 1.0), "attack_thrust": (27, 0.9), "block": (24, 0.8), "hit": (18, 0.6), "death": (38, 1.2667), "run_drawn": (21, 0.7),
             "draw": (24, 0.8), "sheathe": (24, 0.8), "equip": (48, 1.6)}                       # frames, seconds: as they were before the crouch clips
CROUCH = {"crouch_idle": (150, 5.0, 0.0, 1.00, 1.10), "sneak": (33, 1.1, 1.2, 1.15, 1.10)}      # frames, seconds, speed_mps, crown limit, katana limit (m)
check("the 15 clips before the crouch clips keep their frame counts (Actions)", all(k in _acts and int(_acts[k].frame_range[1] - _acts[k].frame_range[0]) == n for k, (n, _) in OLD_CLIPS.items()),
      {k: int(_acts[k].frame_range[1] - _acts[k].frame_range[0]) for k in OLD_CLIPS if k in _acts})
check("crouch_idle (5 s) and sneak (1.1 s, stride 1.2 m/s) are baked as sheathed loops", all(k in _acts and bool(_acts[k]["gp_loop"]) and int(_acts[k].frame_range[1] - _acts[k].frame_range[0]) == n
      and abs(_acts[k]["gp_speed"] - v) < 1e-6 and _acts[k]["gp_weapon"] == "sheathed" and _acts[k]["gp_weapon_end"] == "sheathed" for k, (n, _, v, _, _) in CROUCH.items()))
_sc = bpy.context.scene
_AW = arm.matrix_world.copy()


def _play(name):
    arm.animation_data_create()
    act = _acts[name]
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and len(getattr(act, "slots", [])):
        arm.animation_data.action_slot = act.slots[0]
    return int(act.frame_range[0]), int(act.frame_range[1])


def _frames(name):
    f0, f1 = _play(name)
    for f in range(f0, f1 + 1):
        _sc.frame_set(f)
        bpy.context.view_layer.update()
        yield f - f0


def _evaluated(name):
    o = bpy.data.objects[name]
    e = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = e.to_mesh()
    a = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", a)
    e.to_mesh_clear()
    M = np.array(o.matrix_world)
    return a.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]


def _posed(bone, rest_pt):
    return _AW @ arm.pose.bones[bone].matrix @ arm.data.bones[bone].matrix_local.inverted() @ Vector(rest_pt)


from samurai import katana as _Kk  # noqa: E402
_HD = _Kk.HIP_DIR.normalized()
_KOI, _SAYA_END = anim.KOIGUCHI, _Kk.TSUBA_Y + 0.006 + 0.735 + 0.008               # the scabbard's mouth and its end (kojiri), metres from the kashira
_body = bpy.data.objects["Samurai_LOD0"]
_LH = {g.index for g in _body.vertex_groups if g.name.endswith(".L") and g.name.split("_")[0].split(".")[0] in ("hand", "thumb", "index", "middle", "ring", "pinky", "forearm")}
_away = np.array([sum(g.weight for g in v.groups if g.group in _LH) < 0.2 for v in _body.data.vertices])       # the left hand holds the scabbard: leave it out
_LEGG = {g.index for g in _body.vertex_groups if g.name.split(".")[0] in ("thigh", "shin", "foot", "toe")}
_leg = np.array([sum(g.weight for g in v.groups if g.group in _LEGG) > 0.3 for v in _body.data.vertices])


def _clear(pts, s0, s1, radius):
    """unsigned distance of the body points to the sheathed sword's axis between s0 and s1 (metres from the kashira), minus the sword's radius"""
    a, b = np.array(_posed("weapon_hip", _Kk.HIP_ORIGIN + _HD * s0)), np.array(_posed("weapon_hip", _Kk.HIP_ORIGIN + _HD * s1))
    d = b - a
    ln = np.linalg.norm(d)
    d /= ln
    s = np.clip((pts - a) @ d, 0.0, ln)
    return float(np.min(np.linalg.norm(pts - a - s[:, None] * d, axis=1))) - radius


def _sword_clear(B):
    return _clear(B[_away], 0.0, _KOI - 0.10, 0.020), _clear(B[_away], _KOI + 0.15, _SAYA_END, 0.019)       # (hilt, scabbard behind the obi)


for _ in _frames("idle"):
    break
_B = _evaluated("Samurai_LOD0")
_base_hilt, _base_tail = _sword_clear(_B)
check("negative: the same measure finds a standing man (idle) far above the crouch limit", float(_B[:, 2].max()) > 1.6, f"{float(_B[:, 2].max()):.3f} m")
_hi, _info = {}, {}
for name, (n, d, v, crown_lim, kat_lim) in CROUCH.items():
    crown, kat, zmin, hilt, tail, koi_hand, lies_low, legc = 0.0, 0.0, 9.0, 9.0, 9.0, 0.0, True, 9.0
    tops = {k: 0.0 for k in ("Samurai_LOD1", "Samurai_Far_Robe_Bare", "Samurai_Far_Robe_Kabuto", "Helmet", "Helmet_Low", "Samurai_LOD2", "Samurai_Far_Bare")}
    first = last = None
    ank = {"L": [], "R": []}
    knee = []
    for f in _frames(name):
        pb = {b.name: b.matrix.copy() for b in arm.pose.bones}
        first, last = (pb if first is None else first), pb
        B = _evaluated("Samurai_LOD0")
        crown, zmin = max(crown, float(B[:, 2].max())), min(zmin, float(B[:, 2].min()))
        kat = max(kat, *(float(_evaluated(k)[:, 2].max()) for k in ("Katana_Sheathed", "Katana_Saya")))
        h, t = _sword_clear(B)
        hilt, tail = min(hilt, h), min(tail, t)
        legc = min(legc, _clear(B[_leg], 0.0, _SAYA_END, 0.020))
        koi, end = _posed("weapon_hip", _Kk.HIP_ORIGIN + _HD * _KOI), _posed("weapon_hip", _Kk.HIP_ORIGIN + _HD * _SAYA_END)
        koi_hand = max(koi_hand, (_AW @ arm.pose.bones["hand.L"].head - koi).length)
        lies_low = lies_low and end.z < koi.z and end.y > koi.y + 0.5
        for k in tops:
            tops[k] = max(tops[k], float(_evaluated(k)[:, 2].max()))
        for s in "LR":
            ank[s].append(_AW @ arm.pose.bones[f"foot.{s}"].head)
        knee.append(_AW @ arm.pose.bones["shin.L"].head)
    _hi[name] = dict(crown=round(crown, 3), katana=round(kat, 3), helmet=round(tops["Helmet"], 3), helmet_low=round(tops["Helmet_Low"], 3))
    _info[name] = {k: round(z, 3) for k, z in tops.items()}
    check(f"{name}: the bare head's top stays under {crown_lim:.2f} m every frame (the sim's crouched man is 0.95 m)", crown <= crown_lim, f"max {crown:.3f} m")
    check(f"{name}: no part of the katana or its scabbard above {kat_lim:.2f} m, every frame", kat <= kat_lim, f"max {kat:.3f} m")
    check(f"{name}: the scabbard lies back and low (its end behind him and below its mouth, every frame); the left hand stays on its mouth (wrist within 10 cm)",
          lies_low and koi_hand < 0.10, f"low {lies_low}, wrist {koi_hand * 1000:.0f} mm")
    check(f"{name}: no sword through the body: the hilt never closer to it than at idle (it rests on the obi there: {_base_hilt * 1000:.0f} mm), the scabbard behind the obi > 30 mm clear",
          hilt >= _base_hilt - 0.004 and tail > 0.030, f"hilt {hilt * 1000:.1f} mm, scabbard {tail * 1000:.1f} mm")
    check(f"{name}: no sword through the legs: hilt and scabbard keep more than 15 mm from both legs every frame (thigh / shin / foot vertices)", legc > 0.015, f"{legc * 1000:.1f} mm")
    check(f"{name}: a loop (every bone of the first frame is the last)", max(max(abs(x - y) for rx, ry in zip(first[k], last[k]) for x, y in zip(rx, ry)) for k in first) < 1e-4)
    _skinned = all(o.parent == arm and any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers) for o in bpy.data.collections["samurai_game"].all_objects if o.type == "MESH")
    check(f"{name}: LOD1 and the robe far meshes crouch with him (every mesh skinned to SamuraiRig; their tops within 3 cm of the bare body's)",
          _skinned and abs(tops["Samurai_LOD1"] - crown) < 0.03 and abs(tops["Samurai_Far_Robe_Bare"] - crown) < 0.03 and abs(tops["Samurai_Far_Robe_Kabuto"] - crown) < 0.05, str(_info[name]))
    if name == "crouch_idle":
        mv = max((p - q[0]).length for q in list(ank.values()) + [knee] for p in q)
        check("crouch_idle: the feet and the knee on the ground stay where they are (he breathes, he does not shuffle)", mv < 0.002, f"{mv * 1000:.2f} mm")
        check("crouch_idle: down on the left knee (knee joint under 7 cm) and nothing goes through the ground", max(p.z for p in knee) < 0.07 and zmin > -0.005, f"knee {max(p.z for p in knee):.3f} m, lowest {zmin:.3f} m")
    else:
        worst, used = 0.0, 0
        for s, pts in ank.items():
            z0 = min(p.z for p in pts)
            for i in range(len(pts) - 1):
                if pts[i].z < z0 + 0.004 and pts[i + 1].z < z0 + 0.004 and pts[i + 1].y > pts[i].y:
                    used += 1
                    worst = max(worst, abs((pts[i + 1].y - pts[i].y) * 30.0 - v), abs(pts[i + 1].x - pts[i].x) * 30.0)
        check("sneak: no foot slides: every planted frame of both feet moves back at 1.2 m/s (within 0.05 m/s), and not sideways", used >= 20 and worst < 0.05, f"worst {worst:.4f} m/s over {used} frames")
print("info  crouch heights (m): bare crown, katana, with the helmet:", _hi)
print("info  crouch tops of the other meshes (m, not gated):", _info)
arm.animation_data.action = None
for pb in arm.pose.bones:                        # weapon_hip carries location keys in the crouch clips only: leave nothing posed for the gate
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.location = (0, 0, 0)
bpy.context.view_layer.update()

# ---- 4. the gate on the real fixture
out = tempfile.mkdtemp(prefix="gp_char_")
res = gp_cli.run(spec_path, preview=False, out_override=out)
check("samurai_unit_01 passes the gate (0 errors)", res["passed"])
glb = os.path.join(out, "samurai_unit_01", "samurai_unit_01.glb")
info = gp_glb.inspect(glb) if os.path.exists(glb) else {}
check("exported GLB has one skin with 62 joints", info.get("skins") == 1 and info.get("joints") == 62, str((info.get("skins"), info.get("joints"))))
names = {a["name"] for a in info.get("animations", [])}
check(f"all {len(spec['character']['clips'])} clips are in the GLB", names == set(spec["character"]["clips"]), str(sorted(names)))
check("one material, all textures KTX2 only", len(info.get("materials", [])) == 1 and "KHR_texture_basisu" in info.get("extensionsRequired", []))
m = info.get("materials", [{}])[0]
check("PBR: albedo + normal + ORM present", m.get("baseColorTexture") and m.get("normalTexture") and m.get("occlusionTexture") and m.get("metallicRoughnessTexture"))
tr = res.get("stats", {}).get("lod_tris", {})
check("body triangle ranges (the bare body: LOD0 8-18k, LOD1 3-4.8k; the far mesh with everything in it 1-2.5k)", 8000 <= tr.get("LOD0", 0) <= 18000 and 3000 <= tr.get("LOD1", 0) <= 4800 and 1000 <= tr.get("LOD2", 0) <= 2500, str(tr))
clipmeta = json.load(open(os.path.join(out, "samurai_unit_01", "clips.json")))
check("clips.json records loop flag and stride speed", clipmeta["walk"]["loop"] and clipmeta["walk"]["speed_mps"] > 0.9 and clipmeta["run"]["speed_mps"] > 3.0 and not clipmeta["attack_overhead"]["loop"])
check("clips.json: every clip before the crouch clips keeps its frames and duration", all(k in clipmeta and clipmeta[k]["frames"] == n and abs(clipmeta[k]["duration"] - d) < 1e-4 for k, (n, d) in OLD_CLIPS.items()),
      {k: (clipmeta.get(k, {}).get("frames"), clipmeta.get(k, {}).get("duration")) for k in OLD_CLIPS})
check("clips.json: crouch_idle and sneak loop, sheathed; sneak's speed_mps is 1.2", all(k in clipmeta and clipmeta[k]["loop"] is True and clipmeta[k]["frames"] == n and abs(clipmeta[k]["duration"] - d) < 1e-4
      and abs(clipmeta[k]["speed_mps"] - v) < 1e-6 and clipmeta[k]["weapon"] == "sheathed" for k, (n, d, v, _, _) in CROUCH.items()), {k: clipmeta.get(k) for k in CROUCH})
check("clips.json carries events and weapon states (impact times, weapon swap)",
      all("impact" in clipmeta[k]["events"] for k in ("attack_overhead", "attack_diagonal", "attack_horizontal", "attack_thrust"))
      and clipmeta["draw"]["weapon"] == "sheathed" and clipmeta["draw"]["weapon_end"] == "drawn" and "swap_weapon" in clipmeta["draw"]["events"]
      and clipmeta["sheathe"]["weapon_end"] == "sheathed")
mask_path = os.path.join(out, "samurai_unit_01", "samurai_unit_01.team.png")
tm = None
if os.path.exists(mask_path):
    import numpy as _np
    _im = bpy.data.images.load(mask_path)
    _a = _np.empty(_im.size[0] * _im.size[1] * 4, dtype=_np.float32)
    _im.pixels.foreach_get(_a)
    _a = _a.reshape(-1, 4)[:, 0]
    tm = (_im.size[0], float((_a > 0.5).mean()))
check("team mask shipped next to the GLB, covers the lacing/sash only (3-30% of the atlas)", tm is not None and tm[0] == 1024 and 0.03 < tm[1] < 0.30, str(tm))
exp_dur = {k: v["duration"] for k, v in clipmeta.items()}
got = {a["name"]: a["duration"] for a in info.get("animations", [])}
check("exported clip durations match the authored ones (within 1 frame)", all(abs(got[k] - exp_dur[k]) <= 1.01 / 30 for k in exp_dur), str({k: (got.get(k), exp_dur[k]) for k in exp_dur if abs(got.get(k, 0) - exp_dur[k]) > 1.01 / 30}))
shutil.rmtree(out, ignore_errors=True)

# ---- 5. negative tests: the new codes really fire
bpy.context.view_layer.update()
objs, _ = gp_validate.resolve_objects({"include_objects": [o.name for o in bpy.data.collections["samurai_game"].all_objects]})
bad = copy.deepcopy(spec)
bad["character"]["clips"]["no_such_clip"] = {"loop": False}
codes = {f["code"] for f in gp_character.check(bad, objs)}
check("missing clip -> ANIM_MISSING", "ANIM_MISSING" in codes)
act = bpy.data.actions["walk"]
fc = next(iter(gp_character._fcurves(act) if not hasattr(act, "fcurves") else act.fcurves))
kp = fc.keyframe_points[-1]
old = kp.co.y
kp.co.y = old + 0.5
codes = {f["code"] for f in gp_character.check(spec, objs)}
kp.co.y = old
check("loop clip whose last frame differs -> ANIM_LOOP_MISMATCH", "ANIM_LOOP_MISMATCH" in codes)
lod2 = bpy.data.objects["Samurai_LOD2"]
vg = lod2.vertex_groups[0]
vg.remove([0])
codes = {f["code"] for f in gp_character.check(spec, objs)}
check("unweighted vertex -> SKIN_UNWEIGHTED", "SKIN_UNWEIGHTED" in codes)
no_arm = [o for o in objs if o.type != "ARMATURE"]
check("no armature -> SKIN_NO_ARMATURE", {f["code"] for f in gp_character.check(spec, no_arm)} == {"SKIN_NO_ARMATURE"})

print("ALL PASSED" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
