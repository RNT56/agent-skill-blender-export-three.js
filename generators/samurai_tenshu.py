"""The great keep (tenshu 天守閣), the third and last tier of a Samurai Vale house's seat (Azuchi-Momoyama). Blender 5.x, headless:

    bin/gp generate generators/samurai_tenshu.py [-- --out fixtures/samurai_tenshu.blend] [--render out/_tenshu/t.png --no-save]

Needs the keep's tileable textures in out/textures: stone_wall, plaster_white, wood_dark, roof_tile (bin/gp textures specs/biomes.json).
Output: tenshu_LOD0/1/2 collections, one object per material: tenshu_LOD<n>_{Stone,Plaster,Wood,Tile,Gold}

It is raised IN PLACE from the castle (samurai_keep.py), so it shares the keep's frame: origin at the ground centre of the game's 20.4 m site,
+Z up, the entrance faces -Y, everything inside +-10 m. Metres. Ground = z 0; stone footings are sunk to -0.8.

  main tower   centred at (MX, MY) = (2.0, 0.6), offset right and back so the lower tower and the gate fit the site. A 7.8 m ishigaki
               (15.4 m at the foot, 11.8 m at the top, concave batter, long/short corner quoins). Five storeys of white plaster under five
               roofs: four hip skirts and an irimoya top whose gables face front and back (ridge along Y). Chidori gables (single, paired) and
               karahafu on every skirt; plastered (white) soffits; gold eave-end tiles on the two top roofs; a balcony with railing round the
               top storey; the top storey has black posts, gold bands and gold window frames; gold onigawara and shachihoko.
  ko-tenshu    the lower tower on the left: its own 3.8 m stone base, buried in the main base; two storeys; its skirt dies into the main
               base's stone and its upper roof (irimoya gable facing out, -X) runs into the main tower's first-storey wall under the main
               first-roof eave (>= 0.5 m clearance).
  gate         an uzumi-mon: a stone gate block in front of the main base with a passage and a studded door, a stepped stone ramp between
               cheek walls, a plastered watch-house (irimoya, small gold shachi) on the block whose back roof slope runs into the base face.

Every roof is a height field built at the identity transform and then moved (gen_common.build_roof's fascia re-applies the builder matrix, so
it is not used here). Joins: walls follow the roof surface minus a trough; dormer prisms run back until the main roof covers them or into the
wall above; clipped roofs end inside the wall or stone they meet.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gen_common import MB, TILE, sstep, Rz, tileable, render_preview  # noqa: E402

KINDS = ("Stone", "Plaster", "Wood", "Tile", "Gold")
MX, MY = 2.0, 0.6                    # main tower centre (the top ridge passes over it)
WB, WT, BH = 7.7, 5.9, 7.8           # main base half-width at the foot / at the top, height
KO = (-3.4, -0.9)                    # the lower tower's frame: x of the main first-storey wall, y of its axis
PI = math.pi


def T(x, y, z=0.0):
    return Matrix.Translation((x, y, z))


# ------------------------------------------------------------------------------------------------ materials
def make_materials():
    m = {"Stone": tileable("tenshu_stone", "stone_wall"), "Plaster": tileable("tenshu_plaster", "plaster_white"),
         "Wood": tileable("tenshu_wood", "wood_dark"), "Tile": tileable("tenshu_tile", "roof_tile")}
    g = bpy.data.materials.new("tenshu_gold")
    g.use_nodes = True
    b = g.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.86, 0.60, 0.14, 1)
    b.inputs["Metallic"].default_value = 0.92
    b.inputs["Roughness"].default_value = 0.34
    m["Gold"] = g
    return m


# ------------------------------------------------------------------------------------------------ level of detail, builders
class Lod:
    def __init__(self, lod):
        self.lod = lod
        self.step = (0.24, 0.5, 1.0)[lod]           # roof grid
        self.wall_n = (10, 5, 2)[lod]
        self.base_res = (1.0, 0.45, 0.22)[lod]
        self.quoins = lod == 0
        self.eave_sp = (0.4, 0.9, 0.0)[lod]          # round eave-end tiles
        self.hips = lod <= 1
        self.orn = lod <= 1
        self.shachi_n = (14, 7, 0)[lod]
        self.bars = (5, 0, 0)[lod]
        self.frames = lod <= 1
        self.kara_n = (12, 7, 4)[lod]
        self.rail = lod <= 1
        self.sama = lod == 0
        self.detail = lod == 0


class Kit:
    def __init__(self, lod):
        self.d = Lod(lod)
        self.m = {k: MB(k) for k in KINDS}
        self.st, self.pl, self.wd, self.tl, self.gd = (self.m[k] for k in KINDS)
        self.log, self._last = [], 0
        self.weld = []                   # roof-grid verts welded at the very end (deleting during the build would break placed())

    def tris(self):
        return sum(sum(len(f.verts) - 2 for f in mb.bm.faces) for mb in self.m.values())

    def mark(self, label):
        n = self.tris()
        self.log.append((label, n - self._last))
        self._last = n

    def placed(self, mat, fn, *a, **kw):
        """build at the identity, then move what was made by mat. (By membership, not by index: bmesh ops such as create_cone free
        verts internally and later verts reuse those slots, so 'everything after index n' is not 'everything made since'.)"""
        old = {k: set(mb.bm.verts) for k, mb in self.m.items()}
        res = fn(*a, **kw)
        for k, mb in self.m.items():
            new = [v for v in mb.bm.verts if v not in old[k]]
            if new:
                bmesh.ops.transform(mb.bm, matrix=mat, verts=new)
        return res

    def objects(self, lod, mats, coll):
        objs = []
        live = [v for v in self.weld if v.is_valid]
        if live:
            bmesh.ops.remove_doubles(self.tl.bm, verts=live, dist=1e-4)
        for kind, b in self.m.items():
            bad = [f for f in b.bm.faces if f.calc_area() < 1e-7]
            if bad:
                bmesh.ops.delete(b.bm, geom=bad, context="FACES_ONLY")
            loose = [v for v in b.bm.verts if not v.link_faces]
            if loose:
                bmesh.ops.delete(b.bm, geom=loose, context="VERTS")
            if len(b.bm.faces) == 0:
                b.bm.free()
                continue
            objs.append(b.to_object(f"tenshu_LOD{lod}_{kind}", mats[kind], coll))
        return objs


def face_to(mb, pts, want, smooth=False):
    """a polygon wound to face `want`"""
    vs = [mb.bm.verts.new(Vector(p)) for p in pts]
    try:
        f = mb.bm.faces.new(vs)
    except ValueError:
        return None
    f.normal_update()
    if f.normal.dot(Vector(want)) < 0:
        f.normal_flip()
    f.smooth = smooth
    return f


def prism_x(mb, x0, x1, prof):
    """a prism along X: prof = (y, z) points counter-clockwise as seen from +X"""
    n = len(prof)
    for i in range(n):
        (y0, z0), (y1, z1) = prof[i], prof[(i + 1) % n]
        face_to(mb, [(x0, y0, z0), (x1, y0, z0), (x1, y1, z1), (x0, y1, z1)], (0, z1 - z0, -(y1 - y0)))
    face_to(mb, [(x0, y, z) for y, z in prof], (-1, 0, 0))
    face_to(mb, [(x1, y, z) for y, z in prof], (1, 0, 0))


def lin(a, b, step):
    n = max(1, int(round(abs(b - a) / step)))
    return [a + (b - a) * i / n for i in range(n + 1)]


# ------------------------------------------------------------------------------------------------ roofs
class RoofF:
    """Height-field roof over the rectangle +-ex x +-ey (centred at the origin of its frame), curved (sori) slope, kick at the eave,
    upturned corners. ux, uy > 0: a hip skirt round the storey above (its flat top is hidden by that storey); uy = 0: a hip roof with a
    ridge along X; xg: an irimoya, gables at x = +-xg over the hip ends, the long slopes running on over them by ov."""

    def __init__(self, z0, ex, ey, ux, uy, H, lift=0.4, power=1.55, kick=0.26, xg=None, ov=0.35):
        self.z0, self.ex, self.ey, self.ux, self.uy, self.H = z0, ex, ey, ux, uy, H
        self.lift, self.power, self.kick, self.xg, self.ov = lift, power, kick, xg, ov
        if xg is not None:
            self.dxg = (xg - ux) / (ex - ux)
            self.y_g = ey * self.dxg                      # half-width of the gable at its foot
            self.y_e = ey * (xg + ov - ux) / (ex - ux)    # the overhang dies into the slope here

    def hh(self, x, y, inner=False):
        dx = 0.0 if inner else max(abs(x) - self.ux, 0.0) / (self.ex - self.ux)
        dy = max(abs(y) - self.uy, 0.0) / (self.ey - self.uy)
        d = min(max(dx, dy), 1.0)
        h = self.H * (1 - d) ** self.power + self.kick * sstep(0.80, 1.0, d) ** 2
        ax = dy >= dx
        edge = min(abs(x) / self.ex, 1.0) if ax else min(abs(y) / self.ey, 1.0)
        return h + self.lift * edge ** 5 * d ** 3, d, ax

    def z(self, x, y, inner=False):
        """the lower (hipped) surface; the walls under the roof follow this"""
        return self.z0 + self.hh(x, y, inner)[0]

    def top(self, x, y):
        """the visible surface (the gable roof over an irimoya's middle)"""
        if self.xg is not None and abs(x) <= self.xg:
            return self.z(x, y, True)
        return self.z(x, y)


class Rot90:
    """a roof built along X and turned to run along Y (local (u, v) -> world (-v, u))"""

    def __init__(self, r):
        self.r = r

    def z(self, x, y):
        return self.r.z(y, -x)

    def top(self, x, y):
        return self.r.top(y, -x)


def perimeter(ex, ey, step):
    pts = []
    cs = [(-ex, -ey), (ex, -ey), (ex, ey), (-ex, ey)]
    outs = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    for k in range(4):
        a, b = cs[k], cs[(k + 1) % 4]
        n = max(1, int(round(math.dist(a, b) / step)))
        for i in range(n):
            s = i / n
            pts.append((a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s, outs[k]))
    return pts


def shachi(K, x, y, zr, sx, s, gold_oni):
    """onigawara block + gold shachihoko at a ridge end (ridge along X), facing outward sx"""
    d = K.d
    oni = K.gd if gold_oni else K.tl
    oni.box((x, y, zr + 0.45 * s), (0.5 * s, 0.85 * s, 1.0 * s))
    K.tl.box((x + sx * 0.05 * s, y, zr + 0.10 * s), (0.85 * s, 0.95 * s, 0.25 * s))
    n = d.shachi_n
    if not n:
        return
    gd = K.gd
    pts, rad = [], []
    for k in range(n + 1):
        t = k / n
        pts.append((x + sx * s * (0.25 - 0.35 * math.sin(math.pi * t * 0.75) + 0.30 * t * t), y, zr + s * (1.0 + 1.55 * t)))
        rad.append(s * (0.13 + 0.22 * math.sin(math.pi * (t ** 0.8)) + (0.07 if t < 0.14 else 0.0)))
    gd.tube(pts, rad, 7 if d.lod == 0 else 5)
    for k in range(3, n, 2 if d.lod == 0 else 3):
        p = Vector(pts[k])
        gd.cone((p.x + sx * rad[k] * 1.1, y, p.z + 0.02 * s), (sx * 0.6, 0, 0.8), 0.11 * s, 0.01 * s, (0.32 + 0.1 * math.sin(k)) * s, 4)
    gd.box((pts[0][0] + sx * 0.2 * s, y, pts[0][2] - 0.02 * s), (0.55 * s, 0.46 * s, 0.42 * s))
    tt = Vector(pts[-1])
    gd.box((tt.x - sx * 0.1 * s, y, tt.z + 0.14 * s), (0.62 * s, 0.07 * s, 0.55 * s))


def roof(K, r, wall, keep=None, eave="Tile", gold_oni=False, finial=0.0, ridge_x=None, barge="Plaster"):
    """Tiled roof r in its own frame: tile surface, fascia (wood), plastered soffit back to the walls under it (wall = half sizes), round
    eave-end tiles, hip ridges; an irimoya adds its gable walls, the overhang over them, barge boards, descending ridges, the main ridge
    and finials. keep(x, y): which part to build (a clipped roof runs into a wall or stone and stops just inside it). Returns the ridge z."""
    d, tl = K.d, K.tl
    TT = TILE["Tile"]
    ok = (lambda x, y: True) if keep is None else keep
    allv = []

    def grid(xs, ys, inner, face_ok=None):
        V = {}

        def vert(i, j):
            if (i, j) not in V:
                x, y = xs[i], ys[j]
                h, dist, ax = r.hh(x, y, inner)
                v = tl.bm.verts.new(Vector((x, y, r.z0 + h)))
                allv.append(v)
                V[(i, j)] = (v, x, y, dist, ax)
            return V[(i, j)]

        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                ids = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
                pts = [(xs[a], ys[b]) for a, b in ids]
                if not any(ok(px, py) for px, py in pts):
                    continue
                if face_ok and not face_ok(pts):
                    continue
                if max(r.hh(px, py, inner)[1] for px, py in pts) < 1e-6:
                    continue
                vs = [vert(a, b) for a, b in ids]
                try:
                    f = tl.bm.faces.new([v[0] for v in vs])
                except ValueError:
                    continue
                f.smooth = True
                f[tl.cu] = 1
                for lp, v in zip(f.loops, vs):
                    _, x, y, dist, ax = v
                    if ax:
                        lp[tl.uvl].uv = (x / TT, (1 - dist) * (r.ey - r.uy) * 1.12 / TT)
                    else:
                        lp[tl.uvl].uv = (y / TT, (1 - dist) * (r.ex - r.ux) * 1.12 / TT)

    st = d.step
    if r.xg is None:
        grid(lin(-r.ex, r.ex, st), lin(-r.ey, r.ey, st), False)
    else:
        xg, ov = r.xg, r.ov
        xs = lin(-(xg + ov), -xg, st) + lin(-xg, xg, st)[1:] + lin(xg, xg + ov, st)[1:]
        ys = lin(-r.ey, -r.y_e, st) + lin(-r.y_e, r.y_e, st)[1:] + lin(r.y_e, r.ey, st)[1:]

        def over_ok(pts):                       # beyond the gable wall only where the long slope is above the hip end
            cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
            return abs(cx) <= xg or r.z(cx, cy) < r.z(cx, cy, True) - 0.01
        grid(xs, ys, True, over_ok)
        for sx in (-1, 1):
            xa = lin(xg, r.ex, st)
            grid(xa if sx > 0 else [-x for x in xa[::-1]], ys, False)
    K.weld.extend(allv)

    # fascia and soffit, both plastered (nurigome, as on a white castle)
    wx, wy = wall
    zin = r.z0 - 0.12
    per = perimeter(r.ex, r.ey, st)
    for k in range(len(per)):
        ax_, ay_, out = per[k]
        bx_, by_, _ = per[(k + 1) % len(per)]
        if not (ok(ax_, ay_) or ok(bx_, by_)):
            continue
        za, zb_ = r.z(ax_, ay_), r.z(bx_, by_)
        face_to(K.pl, [(ax_, ay_, za + 0.03), (bx_, by_, zb_ + 0.03), (bx_, by_, zb_ - 0.2), (ax_, ay_, za - 0.2)], (out[0], out[1], 0))
        face_to(K.pl, [(ax_, ay_, za - 0.2), (bx_, by_, zb_ - 0.2), (bx_ * wx / r.ex, by_ * wy / r.ey, zin), (ax_ * wx / r.ex, ay_ * wy / r.ey, zin)],
                (0, 0, -1))
    # round eave-end tiles
    if d.eave_sp:
        em = K.m[eave]
        for k, ((cx0, cy0), (cx1, cy1), (nx_, ny_)) in enumerate((((-r.ex, -r.ey), (r.ex, -r.ey), (0, -1)), ((r.ex, -r.ey), (r.ex, r.ey), (1, 0)),
                                                                 ((r.ex, r.ey), (-r.ex, r.ey), (0, 1)), ((-r.ex, r.ey), (-r.ex, -r.ey), (-1, 0)))):
            L = math.dist((cx0, cy0), (cx1, cy1))
            n = max(1, int(L / d.eave_sp))
            for i in range(n):
                s = (i + 0.5) / n
                x, y = cx0 + (cx1 - cx0) * s, cy0 + (cy1 - cy0) * s
                if not ok(x, y):
                    continue
                em.cylinder((x + nx_ * 0.04, y + ny_ * 0.04, r.z(x, y) - 0.03), (nx_ * 0.97, ny_ * 0.97, -0.25), 0.075, 0.2, 5)
    # hip ridges (sumi-mune) and their end tiles
    if d.hips:
        s0 = r.dxg if r.xg is not None else 0.0
        for sx in (-1, 1):
            for sy in (-1, 1):
                L = math.hypot(r.ex - r.ux, r.ey - r.uy) * (1 - s0)
                n = max(3, int(L / (0.4 if d.lod == 0 else 0.8)))
                pts = []
                for kk in range(n + 1):
                    s = s0 + (1 - s0) * kk / n
                    x, y = sx * (r.ux + (r.ex - r.ux) * s), sy * (r.uy + (r.ey - r.uy) * s)
                    if ok(x, y) or (pts and ok(*pts[-1][:2])):
                        pts.append((x, y, r.z(x, y) + 0.07))
                if len(pts) < 2:
                    continue
                if ok(sx * r.ex, sy * r.ey):                       # the hip runs on past the corner and turns up
                    pts.append((sx * (r.ex + 0.22), sy * (r.ey + 0.22), r.z(sx * r.ex, sy * r.ey) + 0.24))
                tl.tube(pts, [0.15] * (len(pts) - 1) + [0.12], 6 if d.lod == 0 else 4)
                if ok(sx * r.ex, sy * r.ey) and d.orn:
                    K.m[eave].box((sx * (r.ex + 0.27), sy * (r.ey + 0.27), r.z(sx * r.ex, sy * r.ey) + 0.34), (0.24, 0.24, 0.3), rz=PI / 4)
    if r.xg is None:
        return r.z0 + r.H

    # ---- irimoya: gable walls, overhang, barge boards, ridges, finials
    xg, ov, yg, ye = r.xg, r.ov, r.y_g, r.y_e
    zg = r.z(xg, 0.0)
    zr = r.z0 + r.H
    rows = [y for y in ys if abs(y) < yg - 1e-6]
    rows = [-yg] + rows + [yg]
    erows = [y for y in ys if abs(y) < ye - 1e-6]
    erows = [-ye] + erows + [ye]
    for sx in (-1, 1):
        if not ok(sx * xg, 0.0):
            continue
        x = sx * xg
        for y0, y1 in zip(rows[:-1], rows[1:]):
            t0, t1 = max(r.z(x, y0, True) - 0.02, zg - 0.02), max(r.z(x, y1, True) - 0.02, zg - 0.02)
            face_to(K.pl, [(x, y0, zg - 0.06), (x, y1, zg - 0.06), (x, y1, t1), (x, y0, t0)], (sx, 0, 0))
        if d.detail:
            K.wd.box((x + sx * 0.04, 0, zg + 0.12), (0.08, 2 * yg - 0.2, 0.14))
            for yy in (-yg * 0.45, yg * 0.45):
                zt = r.z(x, yy, True) - 0.08
                K.wd.box((x + sx * 0.04, yy, (zg + 0.2 + zt) / 2), (0.07, 0.1, max(0.05, zt - zg - 0.2)))
        xo = sx * (xg + ov)
        for y0, y1 in zip(rows[:-1], rows[1:]):              # the overhang's plastered underside
            face_to(K.pl, [(x, y0, r.z(x, y0, True) - 0.1), (xo, y0, r.z(xo, y0, True) - 0.1), (xo, y1, r.z(xo, y1, True) - 0.1),
                           (x, y1, r.z(x, y1, True) - 0.1)], (0, 0, -1))
        prev = None
        for y in erows:                                      # barge boards (hafu)
            p = (xo + sx * 0.03, y, r.z(xo, y, True) - 0.08)
            if prev:
                K.m[barge].box_along(prev, p, 0.09, 0.24)
            prev = p
        if d.orn:
            K.gd.box((xo + sx * 0.07, 0, zr - 0.42), (0.06, 0.55, 0.45))       # gegyo (gold) under the ridge
            xk = sx * (xg + ov * 0.45)                         # descending ridges (kudari-mune) along the barges
            for half in ([yy for yy in erows if yy <= 0][::-1], [yy for yy in erows if yy >= 0]):
                if len(half) > 1:
                    tl.tube([(xk, y, r.z(xk, y, True) + 0.07) for y in half], [0.13] * len(half), 6 if d.lod == 0 else 4)
    # main ridge: a stacked-tile ridge reaching down onto both slopes, a round cap on top
    xa, xb = ridge_x if ridge_x else (-(xg + ov + 0.12), xg + ov + 0.12)
    hw = 0.32
    zl = r.z(0.0, hw, True) - 0.04
    prism_x(tl, xa, xb, [(-hw, zl), (hw, zl), (hw, zr + 0.16), (0.18, zr + 0.3), (-0.18, zr + 0.3), (-hw, zr + 0.16)])
    if d.lod < 2:
        tl.cylinder(((xa + xb) / 2, 0, zr + 0.32), (1, 0, 0), 0.17, xb - xa, 8 if d.lod == 0 else 5)
    if finial and d.orn:
        for sx in (-1, 1):
            if ok(sx * (xg + ov), 0.0):
                shachi(K, sx * (xg + ov + 0.12), 0.0, zr + 0.25, sx, finial, gold_oni)
    return zr


# ------------------------------------------------------------------------------------------------ gables on the slopes
def ogee_outline(w, hg, kara, n):
    pts = []
    hw = w / 2
    for i in range(n + 1):
        s = abs(2 * i / n - 1)
        x = (2 * i / n - 1) * hw
        if kara:
            z = hg * (1 - (3 * (s ** 0.9) ** 2 - 2 * (s ** 0.9) ** 3)) + 0.12 * math.sin(math.pi * min(1, s * 1.15)) * (1 - s) * 2
        else:
            z = hg * (1 - s)
        pts.append((x, z))
    return pts


def dormer(K, rf, ang, f, along, w, hg, kara, upper):
    """chidori (straight) or kara (ogee) gable on face `ang` of roof rf: its wall stands f out from the centre at `along`; its roof prism runs
    back until the main roof covers it, or into the wall of the storey above (upper = that wall's distance from the centre)"""
    d = K.d
    R = Rz(ang).to_3x3()

    def P(a, b, z):
        v = R @ Vector((a, b, 0.0))
        return (v.x, v.y, z)

    gx, gy, _ = P(along, -f, 0)
    zb = rf.top(gx, gy) - 0.04
    n = d.kara_n if kara else 2
    out = ogee_outline(w, hg, kara, n)
    crest = zb + hg + 0.4
    yb = f
    while yb > upper - 0.15:
        yb -= 0.05
        px, py, _ = P(along, -yb, 0)
        if rf.top(px, py) > crest + 0.05:
            break
    depth = f - yb
    want = tuple(R @ Vector((0, -1, 0)))
    face_to(K.pl, [P(along + x, -f, zb + z) for x, z in out] + [P(along + w / 2, -f, zb - 0.25), P(along - w / 2, -f, zb - 0.25)], want)
    ov = 0.30
    offs = []
    for i, (x, z) in enumerate(out):
        x0, z0_ = out[max(i - 1, 0)]
        x1, z1_ = out[min(i + 1, len(out) - 1)]
        tx, tz = x1 - x0, z1_ - z0_
        L = math.hypot(tx, tz) or 1
        nx_, nz_ = -tz / L, tx / L
        if nz_ < 0:
            nx_, nz_ = -nx_, -nz_
        offs.append((x + nx_ * ov, z + nz_ * ov))
    for i in range(len(out) - 1):
        K.pl.box_along(P(along + out[i][0], -f - 0.08, zb + out[i][1] + 0.1), P(along + out[i + 1][0], -f - 0.08, zb + out[i + 1][1] + 0.1), 0.14, 0.3)
    TT = TILE["Tile"]
    u = 0.0
    y0, y1 = -f - 0.30, -f + depth
    for i in range(len(offs) - 1):
        L = math.hypot(offs[i + 1][0] - offs[i][0], offs[i + 1][1] - offs[i][1])
        p = [P(along + offs[i][0], y0, zb + offs[i][1] + 0.05), P(along + offs[i + 1][0], y0, zb + offs[i + 1][1] + 0.05),
             P(along + offs[i + 1][0], y1, zb + offs[i + 1][1] + 0.05), P(along + offs[i][0], y1, zb + offs[i][1] + 0.05)]
        K.tl.face(p, smooth=True, uvs=[(u / TT, 0), ((u + L) / TT, 0), ((u + L) / TT, (y1 - y0) / TT), (u / TT, (y1 - y0) / TT)])
        u += L
    zr = zb + out[len(out) // 2][1] + 0.16
    c = P(along, -f + depth / 2 - 0.1, zr + 0.05)
    K.tl.box(c, (0.36, depth + 0.3, 0.30), rz=ang)
    if d.orn:
        if kara:
            K.gd.box(P(along, -f - 0.2, zb + hg - 0.05), (0.34, 0.08, 0.3), rz=ang)          # gold kazari at the crown
        else:
            K.tl.box(P(along, -f - 0.28, zr + 0.12), (0.5, 0.3, 0.5), rz=ang)                # onigawara
            K.gd.box(P(along, -f - 0.2, zb + hg - 0.25), (0.26, 0.06, 0.24), rz=ang)         # gegyo
    return zb


# ------------------------------------------------------------------------------------------------ walls, windows
def walls_box(K, x0, x1, y0, y1, zb, rf, faces=("-x", "+x", "-y", "+y"), trough=0.06):
    """plaster walls of a rectangle from zb up to the roof over them (top edge follows rf.z minus a trough)"""
    n = K.d.wall_n
    for side in faces:
        if side in ("-y", "+y"):
            y = y0 if side == "-y" else y1
            line = [(x0 + (x1 - x0) * i / n, y) for i in range(n + 1)]
            want = (0, -1 if side == "-y" else 1, 0)
        else:
            x = x0 if side == "-x" else x1
            line = [(x, y0 + (y1 - y0) * i / n) for i in range(n + 1)]
            want = (-1 if side == "-x" else 1, 0, 0)
        top = [(px, py, rf.z(px, py) - trough) for px, py in line]
        face_to(K.pl, [(line[0][0], line[0][1], zb), (line[-1][0], line[-1][1], zb)] + top[::-1], want)


def rbox(mb, ang, c, size):
    p = Rz(ang) @ Vector(c)
    mb.box(tuple(p), size, rz=ang)


def window(K, ang, half, zc, along, w, h, gold=False):
    """a renji window on face `ang` (its wall `half` out from the centre): dark opening, plaster (or gold) surround, white bars"""
    d = K.d
    rbox(K.wd, ang, (along, -(half + 0.02), zc), (w, 0.08, h))
    if d.frames:
        fr = K.gd if gold else K.pl
        t = 0.13
        for sz in (-1, 1):
            rbox(fr, ang, (along, -(half + 0.07), zc + sz * (h / 2 + t / 2)), (w + 2 * t + 0.12, 0.16, t))
        for s in (-1, 1):
            rbox(fr, ang, (along + s * (w / 2 + t / 2), -(half + 0.07), zc), (t, 0.16, h))
    if not gold:
        for k in range(d.bars):
            rbox(K.pl, ang, (along - w / 2 + (k + 0.5) * w / d.bars, -(half + 0.08), zc), (0.06, 0.06, h))


def sama(K, ang, half, z, alongs):
    if not K.d.sama:
        return
    for i, a in enumerate(alongs):
        rbox(K.wd, ang, (a, -(half + 0.01), z), (0.2 if i % 2 else 0.17, 0.04, 0.2 if i % 2 else 0.24))


FACES = {0: "-y", 1: "+x", 2: "+y", 3: "-x"}


# ------------------------------------------------------------------------------------------------ stonework
def stone_block(K, x0, x1, y0, y1, h, b, sides, power=2.2, quoins=True):
    """a battered ishigaki block: top rectangle [x0,x1]x[y0,y1] at height h; each side in `sides` leans out by b at the foot along a concave
    curve (plumb at the top); other sides are buried in another block (not built). Footing sunk to -0.8. Long/short quoins on free corners."""
    st, d = K.st, K.d

    def edge(side, t):
        o = b * (1 - t) ** power if side in sides else 0.0
        return {"-x": x0 - o, "+x": x1 + o, "-y": y0 - o, "+y": y1 + o}[side]

    nt = max(3, int(round(h / 0.5 * d.base_res)))
    ts = [j / nt for j in range(nt + 1)]
    for side in sides:
        along_y = side in ("-x", "+x")
        span = (y1 - y0) if along_y else (x1 - x0)
        na = max(2, int(round(span / 0.5 * d.base_res)))
        out = Vector({"-x": (-1, 0, 0), "+x": (1, 0, 0), "-y": (0, -1, 0), "+y": (0, 1, 0)}[side])
        g = []
        for i in range(na + 1):
            a = i / na
            col = []
            for j, t in enumerate(ts):
                z = -0.8 if j == 0 else t * h
                if along_y:
                    lo, hi = edge("-y", t), edge("+y", t)
                    p = (edge(side, t), lo + (hi - lo) * a, z)
                else:
                    lo, hi = edge("-x", t), edge("+x", t)
                    p = (lo + (hi - lo) * a, edge(side, t), z)
                col.append(st.bm.verts.new(Vector(p)))
            g.append(col)
        for i in range(na):
            for j in range(nt):
                f = st.bm.faces.new((g[i][j], g[i + 1][j], g[i + 1][j + 1], g[i][j + 1]))
                f.normal_update()
                if f.normal.dot(out) < 0:
                    f.normal_flip()
                f.smooth = True
    st.face([(x0, y0, h), (x1, y0, h), (x1, y1, h), (x0, y1, h)])
    if not (quoins and d.quoins):
        return
    nc = max(4, int(round(h / 0.56)))
    ch = h / nc * 0.93
    for sx in (-1, 1):
        for sy in (-1, 1):
            xs_, ys_ = ("-x" if sx < 0 else "+x"), ("-y" if sy < 0 else "+y")
            if xs_ not in sides or ys_ not in sides:
                continue
            for k in range(nc):
                t = (k + 0.5) / nc
                z = t * h
                X, Y = edge(xs_, t), edge(ys_, t)
                alpha = math.atan(b * power * (1 - t) ** (power - 1) / h)
                l1, l2 = (1.3, 0.68) if k % 2 == 0 else (0.68, 1.3)
                st.box((X - sx * l1 / 2, Y + sy * 0.02, z), (l1, 0.46, ch), rx=sy * alpha)
                st.box((X + sx * 0.02, Y - sy * l2 / 2, z), (0.46, l2, ch), ry=-sx * alpha)


# ------------------------------------------------------------------------------------------------ the main tower (its own frame)
R1 = RoofF(11.7, 7.0, 6.7, 4.6, 4.35, 1.7, lift=0.45)
R2 = RoofF(15.5, 6.1, 5.85, 3.85, 3.65, 1.55, lift=0.42)
R3 = RoofF(19.0, 5.25, 5.05, 3.15, 3.0, 1.45, lift=0.38)
R4 = RoofF(22.4, 4.5, 4.35, 2.55, 2.5, 1.3, lift=0.35)
R5L = RoofF(26.3, 3.6, 3.65, 0.4, 0.0, 2.2, lift=0.35, xg=1.9, ov=0.35)       # built along X, turned to run along Y
R5 = Rot90(R5L)
DECK = 23.9                                                                   # top of the balcony deck
DX, DY = 2.95, 2.9                                                            # its half sizes
STOREYS = [  # hx, hy, wall foot, roof, window (zc, w, h), windows per face (front/back, sides)
    (5.4, 5.1, 7.7, R1, (9.9, 1.2, 1.1), ((-3.7, -1.25, 1.25, 3.7), (-3.4, -1.15, 1.15, 3.4))),
    (4.6, 4.35, 12.1, R2, (14.45, 1.05, 0.95), ((-3.3, 3.3), (-2.8, 2.8))),
    (3.85, 3.65, 16.1, R3, (18.0, 1.0, 0.9), ((-2.85, 2.85), (-2.6, 2.6))),
    (3.15, 3.0, 19.8, R4, (21.4, 0.8, 0.85), ((-2.5, 0.0, 2.5), (-2.2, 2.2))),
    (2.15, 2.1, DECK - 0.05, R5, (25.0, 0.85, 1.1), ((-0.95, 0.95), (-0.95, 0.95))),
]
DORMERS = [  # roof, face index (0 front, 1 +x, 2 back, 3 -x), f, along, w, hg, kara, upper
    (R1, 0, 5.65, 0.0, 4.6, 1.55, False, 4.35), (R1, 2, 5.65, 0.0, 4.6, 1.55, False, 4.35),
    (R1, 1, 5.95, 0.0, 3.6, 1.3, False, 4.6), (R1, 3, 5.95, 0.0, 3.6, 1.3, False, 4.6),
    (R2, 0, 4.75, 0.0, 3.4, 1.5, True, 3.65), (R2, 2, 4.75, 0.0, 3.4, 1.5, True, 3.65),
    (R2, 1, 5.0, 0.0, 3.0, 1.2, False, 3.85), (R2, 3, 5.0, 0.0, 3.0, 1.2, False, 3.85),
    (R3, 0, 4.05, -1.6, 2.6, 1.2, False, 3.0), (R3, 0, 4.05, 1.6, 2.6, 1.2, False, 3.0),
    (R3, 2, 4.05, -1.6, 2.6, 1.2, False, 3.0), (R3, 2, 4.05, 1.6, 2.6, 1.2, False, 3.0),
    (R3, 1, 4.2, 0.0, 2.8, 1.3, True, 3.15), (R3, 3, 4.2, 0.0, 2.8, 1.3, True, 3.15),
]


def main_tower(K):
    d = K.d
    stone_block(K, -WT, WT, -WT, WT, BH, WB - WT, ("-x", "+x", "-y", "+y"))
    K.mark("main base")
    for i, (hx, hy, zb, rf, (zc, w, h), (fb, sd)) in enumerate(STOREYS):
        walls_box(K, -hx, hx, -hy, hy, zb, rf)
        top = i == 4
        for k in range(4):
            ang = k * PI / 2
            half = hy if k % 2 == 0 else hx
            alongs = fb if k % 2 == 0 else sd
            if i == 0 and k == 3:
                alongs = (-2.6, -4.0)                     # the -x face: only behind the lower tower's roof
            for a in alongs:
                window(K, ang, half, zc, a, w, h, gold=top)
        if i == 0:
            for k in (0, 1, 2):
                half = hy if k % 2 == 0 else hx
                span = hx if k % 2 == 0 else hy
                sama(K, k * PI / 2, half, 8.35, [a for a in lin(-span + 0.5, span - 0.5, 0.95)])
    K.mark("walls, windows")
    for rf, wall, eave in ((R1, (5.4, 5.1), "Tile"), (R2, (4.6, 4.35), "Tile"), (R3, (3.85, 3.65), "Tile"), (R4, (3.15, 3.0), "Gold")):
        roof(K, rf, wall, eave=eave)
    K.mark("skirt roofs")
    zr = K.placed(Matrix.Rotation(PI / 2, 4, "Z"), roof, K, R5L, (2.1, 2.15), eave="Gold", finial=0.85, barge="Gold")
    K.mark("top roof")
    for rf, k, f, along, w, hg, kara, upper in DORMERS:
        dormer(K, rf, k * PI / 2, f, along, w, hg, kara, upper)
    K.mark("gables")
    balcony(K)
    K.mark("balcony")
    return zr


def balcony(K):
    d, wd, gd = K.d, K.wd, K.gd
    wd.box((0, 0, DECK - 0.075), (2 * DX, 2 * DY, 0.15))
    # posts under the deck, down to the roof below (clear of the karahafu at front and back)
    for x, y in [(sx * (DX - 0.12), sy * (DY - 0.12)) for sx in (-1, 1) for sy in (-1, 1)] + \
                [(sx * 1.95, sy * (DY - 0.12)) for sx in (-1, 1) for sy in (-1, 1)] + [(sx * (DX - 0.12), 0.0) for sx in (-1, 1)]:
        zb = R4.z(x, y) - 0.06
        wd.box((x, y, (zb + DECK - 0.15) / 2), (0.16, 0.16, DECK - 0.15 - zb))
    # top storey: black corner posts, gold bands
    hx, hy = STOREYS[4][0], STOREYS[4][1]
    for sx in (-1, 1):
        for sy in (-1, 1):
            wd.box((sx * hx, sy * hy, (DECK + 26.2) / 2), (0.2, 0.2, 26.2 - DECK))
    for z, hgt in ((26.02, 0.13), (DECK + 0.1, 0.12)):
        gd.box((0, -(hy + 0.03), z), (2 * hx + 0.1, 0.06, hgt))
        gd.box((0, hy + 0.03, z), (2 * hx + 0.1, 0.06, hgt))
        gd.box((-(hx + 0.03), 0, z), (0.06, 2 * hy + 0.1, hgt))
        gd.box((hx + 0.03, 0, z), (0.06, 2 * hy + 0.1, hgt))
    if not d.rail:
        return
    rh = 0.78
    cs = [(-DX + 0.06, -DY + 0.06), (DX - 0.06, -DY + 0.06), (DX - 0.06, DY - 0.06), (-DX + 0.06, DY - 0.06)]
    for k in range(4):
        a, b = Vector(cs[k] + (DECK,)), Vector(cs[(k + 1) % 4] + (DECK,))
        n = max(2, int(round((b - a).length / 0.72)))
        for i in range(n):
            p = a.lerp(b, i / n)
            wd.box((p.x, p.y, DECK + rh / 2), (0.08, 0.08, rh))
            if d.detail:
                gd.box((p.x, p.y, DECK + rh + 0.05), (0.11, 0.11, 0.1))
        wd.box_along((a.x, a.y, DECK + rh), (b.x, b.y, DECK + rh), 0.1, 0.07)
        wd.box_along((a.x, a.y, DECK + 0.42), (b.x, b.y, DECK + 0.42), 0.06, 0.05)
        wd.box_along((a.x, a.y, DECK + 0.08), (b.x, b.y, DECK + 0.08), 0.07, 0.06)
    for x, y in cs:
        gd.cone((x, y, DECK + rh + 0.12), (0, 0, 1), 0.08, 0.01, 0.2, 6)          # giboshi on the corner posts


# ------------------------------------------------------------------------------------------------ the lower tower (ko-tenshu), its own frame
KR1 = RoofF(6.4, 6.1, 3.4, 4.7, 2.0, 0.8, lift=0.3)
KR2 = RoofF(9.0, 5.7, 3.0, 2.7, 0.0, 1.5, lift=0.3, xg=3.9, ov=0.3)


def ko_tenshu(K):
    walls_box(K, -5.2, 0.2, -2.5, 2.5, 3.7, KR1, ("-x", "-y", "+y"))
    walls_box(K, -4.7, 0.3, -2.0, 2.0, 6.8, KR2, ("-x", "-y", "+y"))
    for ang in (0.0, PI):
        sg = 1 if ang == 0 else -1
        for a in (-4.0, -2.0):
            window(K, ang, 2.5, 5.0, sg * a, 1.0, 1.0)
        for a in (-4.1, -0.9):
            window(K, ang, 2.0, 8.15, sg * a, 0.75, 0.7)
        sama(K, ang, 2.5, 4.3, [sg * a for a in lin(-4.6, -0.9, 0.95)])
    for a in (-1.1, 1.1):
        window(K, 3 * PI / 2, 5.2, 5.0, a, 1.0, 1.0)
    window(K, 3 * PI / 2, 4.7, 8.15, 0.0, 0.8, 0.7)
    K.mark("ko walls")
    roof(K, KR1, (5.2, 2.5), keep=lambda x, y: x <= -0.55)
    zr = roof(K, KR2, (4.7, 2.0), keep=lambda x, y: x <= 0.0, finial=0.6, ridge_x=(-(KR2.xg + KR2.ov + 0.12), 0.3))
    dormer(K, KR1, 0.0, 2.95, -2.6, 2.0, 0.9, False, 2.0)
    K.mark("ko roofs")
    return zr


# ------------------------------------------------------------------------------------------------ the gate
GY0, GY1, GH = -8.35, -5.3, 3.6            # gate block front, back (buried), height
GX = 2.45
DOOR = (1.1, 0.9, 3.0)                     # passage half-width, threshold, head
GR = RoofF(5.9, 2.95, 2.15, 0.8, 0.0, 1.25, lift=0.3, xg=1.75, ov=0.3)
GRY = -6.65                                # the watch-house roof's axis


def gate(K):
    d, st, wd = K.d, K.st, K.wd
    b, p = 0.35, 1.6
    stone_block(K, -GX, GX, GY0, GY1, GH, b, ("-x", "+x"), power=p, quoins=False)
    nt = max(3, int(round(GH / 0.5 * d.base_res)))
    hw, z0, z1 = DOOR
    for sx in (-1, 1):                     # front face (plumb), around the passage
        for j in range(nt):
            ta, tb = j / nt, (j + 1) / nt
            za, zb_ = (-0.8 if j == 0 else ta * GH), tb * GH
            xa, xb = sx * (GX + b * (1 - ta) ** p), sx * (GX + b * (1 - tb) ** p)
            face_to(st, [(xa, GY0, za), (sx * hw, GY0, za), (sx * hw, GY0, zb_), (xb, GY0, zb_)], (0, -1, 0))
    face_to(st, [(-hw, GY0, z1), (hw, GY0, z1), (hw, GY0, GH), (-hw, GY0, GH)], (0, -1, 0))
    face_to(st, [(-hw, GY0, -0.8), (hw, GY0, -0.8), (hw, GY0, z0), (-hw, GY0, z0)], (0, -1, 0))
    yd = GY0 + 0.75
    for sx in (-1, 1):
        face_to(st, [(sx * hw, GY0, z0), (sx * hw, yd, z0), (sx * hw, yd, z1), (sx * hw, GY0, z1)], (-sx, 0, 0))
    face_to(st, [(-hw, GY0, z1), (hw, GY0, z1), (hw, yd, z1), (-hw, yd, z1)], (0, 0, -1))
    # door leaves, frame, studs; lintel and jamb stones round the mouth
    wd.box((0, yd - 0.04, (z0 + z1) / 2), (2 * hw, 0.1, z1 - z0))
    wd.box((0, yd - 0.1, (z0 + z1) / 2), (0.08, 0.06, z1 - z0))
    if d.detail:
        for bx in (-0.7, -0.35, 0.35, 0.7):
            for bz in (1.3, 1.9, 2.5):
                K.gd.box((bx, yd - 0.11, bz), (0.07, 0.04, 0.07))
    st.box((0, GY0 - 0.12, z1 + 0.27), (2 * hw + 1.0, 0.3, 0.54))
    for sx in (-1, 1):
        st.box((sx * (hw + 0.24), GY0 - 0.1, (z0 + z1) / 2), (0.48, 0.26, z1 - z0))
    # stepped ramp between cheek walls
    for k in range(4):
        zt = 0.225 * (k + 1)
        yf = -9.9 + 0.36 * k
        st.box((0, (yf + yd) / 2, (zt - 0.3) / 2), (2 * hw + 0.1, yd - yf, zt + 0.3))
    for sx in (-1, 1):
        xa, xb = sx * (hw + 0.05), sx * (hw + 1.0)
        prof = [(-9.98, -0.3), (GY0 + 0.1, -0.3), (GY0 + 0.1, 2.05), (GY0 - 0.25, 2.05), (-9.98, 0.8)]
        prism_x(st, min(xa, xb), max(xa, xb), prof)
    K.mark("gate stone")
    # the watch-house on the block (its back wall and roof run into the base face)
    K.placed(T(0, GRY), gatehouse, K)
    K.mark("gatehouse")


def gatehouse(K):
    walls_box(K, -2.2, 2.2, -1.45, 1.45, GH - 0.05, GR, ("-x", "+x", "-y"))
    for a in (-1.2, 1.2):
        window(K, 0.0, 1.45, 4.75, a, 0.9, 0.75)
    sama(K, 0.0, 1.45, 4.0, [-0.3, 0.3])
    roof(K, GR, (2.2, 1.45), keep=lambda x, y: y <= (-5.33 - GRY), finial=0.45)


# ------------------------------------------------------------------------------------------------ assemble
def build(lod, mats, coll):
    K = Kit(lod)
    zr = K.placed(T(MX, MY), main_tower, K)
    # lower tower: stone base buried in the main base, then the tower in its own frame
    stone_block(K, -8.9, -3.0, -3.7, 1.9, 3.8, 0.9, ("-x", "-y", "+y"))
    K.mark("ko base")
    K.placed(T(*KO), ko_tenshu, K)
    gate(K)
    objs = K.objects(lod, mats, coll)
    return objs, K.log, zr


def report(objs):
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    gold_top, tile_top = (-1e9, None), (-1e9, None)
    for o in objs:
        for v in o.data.vertices:
            p = v.co
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
            if o.name.endswith("_Gold") and p.z > gold_top[0]:
                gold_top = (p.z, (round(p.x, 2), round(p.y, 2)))
            if o.name.endswith("_Tile") and abs(p.x - MX) < 0.6 and abs(p.y - MY) < 2.6 and p.z > tile_top[0]:
                tile_top = (p.z, (round(p.x, 2), round(p.y, 2)))
    print(f"LOD0 bounds x {lo.x:.2f}..{hi.x:.2f}  y {lo.y:.2f}..{hi.y:.2f}  z {lo.z:.2f}..{hi.z:.2f}")
    zr = R5L.z0 + R5L.H
    print(f"top: ridge line {zr:.2f} m over ({MX}, {MY}), ridge cap (round tile) {zr + 0.32 + 0.17:.2f} m, onigawara {tile_top[0]:.2f} m at {tile_top[1]}, "
          f"highest gold (shachihoko tip) {gold_top[0]:.2f} m at {gold_top[1]}")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "fixtures", "samurai_tenshu.blend")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    allobjs = {}
    for lod in (0, 1, 2):
        coll = bpy.data.collections.new(f"tenshu_LOD{lod}")
        bpy.context.scene.collection.children.link(coll)
        objs, log, zr = build(lod, mats, coll)
        allobjs[lod] = objs
        tris = 0
        for o in objs:
            o.data.calc_loop_triangles()
            tris += len(o.data.loop_triangles)
        print(f"LOD{lod}: {tris:,} tris in {len(objs)} objects; top ridge line z {zr:.2f}")
        print("   " + ", ".join(f"{k} {v:,}" for k, v in log))
    report(allobjs[0])
    if "--render" in argv:
        rp = argv[argv.index("--render") + 1]
        os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
        show = int(argv[argv.index("--lod") + 1]) if "--lod" in argv else 0
        for lod in (0, 1, 2):
            for o in allobjs[lod]:
                o.hide_render = lod != show
        tgt = (MX - 0.5, MY, 13.0)
        az, el, dist = math.radians(25), math.radians(45), 40.0
        rts_t = (1.0, -1.0, 16.0)
        rts = (rts_t[0] + dist * math.cos(el) * math.sin(az), rts_t[1] - dist * math.cos(el) * math.cos(az), rts_t[2] + dist * math.sin(el))
        views = [("front", (30, -50, 15), tgt, 40), ("back", (-26, 50, 15), tgt, 40), ("side", (-55, -8, 13), (0, 0, 12), 40),
                 ("top", (MX, MY - 2.0, 75), (MX, MY, 0), 38), ("rts", rts, rts_t, 30),
                 ("gate", (9, -24, 5.5), (0, -8, 3.6), 40), ("junction", (-17, -17, 13), (-4, -1, 9.5), 45),
                 ("topback", (-10, 16, 31), (MX, MY, 25.5), 40), ("koback", (-15, 14, 14), (-5, -1, 9.5), 40)]
        only = argv[argv.index("--views") + 1].split(",") if "--views" in argv else None
        if only:
            views = [v for v in views if v[0] in only]
        render_preview(rp, views, ground_z=0.0)
    if "--no-save" not in argv:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)
