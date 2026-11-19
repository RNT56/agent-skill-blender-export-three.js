"""The working buildings of Samurai Vale's settlement, generated from the game's own definitions: every hall, hut and shed at the footprint and height its
definition gives it, three LODs each, in ONE blend that shares nine tileable materials.

A building keeps to its footprint (the game snaps and paths by that box) but does not look like one:

  the body      stands back from the box, off-centre: timber posts on foundation stones with a shadow under the sill, bays of daub, plaster or boards, a
                boarded dado, shoji and lattice windows, a sliding door left half open
  the veranda   an engawa along the front of a house under its own pent roof on slender posts
  the lean-to   a low boarded annex on one side of the bigger halls, for firewood
  the roof      thatch with rounded hips and a bound ridge, a curved tiled hip roof, shingles, or lapped boards under poles and stones (roofs.py); a louvred
                smoke vent rides the ridge of a forge
  what is done there   every kind has its own things about it: rice bales, barrels, a quench tub and an anvil, staves, cloth on a pole, stone blocks...

  hall  a house, store or workshop     kura (plaster)  thick white walls over a dark tile band, barred windows     raised  on posts, with a ladder
  hut   a small boarded hall under thatch     shed  an open-fronted work shed
  and the ones that are round by nature:  well (a round stone curb under a round cap of thatch)   kiln (a charcoal burner's earthen dome)
  stalls (a market under big paper umbrellas)   shrine (a torii of round posts, stone lanterns, a water basin)   tower (a lookout with a signal drum)

Parameters come from specs/vale_buildings.params.json ({ id: { w, d, h, shape, roof, plaster, raised, chimney } }), which the game writes from
src/content/buildings.js (tools/export_building_params.mjs there): a new building in the game is a new model here with no further work.
Objects are named  vb_<id>_LOD<n>_<Material>. Frame: the game's +x is the width, +y up, +z the FRONT (the door, at x = 0); here that is (x, -z, y). y = 0 is
the ground (the levelled pad): there is no plinth. Posts stand on half-buried field stones, boards and walls go SINK metres into the earth, a dwelling's
floor is raised on its stones with the dark under it, and a flat stone lies before every door.

  blender -b --factory-startup -P generators/vale_buildings.py -- [--out fixtures/vale_buildings.blend] [--render out/_vb/vb.png]
"""
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_common import ROOT, Roof, D, build_roof, render_preview  # noqa: E402
from wall_kit import Kit, make_materials  # noqa: E402
from roofs import thatch_roof, shingle_roof, board_roof, rock, G  # noqa: E402

BASE, M, SINK = 0.0, 0.32, 0.24      # BASE: the ground (the levelled pad). Nothing stands ON it: posts, boards and walls go SINK metres into it


class B(Kit):
    def __init__(self, lod, seed, P):
        super().__init__(lod, seed)
        self.P, self.bw, self.bd = P, 1.0, 1.0

    def box(self, kind, w, h, d, x, y, z, rz=0.0, rx=0.0, ry=0.0):
        """whatever is tall and starts at the ground is rooted in it (so no post or wall ever ends in a ruled line on the earth, and a dip never shows a gap)"""
        if abs(y - BASE) < 1e-6 and h >= 0.3 and not (rz or rx or ry):
            y, h = y - SINK, h + SINK
        super().box(kind, w, h, d, x, y, z, rz=rz, rx=rx, ry=ry)

    def shift(self, cx, cz):
        """everything built inside is centred on (cx, cz) of the footprint"""
        k = self

        class _Ctx:
            def __enter__(s):
                for mb in k.m.values():
                    mb.push(Matrix.Translation(G(cx, 0, cz)))

            def __exit__(s, *a):
                for mb in k.m.values():
                    mb.pop()
        return _Ctx()

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


# ------------------------------------------------------------------------------------------------------------------ things
def barrel(K, x, z, y=BASE, r=0.3, h=0.72, lid=True):
    if K.lod == 2:
        return
    segs = 10 if K.lod == 0 else 6
    K.m["WoodL"].cone(G(x, y + h * 0.25, z), (0, 0, 1), r * 0.88, r, h * 0.5, segs)
    K.m["WoodL"].cone(G(x, y + h * 0.75, z), (0, 0, 1), r, r * 0.88, h * 0.5, segs)
    if K.lod == 0:
        for f in (0.16, 0.5, 0.84):
            K.m["Wood"].cylinder(G(x, y + h * f, z), (0, 0, 1), r * (1.02 if f == 0.5 else 0.95), 0.045, segs)
    if lid:
        K.m["Wood"].cylinder(G(x, y + h + 0.01, z), (0, 0, 1), r * 0.9, 0.03, segs)


def bale(K, x, z, y=BASE, ang=0.0, r=0.27, ln=0.8):
    """a tawara: a rice bale of straw, lying"""
    if K.lod == 2:
        return
    d = (math.cos(ang), -math.sin(ang), 0)
    K.m["Thatch"].cylinder(G(x, y + r, z), d, r, ln, 9 if K.lod == 0 else 6)
    if K.lod == 0:
        for f in (-0.3, 0.3):
            K.m["WoodL"].cylinder(G(x + math.cos(ang) * ln * f, y + r, z + math.sin(ang) * ln * f), d, r * 1.03, 0.04, 9)


def jar(K, x, z, y=BASE, s=1.0):
    if K.lod == 2:
        return
    segs = 9 if K.lod == 0 else 6
    K.m["Tile"].cone(G(x, y + 0.2 * s, z), (0, 0, 1), 0.16 * s, 0.26 * s, 0.4 * s, segs)
    K.m["Tile"].cone(G(x, y + 0.5 * s, z), (0, 0, 1), 0.26 * s, 0.15 * s, 0.2 * s, segs)


def woodpile(K, x, z, ln=1.6, rows=4, along_x=True, y=BASE):
    if K.lod == 2:
        return
    for row in range(rows):
        n = max(1, int(ln / 0.24)) - row % 2
        for i in range(n):
            u = -ln / 2 + 0.14 + i * 0.24 + (0.12 if row % 2 else 0)
            px, pz = (x + u, z) if along_x else (x, z + u)
            K.m["WoodL" if (i + row) % 3 else "Wood"].cylinder(G(px, y + 0.11 + row * 0.2, pz), (0, 1, 0) if along_x else (1, 0, 0), 0.105 + 0.02 * K.r.random(), 0.72, 6 if K.lod == 0 else 4)


def lantern(K, x, z, y):
    """an andon by the door: a paper box in a slight frame on a foot"""
    if K.lod == 2:
        return
    K.box("Paper", 0.26, 0.4, 0.26, x, y + 0.28, z)
    if K.lod == 0:
        for sx in (-1, 1):
            for sz in (-1, 1):
                K.box("Wood", 0.035, 0.74, 0.035, x + sx * 0.135, y, z + sz * 0.135)
        K.box("Wood", 0.34, 0.035, 0.34, x, y + 0.68, z)
        K.box("Wood", 0.3, 0.03, 0.3, x, y + 0.25, z)


def rack(K, x, z, ln, y=BASE, h=1.5, items=6, kind="WoodL", along_x=True):
    """two posts and two rails with staves, spears or bows leaning in it"""
    if K.lod == 2:
        return
    e = (ln / 2, 0) if along_x else (0, ln / 2)
    for s in (-1, 1):
        K.box("Wood", 0.08, h, 0.08, x + s * e[0], y, z + s * e[1])
    for yy in (0.55, h - 0.12):
        K.box("Wood", ln if along_x else 0.06, 0.06, 0.06 if along_x else ln, x, y + yy, z)
    if K.lod == 0:
        for i in range(items):
            f = (i + 0.5) / items - 0.5
            px, pz = (x + f * ln * 0.86, z) if along_x else (x, z + f * ln * 0.86)
            K.rod(kind, (px, y, pz + (0.18 if along_x else 0)) if along_x else (px + 0.18, y, pz), (px, y + h + 0.45 + 0.3 * K.r.random(), pz - (0.04 if along_x else 0)) if along_x else (px - 0.04, y + h + 0.45 + 0.3 * K.r.random(), pz), 0.02, 4)


def bench(K, x, z, ln=1.3, y=BASE, along_x=True):
    if K.lod == 2:
        return
    K.box("WoodL", ln if along_x else 0.36, 0.05, 0.36 if along_x else ln, x, y + 0.4, z)
    for s in (-1, 1):
        K.box("Wood", 0.06 if along_x else 0.3, 0.4, 0.3 if along_x else 0.06, x + (s * (ln / 2 - 0.12) if along_x else 0), y, z + (0 if along_x else s * (ln / 2 - 0.12)))


