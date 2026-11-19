"""Fortification kit for Samurai Vale: the four ages of a Japanese wall as snap-together parts, three LODs each, in ONE blend.

  palisade  saku: sharpened logs lashed to rails, a plank fighting step        itabei    boards on posts under shingles, a railed walkway
  dobei     plastered rammed earth, loopholed and tiled, on field stone        ishigaki  a battered stone rampart crowned by a plastered parapet

Parts per tier (objects are named  wk_<tier>_<part>_LOD<n>_<Material>; the game groups them by tier, part and LOD and ignores node transforms):
  span      one MODULE metres of wall, centred on x = 0; the game sets as many side by side as a piece is long (scaled a little in x to fit)
  spanb     the same module battered: logs snapped, boards gone, plaster fallen, the crown slid away
  gateside  the LEFT side of a gate, its outer edge at x = 0, the passage toward +x (the right side is its mirror image)
  gatetop   lintel, walkway and roof over the passage, modelled GATE_L long and scaled in x to the gate's width
  leaf      one door leaf, hinge at x = 0, LEAF_W wide toward +x (scaled to fit; the other leaf is its mirror image)
  tower     a tower of the tier's size, centred
  (stairs and the short flights between decks of different height are assembled by the game from plain timbers and stone blocks: view/walls/flights.js)

Game frame -> Blender: the game's +x runs along the wall, +y is up, +z is the INSIDE. Here that is (x, -z, y): the outside of the wall faces +Y.
All measures (height, deck, thickness, walkway, deck offset, tower sizes) repeat src/content/walls.js and src/build/wallnet.js of the game: change them together.

  blender -b --factory-startup -P generators/wall_kit.py -- [--out fixtures/wall_kit.blend] [--render out/_wall_kit.png]
"""
import math
import os
import random
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_common import MB, ROOT, Roof, D, build_roof, render_preview, tileable  # noqa: E402
from roofs import thatch_roof, shingle_roof, board_roof, rock  # noqa: E402,F401

MODULE, GATE_L, LEAF_W = 1.4, 5.4, 2.2
TIERS = {
    "palisade": dict(k=0, height=3.1, deck=1.9, thick=0.7, walk=1.2, off=0.95, tower=3.4, rise=2.6),
    "itabei": dict(k=1, height=3.8, deck=2.5, thick=1.0, walk=1.5, off=1.2, tower=3.8, rise=3.0),
    "dobei": dict(k=2, height=4.6, deck=3.1, thick=1.5, walk=1.7, off=1.5, tower=4.6, rise=3.4),
    "ishigaki": dict(k=3, height=6.2, deck=4.9, thick=2.6, walk=2.2, off=0.3, tower=5.6, rise=4.0),
}
STAIR_RUN = {t: max(2.4, v["deck"] * 1.45) for t, v in TIERS.items()}
STAIR_W = 1.5
KINDS = ("Stone", "Plaster", "Wood", "WoodL", "Tile", "Thatch", "Shingle", "Earth", "Paper")
# what each of the kit's materials is made of: the builder kind (its texel density, gen_common.TILE / roofs.py) and the texture set (out/textures)
SURFACE = {"Stone": ("Nozura", "stone_nozura"), "Plaster": ("Shikkui", "plaster_shikkui"), "Wood": ("Timber", "timber_dark"), "WoodL": ("TimberL", "timber_pale"),
           "Tile": ("Tile", "roof_tile"), "Thatch": ("Kaya", "thatch_kaya"), "Shingle": ("Shingle", "wood_shingle"), "Earth": ("Earth", "earth_wall"), "Paper": ("Paper", "paper_washi")}
POST = (0.32, 0.36, 0.5, 0.9)
DOOR_H = (3.0, 3.2, 3.4, 3.6)


