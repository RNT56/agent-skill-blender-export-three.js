"""The working buildings of Samurai Vale's settlement, generated from the game's own definitions: every hall, hut and shed at the footprint and height its
definition gives it, three LODs each, in ONE blend that shares six tileable materials.

  hall   a timber-framed house: plastered or boarded bays between posts, lattice windows, a door on the front; thatched (hipped, with a bound ridge), tiled
         (curved hip roof with eave tiles and hip ridges) or boarded (a gable); `plaster` makes it a kura (thick white walls over a dark tile band, barred
         windows), `raised` stands it on posts with a ladder, `chimney` gives it a smoke hood
  hut    a small boarded hall under thatch with a woodpile        shed   an open-fronted work shed: boarded back and sides, posts, a bench, a boarded gable

Parameters come from specs/vale_buildings.params.json ({ id: { w, d, h, shape, roof, plaster, raised, chimney } }), which the game writes from
src/content/buildings.js (tools/export_building_params.mjs there): a new building in the game is a new model here with no further work.
Objects are named  vb_<id>_LOD<n>_<Material>. Frame: the game's +x is the width, +y up, +z the FRONT (the door); here that is (x, -z, y). y = 0 is pad level;
the game keeps drawing its own stone footing up to BASE under the model.

  blender -b --factory-startup -P generators/vale_buildings.py -- [--out fixtures/vale_buildings.blend] [--render out/_vb/vb.png]
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_common import ROOT, Roof, D, build_roof, render_preview, tileable  # noqa: E402
from wall_kit import Kit  # noqa: E402

BASE, INSET = 0.28, 0.3


class B(Kit):
    def __init__(self, lod, seed, P):
        super().__init__(lod, seed)
        self.P = P
        self.bw, self.bd = P["w"] - INSET * 2, P["d"] - INSET * 2

    def face_out(self, kind, pts, centre):
        """a polygon of game points, wound so that it faces away from `centre`"""
        q = [Vector((x, -z, y)) for x, y, z in pts]
        n = (q[1] - q[0]).cross(q[2] - q[0])
        c = Vector((centre[0], -centre[2], centre[1]))
        if n.dot(q[0] - c) < 0:
            q = q[::-1]
        self.m[kind].face([tuple(v) for v in q])

    def fbox(self, kind, side, wd, h, depth, u, y, out=0.0):
        """a box on one face of the body: u along the face (left to right seen from outside), y its base, `out` how far its centre stands off the wall"""
        hx, hz = self.bw / 2, self.bd / 2
        if side == "f":
            self.box(kind, wd, h, depth, u, y, hz + out)
        elif side == "b":
            self.box(kind, wd, h, depth, -u, y, -hz - out)
        elif side == "l":
            self.box(kind, depth, h, wd, -hx - out, y, u)
        else:
            self.box(kind, depth, h, wd, hx + out, y, -u)

    def span_of(self, side):
        return self.bw if side in "fb" else self.bd


def lattice(K, side, u, y, w, h, bars=True):
    """a renji window: a dark opening, a pale frame, upright bars"""
    if K.lod == 2:
        return
    K.fbox("Wood", side, w, h, 0.06, u, y, 0.02)
    for yy in (y - 0.07, y + h):
        K.fbox("WoodL", side, w + 0.2, 0.07, 0.1, u, yy, 0.04)
    if K.lod == 0 and bars:
        n = max(3, round(w / 0.16))
        for i in range(n):
            K.fbox("WoodL", side, 0.045, h, 0.05, u - w / 2 + w * (i + 0.5) / n, y, 0.07)


def frame_walls(K, y0, hw, style):
    """posts, sill and plate, and what fills the bays: 'plaster' (white over a boarded dado), 'board' (upright boards), 'kura' (plaster over a tile band)"""
    P, lod, bw, bd = K.P, K.lod, K.bw, K.bd
    kura = style == "kura"
    if lod == 2 or kura:
        K.box("Plaster" if style != "board" else "Wood", bw, hw, bd, 0, y0, 0)
        if kura:
            K.box("Tile", bw + 0.08, hw * 0.34, bd + 0.08, 0, y0, 0)                                   # the namako band
            if lod < 2:
                K.box("Plaster", bw + 0.2, 0.14, bd + 0.2, 0, y0 + hw * 0.34, 0)
                K.box("Plaster", bw + 0.24, 0.2, bd + 0.24, 0, y0 + hw - 0.2, 0)
        return
    t = 0.2
    K.box("Plaster" if style == "plaster" else "Wood", bw - 0.1, hw, bd - 0.1, 0, y0, 0)              # the wall plane, a little behind the frame
    for side in "fblr":
        L = K.span_of(side)
        n = max(1, round(L / 1.9))
        for i in range(n + 1):
            K.fbox("Wood", side, t, hw, t, -L / 2 + L * i / n + (t / 2 if i == 0 else -t / 2 if i == n else 0), y0, -t / 2 + 0.02)      # posts
        K.fbox("Wood", side, L, 0.16, 0.14, 0, y0, 0.0)                                               # sill
        K.fbox("Wood", side, L, 0.18, 0.14, 0, y0 + hw - 0.18, 0.0)                                   # plate
        if style == "plaster":
            K.fbox("Wood", side, L, 0.1, 0.1, 0, y0 + hw * 0.42, -0.01)                               # the rail over the dado
            if lod == 0:
                m = max(4, round(L / 0.24))
                for i in range(m):
                    K.fbox("WoodL" if i % 5 == 2 else "Wood", side, L / m - 0.012, hw * 0.42 - 0.16, 0.04, -L / 2 + L * (i + 0.5) / m, y0 + 0.16, -0.03)
            else:
                K.fbox("Wood", side, L - 0.3, hw * 0.42 - 0.16, 0.04, 0, y0 + 0.16, -0.03)
        elif lod == 0:
            m = max(4, round(L / 0.26))
            for i in range(m):
                K.fbox("Wood", side, L / m - 0.014, hw - 0.34, 0.04, -L / 2 + L * (i + 0.5) / m, y0 + 0.16, -0.03 + K.r.uniform(-0.006, 0.006))
                if i % 2:
                    K.fbox("WoodL", side, 0.04, hw - 0.34, 0.03, -L / 2 + L * i / m, y0 + 0.16, 0.0)


def door(K, y0, h, dw=1.1, kura=False):
    lod = K.lod
    K.fbox("Wood", "f", dw, h, 0.1, 0, y0, 0.03)
    if lod == 2:
        return
    fr = "Plaster" if kura else "WoodL"
    for sx in (-1, 1):
        K.fbox(fr, "f", 0.16 if kura else 0.1, h + 0.1, 0.2 if kura else 0.14, sx * (dw / 2 + 0.05), y0, 0.05)
    K.fbox(fr, "f", dw + (0.5 if kura else 0.3), 0.18 if kura else 0.12, 0.24 if kura else 0.16, 0, y0 + h, 0.05)
    if lod == 0 and not kura:
        for i in range(1, 4):
            K.fbox("WoodL", "f", dw - 0.1, 0.035, 0.03, 0, y0 + h * i / 4, 0.09)
        K.fbox("WoodL", "f", 0.035, h - 0.1, 0.03, 0, y0 + 0.05, 0.09)
    if not K.P.get("raised"):
        K.box("Stone", dw + 0.5, 0.2, 0.7, 0, BASE - 0.2, K.bd / 2 + 0.45)                            # the doorstep stone


def thatch_roof(K, ye, rise, over=0.85, thick=0.36):
    """a hipped thatch: a thick eave, a pillowed slope, a bound ridge with crossed poles"""
    lod, ex, ez = K.lod, K.bw / 2 + over, K.bd / 2 + over
    rx = max(0.5, ex - ez * 0.82)
    yr = ye + rise
    c = (0, ye + rise * 0.3, 0)
    rings = [(ex, ez, ye - 0.12), (ex + 0.02, ez + 0.02, ye + thick * 0.6), (ex - 0.14, ez - 0.14, ye + thick)]
    if lod < 2:
        f = 0.52
        rings.append((rx + (ex - rx) * (1 - f), ez * (1 - f), ye + thick + (rise - thick) * f + rise * 0.07))
    quad = lambda a: [(-a[0], a[2], -a[1]), (a[0], a[2], -a[1]), (a[0], a[2], a[1]), (-a[0], a[2], a[1])]
    K.face_out("Thatch", quad(rings[0]), c)                                                           # the cut underside of the eave
    for a, b in zip(rings[:-1], rings[1:]):
        qa, qb = quad(a), quad(b)
        for i in range(4):
            K.face_out("Thatch", [qa[i], qa[(i + 1) % 4], qb[(i + 1) % 4], qb[i]], c)
    top = quad(rings[-1])
    r0, r1 = (-rx, yr, 0), (rx, yr, 0)
    K.face_out("Thatch", [top[3], top[2], r1, r0], c)
    K.face_out("Thatch", [top[1], top[0], r0, r1], c)
    K.face_out("Thatch", [top[0], top[3], r0], c)
    K.face_out("Thatch", [top[2], top[1], r1], c)
    if lod < 2:
        K.rod("Thatch", (-rx - 0.35, yr + 0.02, 0), (rx + 0.35, yr + 0.02, 0), 0.3, 8 if lod == 0 else 6)
        K.rod("WoodL", (-rx - 0.5, yr + 0.34, 0), (rx + 0.5, yr + 0.34, 0), 0.06, 5)
    if lod == 0:
        n = max(2, round(2 * rx / 0.9))
        for i in range(n + 1):
            x = -rx + 2 * rx * i / n
            for s in (-1, 1):
                K.beam("WoodL", (x, yr + 0.62, -s * 0.2), (x, yr - 0.3, s * 0.62), 0.07, 0.07)
    if lod < 2:                                                                                       # rafter ends under the eave
        m = max(3, round(K.bw / (0.5 if lod == 0 else 1.2)))
        for i in range(m + 1):
            x = -K.bw / 2 + K.bw * i / m
            for s in (-1, 1):
                K.beam("Wood", (x, ye - 0.02, s * K.bd / 2), (x, ye - 0.16, s * (ez - 0.1)), 0.08, 0.1)


def tile_roof(K, ye, rise, over=0.75):
    d = D(K.lod)
    d.step, d.amp = (0.3, 0.6, 1.4)[K.lod], 0.0                                                      # the normal map carries the tile relief: these are small roofs, many of them
    ex, ez = K.bw / 2 + over, K.bd / 2 + over
    ux = max(0.4, ex - ez * 0.72)
    build_roof(K.m["Tile"], K.m["Wood"], d, Roof(ye, ex, ez, ux, 0.0, rise, 0.26, power=1.35, kick=0.16), (K.bw / 2, K.bd / 2))
    yr = ye + rise
    K.box("Tile", 2 * ux + 0.5, 0.2, 0.3, 0, yr - 0.04, 0)
    if K.lod < 2:
        K.rod("Tile", (-ux - 0.25, yr + 0.22, 0), (ux + 0.25, yr + 0.22, 0), 0.1, 6)
        for s in (-1, 1):
            K.box("Tile", 0.2, 0.42, 0.34, s * (ux + 0.32), yr - 0.02, 0)                             # onigawara at the ridge ends


def plank_roof(K, ye, rise, over=0.5, open_front=False):
    hw = K.bd / 2 + over
    K.gable("Wood", K.bw + 2 * over, 0, 0, ye, hw, rise, gap=0.3)
    if K.lod < 2:
        for sx in (-1, 1):                                                                            # boarded gable ends, barge boards
            x = sx * K.bw / 2
            K.prism("Wood", 0.08, x, [(-K.bd / 2, ye), (K.bd / 2, ye), (0, ye + rise * (K.bd / 2) / hw)])
            for s in (-1, 1):
                K.beam("WoodL", (sx * (K.bw / 2 + over), ye + rise + 0.1, 0), (sx * (K.bw / 2 + over), ye + 0.1, s * hw), 0.06, 0.2)
        if K.lod == 0:
            for i in range(5):                                                                        # stones that hold the boards down in a wind
                K.box("Stone", 0.3, 0.16, 0.26, K.r.uniform(-K.bw / 2, K.bw / 2), ye + rise * 0.45 + 0.08, K.r.choice((-1, 1)) * hw * 0.55, rx=0.0)


def hall(K):
    P, lod, bw, bd = K.P, K.lod, K.bw, K.bd
    H, raised = P["h"], P.get("raised", 0)
    roof, kura, hut = P["roof"], P.get("plaster", False), P["shape"] == "hut"
    thatch = roof == "thatch"
    hw = (H - raised) * (0.44 if thatch else 0.52)
    y0 = BASE + raised
    style = "kura" if kura else "board" if (hut or roof == "plank") else "plaster"
    if raised:
        for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1), (0, -1), (0, 1), (-1, 0), (1, 0)):
            K.log("Wood", 0.16, 0.15, raised + 0.1, sx * (bw / 2 - 0.25), BASE, sz * (bd / 2 - 0.25), 6 if lod < 2 else 4)
            if lod == 0:
                K.box("Stone", 0.5, 0.14, 0.5, sx * (bw / 2 - 0.25), BASE, sz * (bd / 2 - 0.25))
        K.box("Wood", bw + 0.3, 0.16, bd + 0.3, 0, y0 - 0.16, 0)
        if lod < 2:                                                                                   # a landing and a ladder to the door
            K.box("WoodL", 1.5, 0.1, 0.9, 0, y0 - 0.1, bd / 2 + 0.45)
            for sx in (-1, 1):
                K.beam("Wood", (sx * 0.45, BASE, bd / 2 + 1.55), (sx * 0.45, y0 - 0.05, bd / 2 + 0.85), 0.08, 0.14)
            for i in range(4):
                f = (i + 0.5) / 4
                K.box("WoodL", 0.9, 0.05, 0.2, 0, BASE + raised * f, bd / 2 + 1.55 - 0.7 * f)
    frame_walls(K, y0, hw, style)
    dh = min(1.9, hw * 0.8)
    door(K, y0, dh, 1.1 if not kura else 1.2, kura)
    # windows: beside the door where there is room, and along the other faces
    wh, wy = min(0.8, hw * 0.34), y0 + hw * (0.56 if not kura else 0.62)
    if kura:
        for side in "lrb":
            L = K.span_of(side)
            for u in ([-L * 0.25, L * 0.25] if L > 5 else [0]):
                lattice(K, side, u, wy + 0.2, 0.6, 0.5)
                if lod < 2:
                    K.fbox("Plaster", side, 0.9, 0.12, 0.2, u, wy + 0.72, 0.06)
    else:
        if bw > 4.4:
            for s in (-1, 1):
                lattice(K, "f", s * (bw / 4 + 0.35), wy, min(1.3, bw / 2 - 1.5), wh)
        for side in "lr":
            lattice(K, side, 0, wy, min(1.6, bd * 0.4), wh)
        if bw > 7:
            for u in (-bw * 0.25, bw * 0.25):
                lattice(K, "b", u, wy, 1.2, wh)
    ye = y0 + hw
    rise = (H - raised) - hw - (0 if thatch else 0.2)
    if thatch:
        thatch_roof(K, ye, rise + 0.2)
    elif roof == "tile":
        tile_roof(K, ye, rise)
    else:
        plank_roof(K, ye, rise * 0.8)
    if P.get("chimney"):                                                                              # a plastered smoke hood through the roof, under its own little gable
        cx, cz = bw * 0.26, -bd * 0.18
        K.box("Plaster", 0.8, rise + 0.9, 0.8, cx, ye + 0.2, cz)
        K.gable("Wood" if roof != "tile" else "Tile", 1.3, cx, cz, ye + rise + 1.3, 0.62, 0.3, rolls=False)
        if lod < 2:
            for sx in (-1, 1):
                for sz in (-1, 1):
                    K.box("Wood", 0.08, 0.26, 0.08, cx + sx * 0.36, ye + rise + 1.08, cz + sz * 0.36)
    if hut and lod < 2:                                                                               # the woodpile against the side wall
        for row in range(3):
            for i in range(4 - row):
                K.m["WoodL" if (row + i) % 2 else "Wood"].cylinder((bw / 2 + 0.75, bd * 0.25 - i * 0.27 - row * 0.135, BASE + 0.13 + row * 0.23), (1, 0, 0), 0.13, 0.9, 6)


def shed(K):
    P, lod, bw, bd = K.P, K.lod, K.bw, K.bd
    H = P["h"]
    hw = H * 0.55
    y0 = BASE
    for side in "blr":                                                                                # boarded back and sides
        L = K.span_of(side)
        if lod == 0:
            m = max(4, round(L / 0.26))
            for i in range(m):
                K.fbox("Wood", side, L / m - 0.014, hw - 0.1, 0.05, -L / 2 + L * (i + 0.5) / m, y0, -0.06 + K.r.uniform(-0.006, 0.006))
        else:
            K.fbox("Wood", side, L, hw - 0.1, 0.05, 0, y0, -0.06)
        if lod < 2:
            for yy in (y0 + 0.4, y0 + hw * 0.6):
                K.fbox("WoodL", side, L, 0.1, 0.06, 0, yy, -0.12)
    n = max(2, round(bw / 2.4))
    for i in range(n + 1):
        x = -bw / 2 + 0.1 + (bw - 0.2) * i / n
        for z in (bd / 2 - 0.1, -bd / 2 + 0.1):
            K.box("Wood", 0.18, hw, 0.18, x, y0, z)
            if lod == 0 and z > 0:
                K.box("Stone", 0.4, 0.12, 0.4, x, y0 - 0.04, z)
        if lod < 2:
            K.box("Wood", 0.14, 0.16, bd - 0.2, x, y0 + hw - 0.16, 0)
            if True:
                K.beam("Wood", (x, y0 + hw - 0.7, bd / 2 - 0.1), (x + (0.6 if i < n else -0.6), y0 + hw - 0.1, bd / 2 - 0.1), 0.08, 0.08)
    K.box("Wood", bw, 0.18, 0.16, 0, y0 + hw - 0.18, bd / 2 - 0.1)
    if lod < 2:                                                                                       # the bench, a trestle, a rack on the back wall
        K.box("WoodL", bw * 0.5, 0.1, bd * 0.3, 0, y0 + 0.62, -bd * 0.08)
        for sx in (-1, 1):
            K.box("Wood", 0.1, 0.62, bd * 0.26, sx * bw * 0.2, y0, -bd * 0.08)
        K.box("WoodL", bw * 0.6, 0.06, 0.3, 0, y0 + hw * 0.62, -bd / 2 + 0.3)
        if lod == 0:
            for i in range(4):
                K.box("Stone" if i % 2 else "WoodL", 0.3, 0.26, 0.3, -bw * 0.32 + i * 0.36, y0, bd * 0.2, rz=K.r.uniform(0, 1))
    plank_roof(K, y0 + hw, H * 0.3)


def make_materials():
    return {"Stone": tileable("vb_stone", "stone_wall"), "Plaster": tileable("vb_plaster", "plaster_white"), "Wood": tileable("vb_wood", "wood_dark"),
            "WoodL": tileable("vb_woodl", "wood_light"), "Tile": tileable("vb_tile", "roof_tile"), "Thatch": tileable("vb_thatch", "thatch")}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "fixtures", "vale_buildings.blend")
    params = json.load(open(os.path.join(ROOT, "specs", "vale_buildings.params.json")))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    built = {}
    for lod in (0, 1, 2):
        coll = bpy.data.collections.new(f"vb_LOD{lod}")
        bpy.context.scene.collection.children.link(coll)
        total = 0
        for bi, (bid, P) in enumerate(params.items()):
            K = B(lod, 500 + bi * 53, P)
            (shed if P["shape"] == "shed" else hall)(K)
            objs = K.objects(f"vb_{bid}", mats, coll)
            tris = 0
            for o in objs:
                o.data.calc_loop_triangles()
                tris += len(o.data.loop_triangles)
            built[(lod, bid)] = objs
            total += tris
            if lod == 0:
                print(f"LOD0 {bid:16s} {tris:6,d} tris")
        print(f"LOD{lod}: {total:,} tris")
    if "--render" in argv:
        ids = list(params)
        for (lod, bid), objs in built.items():
            for o in objs:
                o.hide_render = lod != 0
                if lod == 0:
                    i = ids.index(bid)
                    o.location = ((i % 5 - 2) * 14.0, -(i // 5) * 13.0, 0)
        tag = argv[argv.index("--render") + 1]
        views = [("all", (10, 30, 42), (0, -22, 0), 30)]
        for row in range((len(ids) + 4) // 5):
            y = -row * 13.0
            views += [(f"row{row}_front", (6, y - 16, 12), (0, y, 2), 20), (f"row{row}_back", (-14, y + 13, 9), (0, y, 2), 22)]
        render_preview(tag, views, ground_z=0.0)
        for objs in built.values():
            for o in objs:
                o.location = (0, 0, 0)
                o.hide_render = False
        for o in list(bpy.data.objects):
            if o.type != "MESH" or not o.name.startswith("vb_"):
                bpy.data.objects.remove(o)
    if "--no-save" not in argv:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)


if __name__ == "__main__":
    main()