# ------------------------------------------------------------------------------------------------------------------ the body
def shoji(K, side, u, y, w, h):
    """a paper window behind upright bars (the paper glows at night in the game)"""
    if K.lod == 2:
        return
    K.fbox("Paper", side, w, h, 0.05, u, y, 0.015)
    for yy in (y - 0.07, y + h):
        K.fbox("WoodL", side, w + 0.2, 0.07, 0.1, u, yy, 0.04)
    for uu in (u - w / 2 - 0.035, u + w / 2 + 0.035):
        K.fbox("WoodL", side, 0.07, h, 0.1, uu, y, 0.04)
    if K.lod == 0:
        n = max(3, round(w / 0.19))
        for i in range(1, n):
            K.fbox("Wood", side, 0.032, h, 0.04, u - w / 2 + w * i / n, y, 0.06)
        K.fbox("Wood", side, w, 0.03, 0.04, u, y + h * 0.5, 0.06)


def barred(K, side, u, y, w, h):
    """the small barred window of a store, with a plaster hood"""
    if K.lod == 2:
        return
    K.fbox("Wood", side, w, h, 0.08, u, y, 0.0)
    K.fbox("Plaster", side, w + 0.36, 0.13, 0.26, u, y + h + 0.02, 0.07)
    K.fbox("Plaster", side, w + 0.22, 0.09, 0.16, u, y - 0.09, 0.04)
    if K.lod == 0:
        for i in range(4):
            K.fbox("WoodL", side, 0.05, h, 0.06, u - w / 2 + w * (i + 0.5) / 4, y, 0.04)


def frame_walls(K, y0, hw, style, door_u):
    """posts on foundation stones, sill and plate, and what fills the bays: 'earth' / 'plaster' (a panel over a boarded dado), 'board', 'kura'"""
    lod, bw, bd, r = K.lod, K.bw, K.bd, K.r
    if style == "kura":
        K.box("Plaster", bw, hw + y0 - BASE, bd, 0, BASE, 0)
        K.box("Tile", bw + 0.09, hw * 0.36, bd + 0.09, 0, BASE, 0)                                     # the namako band
        if lod < 2:
            K.box("Plaster", bw + 0.2, 0.13, bd + 0.2, 0, BASE + hw * 0.36, 0)
            K.box("Plaster", bw + 0.3, 0.24, bd + 0.3, 0, y0 + hw - 0.24, 0)                           # the swelling cornice under the eaves
            for sx in (-1, 1):
                for sz in (-1, 1):
                    K.box("Plaster", 0.34, hw, 0.34, sx * bw / 2, BASE, sz * bd / 2)
                    rock(K, sx * (bw / 2 + 0.08), BASE - 0.18, sz * (bd / 2 + 0.08), r.uniform(0.44, 0.58), flat=0.5)      # a boulder under each corner, half in the earth
        return
    panel = {"earth": "Earth", "plaster": "Plaster", "board": "Wood"}[style]
    if lod == 2:
        K.box(panel, bw, hw + y0 - BASE, bd, 0, BASE, 0)
        return
    if y0 - BASE < 0.6:                                                                                # (a granary on stilts is open underneath)
        K.box("Wood", bw - 0.56, y0 - BASE + SINK, bd - 0.56, 0, BASE - SINK, 0)                         # the dark under the floor, well back from the sill
    K.box(panel, bw - 0.1, hw, bd - 0.1, 0, y0, 0)
    t = 0.19
    for side in "fblr":
        L = K.span_of(side)
        n = max(1, round(L / 1.85))
        for i in range(n + 1):
            u = -L / 2 + L * i / n + (t / 2 if i == 0 else -t / 2 if i == n else 0)
            K.fbox("Wood", side, t * r.uniform(0.92, 1.08), hw + (y0 - BASE) - 0.1, t, u, BASE + 0.1, -t / 2 + 0.03)
            if side in "fb" or 0 < i < n:                                                              # every post stands on a stone
                hx, hz = K.bw / 2, K.bd / 2
                px, pz = {"f": (u, hz - 0.05), "b": (-u, -hz + 0.05), "l": (-hx + 0.05, u), "r": (hx - 0.05, -u)}[side]
                rock(K, px, BASE - 0.12, pz, r.uniform(0.24, 0.34), flat=0.7)
        K.fbox("Wood", side, L, 0.17, 0.15, 0, y0 - 0.02, 0.0)                                         # sill
        K.fbox("Wood", side, L, 0.18, 0.15, 0, y0 + hw - 0.18, 0.0)                                    # plate
        if style != "board":
            K.fbox("Wood", side, L, 0.1, 0.1, 0, y0 + hw * 0.4, -0.01)                                 # the rail over the dado
            if lod == 0:
                m = max(4, round(L / 0.23))
                for i in range(m):
                    uu = -L / 2 + L * (i + 0.5) / m
                    if side == "f" and abs(uu - door_u) < 0.7:
                        continue
                    K.fbox("WoodL" if i % 6 == 2 else "Wood", side, L / m - 0.012, hw * 0.4 - 0.15, 0.04, uu, y0 + 0.15, -0.03 + r.uniform(-0.005, 0.005))
                K.fbox("Wood", side, L, 0.07, 0.08, 0, y0 + hw * 0.74, -0.03)                          # a nuki shows through the daub
            else:
                K.fbox("Wood", side, L - 0.3, hw * 0.4 - 0.15, 0.04, 0, y0 + 0.15, -0.03)
        elif lod == 0:
            m = max(4, round(L / 0.25))
            for i in range(m):
                K.fbox("Wood", side, L / m - 0.014, hw - 0.34, 0.04, -L / 2 + L * (i + 0.5) / m, y0 + 0.16, -0.03 + r.uniform(-0.006, 0.006))
                if i % 2:
                    K.fbox("WoodL", side, 0.04, hw - 0.34, 0.03, -L / 2 + L * i / m, y0 + 0.16, 0.0)


def door(K, y0, h, u, dw=1.1, kura=False, shop=False):
    """a doorway on the front at u: the dark of the room, a sliding door left half open (or a store's heavy plastered leaf), a shop's short curtain"""
    lod = K.lod
    K.fbox("Wood", "f", dw, h, 0.12, u, y0, -0.02)
    if lod == 2:
        return
    fr = "Plaster" if kura else "WoodL"
    for sx in (-1, 1):
        K.fbox(fr, "f", 0.2 if kura else 0.1, h + 0.1, 0.26 if kura else 0.15, u + sx * (dw / 2 + (0.1 if kura else 0.05)), y0, 0.05)
    K.fbox(fr, "f", dw + (0.62 if kura else 0.3), 0.2 if kura else 0.12, 0.3 if kura else 0.17, u, y0 + h, 0.06)
    if kura:
        K.fbox("Plaster", "f", dw * 0.55, h - 0.08, 0.16, u + dw * 0.62, y0 + 0.04, 0.12)             # the thick leaf, swung open
        if lod == 0:
            K.fbox("Tile", "f", 0.1, 0.5, 0.05, u + dw * 0.4, y0 + h * 0.45, 0.21)
    else:
        leaf = dw * 0.56
        K.fbox("WoodL", "f", leaf, h - 0.04, 0.035, u + dw * 0.46, y0 + 0.02, 0.085)                   # the door slid half across
        K.fbox("Paper", "f", leaf - 0.14, h * 0.5, 0.02, u + dw * 0.46, y0 + h * 0.42, 0.105)
        if lod == 0:
            for i in range(1, 4):
                K.fbox("Wood", "f", leaf - 0.1, 0.028, 0.02, u + dw * 0.46, y0 + h * 0.42 + h * 0.5 * i / 4, 0.115)
            for i in range(1, 3):
                K.fbox("Wood", "f", 0.028, h * 0.5, 0.02, u + dw * 0.46 - (leaf - 0.14) / 2 + (leaf - 0.14) * i / 3, y0 + h * 0.42, 0.115)
        if shop:                                                                                       # noren
            for i in range(3):
                K.fbox("Paper", "f", dw / 3 - 0.04, 0.52, 0.015, u - dw / 3 + dw / 3 * i, y0 + h - 0.56, 0.14 + 0.012 * (i % 2))
            K.fbox("Wood", "f", dw + 0.2, 0.035, 0.035, u, y0 + h - 0.04, 0.14)


