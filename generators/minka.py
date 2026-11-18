"""Procedural samurai-era village farmhouse (minka) with a thatched hip roof. Blender 5.x, headless:

    blender -b --factory-startup -P generators/minka.py -- [--out fixtures/minka.blend] [--render out/_minka.png] [--no-save]

Needs:  bin/gp textures specs/biomes.json   (stone_wall, plaster_white, wood_dark, wood_light, thatch)
Output: minka_LOD0/1/2 sets, one object per material: minka_LOD<n>_{Stone,Plaster,Wood,WoodL,Thatch}
Units: metres, origin at ground level centre, +Z up, front (veranda + entrance) faces -Y. Footprint 11.2 x 7.6 m, ridge ~7.5 m.

Architecture: stone plinth, post-and-beam frame with plaster infill, lattice shoji screens on the veranda side, plank engawa veranda on round
posts, stone entrance steps, steep irimoya-style hip roof of layered straw (kayabuki) with thick rolled ridge and hip caps, smoke vent
(kemuridashi) at the ridge. Thatch is modelled as a lumpy height-field (hand-laid, not a perfect surface) with a thick rounded eave edge.
"""
import math
import os
import random
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_common import *  # noqa: E402,F401,F403
from gen_common import Rz, C, walls_rect, shoji  # noqa: E402

HX, HY = 5.6, 3.8        # wall half sizes
FZ = 0.5                 # floor level
Z0 = 3.1                 # eave (roof reference) height


def make_materials():
    return {"Stone": tileable("minka_stone", "stone_wall"), "Plaster": tileable("minka_plaster", "plaster_white"),
            "Wood": tileable("minka_wood", "wood_dark"), "WoodL": tileable("minka_woodl", "wood_light"),
            "Thatch": tileable("minka_thatch", "thatch")}


