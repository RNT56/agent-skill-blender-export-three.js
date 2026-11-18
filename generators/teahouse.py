"""Procedural waterside teahouse (chaya) on stilts with a pier and stone lanterns. Blender 5.x, headless:

    blender -b --factory-startup -P generators/teahouse.py -- [--out fixtures/teahouse.blend] [--render out/_tea.png] [--no-save]

Needs:  bin/gp textures specs/biomes.json   (stone_wall, plaster_white, wood_dark, wood_light, roof_tile)
Output: teahouse_LOD0/1/2 sets: teahouse_LOD<n>_{Stone,Plaster,Wood,WoodL,Tile}
Units: metres. ORIGIN = THE WATER SURFACE (z=0); deck top at z=0.9. +Y points to the SHORE (the pier runs along +Y for 9 m), the
lake-side front faces -Y. Footprint 7.8 x 5.4 m room, 10.6 x 8.2 m deck, ridge ~6.1 m above the water.

Architecture: 28 round posts driven into the lake bed, plank deck on joists, post-and-beam room with plaster knee walls and shoji screens,
low railings, tiled irimoya-style hip roof with the shared curved-eave builder, plank pier with rails, two stone lanterns (tourou).
"""
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_common import *  # noqa: E402,F401,F403
from gen_common import Rz, C, walls_rect, shoji, railing  # noqa: E402

HX, HY = 3.9, 2.7
DZ = 0.9                  # deck top above the water
Z0 = DZ + 2.85            # eave height
PIER = 9.0


def make_materials():
    return {"Stone": tileable("tea_stone", "stone_wall"), "Plaster": tileable("tea_plaster", "plaster_white"),
            "Wood": tileable("tea_wood", "wood_dark"), "WoodL": tileable("tea_woodl", "wood_light"),
            "Tile": tileable("tea_tile", "roof_tile")}


def lantern(st, x, y, z):
    st.box((x, y, z + 0.06), (0.62, 0.62, 0.12))
    st.box((x, y, z + 0.5), (0.24, 0.24, 0.75))
    st.box((x, y, z + 0.93), (0.58, 0.58, 0.1))
    st.box((x, y, z + 1.17), (0.36, 0.36, 0.4))
    st.box((x, y, z + 1.45), (0.78, 0.78, 0.12))
    st.box((x, y, z + 1.58), (0.44, 0.44, 0.14))
    st.box((x, y, z + 1.72), (0.16, 0.16, 0.16))