def pent(K, x0, x1, z_wall, z_out, y_wall, y_out, kind="Shingle", posts=True, y_floor=None):
    """a lean-to roof from a wall down to its outer edge, on slender posts"""
    L, run = x1 - x0, z_out - z_wall
    s = 1 if run > 0 else -1
    sl = math.atan2(y_wall - y_out, abs(run))
    ln = math.hypot(run, y_wall - y_out) + 0.12
    xc, zc, yc = (x0 + x1) / 2, (z_wall + z_out) / 2, (y_wall + y_out) / 2
    K.box(kind, L + 0.3, 0.07, ln, xc, yc - 0.035 + 0.05, zc, rx=s * sl)
    if K.lod < 2:
        K.box("Wood", L + 0.24, 0.1, 0.1, xc, y_out - 0.12, z_out - s * 0.1)                           # the beam at the eave
        n = max(2, round(L / 0.7))
        if K.lod == 0:
            for i in range(n + 1):
                x = x0 + L * i / n
                K.beam("Wood", (x, y_wall - 0.06, z_wall), (x, y_out - 0.06, z_out), 0.06, 0.08)
        if posts:
            m = max(1, round(L / 2.2))
            for i in range(m + 1):
                x = x0 + 0.06 + (L - 0.12) * i / m
                yb = y_floor if y_floor is not None else BASE
                K.box("Wood", 0.1, y_out - 0.12 - yb, 0.1, x, yb, z_out - s * 0.1)
                if K.lod == 0 and y_floor is None:
                    rock(K, x, BASE - 0.1, z_out - s * 0.1, 0.17, flat=0.7)


def smoke_vent(K, ye, rise, kind):
    """koshi-yane: a little louvred roof riding the ridge, where the smoke of a forge gets out"""
    ln, hw, y = min(2.0, K.bw * 0.34), 0.42, ye + rise - 0.12
    cx = K.bw * 0.14
    if K.lod == 2:
        K.box("Wood", ln, 0.5, hw * 2, cx, y, 0)
        return
    for sz in (-1, 1):
        for i in range(3):
            K.box("Wood", ln, 0.05, 0.16, cx, y + 0.12 + i * 0.13, sz * hw, rx=sz * 0.6)
    for sx in (-1, 1):
        K.box("Wood", 0.07, 0.56, hw * 2, cx + sx * ln / 2, y, 0)
    K.gable("Tile" if kind == "Tile" else "Shingle", ln + 0.5, cx, 0, y + 0.52, hw + 0.3, 0.26, rolls=kind == "Tile")


def tile_roof(K, ye, rise, over=0.78):
    d = D(K.lod)
    d.step, d.amp = (0.3, 0.6, 1.4)[K.lod], 0.0                                                      # the normal map carries the tile relief: these are small roofs, many of them
    ex, ez = K.bw / 2 + over, K.bd / 2 + over
    ux = max(0.4, ex - ez * 0.72)
    build_roof(K.m["Tile"], K.m["Wood"], d, Roof(ye, ex, ez, ux, 0.0, rise, 0.28, power=1.35, kick=0.16), (K.bw / 2, K.bd / 2))
    yr = ye + rise
    K.box("Tile", 2 * ux + 0.5, 0.2, 0.3, 0, yr - 0.04, 0)
    if K.lod < 2:
        K.rod("Tile", (-ux - 0.25, yr + 0.22, 0), (ux + 0.25, yr + 0.22, 0), 0.1, 6)
        for s in (-1, 1):
            K.box("Tile", 0.2, 0.42, 0.34, s * (ux + 0.32), yr - 0.02, 0)                             # onigawara at the ridge ends


# ------------------------------------------------------------------------------------------------------------------ what is done there
def things(K, bid, x0, x1, z0, z1, y_eng, eng):
    """the working clutter of a kind of building. x0..x1, z0..z1: the body in footprint coordinates; y_eng: the veranda's floor (if eng)"""
    P, lod, r = K.P, K.lod, K.r
    if lod == 2:
        return
    w, d = P["w"], P["d"]
    fz = z1 + (0.5 if eng else 0.18)                                                                  # the strip before the front wall
    fy = y_eng if eng else BASE
    right = x1 + 0.2
    side = (x1 + 0.34, (z0 + z1) / 2)
    if bid in ("minka", "bowyer", "weaver"):
        lantern(K, 0.95, fz - 0.1, fy)
        bench(K, x1 - 1.0, fz, 1.2, fy)
        jar(K, x1 - 0.5, fz + 0.02, fy + 0.45, 0.7) if lod == 0 else None
        barrel(K, side[0] + 0.02, z1 - 0.5, BASE, 0.3, 0.7, lid=False)                                # the rain tub at the corner
    if bid == "minka":
        woodpile(K, side[0], side[1] - 0.6, 1.5, 4, along_x=False)
    if bid == "bowyer":
        rack(K, side[0] + 0.02, side[1] - 0.3, 1.8, items=7, along_x=False)
    if bid == "weaver":                                                                               # cloth drying on a pole
        zc = side[1] - 0.2
        for s in (-1, 1):
            K.box("Wood", 0.07, 1.9, 0.07, side[0] + 0.1, BASE, zc + s * 1.1)
        K.rod("WoodL", (side[0] + 0.1, BASE + 1.8, zc - 1.25), (side[0] + 0.1, BASE + 1.8, zc + 1.25), 0.03, 5)
        for i in range(3):
            K.box("Paper", 0.03, 1.0 + 0.2 * (i % 2), 0.6, side[0] + 0.1, BASE + 0.78 - 0.2 * (i % 2), zc - 0.75 + i * 0.75)
    if bid == "nagaya":
        for u in (-w * 0.3, w * 0.36):
            barrel(K, u, fz + 0.1, fy, 0.26, 0.6, lid=False)
        lantern(K, 1.0, fz - 0.1, fy)
        bench(K, -w * 0.12, fz, 1.2, fy)
    if bid in ("storehouse", "sake_brewery"):
        for i in range(3):
            barrel(K, side[0] + 0.08, z1 - 0.7 - i * 0.7, BASE, 0.33, 0.8)
        if lod == 0:
            barrel(K, side[0] + 0.08, z1 - 1.05, BASE + 0.82, 0.33, 0.8)
        bale(K, x0 - 0.35, z1 - 0.9, BASE, math.pi / 2)
        bale(K, x0 - 0.35, z1 - 1.8, BASE, math.pi / 2)
        bale(K, x0 - 0.35, z1 - 1.35, BASE + 0.48, math.pi / 2) if lod == 0 else None
    if bid == "sake_brewery" and lod < 2:                                                             # sugidama: the ball of cedar that says the new sake is in
        K.m["Thatch"].cone(G(1.4, BASE + 2.55, z1 + 0.5), (0, 0, 1), 0.3, 0.3, 0.42, 8)
        K.m["Thatch"].cone(G(1.4, BASE + 2.86, z1 + 0.5), (0, 0, 1), 0.3, 0.1, 0.2, 8)
        K.m["Thatch"].cone(G(1.4, BASE + 2.24, z1 + 0.5), (0, 0, 1), 0.1, 0.3, 0.2, 8)
    if bid == "granary":
        for i in range(3):
            bale(K, x1 - 0.5 - i * 0.6, z1 + 0.25, BASE, math.pi / 2)
        bale(K, x1 - 0.8, z1 + 0.25, BASE + 0.48, math.pi / 2)
    if bid == "armoury":
        rack(K, side[0] + 0.05, side[1], 2.2, h=1.7, items=8, kind="Wood", along_x=False)
    if bid == "dojo":
        rack(K, x1 - 1.4, fz + 0.1, 2.0, fy, h=1.6, items=7, kind="Wood")
        lantern(K, 1.1, fz - 0.1, fy)
        lantern(K, -1.1, fz - 0.1, fy)
    if bid in ("smithy", "tatara", "armourer"):
        barrel(K, 1.3, fz + 0.15, BASE, 0.34, 0.6, lid=False)                                         # the quench tub
        K.m["Wood"].cylinder(G(-1.45, BASE + 0.25, fz + 0.2), (0, 0, 1), 0.26, 0.5, 8)                # the anvil on its stump
        K.box("Tile", 0.5, 0.2, 0.2, -1.45, BASE + 0.5, fz + 0.2)
        K.box("Tile", 0.2, 0.1, 0.16, -1.15, BASE + 0.6, fz + 0.2)
        for i in range(3):
            bale(K, side[0] + 0.02, z1 - 0.7 - i * 0.62, BASE, 0.0, 0.25, 0.7)                        # charcoal in straw bales
    if bid == "armourer":
        rack(K, x0 + 1.3, fz + 0.1, 1.6, fy, h=1.4, items=5, kind="Wood")
    if bid == "tatara":
        for i in range(7):
            rock(K, x0 - 0.3 + r.uniform(-0.25, 0.25), BASE - 0.05 + 0.12 * (i % 3), z1 - 1.0 + r.uniform(-0.5, 0.5), r.uniform(0.2, 0.34), kind="Tile")       # iron sand and ore
    if bid == "woodcutter":
        woodpile(K, side[0] + 0.02, side[1], 1.8, 5, along_x=False)
        K.m["Wood"].cylinder(G(x0 + 0.4, BASE + 0.22, z1 + 0.55), (0, 0, 1), 0.3, 0.44, 8)            # the chopping block, the axe in it
        K.rod("WoodL", (x0 + 0.4, BASE + 0.44, z1 + 0.55), (x0 + 0.72, BASE + 1.05, z1 + 0.62), 0.022, 4)
        K.box("Tile", 0.16, 0.1, 0.04, x0 + 0.42, BASE + 0.46, z1 + 0.55)
    if bid == "bamboo_cutter":
        for i in range(9):
            K.rod("WoodL", (side[0] + 0.3 + 0.03 * (i % 3), BASE, side[1] - 0.9 + i * 0.2), (x1 - 0.02, BASE + 2.5 + 0.25 * r.random(), side[1] - 0.86 + i * 0.2), 0.035, 5)
        K.rod("Thatch", (side[0] + 0.1, BASE + 1.2, side[1] - 1.0), (side[0] + 0.1, BASE + 1.2, side[1] + 0.95), 0.02, 4)
    if bid == "fishing_hut":
        zc = side[1]
        for s in (-1, 1):
            K.box("Wood", 0.07, 1.7, 0.07, side[0] + 0.1, BASE, zc + s * 1.0)
        for yy in (1.1, 1.6):
            K.rod("WoodL", (side[0] + 0.1, BASE + yy, zc - 1.15), (side[0] + 0.1, BASE + yy, zc + 1.15), 0.025, 5)
            for i in range(6):
                K.box("WoodL", 0.02, 0.3, 0.09, side[0] + 0.1, BASE + yy - 0.32, zc - 0.85 + i * 0.34)   # fish split and hung to dry
        barrel(K, x0 + 0.3, z1 + 0.5, BASE, 0.28, 0.5, lid=False)
        K.m["Thatch"].cone(G(x0 + 0.95, BASE + 0.16, z1 + 0.5), (0, 0, 1), 0.3, 0.22, 0.32, 8)       # a basket