def build_thatch(th, wd, d, r, wall_half):
    step = (0.22, 0.5, 1.0)[d.lod]
    nx, ny = max(4, int(round(2 * r.ex / step))), max(4, int(round(2 * r.ey / step)))
    rng = random.Random(11)
    ph = [rng.random() * 6.28 for _ in range(4)]
    grid, meta = {}, {}
    T = TILE["Thatch"]

    def vert(i, j):
        if (i, j) in grid:
            return grid[(i, j)]
        x, y = -r.ex + 2 * r.ex * i / nx, -r.ey + 2 * r.ey * j / ny
        h, dist, along_x = r.h(x, y)
        if d.lod == 0:                                    # hand-laid lumpiness
            h += 0.038 * (math.sin(x * 2.3 + ph[0]) + math.sin(y * 3.1 + ph[1]) + 0.6 * math.sin(x * 5.7 - y * 4.3 + ph[2])) * sstep(0.02, 0.15, dist)
        v = th.bm.verts.new(th.M @ Vector((x, y, r.z0 + h)))
        grid[(i, j)] = v
        meta[(i, j)] = (x, y, dist, along_x)
        return v

    run_x, run_y = r.ex - r.ux, r.ey - r.uy
    for i in range(nx):
        for j in range(ny):
            ids = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            if max(r.h(-r.ex + 2 * r.ex * a / nx, -r.ey + 2 * r.ey * b / ny)[1] for a, b in ids) < 1e-6:
                continue
            vs = [vert(a, b) for a, b in ids]
            try:
                f = th.bm.faces.new(vs)
            except ValueError:
                continue
            f.smooth = True
            f[th.cu] = 1
            for lp, (a, b) in zip(f.loops, ids):
                x, y, dist, along_x = meta[(a, b)]
                lp[th.uvl].uv = ((x / T, (1 - dist) * run_y * 1.15 / T) if along_x else (y / T, (1 - dist) * run_x * 1.15 / T))
    # thick eave edge: vertical thatch band + soffit ring (wood) underneath
    thick = 0.55
    zs = r.z0 - thick
    ring = [(i, 0) for i in range(nx)] + [(nx, j) for j in range(ny)] + [(i, ny) for i in range(nx, 0, -1)] + [(0, j) for j in range(ny, 0, -1)]
    ring.append(ring[0])
    arc = 0.0
    for (a_, b_), (c_, e_) in zip(ring[:-1], ring[1:]):
        pa, pb = vert(a_, b_).co, vert(c_, e_).co
        out = Vector(((pa.x + pb.x) / 2, (pa.y + pb.y) / 2, 0)).normalized()
        seg = (pb - pa).length
        q = [pa, pb, Vector((pb.x, pb.y, zs)), Vector((pa.x, pa.y, zs))]
        uvs = [(arc / T, pa.z / T), ((arc + seg) / T, pb.z / T), ((arc + seg) / T, zs / T), (arc / T, zs / T)]
        if (q[1] - q[0]).cross(q[3] - q[0]).dot(out) < 0:
            q, uvs = q[::-1], uvs[::-1]
        th.face([tuple(p) for p in q], uvs=uvs)
        arc += seg
    wx, wy = wall_half
    co = [(-r.ex, -r.ey), (r.ex, -r.ey), (r.ex, r.ey), (-r.ex, r.ey)]
    ci = [(-wx, -wy), (wx, -wy), (wx, wy), (-wx, wy)]
    for k in range(4):
        a_o, b_o, a_i, b_i = co[k], co[(k + 1) % 4], ci[k], ci[(k + 1) % 4]
        q = [(a_o[0], a_o[1], zs), (b_o[0], b_o[1], zs), (b_i[0], b_i[1], zs), (a_i[0], a_i[1], zs)]
        if (Vector(q[1]) - Vector(q[0])).cross(Vector(q[3]) - Vector(q[0])).z > 0:
            q = q[::-1]
        wd.face(q)
    # exposed rafter ends under the eave (front/back)
    if d.rafters:
        k = -r.ex + 0.3
        while k < r.ex - 0.2:
            for sgn in (-1, 1):
                ln = r.ey - wy
                wd.box((k, sgn * (wy + ln / 2), zs + 0.04), (0.11, ln, 0.13))
            k += 0.55
    # thick rolled ridge + hip caps (straw bundles bound over the hips)
    a = r.ux
    zr = r.z0 + r.H
    th.cylinder((0, 0, zr + 0.12), (1, 0, 0), 0.46, 2 * a + 1.2, 8 if d.lod == 0 else 6)
    n = 9 if d.lod == 0 else 4
    for sx in (-1, 1):
        for sy in (-1, 1):
            prev = None
            for kk in range(n + 1):
                s = kk / n
                x, y = sx * (r.ux + (r.ex - r.ux) * s), sy * (r.uy + (r.ey - r.uy) * s)
                p = Vector((x, y, r.z(x, y) + 0.05))
                if prev is not None and (p - prev).length > 1e-3:
                    th.cylinder((prev + p) / 2, p - prev, 0.25, (p - prev).length + 0.1, 6)
                prev = p
    # smoke vent (kemuridashi): timber box with its own small thatched roof, set on the ridge
    if d.lod <= 1:
        wd.box((0, 0, zr + 0.45), (2.4, 1.5, 0.9))
        for sgn in (-1, 1):
            th.box((0, sgn * 0.62, zr + 1.2), (2.9, 1.25, 0.16), rx=-sgn * 0.62)
        th.box((0, 0, zr + 1.62), (2.9, 0.3, 0.3))


