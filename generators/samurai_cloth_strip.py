"""Contact strips of the BAKED clips (cloth included), from a placeholder build:
    blender -b --factory-startup -P generators/samurai_cloth_strip.py -- --clip run --frames 8 --views back_q,front_c [--out out/_cloth]
The pose-only strips of samurai_unit.py --clip do not run the cloth simulation; these evaluate the armature's Action, so the tails and the flag move as they will in the game."""
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from samurai import build, clips, finalize, qa

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(n, d=None):
    return argv[argv.index(n) + 1] if n in argv else d


def main():
    name = arg("--clip", "run")
    mdl = build.build_model("all")
    arm = mdl["arm"]
    sc = bpy.context.scene
    sc.render.fps = 30
    finalize.bake_clips(arm, names=[name], log=print)
    act = bpy.data.actions[name]
    arm.animation_data_create()
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and act.slots:
        arm.animation_data.action_slot = act.slots[0]
    drawn = clips.CLIPS[name]["weapon"] == "drawn"
    mdl["Katana_Drawn"].hide_render = not drawn
    mdl["Katana_Sheathed"].hide_render = drawn
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    nfr = int(arg("--frames", 8))
    cam = qa.setup_scene((int(arg("--w", 360)), int(arg("--h", 520))), 8)
    out = os.path.join(ROOT, arg("--out", "out/_cloth"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rows = []
    for view in arg("--views", "back_q,front_c").split(","):
        loc, tgt, lens = qa.VIEWS[view]
        files = []
        for i in range(nfr):
            f = f0 + round((f1 - f0) * i / nfr) if clips.CLIPS[name]["loop"] else f0 + round((f1 - f0) * i / max(nfr - 1, 1))
            sc.frame_set(f)
            bpy.context.view_layer.update()
            cam.data.lens = lens
            cam.location = loc
            cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = f"{out}_{name}_{view}_{i}.png"
            bpy.ops.render.render(write_still=True)
            files.append(sc.render.filepath)
        qa.montage(files, f"{out}_{name}_{view}.png", cols=nfr)
        rows.append(f"{out}_{name}_{view}.png")
    print("STRIP", " ".join(rows))


main()
