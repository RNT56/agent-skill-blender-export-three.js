"""QA sheets from the saved fixture (EEVEE, studio + environment):  blender -b fixtures/samurai_unit.blend -P generators/samurai_qa.py
Writes out/samurai_unit_01/qa/: hero views (rest pose) and one contact strip per clip. LOOK at them: logs cannot tell a floating
cuff from a held hilt. Needs the baked textures in out/samurai_tex/ (the fixture references them)."""
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from samurai import anim, clips, qa
from samurai.pose import show_pose

OUT = os.path.join(ROOT, "out", "samurai_unit_01", "qa")
os.makedirs(OUT, exist_ok=True)
arm = bpy.data.objects["SamuraiRig"]
sv = anim.Solver(arm)
for o in bpy.data.objects:
    if o.type == "MESH" and o.name in ("Samurai_LOD1", "Samurai_LOD2"):
        o.hide_render = True
cam = qa.setup_scene((600, 900), 24)
sc = bpy.context.scene
sc.render.fps = 30


def shoot(tag, view):
    loc, tgt, lens = qa.VIEWS[view]
    cam.data.lens = lens
    cam.location = loc
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = os.path.join(OUT, f"_{tag}.png")
    bpy.ops.render.render(write_still=True)
    return sc.render.filepath


bpy.data.objects["Katana_Drawn"].hide_render = True
files = [shoot(f"hero_{v}", v) for v in ("front", "three", "back", "head")]
qa.montage(files, os.path.join(OUT, "hero.png"))
for name, c in clips.CLIPS.items():
    sc.render.resolution_x, sc.render.resolution_y = 330, 480
    view = "side_c" if name in ("walk", "run") else "three_c"
    fr = []
    n = 8
    for i in range(n):
        t = c["duration"] * (i / n if c["loop"] else i / (n - 1))
        drawn = clips.weapon_at(name, t) == "drawn"
        bpy.data.objects["Katana_Drawn"].hide_render = not drawn
        bpy.data.objects["Katana_Sheathed"].hide_render = drawn
        show_pose(arm, sv.solve(c["fn"](t)))
        bpy.context.view_layer.update()
        fr.append(shoot(f"clip_{name}_{i}", view))
    qa.montage(fr, os.path.join(OUT, f"clip_{name}.png"))
    for f in fr:
        os.remove(f)
    sc.render.resolution_x, sc.render.resolution_y = 600, 900
for f in files:
    os.remove(f)
print("QA sheets ->", OUT)
