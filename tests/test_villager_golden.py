"""Golden checks for the villager unit (fixtures/villager_unit.blend + out/villager_unit_01). Run:
    blender -b fixtures/villager_unit.blend -P tests/test_villager_golden.py [-- villager_unit_02   with fixtures/villager_unit_02.blend]
    (-- <name> --write-baseline records the delivered clips' fingerprints in tests/villager_clips_baseline.json: only when they change on purpose)
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


ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
NAME = next((a for a in ARGS if not a.startswith("--")), "villager_unit_01")      # which body
spec = json.load(open(os.path.join(ROOT, "specs", NAME + ".json")))
# the 20 clips the villager was first delivered with: adding clips must leave them as they are (tests/villager_clips_baseline.json)
OLD_CLIPS = ["idle", "walk", "run", "walk_tool", "run_tool", "carry_shoulder_idle", "carry_shoulder_walk", "carry_shoulder_run", "carry_front_idle", "carry_front_walk",
             "carry_front_run", "chop", "mine", "hoe", "hammer", "chisel", "saw", "cut", "fish", "craft"]
BASELINE = os.path.join(ROOT, "tests", "villager_clips_baseline.json")


def signature(act):
    """a clip's fingerprint: its frame range and three sums over every key channel sampled at every frame (plain, time-weighted, channel-weighted)."""
    f0, f1 = (int(round(x)) for x in act.frame_range)
    chans = sorted(gp_character._fcurves(act), key=lambda fc: (fc.data_path, fc.array_index))
    s0 = s1 = s2 = 0.0
    for i, fc in enumerate(chans):
        w = ((i + 1) * 0.6180339887) % 1.0
        for f in range(f0, f1 + 1):
            v = fc.evaluate(f)
            s0 += v
            s1 += v * (f - f0) / max(f1 - f0, 1)
            s2 += v * w
    return [f0, f1, len(chans), round(s0, 7), round(s1, 7), round(s2, 7)]


if "--write-baseline" in ARGS:                                     # once, from the fixture as it was delivered
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    base[NAME] = {c: signature(bpy.data.actions[c]) for c in OLD_CLIPS}
    with open(BASELINE, "w") as fh:
        json.dump(base, fh, indent=0, sort_keys=True)
    print("baseline written for", NAME)
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
check(f"all {len(clips)} clips are Actions", set(clips) <= set(acts), str(sorted(set(clips) - set(acts))))
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
loco = [n for n in clips if n in acts and (n.endswith(("walk", "run")) or n in ("walk_tool", "run_tool", "sneak"))]
check("locomotion clips carry a stride speed, standing clips none", all(sp[n] > 0.5 for n in loco) and all(sp[n] == 0 for n in clips if n not in loco), str(sp))
check("a walk the sim's slow ground fits and a trot its usual pace does", 0.9 < sp["walk"] < 1.5 and 2.3 < sp["run"] < 3.2, f"{sp['walk']} {sp['run']}")
check("the variants of a gait share its stride (the engine carries the phase over)", all(abs(sp[n] - sp["walk"]) < 1e-6 for n in loco if "walk" in n) and all(abs(sp[n] - sp["run"]) < 1e-6 for n in loco if "run" in n)
      and len({tuple(acts[n].frame_range) for n in loco if "walk" in n}) == 1 and len({tuple(acts[n].frame_range) for n in loco if "run" in n}) == 1)
ev = {n: json.loads(acts[n].get("gp_events", "{}")) for n in clips if n in acts}
check("striking clips say when they strike", all("impact" in ev[n] for n in ("chop", "mine", "hoe", "hammer", "chisel")))


# ---- the delivered clips stay as they were
def _same(a, b):
    return a[:3] == b[:3] and all(abs(x - y) <= 2e-4 for x, y in zip(a[3:], b[3:]))       # one key moved by 0.01 shows; float noise of a rebuild does not


base = json.load(open(BASELINE)).get(NAME) if os.path.exists(BASELINE) else None
if base is None:
    check("a baseline of the delivered clips exists (--write-baseline on the delivered fixture)", False)
else:
    changed = [c for c in OLD_CLIPS if c not in acts or not _same(signature(acts[c]), base[c])]
    check(f"the {len(OLD_CLIPS)} delivered clips are unchanged (frame ranges and key sums as delivered)", not changed, str(changed))