def build_teahouse(lod, mats, coll):
    d = D(lod)
    mb = {k: MB(k) for k in ("Stone", "Plaster", "Wood", "WoodL", "Tile")}
    st, pl, wd, wl, tl = mb["Stone"], mb["Plaster"], mb["Wood"], mb["WoodL"], mb["Tile"]
    DX, DY = HX + 1.4, HY + 1.4                                        # deck half sizes

    # stilts + deck
    seg = 8 if lod == 0 else 5
    for x in (-5.0, -2.5, 0.0, 2.5, 5.0):
        for y in (-3.9, -1.3, 1.3, 3.9):
            wd.cylinder((x, y, (-3.2 + 0.72) / 2), (0, 0, 1), 0.16, 3.92, seg)
    wl.box((0, 0, DZ - 0.1), (2 * DX, 2 * DY, 0.2))
    if d.rafters:
        for i in range(-4, 5):                                          # joists under the deck
            wd.box((i * 1.2, 0, DZ - 0.38), (0.16, 2 * DY - 0.2, 0.28))
        for sy in (-DY + 0.1, DY - 0.1):
            wd.box((0, sy, DZ - 0.3), (2 * DX, 0.22, 0.3))

    # room
    r = Roof(Z0, HX + 1.9, HY + 1.9, 1.6, 0.0, 2.3, 0.35)
    walls_rect(pl, HX, HY, DZ, r, trough=0.04)
    if d.window_frames:
        for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
            half, span = (HY, HX) if ang in (0, math.pi) else (HX, HY)
            nb = int(round(2 * span / 1.95))
            with wd.at(Rz(ang)):
                for i in range(nb + 1):
                    x = -span + 2 * span * i / nb
                    wd.box((x, -(half + 0.05), (DZ + Z0 - 0.3) / 2), (0.17, 0.17, Z0 - 0.3 - DZ))
                wd.box((0, -(half + 0.05), DZ + 0.1), (2 * span + 0.2, 0.16, 0.2))
                wd.box((0, -(half + 0.05), DZ + 2.5), (2 * span + 0.2, 0.16, 0.22))
                wd.box((0, -(half + 0.05), Z0 - 0.3), (2 * span + 0.3, 0.2, 0.22))
        # shoji: lake side (-Y) all five bays; sides three bays; shore side (+Y) with an open doorway in the middle
        for i in range(5):
            shoji(pl, wd, d, 0, HY, DZ + 1.5, -3.12 + 1.56 * i, 1.4, 1.9)
        for ang in (math.pi / 2, 3 * math.pi / 2):
            for a in (-1.8, 0.0, 1.8):
                shoji(pl, wd, d, ang, HX, DZ + 1.5, a, 1.55, 1.9)
        for i in range(5):
            x = -3.12 + 1.56 * i
            if i == 2:
                wd.box((x, HY + 0.02, DZ + 1.0), (1.2, 0.05, 1.9))
            else:
                shoji(pl, wd, d, math.pi, HY, DZ + 1.5, x, 1.4, 1.9)
        # deck railings (open at the pier)
        for p0, p1 in [((-DX, -DY, DZ), (DX, -DY, DZ)), ((-DX, -DY, DZ), (-DX, DY, DZ)), ((DX, -DY, DZ), (DX, DY, DZ)),
                       ((-DX, DY, DZ), (-1.1, DY, DZ)), ((1.1, DY, DZ), (DX, DY, DZ))]:
            railing(wl if lod == 0 else wd, p0, p1)
        # veranda posts carry the eave
        for x in (-DX + 0.15, -DX / 2, 0.0, DX / 2, DX - 0.15):
            for y in (-DY + 0.15, DY - 0.15):
                if abs(x) < 0.01 and y > 0:
                    continue
                wd.cylinder((x, y, (DZ + Z0 - 0.45) / 2), (0, 0, 1), 0.12, Z0 - 0.45 - DZ, 8 if lod == 0 else 5)
        wd.box((0, -DY + 0.15, Z0 - 0.4), (2 * DX, 0.2, 0.22))
        wd.box((0, DY - 0.15, Z0 - 0.4), (2 * DX, 0.2, 0.22))

    # pier
    y0 = DY
    wl.box((0, y0 + PIER / 2, DZ - 0.08), (2.0, PIER, 0.16))
    if d.window_frames:
        for yy in (y0 + 1.5, y0 + 4.5, y0 + 7.5):
            for sx in (-0.9, 0.9):
                wd.cylinder((sx, yy, (-3.2 + 0.8) / 2), (0, 0, 1), 0.13, 4.0, 6)
        for sx in (-0.95, 0.95):
            railing(wd, (sx, y0, DZ), (sx, y0 + PIER, DZ), h=0.8, post_every=1.5)
        for sx in (-1.45, 1.45):
            lantern(st, sx, y0 + PIER + 0.2, DZ)
        st.box((0, y0 + PIER + 0.5, DZ - 0.1), (2.6, 0.8, 0.22))                 # shore landing stone

    # tiled hip roof
    build_roof(tl, wd, d, r, (HX, HY))
    zr = r.z0 + r.H
    a = r.ux
    tl.box((0, 0, zr + 0.12), (2 * a + 0.6, 0.62, 0.30))
    tl.cylinder((0, 0, zr + 0.40), (1, 0, 0), 0.26, 2 * a + 0.6, 8)
    if d.ornaments:
        for sx in (-1, 1):
            tl.box((sx * (a + 0.28), 0, zr + 0.42), (0.5, 0.8, 0.8))
            tl.box((sx * (a + 0.33), 0, zr + 0.95), (0.3, 0.5, 0.4))

    objs = []
    for kind, b in mb.items():
        if len(b.bm.faces) == 0:
            b.bm.free()
            continue
        objs.append(b.to_object(f"teahouse_LOD{lod}_{kind}", mats[kind], coll))
    return objs


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "fixtures", "teahouse.blend")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    allobjs = {}
    for lod in (0, 1, 2):
        coll = bpy.data.collections.new(f"teahouse_LOD{lod}")
        bpy.context.scene.collection.children.link(coll)
        allobjs[lod] = build_teahouse(lod, mats, coll)
        tris = 0
        for o in allobjs[lod]:
            o.data.calc_loop_triangles()
            tris += len(o.data.loop_triangles)
        print(f"LOD{lod}: {tris:,} tris in {len(allobjs[lod])} objects")
    if "--render" in argv:
        for lod in (1, 2):
            for o in allobjs[lod]:
                o.hide_render = True
        # a water plane at z=0 so the stilts read in the QA render
        bpy.ops.mesh.primitive_plane_add(size=120, location=(0, 0, 0))
        wm = bpy.data.materials.new("water")
        wm.use_nodes = True
        wm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.03, 0.12, 0.16, 1)
        wm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.08
        bpy.context.active_object.data.materials.append(wm)
        render_preview(argv[argv.index("--render") + 1],
                       [("front", (15, -22, 5), (0, 3, 2.8), 38), ("pier", (-9, 22, 4), (0, 6, 2), 36), ("roof", (9, -11, 9), (0, 0, 4), 40)],
                       ground_z=-3.3)
    if "--no-save" not in argv:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)