def build_minka(lod, mats, coll):
    d = D(lod)
    mb = {k: MB(k) for k in ("Stone", "Plaster", "Wood", "WoodL", "Thatch")}
    st, pl, wd, wl, th = mb["Stone"], mb["Plaster"], mb["Wood"], mb["WoodL"], mb["Thatch"]

    r = Roof(Z0, HX + 1.9, HY + 1.9, 3.4, 0.0, 4.4, 0.0, power=0.95, kick=0.15)
    st.box((0, 0, 0.1), (2 * HX + 0.5, 2 * HY + 0.5, 0.8))                       # plinth (z -0.3 .. 0.5)
    if lod == 0:                                                                  # individual cobbles on the plinth edge
        rng = random.Random(4)
        for side in (-1, 1):
            x = -HX - 0.1
            while x < HX + 0.1:
                w = 0.45 + rng.random() * 0.4
                st.box((x + w / 2, side * (HY + 0.28), 0.12), (w, 0.2, 0.5 + rng.random() * 0.12))
                x += w + 0.04
    walls_rect(pl, HX, HY, FZ, r, trough=0.22)          # tops sit inside the thick thatch (lumps are +-0.1)

    if d.window_frames:
        # post-and-beam frame on all four faces
        for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
            half, span = (HY, HX) if ang in (0, math.pi) else (HX, HY)
            nb = int(round(2 * span / 1.4))
            with wd.at(Rz(ang)):
                for i in range(nb + 1):
                    x = -span + 2 * span * i / nb
                    wd.box((x, -(half + 0.05), (FZ + Z0 - 0.5) / 2), (0.17, 0.17, Z0 - 0.5 - FZ))
                wd.box((0, -(half + 0.05), FZ + 0.12), (2 * span + 0.2, 0.16, 0.22))
                wd.box((0, -(half + 0.05), FZ + 1.9), (2 * span + 0.2, 0.16, 0.2))
                wd.box((0, -(half + 0.05), Z0 - 0.5), (2 * span + 0.3, 0.2, 0.24))
        # shoji bays on the veranda side (front, -Y); the middle two bays are an open entrance
        bays = [-4.9 + 1.4 * i for i in range(8)]
        for i, x in enumerate(bays):
            if i in (3, 4):
                wd.box((x, -(HY + 0.02), FZ + 0.95), (1.2, 0.05, 1.7))             # dark open doorway
            else:
                shoji(pl, wd, d, 0, HY, FZ + 1.0, x, 1.25, 1.75)
        for x in (-2.6, 0.0, 2.6):                                                # back wall windows
            window(wd, math.pi, HY, FZ + 1.4, x, 0.95, 0.8, d)
        for ang in (math.pi / 2, 3 * math.pi / 2):                                # gable-side windows
            window(wd, ang, HX, FZ + 1.4, 0.0, 1.0, 0.85, d)

    # veranda (engawa): plank deck, round posts, eave beam, stone steps
    vy = -(HY + 0.85)
    wl.box((0, vy, FZ - 0.1), (2 * HX + 0.8, 1.7, 0.2))
    if d.window_frames:
        for i in range(6):
            x = -HX + 0.2 + i * (2 * HX - 0.4) / 5
            wd.cylinder((x, -(HY + 1.55), (0.15 + Z0 - 0.62) / 2), (0, 0, 1), 0.13, Z0 - 0.77, 8 if lod == 0 else 6)
        wd.box((0, -(HY + 1.55), Z0 - 0.52), (2 * HX + 0.8, 0.22, 0.24))
        st.box((0, -(HY + 2.05), 0.16), (2.6, 0.7, 0.32))
        st.box((0, -(HY + 2.6), 0.07), (2.9, 0.6, 0.14))
        for sx in (-1, 1):
            st.box((sx * (HX + 0.3), -(HY + 1.6), 0.06), (0.5, 0.5, 0.2))

    build_thatch(th, wd, d, r, (HX, HY))

    objs = []
    for kind, b in mb.items():
        if len(b.bm.faces) == 0:
            b.bm.free()
            continue
        objs.append(b.to_object(f"minka_LOD{lod}_{kind}", mats[kind], coll))
    return objs


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "fixtures", "minka.blend")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    allobjs = {}
    for lod in (0, 1, 2):
        coll = bpy.data.collections.new(f"minka_LOD{lod}")
        bpy.context.scene.collection.children.link(coll)
        allobjs[lod] = build_minka(lod, mats, coll)
        tris = 0
        for o in allobjs[lod]:
            o.data.calc_loop_triangles()
            tris += len(o.data.loop_triangles)
        print(f"LOD{lod}: {tris:,} tris in {len(allobjs[lod])} objects")
    if "--render" in argv:
        for lod in (1, 2):
            for o in allobjs[lod]:
                o.hide_render = True
        render_preview(argv[argv.index("--render") + 1],
                       [("front", (14, -22, 6), (0, 0, 3.5), 38), ("side", (-20, -9, 5), (0, 0, 3.8), 36), ("roof", (9, -12, 9.5), (0, 0, 5.5), 40)],
                       ground_z=-0.3)
    if "--no-save" not in argv:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)