class Kit:
    """the six one-material builders of one part, with the game's frame: x along, y up, z inside"""

    def __init__(self, lod, seed):
        self.lod, self.r = lod, random.Random(seed)
        self.m = {k: MB(SURFACE[k][0]) for k in KINDS}

    def box(self, kind, w, h, d, x, y, z, rz=0.0, rx=0.0, ry=0.0):          # like the game's box(): y is the BASE of the box
        self.m[kind].box((x, -z, y + h / 2), (w, d, h), rz=rz, rx=rx, ry=ry)

    def log(self, kind, rb, rt, h, x, y, z, segs=8, lean=0.0):              # an upright log from y to y + h; lean tips it about the wall's axis
        mb = self.m[kind]
        with mb.at(Matrix.Translation((x, -z, y)) @ Matrix.Rotation(lean, 4, "X")):
            mb.cone((0, 0, h / 2), (0, 0, 1), rb, rt, h, segs)

    def beam(self, kind, a, b, w, h):                                       # a timber between two game points
        self.m[kind].box_along((a[0], -a[2], a[1]), (b[0], -b[2], b[1]), w, h)

    def rod(self, kind, a, b, r, segs=6):                                   # a round timber / ridge tile between two game points
        self.m[kind].tube([(a[0], -a[2], a[1]), (b[0], -b[2], b[1])], [r, r], sides=segs)

    def prism(self, kind, L, x, sec):                                       # along x, cross-section [(z, y), ...] in the game's frame
        pts = [(-z, y) for z, y in sec]
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
        if area < 0:
            pts = pts[::-1]
        x0, x1, mb, n = x - L / 2, x + L / 2, self.m[kind], len(pts)
        mb.face([(x1, p[0], p[1]) for p in pts])
        mb.face([(x0, p[0], p[1]) for p in pts[::-1]])
        for i in range(n):
            p, q = pts[i], pts[(i + 1) % n]
            mb.face([(x1, p[0], p[1]), (x0, p[0], p[1]), (x0, q[0], q[1]), (x1, q[0], q[1])])

    # ---- shared assemblies
    def gable(self, kind, L, x, z0, y0, hw, rise, rolls=True, ridge=True, gap=0.26):
        """a gable roof along x: eaves at y0, ridge `rise` above, half-width hw around z0. Tiled kinds get rolls down the slope, eave ends and a ridge."""
        self.prism(kind, L, x, [(z0 - hw, y0), (z0 + hw, y0), (z0 + hw, y0 + 0.08), (z0, y0 + rise + 0.08), (z0 - hw, y0 + 0.08)])
        tiled = kind == "Tile"
        batten = "Wood" if kind == "Shingle" else kind
        if self.lod == 0 and rolls:
            n = max(1, round(L / gap))
            for i in range(n):
                xx = x - L / 2 + L * (i + 0.5) / n
                for s in (-1, 1):
                    a, b = (xx, y0 + rise + 0.1, z0), (xx, y0 + 0.1, z0 + s * hw)
                    if tiled:
                        self.rod(kind, a, (b[0], b[1], b[2] + s * 0.02), 0.045, 5)
                    else:
                        self.beam(batten, a, b, 0.05, 0.035)
        if self.lod <= 1 and tiled:                                         # the round eave tiles
            n = max(1, round(L / (gap if self.lod == 0 else gap * 2)))
            for i in range(n):
                xx = x - L / 2 + L * (i + 0.5) / n
                for s in (-1, 1):
                    self.m[kind].cylinder((xx, -(z0 + s * (hw + 0.01)), y0 + 0.08), (0, -s, -0.25), 0.065, 0.12, 6)
        if ridge:
            if tiled:
                self.box(kind, L, 0.1, 0.24, x, y0 + rise + 0.05, z0)
                if self.lod <= 1:
                    self.rod(kind, (x - L / 2, y0 + rise + 0.2, z0), (x + L / 2, y0 + rise + 0.2, z0), 0.085, 6)
            else:
                self.box(batten, L, 0.09, 0.14, x, y0 + rise + 0.06, z0)

    def walkway(self, T, L, x0=0.0, lost=()):
        """the fighting step behind a timber or plastered wall: boards on a bearer, a post and a brace under them, once per module"""
        y, z, w, r = T["deck"], T["off"], T["walk"], self.r
        n = max(1, round(L / 0.35)) if self.lod == 0 else 1
        for i in range(n):
            if i in lost:
                continue
            d = L / n
            self.box("WoodL", d - (0.012 if n > 1 else 0), 0.08, w + (r.uniform(-0.04, 0.04) if n > 1 else 0), x0 - L / 2 + d * (i + 0.5), y - 0.08, z)
        if self.lod == 2:
            return
        xp = x0 - L / 2 + 0.35
        self.log("Wood", 0.1, 0.085, y + 0.4, xp, -0.5, z + w / 2 - 0.12, 6 if self.lod == 0 else 4)
        self.box("Wood", 0.11, 0.13, w + 0.1, xp, y - 0.21, z)
        if self.lod == 0:
            self.beam("Wood", (xp, y * 0.42, z + w / 2 - 0.12), (xp, y - 0.2, z - w * 0.3), 0.08, 0.08)
            self.box("Wood", L, 0.1, 0.09, x0, y - 0.19, z + w / 2 - 0.12)

    def loophole(self, x, y, z, round_=False):
        if self.lod > 1:
            return
        if round_:
            self.m["Wood"].cylinder((x, -z, y + 0.15), (0, 1, 0), 0.15, 0.06, 10)
        else:
            self.box("Wood", 0.2, 0.36, 0.06, x, y, z)

    def stones(self, L, x0, hw, b, top, n, big=0.5):
        """boulders standing proud of a battered stone face (outside and, fewer, inside): what makes a rampart read as fitted stone, not a slab"""
        r = self.r
        for i in range(n):
            y = -0.3 + (top - 0.2) * r.random() ** 1.3
            f = 1 - (y + 0.8) / (top + 0.8)
            inside = r.random() < 0.25
            z = (hw + b * 0.45 * f) if inside else -(hw + b * f)
            s = big * r.uniform(0.55, 1.0) * (1.25 - 0.5 * (y / top))
            lean = math.atan2(b * (0.45 if inside else 1.0), top + 0.8)
            self.box("Stone", s * r.uniform(0.9, 1.5), s * r.uniform(0.6, 0.9), 0.2, x0 + (r.random() - 0.5) * (L - s), y, z + (-0.05 if inside else 0.05),
                     rz=r.uniform(-0.03, 0.03), rx=(lean if not inside else -lean), ry=r.uniform(-0.06, 0.06))

    def rubble(self, kinds, n, L, zmin, zmax, size=0.3):
        r = self.r
        for _ in range(n if self.lod < 2 else n // 3):
            s = size * r.uniform(0.5, 1.3)
            self.box(r.choice(kinds), s * r.uniform(0.8, 1.6), s * 0.6, s * r.uniform(0.7, 1.4), (r.random() - 0.5) * L, -0.05 + s * 0.1, r.uniform(zmin, zmax),
                     rz=r.random() * 3.1, rx=r.uniform(-0.3, 0.3))

    def objects(self, name, mats, coll):
        out = []
        for kind, mb in self.m.items():
            if len(mb.bm.faces):
                out.append(mb.to_object(f"{name}_LOD{self.lod}_{kind}", mats[kind], coll))
            else:
                mb.bm.free()
        return out


# ------------------------------------------------------------------------------------------------------------------ spans
def span(K, tier, broken=False):
    T, L, r, lod = TIERS[tier], MODULE, K.r, K.lod
    k = T["k"]
    if k == 0:
        n = 5 if lod < 2 else 3
        d = L / n
        gone = {1, 3} if broken else set()
        for i in range(n):
            x = -L / 2 + d * (i + 0.5)
            rad = d / 2 * r.uniform(0.9, 1.04)
            z = r.uniform(-0.035, 0.035)
            h = T["height"] - 0.42 + r.uniform(-0.23, 0.23)
            segs = (8, 6, 4)[lod]
            if i in gone:
                if i == 1:
                    K.log("Wood", rad * 1.05, rad, 0.3 + r.random() * 0.4, x, -0.3, z, segs)                       # a stump
                    if lod < 2:
                        K.rod("Wood", (x - 0.2, 0.14, -0.5), (x + 0.5, 0.16, -2.6), rad * 0.95, 6)                  # the log, felled outward
                continue
            snapped = broken and i == 2
            if snapped:
                h *= 0.55
            lean = r.uniform(-0.07, 0.07) if broken else 0.0
            K.log("Wood", rad * 1.06, rad * 0.94, h + 0.6, x, -0.6, z, segs, lean)
            if lod < 2:
                tip = Matrix.Translation((x, -z, -0.6)) @ Matrix.Rotation(lean, 4, "X")
                with K.m["WoodL"].at(tip):
                    K.m["WoodL"].cone((0, 0, h + 0.6 + (0.08 if snapped else 0.21)), (0, 0, 1), rad * 0.94, 0.02, 0.16 if snapped else 0.42, segs)
            if lod == 0 and i % 2 == 1:
                for y in (0.98, 2.28):
                    if y < h:
                        K.box("Thatch", rad * 2.3, 0.08, 0.07, x, y, z + rad + 0.09)                                 # rope lashing to the rail
        for y in (0.95, 2.25):
            if lod < 2:
                K.rod("Wood", (-L / 2, y + 0.06, 0.22), (L / 2, y + 0.06, 0.22), 0.075, 6 if lod == 0 else 4)
        K.walkway(T, L, lost={1, 2} if broken else ())
        if broken:
            K.rubble(["Wood", "WoodL"], 5, L, -1.6, -0.4, 0.22)
    elif k == 1:
        K.box("Wood", 0.22, T["height"] + 0.5, 0.22, -L / 2, -0.5, 0)
        if lod < 2:
            K.box("Stone", 0.52, 0.3, 0.52, -L / 2, -0.12, 0, rz=r.uniform(-0.1, 0.1))
        n = 7 if lod == 0 else 1
        d = L / n
        for i in range(n):
            if broken and i in (2, 3):
                continue
            h = (T["height"] - 0.25) * ((0.35 + r.random() * 0.3) if broken and i in (1, 4) else 1)
            K.box("Wood", d - (0.012 if n > 1 else 0), h, 0.05, -L / 2 + d * (i + 0.5), 0.1, -0.1 + (r.uniform(-0.008, 0.008) if n > 1 else 0))
            if lod == 0 and h > 2 and not (broken and i in (1, 4)):
                K.box("WoodL", 0.045, h - 0.1, 0.03, -L / 2 + d * i, 0.15, -0.135)                                   # the batten over each joint
        if lod < 2:
            for y in (0.55, T["height"] * 0.5, T["height"] - 0.75):
                K.box("Wood", L, 0.14, 0.1, 0, y, 0.0)
        if not broken:
            K.gable("Shingle", L, 0, -0.05, T["height"] - 0.05, 0.64, 0.34, gap=0.35)
        else:
            K.gable("Shingle", L * 0.4, -L * 0.3, -0.05, T["height"] - 0.05, 0.64, 0.34, gap=0.35)
            K.rubble(["Wood", "WoodL"], 6, L, -1.5, -0.3, 0.26)
        K.box("Wood", L, 0.1, 0.1, 0, T["height"] + 0.3 - (0.42 if broken else 0), -0.05) if lod < 2 and not broken else None
        K.walkway(T, L, lost={2} if broken else ())
        # (the rail along the walkway is made by the game, piece by piece: it has to leave a gap wherever a stair lands)
    elif k == 2:
        base, top, zc = 1.15, T["height"] - 0.7, -0.22
        K.prism("Stone", L, 0, [(-1.0, -0.6), (0.55, -0.6), (0.4, base), (-0.85, base)])
        if lod == 0:
            K.stones(L, 0, 0.47, 0.55, base, 5, 0.42)
        K.box("Wood", L, 0.14, 0.95, 0, base, zc)
        if not broken:
            K.box("Plaster", L, top - base - 0.12, 0.85, 0, base + 0.12, zc)
            K.loophole(-0.35, 2.75, zc - 0.44)
            K.loophole(0.35, 2.75, zc - 0.44, round_=True)
            K.box("Wood", L, 0.12, 0.95, 0, top - 0.1, zc)
            K.gable("Tile", L, 0, zc, top, 0.8, 0.6)
        else:
            cols = 4 if lod < 2 else 2
            d = L / cols
            for i in range(cols):
                h = (top - base - 0.12) * (1.0 if i == 0 else (0.25, 0.45, 0.7)[i % 3])
                K.box("Plaster", d, h, 0.85 if i == 0 else 0.78, -L / 2 + d * (i + 0.5), base + 0.12, zc, rz=0.0 if i == 0 else r.uniform(-0.03, 0.03))     # a jagged break
            K.gable("Tile", d, -L / 2 + d / 2, zc, top, 0.8, 0.6)
            K.box("Wood", d, 0.12, 0.95, -L / 2 + d / 2, top - 0.1, zc)
            K.rubble(["Plaster", "Tile", "Stone", "Plaster"], 9, L, -2.0, -0.9, 0.3)
        if lod < 2:                                                                                                 # the stay post that props the wall from inside
            K.beam("Wood", (0.2, 0.0, 1.35), (0.2, 2.25, 0.2), 0.14, 0.14)
            K.box("Wood", 0.14, 0.14, 1.2, 0.2, 2.1, 0.55)
        K.walkway(T, L, lost={1} if broken else ())
    else:
        top, hw = T["deck"], T["thick"] / 2
        b = top * 0.2 + 0.2
        sec = lambda y1: [(-hw - b, -0.8), (hw + b * 0.45, -0.8), (hw + b * 0.45 * (1 - (y1 + 0.8) / (top + 0.8)), y1), (-hw - b * (1 - (y1 + 0.8) / (top + 0.8)), y1)]
        if not broken:
            K.prism("Stone", L, 0, sec(top))
            if lod == 0:
                K.stones(L, 0, hw, b, top, 16, 0.62)
            if lod < 2:
                K.box("Stone", L, 0.07, T["thick"] - 0.3, 0, top - 0.05, 0.15)
            pz = -hw + 0.3
            K.box("Plaster", L, 1.05, 0.46, 0, top, pz)
            K.box("Wood", L, 0.1, 0.52, 0, top, pz) if lod < 2 else None
            K.loophole(0, top + 0.42, pz - 0.24, round_=False)
            K.gable("Tile", L, 0, pz, top + 1.0, 0.46, 0.34)
        else:
            low = top * 0.62
            K.prism("Stone", L, 0, sec(low))
            K.prism("Stone", L * 0.45, -L * 0.275, sec(top))
            if lod == 0:
                K.stones(L, 0, hw, b, low, 10, 0.62)
            pz = -hw + 0.3
            K.box("Plaster", L * 0.3, 0.7, 0.46, -L * 0.35, top, pz, rz=0.0)
            for i in range(7 if lod < 2 else 3):                                                                    # what slid from the crown lies on the slope and at its foot
                s = r.uniform(0.35, 0.7)
                K.box("Stone", s * 1.3, s * 0.7, s, L * (0.1 + 0.35 * r.random()), low - 0.1 + r.random() * 0.25, r.uniform(-hw, hw * 0.4), rz=r.random() * 3, rx=r.uniform(-0.4, 0.4))
            K.rubble(["Stone", "Stone", "Plaster", "Tile"], 10, L, -hw - b - 1.6, -hw - b - 0.1, 0.42)


# ------------------------------------------------------------------------------------------------------------------ gates
def gate_side(K, tier):
    """the left jamb: x from 0 (the wall's end) to POST (the passage)"""
    T, lod, r = TIERS[tier], K.lod, K.r
    k, post, dh, off = T["k"], POST[T["k"]], DOOR_H[T["k"]], T["off"]
    xc = post / 2
    if k <= 1:
        segs = (10, 7, 5)[lod]
        if k == 0:
            K.log("Wood", post * 0.9, post * 0.8, T["height"] + 1.5, xc, -0.6, 0, segs)
            if lod < 2:
                K.m["WoodL"].cone((xc, 0, T["height"] + 0.9 + 0.2), (0, 0, 1), post * 0.8, 0.03, 0.4, segs)
                for y in (dh - 0.25, dh + 0.5):
                    K.box("Thatch", post * 1.75, 0.1, post * 1.75, xc, y, 0)                                          # rope bindings round the post
        else:
            K.box("Wood", post * 1.5, T["height"] + 1.3, post * 1.5, xc, -0.6, 0)
            if lod < 2:
                K.box("Stone", post * 2.3, 0.34, post * 2.3, xc, -0.1, 0)
                K.box("WoodL", post * 1.8, 0.1, post * 1.8, xc, T["height"] + 0.7, 0)
                K.box("Wood", 0.2, T["deck"] + 1.2, 0.2, xc, -0.3, 1.1)                                               # the smaller post behind, and the tie between them
                K.box("Wood", 0.14, 0.16, 1.1, xc, dh * 0.62, 0.55)
        K.box("Wood", 0.12, T["deck"] + (1.2 if k else 1.35) + 1.3, 0.12, 0.1, -0.3, off + T["walk"] / 2 - 0.1)       # carries the rail of the walkway over the gate
    elif k == 2:
        K.prism("Stone", post, xc, [(-1.0, -0.6), (0.6, -0.6), (0.45, 1.2), (-0.85, 1.2)])
        K.box("Plaster", post, T["height"] - 1.2, 0.9, xc, 1.2, -0.2)
        K.box("Wood", 0.3, dh + 0.3, 0.36, post + 0.16, -0.2, -0.2)
        if lod < 2:
            K.box("Stone", 0.46, 0.3, 0.52, post + 0.16, -0.1, -0.2)
            K.box("Wood", post + 0.02, 0.14, 0.94, xc, 1.2, -0.2)
    else:
        top, hw = T["deck"], T["thick"] / 2
        b = top * 0.2 + 0.2
        K.prism("Stone", post, xc, [(-hw - b, -0.8), (hw + b * 0.45, -0.8), (hw, top), (-hw, top)])
        if lod == 0:
            K.stones(post, xc, hw, b, top, 9, 0.6)
            for y in (0.0, 0.9, 1.8, 2.7, 3.6):                                                                     # dressed corner stones on the passage side
                K.box("Stone", 0.26, 0.8, T["thick"] + 0.5 - y * 0.12, post - 0.08, y - 0.4, 0)
        K.box("Wood", 0.34, dh + 0.3, 0.4, post + 0.18, -0.2, -0.3)
        if lod < 2:
            K.box("Stone", 0.5, 0.3, 0.56, post + 0.18, -0.1, -0.3)


def gate_top(K, tier):
    """everything over the passage, GATE_L long (the jambs included), centred"""
    T, lod, L = TIERS[tier], K.lod, GATE_L
    k, dh, off = T["k"], DOOR_H[T["k"]], T["off"]
    if k <= 1:
        if k == 0:
            K.rod("Wood", (-L / 2 - 0.35, dh + 0.27, 0), (L / 2 + 0.35, dh + 0.27, 0), 0.17, (8, 6, 4)[lod])
            K.rod("Wood", (-L / 2 - 0.6, dh + 0.78, 0), (L / 2 + 0.6, dh + 0.78, 0), 0.13, (8, 6, 4)[lod])
        else:
            K.box("Wood", L + 0.5, 0.3, 0.34, 0, dh + 0.12, 0)
            K.box("Wood", L + 0.9, 0.24, 0.28, 0, dh + 0.62, 0)
            if lod < 2:
                for x in (-L * 0.3, 0, L * 0.3):
                    K.box("Wood", 0.16, 0.26, 0.2, x, dh + 0.4, 0)
            K.gable("Shingle", L + 1.0, 0, 0, dh + 0.86, 1.15, 0.6, gap=0.45)
            if lod < 2:
                for s in (-1, 1):
                    K.box("WoodL", L + 1.0, 0.1, 0.05, 0, dh + 0.82, s * 1.13)
        yw = T["deck"] + (1.2 if k else 1.35)
        K.box("WoodL", L, 0.09, T["walk"], 0, yw, off)
        if lod < 2:
            K.box("Wood", L, 0.14, 0.1, 0, yw - 0.14, off + T["walk"] / 2 - 0.1)
            K.box("Wood", L, 0.14, 0.1, 0, yw - 0.14, off - T["walk"] / 2 + 0.1)
            K.box("Wood", L, 0.07, 0.07, 0, yw + 0.95, off + T["walk"] / 2 - 0.1)
    elif k == 2:
        K.box("Wood", L, 0.34, 0.42, 0, dh + 0.1, -0.2)
        K.box("Plaster", L, T["height"] - dh - 0.75, 0.8, 0, dh + 0.44, -0.2)
        if lod < 2:
            K.box("Wood", L, 0.12, 0.86, 0, T["height"] - 0.42, -0.2)
            for i in range(9):
                K.box("Wood", 0.16, 0.16, 1.5, -L / 2 + L * (i + 0.5) / 9, T["height"] - 0.36, -0.2)                  # rafter ends under the eaves
        K.box("WoodL", L, 0.1, T["walk"], 0, T["deck"] + 0.55, off)
        K.gable("Tile", L + 0.9, 0, -0.2, T["height"] - 0.3, 1.35, 0.85)
        if lod < 2:
            for s in (-1, 1):
                K.box("Tile", 0.22, 0.34, 0.3, s * (L / 2 + 0.36), T["height"] + 0.6, -0.2)
    else:
        top, th = T["deck"], T["thick"]
        K.box("Wood", L, 0.4, th + 0.2, 0, dh + 0.1, 0)
        K.box("Stone", L, top - dh - 0.5, th, 0, dh + 0.5, 0)
        if lod < 2:
            for i in range(11):
                K.box("Wood", 0.18, 0.2, th + 0.5, -L / 2 + L * (i + 0.5) / 11, dh + 0.3, 0)
        K.box("Plaster", L + 0.3, 2.4, th + 0.5, 0, top, 0)                                                         # the gatehouse over the passage
        K.box("Wood", L + 0.36, 0.16, th + 0.56, 0, top, 0)
        if lod < 2:
            n = 7
            for s in (-1, 1):
                for i in range(n):                                                                                  # a band of lattice windows on both faces
                    x = -L / 2 + 0.3 + (L - 0.6) * (i + 0.5) / n
                    K.box("Wood", (L - 0.6) / n - 0.16, 0.6, 0.08, x, top + 0.95, s * (th / 2 + 0.25))
                    if lod == 0:
                        K.box("WoodL", (L - 0.6) / n - 0.06, 0.07, 0.1, x, top + 0.86, s * (th / 2 + 0.26))
                        K.box("WoodL", (L - 0.6) / n - 0.06, 0.07, 0.1, x, top + 1.56, s * (th / 2 + 0.26))
            K.box("Wood", L + 0.4, 0.14, th + 0.6, 0, top + 2.3, 0)
            for i in range(13):
                K.box("Wood", 0.14, 0.14, th + 2.0, -L / 2 + L * (i + 0.5) / 13, top + 2.24, 0)
        K.gable("Tile", L + 1.3, 0, 0, top + 2.35, th / 2 + 1.1, 1.3)
        for s in (-1, 1):                                                                                           # the fish-tailed finials on the ridge ends
            K.box("Tile", 0.3, 0.5, 0.26, s * (L / 2 + 0.5), top + 3.75, 0)
            if lod < 2:
                K.box("Tile", 0.16, 0.34, 0.2, s * (L / 2 + 0.56), top + 4.2, 0, ry=s * 0.5)


def gate_leaf(K, tier):
    T, lod = TIERS[tier], K.lod
    k, dh, w = T["k"], DOOR_H[T["k"]], LEAF_W
    n = 6 if lod == 0 else 1
    for i in range(n):
        K.box("Wood", w / n - (0.01 if n > 1 else 0), dh, 0.1, w * (i + 0.5) / n, 0.05, 0)
    if lod < 2:
        for y in (0.45, dh * 0.5, dh - 0.4):
            K.box("WoodL" if k < 2 else "Wood", w, 0.1, 0.15, w / 2, y, 0)
        if k >= 2 and lod == 0:
            for i in range(5):
                for y in (0.9, dh - 0.9):
                    K.box("Tile", 0.08, 0.08, 0.2, 0.25 + i * 0.42, y, 0)                                            # iron studs (the tile's dark glaze stands in for iron)
        if k < 2 and lod == 0:
            K.beam("Wood", (0.1, 0.5, -0.07), (w - 0.1, dh - 0.45, -0.07), 0.12, 0.05)


# ------------------------------------------------------------------------------------------------------------------ towers
def tower(K, tier):
    T, lod, r = TIERS[tier], K.lod, K.r
    k, s, rise, deck = T["k"], T["tower"], T["rise"], T["deck"]
    h = s / 2
    d = D(lod)
    if k == 0:                                                                                                      # an open look-out on four legs, boarded breast-high, thatched
        for x, z in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            K.log("Wood", 0.2, 0.15, deck + rise + 1.3, x * (h - 0.15), -0.6, z * (h - 0.15), (8, 6, 4)[lod])
        for y in (deck, deck + rise - 0.18):
            n = 9 if lod == 0 else 1
            for i in range(n):
                K.box("WoodL", s / n - (0.012 if n > 1 else 0), 0.1, s, -h + s * (i + 0.5) / n, y - 0.1, 0)
            if lod < 2:
                for z in (-h + 0.15, h - 0.15):
                    K.rod("Wood", (-h - 0.2, y - 0.2, z), (h + 0.2, y - 0.2, z), 0.09, 6)
        for lvl, y in enumerate((deck, deck + rise - 0.1)):
            for x, z, w, dd in ((0, -h, s, 0.07), (-h, 0, 0.07, s), (h, 0, 0.07, s)):
                n = 8 if lod == 0 else 2
                for i in range(n):
                    if w > dd:
                        K.box("Wood", w / n - 0.012 * (n > 1), 1.05 + (r.uniform(-0.05, 0.05) if lod == 0 else 0), dd, -h + s * (i + 0.5) / n, y, z)
                    elif lvl == 1 or -h + s * (i + 0.5) / n < 0.1:           # at the level of the wall's walkway the inner half of each side stays open: the way through
                        K.box("Wood", w, 1.05 + (r.uniform(-0.05, 0.05) if lod == 0 else 0), dd / n - 0.012 * (n > 1), x, y, -h + s * (i + 0.5) / n)
        if lod < 2:
            for a, b in (((-h, 0.3, -h), (h, deck - 0.3, -h)), ((h, 0.3, -h), (-h, deck - 0.3, -h)), ((-h, 0.3, -h), (-h, deck - 0.3, h)), ((h, 0.3, h), (h, deck - 0.3, -h))):
                K.beam("Wood", (a[0] * 0.92, a[1], a[2] * 0.92), (b[0] * 0.92, b[1], b[2] * 0.92), 0.09, 0.09)       # cross braces
            for y_ in [0.4 + 0.42 * i for i in range(int((deck + rise - 0.8) / 0.42))]:
                K.box("WoodL", 0.5, 0.06, 0.06, 0, y_, h + 0.02)                                                    # the ladder, on the inside
            for x in (-0.25, 0.25):
                K.box("Wood", 0.06, deck + rise, 0.06, x, 0, h + 0.02)
        ye = deck + rise + 0.62
        if lod < 2:                                                                                                 # the ring of poles the roof sits on, and its hip poles
            for a_, b_ in (((-1, -1), (1, -1)), ((1, -1), (1, 1)), ((1, 1), (-1, 1)), ((-1, 1), (-1, -1))):
                K.rod("Wood", (a_[0] * (h + 0.25), ye, a_[1] * (h + 0.25)), (b_[0] * (h + 0.25), ye, b_[1] * (h + 0.25)), 0.085, 6)
            for x, z in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                K.rod("WoodL", (x * (h - 0.12), ye + 0.06, z * (h - 0.12)), (0, ye + 1.55, 0), 0.055, 5)
                if lod == 0:
                    K.box("Thatch", 0.34, 0.09, 0.34, x * (h - 0.15), ye - 0.12, z * (h - 0.15))                    # rope round the head of each leg
        thatch_roof(K, h + 0.7, h + 0.7, 0.0, ye + 0.05, 1.75, thick=0.36, q=3.0, wall=(h - 0.2, h - 0.2), ridge="knot")
    elif k == 1:
        n = 12 if lod == 0 else 1
        for ang in range(4):
            with K.m["Wood"].at(Matrix.Rotation(ang * math.pi / 2, 4, "Z")):
                for i in range(n):
                    K.m["Wood"].box((-h + s * (i + 0.5) / n, h, (deck - 0.6) / 2), (s / n - 0.012 * (n > 1), 0.08, deck + 0.6))
                    K.m["Wood"].box((-h - 0.3 + (s + 0.6) * (i + 0.5) / n, h + 0.3, deck + (rise + 0.5) / 2), ((s + 0.6) / n - 0.012 * (n > 1), 0.08, rise + 0.5))
                if lod < 2:                                                                                         # rails round the lower storey; on each face above, an opening under a propped shutter
                    for zz in (0.9, deck * 0.55):
                        K.m["WoodL"].box((0, h + 0.05, zz), (s, 0.06, 0.12))
                    ww, wh_, wz_ = s * 0.52, 0.62, deck + 1.25
                    K.m["Wood"].box((0, h + 0.33, wz_), (ww, 0.08, wh_))
                    for zz in (wz_ - wh_ / 2 - 0.05, wz_ + wh_ / 2 + 0.05):
                        K.m["WoodL"].box((0, h + 0.37, zz), (ww + 0.24, 0.1, 0.1))
                    for xx in (-ww / 2 - 0.05, ww / 2 + 0.05):
                        K.m["WoodL"].box((xx, h + 0.37, wz_), (0.1, 0.1, wh_ + 0.2))
                    K.m["Wood"].box((0, h + 0.36 + 0.27, wz_ + wh_ / 2 - 0.2), (ww + 0.06, 0.05, wh_ + 0.06), rx=-0.95)   # the shutter, hinged at the head and propped out
                    if lod == 0:
                        for xx in (-ww * 0.4, ww * 0.4):
                            K.m["WoodL"].box_along((xx, h + 0.38, wz_ - wh_ / 2), (xx, h + 0.8, wz_ - 0.05), 0.035, 0.035)
                        for i in range(1, 4):
                            K.m["WoodL"].box((-ww / 2 + ww * i / 4, h + 0.36, wz_), (0.05, 0.06, wh_))
        K.box("Wood", s + 0.7, 0.16, s + 0.7, 0, deck - 0.1, 0)
        for x, z in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            K.box("Wood", 0.26, deck + rise + 1.1, 0.26, x * h, -0.6, z * h)
            if lod < 2:
                K.box("Stone", 0.5, 0.3, 0.5, x * h, -0.12, z * h)
        y0 = deck + rise + 0.5
        if lod < 2:
            K.box("Wood", s + 0.86, 0.14, s + 0.86, 0, y0 - 0.14, 0)                                                # the head beam, and brackets under the eave
            for ang in range(4):
                with K.m["Wood"].at(Matrix.Rotation(ang * math.pi / 2, 4, "Z")):
                    for u in ((-h - 0.2, h + 0.2) if lod else (-h - 0.2, -h * 0.35, h * 0.35, h + 0.2)):
                        K.m["Wood"].box_along((u, h + 0.3, y0 - 0.5), (u, h + 0.82, y0 - 0.1), 0.1, 0.12)
        shingle_roof(K, h + 1.12, h + 1.12, 0.0, 0.0, y0, 1.55, lift=0.3, kick=0.2, wall=(h + 0.3, h + 0.3))
        if lod < 2:
            K.box("Wood", 0.9, 1.9, 0.1, 0, 0, h + 0.05)                                                            # the door, on the inside
            K.box("WoodL", 1.06, 0.1, 0.12, 0, 1.9, h + 0.06)
    else:
        base = 1.8 if k == 2 else deck
        bt = 0.35 if k == 2 else base * 0.2 + 0.2
        w0, w1 = s + 2 * bt, s
        K.m["Stone"].cone((0, 0, (base - 0.8) / 2), (0, 0, 1), w0 / math.sqrt(2), w1 / math.sqrt(2), base + 0.8, 4)
        st = K.m["Stone"]
        if lod == 0:                                                                                                # proud stones on the four battered faces, dressed stones up the corners
            for ang in range(4):
                with st.at(Matrix.Rotation(ang * math.pi / 2, 4, "Z")):
                    for _ in range(14 if k == 3 else 6):
                        y = -0.3 + (base - 0.3) * r.random() ** 1.3
                        f = 1 - (y + 0.8) / (base + 0.8)
                        q = 0.6 * r.uniform(0.55, 1.0)
                        st.box(((r.random() - 0.5) * (s - 0.4), h + bt * f - 0.05, y + q * 0.35), (q * r.uniform(0.9, 1.5), 0.2, q * 0.75), rz=0.0, rx=math.atan2(bt, base + 0.8), ry=r.uniform(-0.05, 0.05))
                    for i in range(int(base / 0.75) + 1):
                        y = -0.4 + i * 0.75
                        f = 1 - (y + 0.4 + 0.8) / (base + 0.8)
                        st.box((h + bt * f - 0.25, h + bt * f - 0.25, y + 0.36), (0.62 if i % 2 else 0.9, 0.9 if i % 2 else 0.62, 0.7), rz=0.0)
        s1 = s - 0.3
        h1 = (deck + rise - base) if k == 2 else 2.7
        K.box("Plaster", s1, h1, s1, 0, base, 0)
        K.box("Wood", s1 + 0.12, 0.3, s1 + 0.12, 0, base, 0)
        if lod < 2:
            for ang in range(4):
                with K.m["Wood"].at(Matrix.Rotation(ang * math.pi / 2, 4, "Z")), K.m["WoodL"].at(Matrix.Rotation(ang * math.pi / 2, 4, "Z")):
                    for x in (-s1 * 0.22, s1 * 0.22):
                        K.m["Wood"].box((x, s1 / 2 + 0.02, base + h1 * 0.6), (s1 * 0.26, 0.07, 0.62))               # windows: a dark opening, a pale frame, bars
                        if lod == 0:
                            for dz in (-0.36, 0.36):
                                K.m["WoodL"].box((x, s1 / 2 + 0.05, base + h1 * 0.6 + dz), (s1 * 0.26 + 0.14, 0.08, 0.09))
                            for i in range(5):
                                K.m["WoodL"].box((x - s1 * 0.13 + s1 * 0.26 * (i + 0.5) / 5, s1 / 2 + 0.06, base + h1 * 0.6), (0.04, 0.05, 0.62))
                    for x in (-s1 / 2 + 0.11, s1 / 2 - 0.11):
                        K.m["Wood"].box((x, s1 / 2 - 0.07, base + h1 / 2), (0.22, 0.22, h1))                        # corner posts set in the plaster
        tl, wd = K.m["Tile"], K.m["Wood"]
        if k == 2:
            build_roof(tl, wd, d, Roof(base + h1, s1 / 2 + 0.95, s1 / 2 + 0.95, 0.12, 0.12, 1.75, 0.34), s1 / 2)
            K.box("Tile", 0.42, 0.36, 0.42, 0, base + h1 + 1.72, 0)
        else:                                                                                                       # two storeys: a skirt of tile, a smaller storey, the top roof with its finials
            s2 = s1 - 1.3
            y2 = base + h1
            build_roof(tl, wd, d, Roof(y2, s1 / 2 + 1.0, s1 / 2 + 1.0, s2 / 2, s2 / 2, 0.85, 0.3), s1 / 2)
            h2 = 2.4
            K.box("Plaster", s2, h2 + 0.8, s2, 0, y2, 0)
            if lod < 2:
                for ang in range(4):
                    with K.m["Wood"].at(Matrix.Rotation(ang * math.pi / 2, 4, "Z")), K.m["WoodL"].at(Matrix.Rotation(ang * math.pi / 2, 4, "Z")):
                        K.m["Wood"].box((0, s2 / 2 + 0.02, y2 + 0.8 + h2 * 0.55), (s2 * 0.6, 0.07, 0.6))
                        if lod == 0:
                            for i in range(9):
                                K.m["WoodL"].box((-s2 * 0.3 + s2 * 0.6 * (i + 0.5) / 9, s2 / 2 + 0.06, y2 + 0.8 + h2 * 0.55), (0.04, 0.05, 0.6))
                        for x in (-s2 / 2 + 0.1, s2 / 2 - 0.1):
                            K.m["Wood"].box((x, s2 / 2 - 0.06, y2 + 0.8 + h2 / 2), (0.2, 0.2, h2))
            y3 = y2 + 0.8 + h2
            build_roof(tl, wd, d, Roof(y3, s2 / 2 + 1.05, s2 / 2 + 0.95, 0.9, 0.0, 1.9, 0.36), s2 / 2)
            K.box("Tile", 2.0, 0.2, 0.3, 0, y3 + 1.86, 0)
            for sx in (-1, 1):
                K.box("Tile", 0.26, 0.5, 0.24, sx * 0.95, y3 + 1.95, 0)
                if lod < 2:
                    K.box("Tile", 0.14, 0.3, 0.18, sx * 1.02, y3 + 2.4, 0, ry=sx * 0.5)
        if lod < 2:
            dz = h + (0.2 if k == 2 else bt * 0.5) + 0.05
            K.box("Wood", 1.0, 2.0, 0.12, 0, 0, dz)
            K.box("WoodL", 1.2, 0.12, 0.16, 0, 2.0, dz)
            for x in (-0.56, 0.56):
                K.box("WoodL", 0.12, 2.0, 0.16, x, 0, dz)


PARTS = {"span": lambda K, t: span(K, t), "spanb": lambda K, t: span(K, t, True), "gateside": gate_side, "gatetop": gate_top, "leaf": gate_leaf, "tower": tower}


def make_materials(prefix="wk"):
    return {k: tileable(f"{prefix}_{k.lower()}", SURFACE[k][1]) for k in KINDS}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "fixtures", "wall_kit.blend")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    built = {}
    for lod in (0, 1, 2):
        coll = bpy.data.collections.new(f"wk_LOD{lod}")
        bpy.context.scene.collection.children.link(coll)
        total = 0
        for ti, tier in enumerate(TIERS):
            for pi, (part, fn) in enumerate(PARTS.items()):
                K = Kit(lod, 1000 + ti * 37 + pi * 101)                     # the same seed at every LOD: the same stones, the same broken boards
                fn(K, tier)
                objs = K.objects(f"wk_{tier}_{part}", mats, coll)
                tris = 0
                for o in objs:
                    o.data.calc_loop_triangles()
                    tris += len(o.data.loop_triangles)
                built[(lod, tier, part)] = objs
                total += tris
                print(f"LOD{lod} {tier:9s} {part:9s} {tris:6,d} tris")
        print(f"LOD{lod}: {total:,} tris")
    if "--render" in argv:
        # a parade for the eye: each tier a row; four span modules side by side, a gate assembled as the game would, the tower, the stair. (Object transforms
        # only: the mesh data stays at the origin, and the transforms are put back before the file is saved.)
        moved = []

        def put(o, x, y, sx=1.0, mirror=False):
            c = o.copy() if mirror or (o, 1) in moved else o
            if c is not o:
                bpy.context.scene.collection.objects.link(c)
            c.location = (x, y, 0)
            c.scale = (-sx if mirror else sx, 1, 1)
            moved.append((c, c is not o))
            return c
        for lod in (1, 2):
            for (l, _, _), objs in built.items():
                if l == lod:
                    for o in objs:
                        o.hide_render = True
        for ti, tier in enumerate(TIERS):
            y = -ti * 13.0
            for o in built[(0, tier, "span")]:
                for i in range(3):
                    c = o.copy()
                    bpy.context.scene.collection.objects.link(c)
                    c.location = (-21 + i * MODULE, y, 0)
                    moved.append((c, True))
            for o in built[(0, tier, "spanb")]:
                put(o, -21 + 3 * MODULE, y)
            for o in built[(0, tier, "span")]:
                put(o, -21 + 4 * MODULE, y)
            gx = -9.5
            for o in built[(0, tier, "gateside")]:
                c = o.copy()
                bpy.context.scene.collection.objects.link(c)
                c.location, c.scale = (gx + GATE_L / 2, y, 0), (-1, 1, 1)
                moved.append((c, True))
                put(o, gx - GATE_L / 2, y)
            for o in built[(0, tier, "gatetop")]:
                put(o, gx, y)
            pw = GATE_L - 2 * POST[ti]
            for o in built[(0, tier, "leaf")]:
                c = o.copy()
                bpy.context.scene.collection.objects.link(c)
                c.location, c.scale, c.rotation_euler = (gx + pw / 2, y, 0), (-(pw / 2 - 0.03) / LEAF_W, 1, 1), (0, 0, -0.5)
                moved.append((c, True))
                o.location, o.scale, o.rotation_euler = (gx - pw / 2, y, 0), ((pw / 2 - 0.03) / LEAF_W, 1, 1), (0, 0, 0.5)
                moved.append((o, False))
            for o in built[(0, tier, "tower")]:
                put(o, 1.5, y)
        tag = argv[argv.index("--render") + 1]
        views = [("all", (4, 44, 30), (-3, -22, 0), 30)]
        for ti, tier in enumerate(TIERS):
            y = -ti * 13.0
            views += [(f"{tier}_tower", (9.5, y + 8.5, 7.5), (1.5, y, 4.0), 30), (f"{tier}_towerlow", (-4.5, y - 9, 2.2), (1.5, y, 4.4), 30)]
            views += [(f"{tier}_out", (-12, y + 11.5, 12), (-8, y, 2.2), 24), (f"{tier}_in", (-2, y - 11.5, 12.5), (-5, y, 2.4), 24), (f"{tier}_close", (-22.5, y + 5.2, 4.6), (-18.4, y, 1.7), 32)]
        render_preview(tag, views, ground_z=0.0)
        for o, is_copy in moved:
            if is_copy:
                bpy.data.objects.remove(o)
            else:
                o.location, o.scale, o.rotation_euler = (0, 0, 0), (1, 1, 1), (0, 0, 0)
        for o in list(bpy.data.objects):
            if o.type != "MESH" or not o.name.startswith("wk_"):
                bpy.data.objects.remove(o)
    if "--no-save" not in argv:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)


if __name__ == "__main__":
    main()
