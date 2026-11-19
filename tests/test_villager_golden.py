"""Golden checks for the villager unit (fixtures/villager_unit.blend + out/villager_unit_01). Run:
    blender -b fixtures/villager_unit.blend -P tests/test_villager_golden.py [-- villager_unit_02   with fixtures/villager_unit_02.blend]
Prints ok / FAIL lines and a final ALL PASS / FAILED line (Blender's exit code does not carry a Python failure)."""
import json
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "gamepipe"), os.path.join(ROOT, "generators")):
    if p not in sys.path:
        sys.path.insert(0, p)
import gp_character
import gp_glb
from villager import props as P

fails = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  [{info}]" if info and not cond else ""))
    if not cond:
        fails.append(name)


NAME = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv and len(sys.argv) > sys.argv.index("--") + 1 else "villager_unit_01"      # which body
spec = json.load(open(os.path.join(ROOT, "specs", NAME + ".json")))
coll = bpy.data.collections["villager_game"]
arm = next(o for o in coll.all_objects if o.type == "ARMATURE")
meshes = {o.name: o for o in coll.all_objects if o.type == "MESH"}
bones = {b.name for b in arm.data.bones}

check("34 bones, inside the budget", len(bones) == 34 and len(bones) <= spec["character"]["max_bones"], str(len(bones)))
need = {"root", "hips", "chest", "head", "tool_r", "tool_l", "line", "load_shoulder", "load_front"} | {f"{b}.{s}" for s in "LR" for b in ("thigh", "shin", "foot", "upper_arm", "forearm", "hand", "fingers", "fingers2", "thumb")}
check("the bones the engine and the clips rely on exist", need <= bones, str(sorted(need - bones)))
check("three body LODs", all(f"Villager_LOD{i}" in meshes for i in range(3)))
check("every tool, load and the hat is its own node", all(f"Tool_{t}" in meshes for t in P.TOOLS) and all(f"Load_{l}" in meshes for l in P.LOADS) and "Hat_kasa" in meshes)
check("one material on everything", len({m.name for o in meshes.values() for m in o.data.materials}) == 1)
for name, o in meshes.items():
    n, bad, mx, stray = gp_character.weight_stats(o, bones)
    if bad or mx > 4 or stray:
        check(f"weights of {name}", False, f"bad {bad} max {mx} stray {stray}")
check("every mesh is fully weighted, at most 4 influences", not any(f.startswith("weights of") for f in fails))


def rigid(o):
    return {g.name for g in o.vertex_groups if any(g.index == vg.group and vg.weight > 0.5 for v in o.data.vertices for vg in v.groups)}


check("tools ride the grip bones (the chisel the left one), the line its own", rigid(meshes["Tool_ono"]) == {"tool_r"} and rigid(meshes["Tool_nomi"]) == {"tool_l"} and rigid(meshes["Tool_tsurizao"]) == {"tool_r", "line"})
check("loads ride the load bones, the hat the head", rigid(meshes["Load_sack"]) == {"load_shoulder"} and rigid(meshes["Load_basket"]) == {"load_front"} and rigid(meshes["Hat_kasa"]) == {"head"})
tris = {n: sum(len(p.vertices) - 2 for p in o.data.polygons) for n, o in meshes.items()}
lb = spec["lod_budgets"]
check("LOD triangle budgets", tris["Villager_LOD0"] <= lb["LOD0"] and tris["Villager_LOD1"] <= lb["LOD1"] and tris["Villager_LOD2"] <= lb["LOD2"], str({k: v for k, v in tris.items() if "LOD" in k}))
check("the props are cheap (all of them under 1500 triangles)", sum(v for k, v in tris.items() if "LOD" not in k) < 1500)

clips = spec["character"]["clips"]
acts = {a.name: a for a in bpy.data.actions}
check("all 20 clips are Actions", set(clips) <= set(acts), str(sorted(set(clips) - set(acts))))
worst = 0.0
for name in clips:
    a = acts.get(name)
    if a is None:
        continue
    f0, f1 = a.frame_range
    for fc in gp_character._fcurves(a):
        worst = max(worst, abs(fc.evaluate(f0) - fc.evaluate(f1)))
check("every loop's last key is its first", worst < 1e-5, f"{worst:.6f}")
sp = {n: float(acts[n].get("gp_speed", 0.0)) for n in clips if n in acts}
loco = [n for n in clips if n.endswith(("walk", "run")) or n in ("walk_tool", "run_tool")]
check("locomotion clips carry a stride speed, standing clips none", all(sp[n] > 0.5 for n in loco) and all(sp[n] == 0 for n in clips if n not in loco), str(sp))
check("a walk the sim's slow ground fits and a trot its usual pace does", 0.9 < sp["walk"] < 1.5 and 2.3 < sp["run"] < 3.2, f"{sp['walk']} {sp['run']}")
check("the variants of a gait share its stride (the engine carries the phase over)", all(abs(sp[n] - sp["walk"]) < 1e-6 for n in loco if "walk" in n) and all(abs(sp[n] - sp["run"]) < 1e-6 for n in loco if "run" in n)
      and len({tuple(acts[n].frame_range) for n in loco if "walk" in n}) == 1 and len({tuple(acts[n].frame_range) for n in loco if "run" in n}) == 1)
ev = {n: json.loads(acts[n].get("gp_events", "{}")) for n in clips if n in acts}
check("striking clips say when they strike", all("impact" in ev[n] for n in ("chop", "mine", "hoe", "hammer", "chisel")))

out = os.path.join(ROOT, "out", NAME)
glb = os.path.join(out, NAME + ".glb")
if os.path.exists(glb):
    g = gp_glb.inspect(glb)
    check("GLB: one skin of 34 joints, 17 meshes, 20 animations", g["skins"] == 1 and g["joints"] == 34 and g["meshes"] == 17 and len(g["animations"]) == 20, str({k: g[k] for k in ("skins", "joints", "meshes")}))
    check("GLB: textures are plain images (the engine mip-maps them), with occlusion", all(i["mime"] in ("image/jpeg", "image/png") for i in g["images"]) and g["materials"][0]["occlusionTexture"])
    man = json.load(open(os.path.join(out, "manifest.json")))
    check("the gate passed and stamped a build id", man["passed"] and bool(man.get("build")))
    mask = bpy.data.images.load(os.path.join(out, NAME + ".team.png"))
    import numpy as np
    a = np.empty(mask.size[0] * mask.size[1] * 4, dtype=np.float32)
    mask.pixels.foreach_get(a)
    a = a.reshape(mask.size[1], mask.size[0], 4)
    r, gch = float((a[..., 0] > 0.5).mean()), float((a[..., 1] > 0.5).mean())
    strip = int(mask.size[1] * P.STRIP_V)
    check("mask: the jacket is 12-30% of the atlas and stays out of the prop strip", 0.12 < r < 0.30 and float(a[:strip - 2, :, 0].max()) < 0.05, f"{r:.3f}")
    check("mask: the basket's contents are one cell of the strip", 0.010 < gch < 0.020 and float(a[strip + 2:, :, 1].max()) < 0.05, f"{gch:.4f}")
else:
    check(f"the built GLB exists (run bin/gp build specs/{NAME}.json first)", False)

print("ALL PASS" if not fails else f"FAILED {len(fails)}: {fails}")