def shed_things(K, bid, bw, bd, y0):
    lod, r = K.lod, K.r
    if lod == 2:
        return
    if bid == "stonecutter":
        for i in range(4):
            K.box("Stone", 0.9, 0.42, 0.5, -bw * 0.26 + (i % 2) * 0.95, y0 + (i // 2) * 0.43, bd * 0.12 + (i // 2) * 0.03, rz=r.uniform(-0.05, 0.05))
        for i in range(8):
            rock(K, bw * 0.2 + r.uniform(-0.7, 0.7), y0 - 0.05, bd * 0.28 + r.uniform(-0.5, 0.4), r.uniform(0.12, 0.3))
        K.rod("WoodL", (bw * 0.36, y0, -bd * 0.3), (bw * 0.3, y0 + 1.5, -bd * 0.42), 0.025, 4)
    elif bid == "clay_pit":
        for i in range(5):
            rock(K, -bw * 0.25 + r.uniform(-0.6, 0.6), y0 - 0.08, bd * 0.2 + r.uniform(-0.5, 0.5), r.uniform(0.3, 0.5), kind="Earth", flat=0.5)
        for i in range(6):
            jar(K, bw * 0.12 + (i % 3) * 0.5, -bd * 0.12 + (i // 3) * 0.5, y0, 0.9)
    elif bid == "iron_mine":
        for i in range(12):
            rock(K, -bw * 0.22 + r.uniform(-0.8, 0.8), y0 - 0.05 + 0.1 * (i % 3), bd * 0.22 + r.uniform(-0.5, 0.5), r.uniform(0.16, 0.34), kind="Tile")
        K.box("Wood", 1.2, 0.5, 0.7, bw * 0.24, y0 + 0.3, bd * 0.2)                                    # an ore sledge
        for s in (-1, 1):
            K.box("WoodL", 1.5, 0.08, 0.08, bw * 0.24, y0 + 0.2, bd * 0.2 + s * 0.4)
    elif bid == "sawpit":
        for s in (-1, 1):                                                                             # a log on trestles, half sawn into planks
            for t in (-1, 1):
                K.beam("Wood", (s * bw * 0.22 + t * 0.35, y0, bd * 0.16), (s * bw * 0.22, y0 + 0.95, bd * 0.16), 0.08, 0.08)
        K.m["WoodL"].cylinder(G(0, y0 + 1.17, bd * 0.16), (1, 0, 0), 0.24, bw * 0.62, 9)
        for i in range(5):
            K.box("WoodL", bw * 0.42, 0.045, 0.3, -bw * 0.2, y0 + 0.05 + i * 0.05, -bd * 0.2 + r.uniform(-0.03, 0.03), rz=r.uniform(-0.04, 0.04))


# ------------------------------------------------------------------------------------------------------------------ the kinds
def hall(K, bid):
    P, lod = K.P, K.lod
    w, d, H, raised = P["w"], P["d"], P["h"], P.get("raised", 0)
    roof, kura, hut = P["roof"], P.get("plaster", False), P["shape"] == "hut"
    thatch = roof == "thatch"
    eng = not kura and not hut and not raised and w >= 6 and d >= 5 and bid not in ("tatara", "smithy")
    lean = not kura and not hut and not raised and w >= 8
    fz, lw = (1.0 if eng else M), (1.45 if lean else 0.0)
    bw, bd = w - 2 * M - lw, d - M - fz
    cx, cz = lw / 2, (M - fz) / 2
    K.bw, K.bd = bw, bd
    hw = (H - raised) * (0.41 if thatch else 0.5)
    y0 = BASE + raised + (0.0 if kura else 0.36 if eng else 0.2)                                      # a dwelling's boarded floor stands clear of the damp on its stones; a workshop's is the earth
    style = "kura" if kura else "board" if (hut or roof == "plank") else "earth" if thatch else "plaster"
    du = -cx                                                                                          # the door stays at the footprint's x = 0
    shop = bid in ("weaver", "bowyer", "sake_brewery", "armourer", "smithy")
    with K.shift(cx, cz):
        if raised:
            for sx in (-1, 0, 1):
                for sz in (-1, 0, 1):
                    if sx or sz:
                        K.log("Wood", 0.16, 0.15, raised + 0.2, sx * (bw / 2 - 0.22), BASE, sz * (bd / 2 - 0.22), 7 if lod < 2 else 4)
                        if lod < 2:
                            rock(K, sx * (bw / 2 - 0.22), BASE - 0.1, sz * (bd / 2 - 0.22), 0.26, flat=0.6)
                            K.box("WoodL", 0.5, 0.06, 0.5, sx * (bw / 2 - 0.22), BASE + raised * 0.82, sz * (bd / 2 - 0.22))       # rat guards
            K.box("Wood", bw + 0.3, 0.16, bd + 0.3, 0, y0 - 0.2, 0)
            if lod < 2:                                                                               # a landing and a ladder to the door
                K.box("WoodL", 1.5, 0.08, 0.8, du, y0 - 0.1, bd / 2 + 0.4)
                for sx in (-1, 1):
                    K.beam("Wood", (du + sx * 0.42, BASE, bd / 2 + 1.5), (du + sx * 0.42, y0 - 0.05, bd / 2 + 0.78), 0.07, 0.13)
                for i in range(4):
                    f = (i + 0.5) / 4
                    K.box("WoodL", 0.84, 0.045, 0.2, du, BASE + (y0 - BASE) * f, bd / 2 + 1.5 - 0.72 * f)
        frame_walls(K, y0, hw, style, du)
        dh = min(1.9, hw * 0.82)
        door(K, y0, dh, du, 1.1 if not kura else 1.2, kura, shop)
        if lod < 2 and not raised:                                                                    # kutsunugi-ishi: the broad flat stone one steps up from
            sz_, top_ = bd / 2 + (1.36 if eng else 0.46), max(0.05, (y0 + (0.02 if eng else 0.0)) - BASE - 0.15)      # its top a comfortable step below the floor
            rock(K, du + K.r.uniform(-0.1, 0.1), BASE + top_ - 0.21, sz_ - 0.08, 0.58, flat=0.24)             # a slab, most of it in the earth (rock(): top = y + 1.5 s flat)
            if eng:
                rock(K, du + K.r.uniform(-0.3, 0.3), BASE + 0.05 - 0.12, sz_ + 0.62, 0.4, flat=0.2)
        if bid == "nagaya" and lod < 2:                                                               # a row house: a door to every lodging
            for u in (du - bw * 0.3, du + bw * 0.3):
                if abs(u) < bw / 2 - 0.9:
                    door(K, y0, dh, u, 0.95)
        wh, wy = min(0.85, hw * 0.36), y0 + hw * (0.5 if not kura else 0.6)
        if kura:
            for side in "lrb":
                L = K.span_of(side)
                for u in ([-L * 0.25, L * 0.25] if L > 5 else [0]):
                    barred(K, side, u, wy + 0.2, 0.55, 0.5)
        elif style == "board":
            for side in "lr":
                shoji(K, side, 0, wy, min(1.2, bd * 0.34), wh * 0.8)
        else:
            taken = [du] + ([du - bw * 0.3, du + bw * 0.3] if bid == "nagaya" else [])
            n = max(2, round(bw / 2.4))
            for i in range(n):
                u = -bw / 2 + bw * (i + 0.5) / n
                if all(abs(u - t) > 1.25 for t in taken):
                    shoji(K, "f", u, wy, min(1.25, bw / n - 0.75), wh)
            for side in "lr":
                if side == "l" and lean:
                    continue
                shoji(K, side, bd * 0.12, wy, min(1.5, bd * 0.36), wh)
            if bw > 6:
                for u in (-bw * 0.25, bw * 0.25):
                    shoji(K, "b", u, wy, 1.1, wh)
        ye = y0 + hw
        rise = (BASE + H) - ye - (0.75 if thatch else 0.25)
        vent = P.get("chimney")
        if thatch:
            ex, ez = bw / 2 + 0.78, bd / 2 + 0.78
            rx = max(0.45, ex - ez * 0.86) if not hut else max(0.3, (ex - ez) + 0.25)
            thatch_roof(K, ex, ez, rx, ye - 0.04, rise, thick=0.42 if not hut else 0.36, wall=(bw / 2, bd / 2))
        elif roof == "tile":
            tile_roof(K, ye, rise)
        else:
            shingle_roof(K, bw / 2 + 0.8, bd / 2 + 0.8, max(0.4, bw / 2 - bd / 2 * 0.55), 0.0, ye, rise, lift=0.22, kick=0.14, wall=(bw / 2, bd / 2))
        if vent:
            smoke_vent(K, ye, rise, "Tile" if roof == "tile" else "Shingle")
        if eng:                                                                                       # the veranda: a boarded floor on stones under its own pent roof
            ez0, ez1, ey = bd / 2, bd / 2 + 0.92, y0 + 0.02
            nb = 3 if lod == 0 else 1
            for i in range(nb):
                K.box("WoodL", bw - 0.06, 0.05, (ez1 - ez0) / nb - (0.012 if nb > 1 else 0), 0, ey - 0.05, ez0 + (ez1 - ez0) * (i + 0.5) / nb)
            if lod < 2:
                K.box("Wood", bw, 0.13, 0.09, 0, ey - 0.18, ez1 - 0.06)
                m = max(2, round(bw / 1.8))
                for i in range(m + 1):
                    x = -bw / 2 + 0.08 + (bw - 0.16) * i / m
                    K.box("Wood", 0.11, ey - 0.18 - BASE + 0.1, 0.11, x, BASE - 0.1, ez1 - 0.06)
                    if lod == 0:
                        rock(K, x, BASE - 0.1, ez1 - 0.06, 0.19, flat=0.65)
            pent(K, -bw / 2 - 0.1, bw / 2 + 0.1, bd / 2 - 0.02, ez1 + 0.22, ye - 0.3, ye - 0.72, "Shingle" if roof != "plank" else "Wood", posts=lod < 2, y_floor=ey)
        if lean:                                                                                      # the lean-to: boarded, open to the front, firewood inside
            lx0, lx1, ly = -bw / 2 - lw, -bw / 2, y0 + hw
            K.box("Wood", 0.07, 1.75, bd - 0.5, lx0 + 0.04, BASE, -0.25)
            K.box("Wood", lw, 1.75, 0.07, (lx0 + lx1) / 2, BASE, -bd / 2 + 0.04)
            if lod < 2:
                for z in (-bd / 2 + 0.06, bd / 2 - 0.5):
                    K.box("Wood", 0.12, 1.85, 0.12, lx0 + 0.06, BASE, z)
                woodpile(K, (lx0 + lx1) / 2, bd / 2 - 1.3, 1.5, 5, along_x=False)
            ln = math.hypot(lw + 0.3, 0.75)
            K.box("Shingle" if roof != "plank" else "Wood", ln, 0.07, bd - 0.1, (lx0 + lx1) / 2 - 0.15, ly - 0.42 - 0.375 + 0.03, -0.2, ry=-math.atan2(0.75, lw + 0.3))
            if lod < 2:
                K.box("Wood", 0.1, 0.1, bd - 0.1, lx0 - 0.12, ly - 1.22, -0.2)
    things(K, bid, cx - bw / 2, cx + bw / 2, cz - bd / 2, cz + bd / 2, y0 + 0.02, eng)


def shed(K, bid):
    P, lod = K.P, K.lod
    bw, bd, H = P["w"] - 2 * M, P["d"] - 2 * M, P["h"]
    K.bw, K.bd = bw, bd
    hw, y0 = H * 0.56, BASE
    for side in "blr":                                                                                # boarded back and sides, a gap under the eaves
        L = K.span_of(side)
        hb = hw - (0.1 if side == "b" else 0.45)
        if lod == 0:
            m = max(4, round(L / 0.26))
            for i in range(m):
                K.fbox("Wood", side, L / m - 0.014, hb + K.r.uniform(-0.05, 0.03), 0.05, -L / 2 + L * (i + 0.5) / m, y0, -0.06 + K.r.uniform(-0.006, 0.006))
        else:
            K.fbox("Wood", side, L, hb, 0.05, 0, y0, -0.06)
        if lod < 2:
            for yy in (y0 + 0.4, y0 + hw * 0.62):
                K.fbox("WoodL", side, L, 0.1, 0.06, 0, yy, -0.12)
    n = max(2, round(bw / 2.4))
    for i in range(n + 1):
        x = -bw / 2 + 0.1 + (bw - 0.2) * i / n
        for z in (bd / 2 - 0.1, -bd / 2 + 0.1):
            K.log("Wood", 0.1, 0.085, hw + 0.1, x, y0 - 0.1, z, 7 if lod == 0 else 4)
            if lod == 0:
                rock(K, x, y0 - 0.12, z, 0.22, flat=0.65)
        if lod < 2:
            K.box("Wood", 0.14, 0.16, bd - 0.2, x, y0 + hw - 0.16, 0)
            K.beam("Wood", (x, y0 + hw - 0.75, bd / 2 - 0.1), (x + (0.62 if i < n else -0.62), y0 + hw - 0.1, bd / 2 - 0.1), 0.08, 0.08)
    K.rod("Wood", (-bw / 2 - 0.2, y0 + hw - 0.08, bd / 2 - 0.1), (bw / 2 + 0.2, y0 + hw - 0.08, bd / 2 - 0.1), 0.09, 6)
    if lod < 2:                                                                                       # the bench and a shelf on the back wall
        K.box("WoodL", bw * 0.42, 0.08, bd * 0.24, bw * 0.2, y0 + 0.66, -bd * 0.3)
        for sx in (-1, 1):
            K.box("Wood", 0.1, 0.66, bd * 0.2, bw * 0.2 + sx * bw * 0.17, y0, -bd * 0.3)
        K.box("WoodL", bw * 0.6, 0.05, 0.28, -bw * 0.1, y0 + hw * 0.64, -bd / 2 + 0.26)
    board_roof(K, bw + 1.0, bd / 2 + 0.55, y0 + hw, H * 0.3, wall_hw=bd / 2 - 0.1)
    shed_things(K, bid, bw, bd, y0)


# ------------------------------------------------------------------------------------------------------------------ the round ones
def dome(K, kind, x, y, z, rx, rz, h, useg=18, vseg=7):
    """the upper half of an ellipsoid, open below"""
    mb = K.m[kind]
    useg, vseg = (useg, vseg) if K.lod == 0 else (12, 5) if K.lod == 1 else (8, 3)
    r = bmesh.ops.create_uvsphere(mb.bm, u_segments=useg, v_segments=vseg * 2, radius=1.0)
    bmesh.ops.delete(mb.bm, geom=[v for v in r["verts"] if v.co.z < -0.02], context="VERTS")
    keep = [v for v in r["verts"] if v.is_valid]
    bmesh.ops.transform(mb.bm, matrix=mb.M @ Matrix.Translation(G(x, y, z)) @ Matrix.Diagonal((rx, rz, h, 1.0)), verts=keep)
    for v in keep:
        for f in v.link_faces:
            f.smooth = True


def disc(K, kind, x, y, z, r, h, segs=14, axis=(0, 0, 1)):
    K.m[kind].cylinder(G(x, y + (h / 2 if axis == (0, 0, 1) else 0), z), axis, r, h, segs if K.lod == 0 else max(6, segs // 2))


def stone_lantern(K, x, z, y=BASE):
    """ishidoro: a round shaft and cap of stone about a paper-lit firebox"""
    if K.lod == 2:
        K.box("Stone", 0.4, 1.5, 0.4, x, y, z)
        return
    rock(K, x, y - 0.14, z, 0.46, flat=0.5)                                                            # it stands on a rough stone, not on a slab
    disc(K, "Stone", x, y, z, 0.3, 0.16, 10)
    disc(K, "Stone", x, y + 0.16, z, 0.11, 0.72, 8)
    disc(K, "Stone", x, y + 0.88, z, 0.25, 0.09, 10)
    K.box("Paper", 0.24, 0.26, 0.24, x, y + 0.97, z)
    for sx in (-1, 1):
        for sz in (-1, 1):
            K.box("Stone", 0.06, 0.28, 0.06, x + sx * 0.13, y + 0.97, z + sz * 0.13)
    K.m["Stone"].cone(G(x, y + 1.38, z), (0, 0, 1), 0.38, 0.07, 0.28, 10 if K.lod == 0 else 6)
    rock(K, x, y + 1.5, z, 0.1, flat=1.0)


def umbrella(K, x, z, y, r=1.3, h=2.4):
    """wagasa: an oiled-paper umbrella on a bamboo pole (the paper glows a little with the lamps under it at night)"""
    segs = 18 if K.lod == 0 else 12 if K.lod == 1 else 8
    K.m["Paper"].cone(G(x, y + h + 0.2, z), (0, 0, 1), r, 0.07, 0.4, segs)
    K.rod("WoodL", (x, y, z), (x, y + h + 0.5, z), 0.03, 5)
    if K.lod < 2:
        disc(K, "Wood", x, y + h + 0.38, z, 0.1, 0.1, 8)
        if K.lod == 0:
            for i in range(segs):
                a = 2 * math.pi * (i + 0.5) / segs
                K.rod("Wood", (x, y + h + 0.4, z), (x + math.cos(a) * r, y + h + 0.015, z + math.sin(a) * r), 0.012, 3)
                if i % 2 == 0:
                    K.rod("Wood", (x, y + h - 0.35, z), (x + math.cos(a) * r * 0.55, y + h + 0.17, z + math.sin(a) * r * 0.55), 0.01, 3)


def basket(K, x, z, y, r=0.3, full="Thatch"):
    if K.lod == 2:
        return
    K.m["Thatch"].cone(G(x, y + 0.09, z), (0, 0, 1), r * 0.72, r, 0.18, 10 if K.lod == 0 else 6)
    if full:
        dome(K, full, x, y + 0.16, z, r * 0.86, r * 0.86, 0.13, 8, 3)


def well(K, bid):
    """a round well: a curb of fitted stones, a windlass on two posts, a round cap of thatch over it"""
    lod, r = K.lod, K.r
    R = 0.72
    n = 13 if lod == 0 else 8
    if lod < 2:
        for ring in range(2):
            for i in range(n):
                a = 2 * math.pi * (i + 0.5 * ring) / n
                rock(K, math.cos(a) * R, BASE - 0.12 + ring * 0.36, math.sin(a) * R, 0.2 + 0.03 * r.random(), flat=1.5)
    K.m["Stone"].cone(G(0, BASE + 0.36, 0), (0, 0, 1), R + 0.04, R - 0.02, 0.76, 14 if lod == 0 else 8)
    disc(K, "Tile", 0, BASE + 0.71, 0, R - 0.2, 0.05, 14)                                              # the dark of the shaft
    for sx in (-1, 1):
        K.log("Wood", 0.085, 0.07, 2.25, sx * 0.98, BASE - 0.1, 0, 8 if lod == 0 else 5)
        if lod < 2:
            rock(K, sx * 0.98, BASE - 0.12, 0, 0.2, flat=0.7)
    K.rod("Wood", (-1.12, BASE + 1.9, 0), (1.12, BASE + 1.9, 0), 0.06, 6)
    if lod < 2:
        disc(K, "WoodL", 0, BASE + 1.72, 0, 0.17, 0.09, 12, axis=(0, 1, 0))                            # the pulley wheel
        K.rod("Thatch", (0.14, BASE + 1.72, 0), (0.14, BASE + 0.98, 0), 0.014, 4)
        K.rod("Thatch", (-0.14, BASE + 1.72, 0), (-0.4, BASE + 0.82, 0.62), 0.014, 4)
        K.m["WoodL"].cone(G(0.14, BASE + 0.9, 0), (0, 0, 1), 0.13, 0.16, 0.26, 10)                     # the bucket in the shaft's mouth
        barrel(K, -0.42, 0.66, BASE + 0.62, 0.15, 0.24, lid=False)                                     # and its fellow on the curb
        for i in range(6):                                                                            # stepping stones round the curb
            a = 0.5 + 2 * math.pi * i / 6
            rock(K, math.cos(a) * 1.12, BASE - 0.1, math.sin(a) * 1.12, 0.24, flat=0.35)
    thatch_roof(K, 1.2, 1.2, 0.0, BASE + 2.05, 0.8, thick=0.24, q=2.0, wall=(0.3, 0.3), ridge="knot")


def kiln(K, bid):
    """sumigama: a low dome of rammed earth with a stone-framed mouth, a clay flue at the back, the wood going in and the charcoal coming out"""
    lod, r = K.lod, K.r
    cz, rx, rz, h = -0.35, 1.95, 1.85, 1.7
    dome(K, "Earth", 0, BASE - 0.02, cz, rx, rz, h)
    if lod == 0:                                                                                      # the dome is patched and tamped, never a clean bowl
        for i in range(9):
            a, f = r.uniform(0.4, 2.8) + (math.pi if i % 2 else 0), r.uniform(0.25, 0.75)
            dome(K, "Earth", math.cos(a) * rx * f, BASE + h * math.sqrt(max(0.05, 1 - f * f)) - 0.12, cz + math.sin(a) * rz * f, r.uniform(0.3, 0.5), r.uniform(0.3, 0.5), 0.14, 8, 3)
    n = 20 if lod == 0 else 10 if lod == 1 else 0
    for i in range(n):                                                                                # a collar of stones round its foot (open at the mouth)
        a = 2 * math.pi * i / n
        if abs(a - math.pi / 2) < 0.42:
            continue
        rock(K, math.cos(a) * (rx + 0.04), BASE - 0.12, cz + math.sin(a) * (rz + 0.04), r.uniform(0.26, 0.4), flat=0.8)
    mz = cz + rz - 0.22                                                                               # the mouth: dark, between stone jambs under a lintel stone
    K.box("Earth", 0.74, 0.74, 0.5, 0, BASE, mz - 0.06)                                               # sealed with clay and stones while the burn is on
    if lod < 2:
        for i in range(5):
            rock(K, -0.2 + 0.2 * (i % 3), BASE - 0.02 + 0.24 * (i // 3), mz + 0.2, 0.22, flat=0.9)
        disc(K, "Tile", 0, BASE + 0.6, mz + 0.19, 0.09, 0.04, 8, axis=(0, 1, 0))                      # the draught hole
    if lod < 2:
        for sx in (-1, 1):
            for i in range(3):
                rock(K, sx * (0.52 + 0.04 * i), BASE - 0.05 + i * 0.3, mz + 0.22 - i * 0.05, 0.3 - 0.02 * i, flat=0.95)
        K.box("Stone", 1.5, 0.26, 0.5, 0, BASE + 0.76, mz + 0.06, rz=r.uniform(-0.04, 0.04))
        K.m["Earth"].cone(G(0.25, BASE + h * 0.78 + 0.35, cz - rz * 0.62), (0.1, 0.3, 1), 0.24, 0.17, 0.95, 9)     # the flue
        disc(K, "Tile", 0.31, BASE + h * 0.78 + 0.8, cz - rz * 0.62 - 0.14, 0.13, 0.04, 8)
        woodpile(K, -1.75, 1.75, 1.3, 4)
        for i in range(3):
            bale(K, 1.55 + 0.02 * i, 1.3 + i * 0.56, BASE, 0.15, 0.24, 0.7)
        bale(K, 1.6, 1.6, BASE + 0.44, 0.1, 0.24, 0.7) if lod == 0 else None
        K.rod("WoodL", (0.9, BASE, 1.9), (1.15, BASE + 1.7, 1.5), 0.022, 4)                           # the rake that draws the coals


def stalls(K, bid):
    """a market: two roofed stalls at the back, and before them mats of goods under big paper umbrellas, a handcart, baskets, jars and tubs"""
    P, lod, r = K.P, K.lod, K.r
    w, d = P["w"], P["d"]
    for sx in (-1, 1):
        cx, cz, sw, sd = sx * w * 0.25, -d * 0.27, w * 0.34, 1.9
        for px in (-1, 1):
            for pz, ph in ((-1, 2.05), (1, 2.5)):
                K.box("Wood", 0.11, ph, 0.11, cx + px * (sw / 2 - 0.06), BASE, cz + pz * (sd / 2 - 0.06))
        pent(K, cx - sw / 2, cx + sw / 2, cz + sd / 2 + 0.25, cz - sd / 2 - 0.3, BASE + 2.62, BASE + 2.0, "Shingle", posts=False)
        nb = 6 if lod == 0 else 1                                                                     # duckboards under the stall, on two sleepers
        for i in range(nb):
            K.box("WoodL", (sw - 0.3) / nb - (0.02 if nb > 1 else 0), 0.045, sd - 0.5 + (r.uniform(-0.12, 0.12) if nb > 1 else 0), cx - (sw - 0.3) / 2 + (sw - 0.3) * (i + 0.5) / nb, BASE + 0.07, cz - 0.1, rz=r.uniform(-0.02, 0.02) if nb > 1 else 0.0)
        if lod < 2:
            for pz in (-1, 1):
                K.box("Wood", sw - 0.1, 0.16, 0.12, cx, BASE - 0.08, cz - 0.1 + pz * (sd / 2 - 0.55))
        K.box("WoodL", sw - 0.2, 0.06, 0.7, cx, BASE + 0.84, cz + sd / 2 - 0.5)                        # the counter
        if lod < 2:
            K.box("Wood", sw - 0.24, 0.84, 0.05, cx, BASE, cz + sd / 2 - 0.2)
            K.box("Wood", sw - 0.1, 1.5, 0.05, cx, BASE, cz - sd / 2 + 0.05)
            for i in range(3):
                K.box("Paper", (sw - 0.3) / 3 - 0.05, 0.5, 0.015, cx - (sw - 0.3) / 3 + (sw - 0.3) / 3 * i, BASE + 1.9, cz + sd / 2 - 0.02 + 0.012 * (i % 2))
            for i in range(4):
                (jar if (i + (sx > 0)) % 2 else basket)(K, cx - sw * 0.33 + i * sw * 0.22, cz + sd / 2 - 0.5, BASE + 0.9, *((0.55,) if (i + (sx > 0)) % 2 else (0.2,)))
            lantern(K, cx + sx * (sw / 2 - 0.25), cz + sd / 2 - 0.5, BASE + 0.9) if lod == 0 else None
    spots = ((-w * 0.3, d * 0.2, 1.35, 2.35), (w * 0.02, d * 0.3, 1.2, 2.15), (w * 0.31, d * 0.16, 1.45, 2.5))
    for i, (x, z, rr, hh) in enumerate(spots):
        umbrella(K, x, z, BASE, rr, hh)
        K.box("Thatch", 1.7, 0.06, 1.2, x + 0.1, BASE - 0.01, z + 0.15, rz=r.uniform(-0.3, 0.3))      # the mat the goods lie on
        if lod < 2:
            for k in range(4):
                a = 0.8 + k * 1.5
                px, pz = x + 0.1 + math.cos(a) * 0.5, z + 0.15 + math.sin(a) * 0.36
                if (i + k) % 3 == 0:
                    jar(K, px, pz, BASE + 0.05, 0.7)
                elif (i + k) % 3 == 1:
                    basket(K, px, pz, BASE + 0.05, 0.26, "Earth" if k % 2 else "Thatch")
                else:
                    barrel(K, px, pz, BASE + 0.05, 0.22, 0.3, lid=False)
    if lod < 2:                                                                                       # a handcart come in from the fields
        cx, cz = w * 0.36, -d * 0.02
        K.box("WoodL", 1.5, 0.07, 0.9, cx, BASE + 0.52, cz)
        for s in (-1, 1):
            disc(K, "Wood", cx - 0.1, BASE + 0.45, cz + s * 0.52, 0.45, 0.06, 14, axis=(0, 1, 0))
            K.box("Wood", 1.5, 0.3, 0.04, cx, BASE + 0.56, cz + s * 0.44)
            K.rod("WoodL", (cx + 0.7, BASE + 0.58, cz + s * 0.36), (cx + 1.7, BASE + 0.2, cz + s * 0.36), 0.03, 5)
        for i in range(3):
            bale(K, cx - 0.4 + i * 0.4, cz, BASE + 0.6, math.pi / 2, 0.2, 0.7)


def shrine(K, bid):
    """a small shrine: a torii of round posts hung with a straw rope, two stone lanterns, a round water basin, and the little hall raised on round posts"""
    P, lod, r = K.P, K.lod, K.r
    w, d = P["w"], P["d"]
    tz, th, tx = d / 2 - 0.9, 3.5, 1.55
    seg = 12 if lod == 0 else 8 if lod == 1 else 5
    for s in (-1, 1):                                                                                 # torii
        K.log("WoodL", 0.2, 0.16, th + 0.1, s * tx, BASE - 0.1, tz, seg)
        if lod < 2:
            disc(K, "Stone", s * tx, BASE - 0.05, tz, 0.34, 0.2, 12)
    K.box("WoodL", 2 * tx + 0.5, 0.16, 0.22, 0, BASE + th * 0.8, tz)                                   # nuki
    K.box("WoodL", 2 * tx + 1.0, 0.16, 0.26, 0, BASE + th - 0.02, tz)                                  # shimaki
    K.box("Wood", 2 * tx + 1.5, 0.17, 0.36, 0, BASE + th + 0.14, tz)                                   # kasagi
    if lod < 2:
        for s in (-1, 1):
            K.box("Wood", 0.62, 0.17, 0.36, s * (tx + 1.0), BASE + th + 0.2, tz, ry=-s * 0.22)         # its ends lift
            K.box("WoodL", 0.1, 0.5, 0.26, s * (tx + 0.02), BASE + th * 0.8 - 0.17, tz + 0.0)
        K.box("WoodL", 0.14, th * 0.2 - 0.16, 0.12, 0, BASE + th * 0.8 + 0.16, tz)
        pts = [G(-tx + 2 * tx * i / 8, BASE + th * 0.72 - 0.34 * math.sin(math.pi * i / 8), tz + 0.22) for i in range(9)]
        K.m["Thatch"].tube(pts, [0.035 + 0.035 * math.sin(math.pi * i / 8) for i in range(9)], sides=6)      # shimenawa
        for i in (2, 3, 5, 6):
            K.box("Paper", 0.11, 0.4, 0.012, -tx + 2 * tx * i / 8, BASE + th * 0.72 - 0.34 * math.sin(math.pi * i / 8) - 0.44, tz + 0.23)
    for s in (-1, 1):
        stone_lantern(K, s * 1.95, d / 2 - 2.5)
    if lod < 2:                                                                                       # chozubachi: the water basin
        K.m["Stone"].cone(G(-2.0, BASE + 0.26, 0.2), (0, 0, 1), 0.3, 0.42, 0.52, 12)
        disc(K, "Tile", -2.0, BASE + 0.5, 0.2, 0.3, 0.03, 12)
        K.rod("WoodL", (-2.3, BASE + 0.55, 0.2), (-1.65, BASE + 0.57, 0.35), 0.015, 4)
        z_, i = d / 2 - 0.25, 0                                                                       # tobi-ishi: stepping stones from the torii to the steps, set by eye
        while z_ > -d / 2 + 2.05 + 1.0 + 2.2:
            sz_ = r.uniform(0.4, 0.56)
            rock(K, (0.2 if i % 2 else -0.2) + r.uniform(-0.1, 0.1), BASE + 0.05 - 1.5 * sz_ * 0.17, z_, sz_, flat=0.17)
            z_ -= sz_ * 1.5 + r.uniform(0.0, 0.14)
            i += 1
    # the hall
    hz, bw, bd, fl = -d / 2 + 2.05, 2.5, 2.0, BASE + 0.95
    for sx in (-1, 0, 1):
        for sz in (-1, 1):
            K.log("WoodL", 0.11, 0.1, fl - BASE + 0.1, sx * (bw / 2 + 0.25), BASE - 0.1, hz + sz * (bd / 2 + 0.25), seg)
            if lod < 2:
                disc(K, "Stone", sx * (bw / 2 + 0.25), BASE - 0.06, hz + sz * (bd / 2 + 0.25), 0.2, 0.14, 10)
    K.box("WoodL", bw + 1.0, 0.1, bd + 1.0, 0, fl - 0.1, hz)                                           # the floor and its veranda
    K.box("WoodL", bw, 1.75, bd, 0, fl, hz)
    if lod < 2:
        for sx in (-1, 1):
            for sz in (-1, 1):
                K.log("Wood", 0.085, 0.08, 1.8, sx * bw / 2, fl, hz + sz * bd / 2, seg)
        K.box("Paper", 1.1, 1.3, 0.04, 0, fl + 0.12, hz + bd / 2 + 0.02)                               # lattice doors with paper behind
        for i in range(5):
            K.box("Wood", 0.03, 1.3, 0.03, -0.55 + 1.1 * i / 4, fl + 0.12, hz + bd / 2 + 0.05)
        for i in range(4):
            K.box("Wood", 1.1, 0.03, 0.03, 0, fl + 0.12 + 1.3 * i / 3, hz + bd / 2 + 0.05)
        for s in (-1, 1):                                                                             # a railed veranda, open at the steps
            K.box("Wood", 0.05, 0.05, bd + 0.9, s * (bw / 2 + 0.45), fl + 0.55, hz)
            K.box("Wood", (bw + 0.9) / 2 - 0.55, 0.05, 0.05, s * ((bw + 0.9) / 4 + 0.28), fl + 0.55, hz + bd / 2 + 0.45)
            for z in (-1, 0, 1):
                K.box("Wood", 0.06, 0.6, 0.06, s * (bw / 2 + 0.45), fl, hz + z * (bd / 2 + 0.42))
            K.box("Wood", 0.06, 0.6, 0.06, s * 0.6, fl, hz + bd / 2 + 0.45)
        for i in range(4):                                                                            # the steps
            K.box("WoodL", 1.1, 0.06, 0.28, 0, BASE + (fl - BASE) * (i + 1) / 5 - 0.06, hz + bd / 2 + 0.5 + (4 - i) * 0.27)
        K.box("WoodL", 0.9, 0.42, 0.5, 0, BASE, hz + bd / 2 + 2.0)                                     # the offering box
    with K.shift(0, hz):
        top = shingle_roof(K, bw / 2 + 0.95, bd / 2 + 0.95, bw / 2 - 0.25, 0.0, fl + 1.75, 1.35, lift=0.32, kick=0.2, wall=(bw / 2, bd / 2), finial=False)
        ry = fl + 1.75 + 1.35
        if lod < 2:
            for i in range(3):                                                                        # katsuogi: round logs laid across the ridge
                K.m["WoodL"].cylinder(G(-0.6 + i * 0.6, ry + 0.28, 0), (0, 1, 0), 0.085, 0.6, 10 if lod == 0 else 6)
            for s in (-1, 1):                                                                         # chigi: the crossed finials at the gable ends
                for t in (-1, 1):
                    K.beam("WoodL", (s * (bw / 2 - 0.1), ry - 0.1, t * 0.34), (s * (bw / 2 - 0.1), ry + 0.95, -t * 0.42), 0.06, 0.11)


def lookout(K, bid):
    """the settlement's watchtower: four tall logs braced crosswise, a boarded platform under a round cap of thatch, a signal drum"""
    P, lod, r = K.P, K.lod, K.r
    w, H = P["w"], P["h"]
    a, top = w / 2 - 0.55, BASE + H * 0.7
    seg = 9 if lod == 0 else 6 if lod == 1 else 4
    for sx in (-1, 1):
        for sz in (-1, 1):
            K.log("Wood", 0.21, 0.15, top + 1.9 - BASE + 0.4, sx * a, BASE - 0.4, sz * a, seg)
            if lod < 2:
                rock(K, sx * a, BASE - 0.1, sz * a, 0.3, flat=0.6)
    mid = BASE + H * 0.36
    for y in (mid, top):
        over = 0.0 if y == mid else 0.4
        n = 9 if lod == 0 else 1
        for i in range(n):
            K.box("WoodL", (2 * a + 2 * over) / n - (0.012 if n > 1 else 0), 0.08, 2 * a + 2 * over, -a - over + (2 * a + 2 * over) * (i + 0.5) / n, y - 0.08, 0)
        if lod < 2:
            for s in (-1, 1):
                K.rod("Wood", (-a - over - 0.2, y - 0.17, s * a), (a + over + 0.2, y - 0.17, s * a), 0.085, 6)
                K.rod("Wood", (s * a, y - 0.3, -a - over - 0.15), (s * a, y - 0.3, a + over + 0.15), 0.075, 6)
    if lod < 2:
        for y0_, y1_ in ((BASE + 0.4, mid - 0.35), (mid + 0.3, top - 0.4)):                           # cross braces on all four sides
            for s in (-1, 1):
                for t in (-1, 1):
                    K.beam("Wood", (t * a, y0_, s * a), (-t * a, y1_, s * a), 0.07, 0.09)
                    K.beam("Wood", (s * a, y0_, t * a), (s * a, y1_, -t * a), 0.07, 0.09)
        for lo, hi, zz in ((BASE, mid, a + 0.12), (mid, top, -a + 0.3)):                              # ladders, one flight to each floor
            for x in (-0.24, 0.24):
                K.box("Wood", 0.055, hi - lo + 0.5, 0.055, x + (0.9 if zz < 0 else 0), lo, zz)
            for i in range(int((hi - lo) / 0.4)):
                K.box("WoodL", 0.5, 0.05, 0.05, 0.9 if zz < 0 else 0, lo + 0.35 + i * 0.4, zz)
    e = a + 0.4                                                                                       # the breast-high boarding of the lookout
    for side in range(4):
        with K.m["Wood"].at(Matrix.Rotation(side * math.pi / 2, 4, "Z")):
            n = 8 if lod == 0 else 1
            for i in range(n):
                if side == 2 and n > 1 and i >= n - 2:
                    continue                                                                          # the gap one climbs in by
                K.m["Wood"].box((-e + 2 * e * (i + 0.5) / n, e - 0.03, top + 0.5 + (r.uniform(-0.04, 0.04) if n > 1 else 0)), (2 * e / n - 0.012 * (n > 1), 0.05, 1.0))
            K.m["Wood"].box((0, e - 0.03, top + 1.02), (2 * e, 0.09, 0.07))
    if lod < 2:                                                                                       # the drum that calls the alarm, hung in the lookout
        K.m["WoodL"].cylinder(G(0.2, top + 1.05, -0.3), (1, 0, 0), 0.4, 0.5, 14 if lod == 0 else 8)
        for s in (-1, 1):
            K.m["Paper"].cylinder(G(0.2 + s * 0.26, top + 1.05, -0.3), (1, 0, 0), 0.37, 0.02, 14 if lod == 0 else 8)
            K.m["Wood"].cylinder(G(0.2 + s * 0.2, top + 1.05, -0.3), (1, 0, 0), 0.415, 0.05, 14 if lod == 0 else 8)
        K.rod("Thatch", (0.2, top + 1.45, -0.3), (0.2, top + 1.95, -0.3), 0.015, 4)
        K.rod("Wood", (-a, top + 1.85, -0.3), (a, top + 1.85, -0.3), 0.06, 5)
    for a_, b_ in (((-1, -1), (1, -1)), ((1, -1), (1, 1)), ((1, 1), (-1, 1)), ((-1, 1), (-1, -1))):
        K.rod("Wood", (a_[0] * (a + 0.2), top + 1.85, a_[1] * (a + 0.2)), (b_[0] * (a + 0.2), top + 1.85, b_[1] * (a + 0.2)), 0.08, 6) if lod < 2 else None
    thatch_roof(K, a + 1.05, a + 1.05, 0.0, top + 1.9, BASE + H - top - 1.9 - 0.6, thick=0.34, q=2.3, wall=(a, a), ridge="knot")


ROUND = {"well": well, "kiln": kiln, "stalls": stalls, "shrine": shrine, "tower": lookout}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "fixtures", "vale_buildings.blend")
    params = json.load(open(os.path.join(ROOT, "specs", "vale_buildings.params.json")))
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials("vb")
    built = {}
    for lod in (0, 1, 2):
        coll = bpy.data.collections.new(f"vb_LOD{lod}")
        bpy.context.scene.collection.children.link(coll)
        total = 0
        for bi, (bid, P) in enumerate(params.items()):
            if only and bid not in only:
                continue
            K = B(lod, 500 + bi * 53, P)
            (ROUND.get(P["shape"]) or (shed if P["shape"] == "shed" else hall))(K, bid)
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
        ids = [b for b in params if not only or b in only]
        for (lod, bid), objs in built.items():
            for o in objs:
                o.hide_render = lod != 0
                if lod == 0:
                    i = ids.index(bid)
                    o.location = ((i % 5 - 2) * 15.0, -(i // 5) * 14.0, 0)
        tag = argv[argv.index("--render") + 1]
        views = []
        for row in range((len(ids) + 4) // 5):
            y = -row * 14.0
            views += [(f"row{row}_front", (10, y - 17, 11), (0, y, 1.8), 19), (f"row{row}_back", (-16, y + 12, 9), (0, y, 2), 22)]
        for i, bid in enumerate(ids):
            x, y = (i % 5 - 2) * 15.0, -(i // 5) * 14.0
            views.append((f"b_{bid}", (x + 6.5, y - 10.5, 5.2), (x, y, 2.0), 34))
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
