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

# ---- 3c. draw starts exactly where the sheathed sword sits (pop-free weapon swap)
from samurai import katana as _K
P0 = clips.CLIPS["draw"]["fn"](clips.CLIPS["draw"]["events"]["swap_weapon"])
check("draw: at the swap event the sword is exactly at the hip carry pose", (P0["sword"]["O"] - _K.HIP_ORIGIN).length < 0.03 and P0["sword"]["A"].dot(_K.HIP_DIR) > 0.995,
      f"{(P0['sword']['O'] - _K.HIP_ORIGIN).length * 1000:.1f} mm")

# ---- 4. the gate on the real fixture
out = tempfile.mkdtemp(prefix="gp_char_")
res = gp_cli.run(spec_path, preview=False, out_override=out)
check("samurai_unit_01 passes the gate (0 errors)", res["passed"])
glb = os.path.join(out, "samurai_unit_01", "samurai_unit_01.glb")
info = gp_glb.inspect(glb) if os.path.exists(glb) else {}
check("exported GLB has one skin with 53 joints", info.get("skins") == 1 and info.get("joints") == 53, str((info.get("skins"), info.get("joints"))))
names = {a["name"] for a in info.get("animations", [])}
check(f"all {len(spec['character']['clips'])} clips are in the GLB", names == set(spec["character"]["clips"]), str(sorted(names)))
check("one material, all textures KTX2 only", len(info.get("materials", [])) == 1 and "KHR_texture_basisu" in info.get("extensionsRequired", []))
m = info.get("materials", [{}])[0]
check("PBR: albedo + normal + ORM present", m.get("baseColorTexture") and m.get("normalTexture") and m.get("occlusionTexture") and m.get("metallicRoughnessTexture"))
tr = res.get("stats", {}).get("lod_tris", {})
check("LOD triangle ranges (LOD0 16-24k, LOD1 4-8k, LOD2 1-2.5k)", 16000 <= tr.get("LOD0", 0) <= 24000 and 4000 <= tr.get("LOD1", 0) <= 8000 and 1000 <= tr.get("LOD2", 0) <= 2500, str(tr))
clipmeta = json.load(open(os.path.join(out, "samurai_unit_01", "clips.json")))
check("clips.json records loop flag and stride speed", clipmeta["walk"]["loop"] and clipmeta["walk"]["speed_mps"] > 0.9 and clipmeta["run"]["speed_mps"] > 3.0 and not clipmeta["attack_overhead"]["loop"])
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