# ---- hiding: crouch_idle (taking cover in tall grass) and sneak (creeping), measured on the skinned meshes at every frame
HIDE = {"crouch_idle": 1.00, "sneak": 1.15}              # the highest the head may come (m); the game's crouch silhouette is 0.95 m
if all(h in acts for h in HIDE):
    from villager import clips as VC
    FPS = 30
    ci, sn = acts["crouch_idle"], acts["sneak"]
    dur = (ci.frame_range[1] - ci.frame_range[0]) / FPS
    check("crouch_idle: a loop of about 5 s that stands still", int(ci.get("gp_loop", 0)) == 1 and 4.5 <= dur <= 5.5 and sp["crouch_idle"] == 0.0, f"{dur:.2f} s, speed {sp['crouch_idle']}")
    v = sp["sneak"]
    check("sneak: a loop authored at about 1.2 m/s", int(sn.get("gp_loop", 0)) == 1 and 1.1 < v < 1.3, f"{v}")
    meas = {}
    for h, limit in HIDE.items():
        m = VC.measure_clip(h, acts[h])
        meas[h] = m
        print(f"     {h}: head top {m['head_top']:.3f} m (lowest {m['head_top_min']:.3f}), tools {m['tool_min']:.3f}..{m['tool_max']:.3f} m, body lowest {m['body_min']:.3f} m, hat {m['hat_top']:.3f} m")
        check(f"{h}: the head stays under {limit:.2f} m in every frame", m["head_top"] <= limit, f"{m['head_top']:.3f}")
        check(f"{h}: every tool in the hands stays low (under 1.1 m) and out of the ground", m["tool_max"] <= 1.10 and m["tool_min"] >= -0.02, f"{m['tool_min']:.3f}..{m['tool_max']:.3f}")
        check(f"{h}: the body does not sink into the ground (as the delivered clips: above -3 cm)", m["body_min"] >= -0.03, f"{m['body_min']:.3f}")
    toes = meas["crouch_idle"]["toes"]
    drift = max((toes[i][s] - toes[0][s]).length for i in range(len(toes)) for s in "LR")
    check("crouch_idle: the feet stay where they are", drift < 0.003, f"{drift * 1000:.1f} mm")
    toes = meas["sneak"]["toes"]
    zmin = min(min(t["L"].z, t["R"].z) for t in toes)
    slide = contact = 0.0
    planted = []
    for i in range(len(toes) - 1):
        for s in "LR":
            a, b = toes[i][s], toes[i + 1][s]
            if a.z < zmin + 0.022 and b.z < zmin + 0.022:              # the stride-speed rule (clips.stride_speed)
                d = max(abs((b.y - a.y) - v / FPS), abs(b.x - a.x))
                slide = max(slide, d)
                planted.append((b.y - a.y) * FPS)
                if a.z < zmin + 0.002 and b.z < zmin + 0.002:          # on the ground
                    contact = max(contact, d)
    print(f"     sneak: planted toe off the ground's motion by {slide * 1000:.2f} mm/frame at most ({contact * 1000:.3f} mm while on the ground)")
    check("sneak: no foot slides (a planted toe moves back at the authored speed)", len(planted) > 10 and slide < 0.003 and contact < 0.0005, f"{slide * 1000:.2f} / {contact * 1000:.3f} mm")
    dif = [(t["L"] - t["R"]).y for t in toes[:-1]]
    check("sneak: starts where the left foot is furthest forward (the footfall walk and run start on)", dif[0] <= min(dif) + 0.001, f"{(dif[0] - min(dif)) * 1000:.1f} mm")
else:
    check("the hiding clips (crouch_idle, sneak) exist", False)

out = os.path.join(ROOT, "out", NAME)
glb = os.path.join(out, NAME + ".glb")
if os.path.exists(glb):
    g = gp_glb.inspect(glb)
    check(f"GLB: one skin of 34 joints, 17 meshes, {len(clips)} animations", g["skins"] == 1 and g["joints"] == 34 and g["meshes"] == 17 and {a["name"] for a in g["animations"]} == set(clips),
          str({k: g[k] for k in ("skins", "joints", "meshes")}) + f" {len(g['animations'])} animations")
    cj = json.load(open(os.path.join(out, "clips.json")))
    check("clips.json: every clip, the creep with its stride speed", set(cj) == set(clips) and abs(cj["sneak"]["speed_mps"] - sp["sneak"]) < 0.002 and cj["crouch_idle"]["loop"] and cj["sneak"]["loop"])
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
