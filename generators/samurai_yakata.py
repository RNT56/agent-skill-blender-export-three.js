"""The homestead (yakata) a house of Samurai Vale begins with: a Kamakura warrior's fortified manor (bushi no yakata). Blender 5.x, headless:

    bin/gp generate generators/samurai_yakata.py [-- --out fixtures/samurai_yakata.blend] [--render out/_yakata.png --no-save] [--lod 1]

Needs:  out/textures/{stone_nozura,plaster_shikkui,timber_dark,wood_shingle,thatch_kaya}_*  (bin/gp textures specs/arch_textures.json) and
        out/textures/meadow_albedo.jpg (bin/gp textures specs/biomes.json); the grass albedo is derived from it here (yakata_grass_albedo.jpg).
Output: yakata_LOD0/1/2 collections, one object per material: yakata_LOD<n>_{Stone,Plaster,Wood,Shingle,Thatch,Grass}

It is upgraded IN PLACE into the castle keep (samurai_keep.py), so it shares the keep's frame: origin at the ground centre of the 20.4 m footprint, +Z up,
the gate (front) faces -Y. Everything stays inside +-10.1 m. y = 0 is the levelled ground: nothing stands ON it, everything is rooted in it.

  the earthwork  a low bank (dorui, ~1.2 m) following a rounded, wobbling square, its grass running down into a shallow ditch and up over a low outer
                 lip; the bank is cut at the gate (stone-faced ends) and the lip opens for an earth causeway (+-2.05 m: the keep site's porch width)
  the fence      vertical boards with gaps on posts and rails along the crest (itabei), its foot sunk in the bank
  the gate       yagura-mon: two pillars and two back posts, leaves swung open inward, a skirt roof under a railed watch platform, a boarded upper room
                 with lattice windows under an irimoya roof of shingles (top ~8.5 m)
  the hall       shuden: raised floor on posts and stones, an engawa on three sides with a railing and steps, shitomi shutters hooked open, sliding doors,
                 plaster friezes; an irimoya roof of shingles (roofs.shingle_roof for the hips + the gables here), crossed logs along the ridge
  the yard       a plastered kura with its door and a little pent, a thatched servants' shed and stall, a well under a small roof, a woodpile, barrels,
                 bales, shrubs inside the bank and two trees on the back corners
"""
import math
import os
import random
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_common  # noqa: E402
from gen_common import MB, ROOT, TEXDIR, Roof, render_preview, tileable, railing, C  # noqa: E402
from wall_kit import Kit  # noqa: E402
from roofs import shingle_roof, thatch_roof, rock  # noqa: E402
from vale_buildings import barrel, bale, woodpile, jar  # noqa: E402

gen_common.TILE["Grass"] = 2.4
TILE = gen_common.TILE
# kind -> (builder kind = texel density, texture set). Six materials; the kit helpers' other kinds are routed to these (ALIAS)
SURF = {"Stone": ("Nozura", "stone_nozura"), "Plaster": ("Shikkui", "plaster_shikkui"), "Wood": ("Timber", "timber_dark"),
        "Shingle": ("Shingle", "wood_shingle"), "Thatch": ("Kaya", "thatch_kaya"), "Grass": ("Grass", None)}
ALIAS = {"WoodL": "Wood", "Paper": "Plaster", "Tile": "Stone", "Earth": "Thatch"}
SINK = 0.24
HALF = 10.1                      # nothing reaches further out than this (the game footprint is 20.4 m)
GATE_HALF = 2.05                 # the bank is cut and the lip opens this far either side of the gate axis
HY0 = 2.45                       # the hall's centre (y)


# ------------------------------------------------------------------------------------------------------------------ materials
def grass_material():
    """grass and leaves: the meadow albedo, calmed (the biome texture is made for the terrain shader, which tints it), no normal / ORM maps"""
    src = bpy.data.images.load(os.path.join(TEXDIR, "meadow_albedo.jpg"))
    w, h = src.size
    px = np.empty(w * h * 4, np.float32)
    src.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    rgb = px[:, :3]
    lum = rgb @ np.array([0.3, 0.59, 0.11], np.float32)
    rgb = lum[:, None] + (rgb - lum[:, None]) * 0.5
    rgb *= np.array([0.86, 0.92, 0.66], np.float32)
    px[:, :3] = np.clip(rgb, 0, 1)
    out = os.path.join(TEXDIR, "yakata_grass_albedo.jpg")
    im = bpy.data.images.new("yakata_grass_tmp", w, h)
    im.pixels.foreach_set(px.ravel())
    im.filepath_raw = out
    im.file_format = "JPEG"
    im.save()
    bpy.data.images.remove(im)
    bpy.data.images.remove(src)
    a = bpy.data.images.load(out)
    a.name = "yakata_grass_albedo.jpg"
    a.colorspace_settings.name = "sRGB"
    m = C.pbr_material("yk_grass", {"albedo": a})
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.94
    return m


def make_materials():
    m = {k: tileable(f"yk_{k.lower()}", v[1]) for k, v in SURF.items() if v[1]}
    m["Grass"] = grass_material()
    return m


# ------------------------------------------------------------------------------------------------------------------ the kit
class Y(Kit):
    """the six one-material builders; the vale helpers' other kinds go to one of them. Kit's game-frame calls (box, rod, beam, log: x, y up, z = -Y)
    still work; most of this file uses Blender coordinates (aab, post, stone)."""

    def __init__(self, lod, seed):
        self.lod, self.r = lod, random.Random(seed)
        self.m = {k: MB(v[0]) for k, v in SURF.items()}
        for a, k in ALIAS.items():
            self.m[a] = self.m[k]

    def builders(self):
        return [self.m[k] for k in SURF]

    def at(self, m):
        k = self

        class _Ctx:
            def __enter__(s):
                for mb in k.builders():
                    mb.push(m)

            def __exit__(s, *a):
                for mb in k.builders():
                    mb.pop()
        return _Ctx()

    def box(self, kind, w, h, d, x, y, z, rz=0.0, rx=0.0, ry=0.0):
        """(game frame) whatever is tall and starts at the ground is rooted in it"""
        if abs(y) < 1e-6 and h >= 0.3 and not (rz or rx or ry):
            y, h = y - SINK, h + SINK
        super().box(kind, w, h, d, x, y, z, rz=rz, rx=rx, ry=ry)

    def aab(self, kind, x0, x1, y0, y1, z0, z1):
        """an axis-aligned box by its bounds (Blender frame); one that starts at the ground is sunk into it"""
        if abs(z0) < 1e-6 and z1 > 0.3:
            z0 = -SINK
        self.m[kind].box(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)))

    def post(self, kind, x, y, z0, z1, s, rz=0.0):
        self.m[kind].box((x, y, (z0 + z1) / 2), (s, s, z1 - z0), rz=rz)

    def stone(self, x, y, top, s, flat=0.6, kind="Stone"):
        """a field stone whose top is at `top` (Blender frame; roofs.rock's top is y + 1.5 s flat)"""
        rock(self, x, top - 1.5 * s * flat, -y, s, kind=kind, flat=flat)

    def blob(self, kind, c, rad, subdiv=1, lump=0.0, seed=0):
        """a lumpy ellipsoid (foliage, shrubs)"""
        mb = self.m[kind]
        r = bmesh.ops.create_icosphere(mb.bm, subdivisions=subdiv, radius=1.0)
        ph = [seed * 1.7 + k for k in (0.3, 1.1, 2.3)]
        for v in r["verts"]:
            p = v.co
            if lump:
                p *= 1.0 + lump * (math.sin(3.1 * p.x + ph[0]) * math.sin(2.7 * p.y + ph[1]) + 0.6 * math.sin(4.3 * p.z + ph[2]))
            v.co = mb.M @ Vector((c[0] + p.x * rad[0], c[1] + p.y * rad[1], c[2] + p.z * rad[2]))
            for f in v.link_faces:
                f.smooth = True

    def objects(self, name, mats, coll):
        out = []
        for kind in SURF:
            mb = self.m[kind]
            if len(mb.bm.faces):
                out.append(mb.to_object(f"{name}_LOD{self.lod}_{kind}", mats[kind], coll))
            else:
                mb.bm.free()
        return out


def T(x, y, z=0.0):
    return Matrix.Translation((x, y, z))


def Rz(a):
    return Matrix.Rotation(a, 4, "Z")


def face_up(mb, pts, want):
    """a polygon (Blender points in the builder's frame) wound to face `want`"""
    vs = [mb.bm.verts.new(mb.M @ Vector(p)) for p in pts]
    try:
        f = mb.bm.faces.new(vs)
    except ValueError:
        return None
    f.normal_update()
    if f.normal.dot(mb.M.to_3x3() @ Vector(want)) < 0:
        f.normal_flip()
    return f


# ------------------------------------------------------------------------------------------------------------------ the earthwork's line
A_RING, Q_RING = 7.25, 5.0


def ring_r(th):
    c, s = abs(math.cos(th)), abs(math.sin(th))
    base = A_RING / (c ** Q_RING + s ** Q_RING) ** (1 / Q_RING)
    return base + 0.13 * math.sin(3 * th + 0.7) + 0.08 * math.sin(5 * th + 2.1) + 0.05 * math.sin(9 * th + 0.3)


class Ring:
    """the crest line of the bank: a rounded square that wobbles, by arc length s from the gate axis (front, -Y) round anticlockwise"""

    def __init__(self):
        n = 4096
        self.pts = []
        for i in range(n + 1):
            th = -math.pi / 2 + 2 * math.pi * i / n
            rr = ring_r(th)
            self.pts.append((rr * math.cos(th), rr * math.sin(th)))
        self.cum = [0.0]
        for i in range(1, len(self.pts)):
            self.cum.append(self.cum[-1] + math.dist(self.pts[i], self.pts[i - 1]))
        self.L = self.cum[-1]
        self.s0 = self._cross(GATE_HALF, first=True)
        self.s1 = self._cross(-GATE_HALF, first=False)

    def p(self, s):
        s = min(max(s, 0.0), self.L)
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        t = (s - self.cum[lo]) / max(self.cum[hi] - self.cum[lo], 1e-9)
        a, b = self.pts[lo], self.pts[hi]
        return Vector((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 0.0))

    def frame(self, s):
        """point, outward normal, tangent"""
        d = 0.3
        t = (self.p(min(s + d, self.L)) - self.p(max(s - d, 0.0))).normalized()
        return self.p(s), Vector((t.y, -t.x, 0.0)), t

    def _cross(self, x, first):
        """the arc length where the line crosses x near the gate"""
        if first:
            lo, hi = 0.0, 4.0
            f = lambda s: self.p(s).x - x
        else:
            lo, hi = self.L - 4.0, self.L
            f = lambda s: self.p(s).x - x
        for _ in range(50):
            mid = (lo + hi) / 2
            if f(mid) < 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2


def hs(s):
    """the bank is not ruled: its height swells and sinks along its length"""
    return 1.1 * (1 + 0.07 * math.sin(s * 0.83 + 0.4) + 0.04 * math.sin(s * 2.3 + 1.3))


# the bank's section: (offset outward from the crest line, height); heights above 0 are scaled by hs(s). The ditch bottom (-0.35) lies under the game's ground
BANK = [(-1.22, -0.3), (-1.05, 0.03), (-0.86, 0.34), (-0.64, 0.66), (-0.42, 0.88), (-0.18, 1.0), (0.08, 1.02), (0.32, 0.9), (0.55, 0.64),
        (0.78, 0.32), (0.98, 0.08), (1.14, -0.07)]
LIP = [(1.14, -0.07), (1.3, 0.05), (1.5, 0.17), (1.72, 0.23), (1.95, 0.19), (2.2, 0.1), (2.42, 0.02), (2.62, -0.1)]
BANK_LOD = (list(range(12)), [0, 1, 3, 5, 6, 7, 9, 10, 11], [0, 2, 5, 7, 10, 11])
LIP_LOD = (list(range(8)), [0, 1, 3, 5, 7], [0, 3, 7])


def prof_z(prof, off):
    for (a, za), (b, zb) in zip(prof[:-1], prof[1:]):
        if a <= off <= b:
            return za + (zb - za) * (off - a) / (b - a)
    return prof[-1][1]


def crest_z(s, off=-0.05):
    z = prof_z(BANK, off)
    return z * hs(s) if z > 0 else z


def section_pt(R, s, off, z, taper=1.0):
    p, n, _ = R.frame(s)
    if z > 0:
        z = z * hs(s) * taper - 0.08 * (1 - taper)
    return p + n * off + Vector((0, 0, z))


def strip(K, R, prof, idx, s_list, kind="Grass", taper=None):
    """a smooth surface swept along the crest line through the section points"""
    mb = K.m[kind]
    rows = []
    for s in s_list:
        tp = taper(s) if taper else 1.0
        rows.append([mb.bm.verts.new(mb.M @ section_pt(R, s, prof[j][0], prof[j][1], tp)) for j in idx])
    for i in range(len(rows) - 1):
        for j in range(len(idx) - 1):
            try:
                f = mb.bm.faces.new((rows[i][j], rows[i + 1][j], rows[i + 1][j + 1], rows[i][j + 1]))
            except ValueError:
                continue
            f.normal_update()
            if f.normal.z < 0:
                f.normal_flip()
            f.smooth = True
    return rows


def earthwork(K, R):
    lod, r = K.lod, K.r
    du = (0.45, 1.1, 2.6)[lod]
    n = max(4, int(round((R.s1 - R.s0) / du)))
    ss = [R.s0 + (R.s1 - R.s0) * i / n for i in range(n + 1)]
    strip(K, R, BANK, BANK_LOD[lod], ss)
    # the cut ends of the bank at the gate: faced with stone
    for s, want in ((R.s0, -1), (R.s1, 1)):
        _, _, t = R.frame(s)
        face_up(K.m["Stone"], [tuple(section_pt(R, s, BANK[j][0], BANK[j][1])) for j in BANK_LOD[lod]], tuple(t * want))
        if lod < 2:
            p, nrm, _ = R.frame(s)
            k = 0
            for zrow, offs in ((0.08, (-0.85, -0.45, -0.05, 0.35, 0.72)), (0.45, (-0.6, -0.2, 0.2, 0.52)), (0.8, (-0.38, 0.0, 0.3))):
                for off in offs:
                    if lod == 1 and k % 2:
                        k += 1
                        continue
                    k += 1
                    top = min(crest_z(s, off), zrow + 0.42)
                    c = p + nrm * (off + r.uniform(-0.05, 0.05)) + t * (want * 0.12)
                    K.stone(c.x, c.y, top, r.uniform(0.24, 0.31), flat=0.85)
    # the outer lip of the ditch, open for the causeway: it dives into the ground over its last metre
    ml = (R.s1 - R.s0)

    def taper(s):
        d = min(s - R.s0, R.s1 - s)
        return gen_common.sstep(0.0, 1.0, d)
    strip(K, R, LIP, LIP_LOD[lod], [R.s0 - 0.35 + (ml + 0.7) * i / n for i in range(n + 1)], taper=lambda s: taper(s))
    if lod == 2:
        return
    # stones at the corners, half in the earth at the foot of the bank and on the lip, and a few strewn along the ditch
    for th in (math.pi / 4, 3 * math.pi / 4, 5 * math.pi / 4, 7 * math.pi / 4):
        best = min(range(0, 4097, 8), key=lambda i: abs(math.atan2(R.pts[i][1], R.pts[i][0]) % (2 * math.pi) - th % (2 * math.pi)))
        s_c = R.cum[best]
        for i in range(7 if lod == 0 else 4):
            s = s_c + r.uniform(-1.1, 1.1)
            off = r.choice((0.84, 0.96, 1.08, -1.0, 0.7, 1.45))
            p, nrm, _ = R.frame(s)
            c = p + nrm * off
            K.stone(c.x, c.y, max(0.12, crest_z(s, off) + r.uniform(0.05, 0.2)), r.uniform(0.26, 0.46), flat=0.7)
    if lod == 0:
        for i in range(14):
            s = R.s0 + 1.5 + (R.s1 - R.s0 - 3.0) * r.random()
            p, nrm, _ = R.frame(s)
            c = p + nrm * r.uniform(1.0, 1.25)
            K.stone(c.x, c.y, r.uniform(0.04, 0.12), r.uniform(0.12, 0.22), flat=0.6)


def fence(K, R):
    """itabei along the crest: posts, two rails on the yard side, upright boards with gaps on the outside; everything sunk in the bank"""
    lod, r = K.lod, K.r
    wd = K.m["Wood"]
    a, b = R.s0 + 0.14, R.s1 - 0.14
    npost = max(2, int(round((b - a) / 1.75)))
    S = [a + (b - a) * i / npost for i in range(npost + 1)]
    H = 1.38
    step = 1 if lod < 2 else 2
    for i in range(0, npost, step):
        s0, s1 = S[i], S[min(i + step, npost)]
        p0, n0, _ = R.frame(s0)
        p1, n1, _ = R.frame(s1)
        q0, q1 = p0 + n0 * -0.05, p1 + n1 * -0.05
        z0, z1 = crest_z(s0), crest_z(s1)
        d = (q1 - q0)
        L = d.length
        ang = math.atan2(d.y, d.x)
        u = d.normalized()
        out = Vector((u.y, -u.x, 0))
        if lod == 0:
            nb = max(2, int(L / 0.205))
            for k in range(nb):
                f = (k + 0.5) / nb
                q = q0.lerp(q1, f) + out * 0.05
                sz = min(crest_z(s0 + (s1 - s0) * f, -0.0), crest_z(s0 + (s1 - s0) * f, 0.12)) - 0.3
                top = z0 + (z1 - z0) * f + H + r.uniform(-0.06, 0.04)
                wd.box((q.x, q.y, (sz + top) / 2), (L / nb - 0.065, 0.04, top - sz), rz=ang + r.uniform(-0.03, 0.03))
        else:
            q = (q0 + q1) / 2 + out * 0.05
            zt = (z0 + z1) / 2 + H
            zb = min(z0, z1) - 0.3
            wd.box((q.x, q.y, (zt + zb) / 2), (L + 0.02, 0.05, zt - zb), rz=ang)
        if lod < 2:
            for zz in (0.38, 1.1):
                c0, c1 = q0 - out * 0.06, q1 - out * 0.06
                wd.box_along((c0.x, c0.y, z0 + zz), (c1.x, c1.y, z1 + zz), 0.06, 0.09)
    if lod < 2:
        for s in S:
            p, nrm, _ = R.frame(s)
            q = p + nrm * -0.05
            z = crest_z(s)
            ang = math.atan2(-nrm.x, nrm.y)
            K.post("Wood", q.x, q.y, z - 0.4, z + H + 0.12, 0.15, rz=ang)


# ------------------------------------------------------------------------------------------------------------------ roofs
def irimoya(K, r, ex, ez, ux, xg, ov, rise):
    """the upper gables of an irimoya roof over shingle_roof's hip roof `r` (same parameters): the long slopes run on over the hip ends up to the gable
    walls at x = +-xg (the hip-end slope stays below them), barge boards at the overhang, a gable wall of plaster and timber, and the ridge over all"""
    lod = K.lod
    tl, wd, pl = K.m["Shingle"], K.m["Wood"], K.m["Plaster"]
    Tt = TILE[tl.kind]
    run = ex - ux
    o = 0.075

    def S(y):
        return r.z(ux, y) + o

    def Sf(x, y):
        """the patch: o above the long slope over the wedge and the hip board, feathering to 15 mm beyond it"""
        e = abs(y) - (yw(x) + 0.12)
        return r.z(ux, y) + (o if e <= 0 else o + (0.015 - o) * min(1.0, e / 0.2))

    def yw(x):
        return ez * (abs(x) - ux) / run

    x0, x1 = ux + 0.14, xg + ov
    wg = yw(xg) + 0.06                                                               # the gable roof's half-width where it overhangs the gable wall
    nx, ny = (6, 3, 1)[lod], (14, 6, 2)[lod]
    slope_len = math.hypot(ez, rise)

    def grid(xa, xb, ni, width, zf):
        g = {}
        for i in range(ni + 1):
            x = xa + (xb - xa) * i / ni
            w = width(x)
            for j in range(ny + 1):
                t_ = -1 + 2 * j / ny
                y = math.copysign(abs(t_) ** 0.8, t_) * w
                g[(i, j)] = (x, y, zf(x, y))
        return g

    for sx in (-1, 1):
        parts = (grid(x0, xg, nx, lambda x: yw(x) + 0.32, Sf), grid(xg, x1, max(1, nx // 3), lambda x: wg, lambda x, y: S(y)))
        for g in parts:
            ni = max(k[0] for k in g)
            for i in range(ni):
                for j in range(ny):
                    ids = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                    vs = [tl.bm.verts.new(tl.M @ Vector((sx * g[k][0], g[k][1], g[k][2]))) for k in ids]
                    try:
                        f = tl.bm.faces.new(vs)
                    except ValueError:
                        continue
                    f.normal_update()
                    if f.normal.z < 0:
                        f.normal_flip()
                    key = {v: k for v, k in zip(vs, ids)}
                    f.smooth = True
                    f[tl.cu] = 1
                    for lp in f.loops:
                        x_, y_, _ = g[key[lp.vert]]
                        lp[tl.uvl].uv = (sx * x_ / Tt, (1 - abs(y_) / ez) * slope_len / Tt)
        # the underside of the overhang beyond the gable wall, and its little eave down each side
        for j in range(ny):
            ya, yb = -wg + 2 * wg * j / ny, -wg + 2 * wg * (j + 1) / ny
            face_up(wd, [(sx * xg, ya, S(ya) - 0.05), (sx * x1, ya, S(ya) - 0.05), (sx * x1, yb, S(yb) - 0.05), (sx * xg, yb, S(yb) - 0.05)], (0, 0, -1))
        for sy in (-1, 1):
            z_ = S(wg)
            face_up(wd, [(sx * xg, sy * wg, z_), (sx * x1, sy * wg, z_), (sx * x1, sy * wg, z_ - 0.12), (sx * xg, sy * wg, z_ - 0.12)], (0, sy, 0))
        # barge boards (hafu) along the overhang's edge, down to its eaves
        nb = (8, 4, 2)[lod]
        prev = None
        for j in range(nb + 1):
            y = -wg + 2 * wg * j / nb
            p = (sx * (x1 + 0.03), y, S(y) - 0.1)
            if prev:
                wd.box_along(prev, p, 0.08, 0.3)
            prev = p
        # the gable wall: plaster in a timber frame, its foot sunk in the hip-end slope
        zb = r.z(xg, 0.0) - 0.08
        wq = yw(xg)
        m = (10, 6, 2)[lod]
        top = [(sx * xg, -wq + 2 * wq * j / m, max(S(-wq + 2 * wq * j / m) - 0.07, zb + 0.02)) for j in range(m + 1)]
        face_up(pl, [(sx * xg, -wq, zb)] + top + [(sx * xg, wq, zb)], (sx, 0, 0))
        if lod < 2:
            wd.box((sx * (xg + 0.03), 0, zb + 0.16), (0.08, 2 * wq - 0.1, 0.16))
            for yy in (-wq * 0.5, 0.0, wq * 0.5):
                zt = S(yy) - 0.1
                wd.box((sx * (xg + 0.03), yy, (zb + 0.2 + zt) / 2), (0.07, 0.1, zt - zb - 0.2))
            wd.box((sx * (x1 + 0.06), 0, S(0) - 0.55), (0.07, 0.34, 0.42))                          # gegyo: the board that hangs under the ridge
    # the ridge: a boarded ridge over all, and on the hall crossed logs riding it
    zr = S(0)
    wd.box((0, 0, zr - 0.06), (2 * x1 + 0.24, 0.34, 0.58))                                      # (deep enough to sit down on the steep top of the slopes)
    if lod < 2:
        wd.cylinder((0, 0, zr + 0.27), (1, 0, 0), 0.11, 2 * x1 + 0.4, 8 if lod == 0 else 5)
    return zr + 0.38


def placed(K, m, fn, *a, **kw):
    """call a roof builder at the origin and move what it made by m. (roofs.shingle_roof's eave lip re-applies the builder's matrix to points that
    already carry it, so under a translated builder its fascia lands twice as far away: build it at identity.)"""
    marks = {id(mb): len(mb.bm.verts) for mb in K.builders()}
    res = fn(*a, **kw)
    for mb in K.builders():
        mb.bm.verts.ensure_lookup_table()
        new = [mb.bm.verts[i] for i in range(marks[id(mb)], len(mb.bm.verts))]
        if new:
            bmesh.ops.transform(mb.bm, matrix=m, verts=new)
    return res


def shingle_irimoya(K, ex, ez, ye, rise, ridge_frac=0.62, gable=0.9, ov=0.3, lift=0.28, kick=0.18, power=1.35, wall=None):
    """(build at the builder's identity: see placed())"""
    ux = ex - ez * ridge_frac
    r = Roof(ye, ex, ez, ux, 0.0, rise, lift, power=power, kick=kick)
    xg = ux + (ex - ux) * gable * 0.45
    wd = K.m["Wood"]
    mark = len(wd.bm.verts)
    shingle_roof(K, ex, ez, ux, 0.0, ye, rise, lift=lift, kick=kick, power=power, wall=wall, finial=False)
    # an irimoya has no hip board above its gables: drop shingle_roof's hip boards between the ridge and the gable overhang
    wd.bm.verts.ensure_lookup_table()
    new = set(wd.bm.verts[i] for i in range(mark, len(wd.bm.verts)))
    run, drop, seen = ex - ux, [], set()
    for v in new:
        if v in seen:
            continue
        comp, todo = [], [v]
        seen.add(v)
        while todo:
            u = todo.pop()
            comp.append(u)
            for e in u.link_edges:
                w = e.other_vert(u)
                if w in new and w not in seen:
                    seen.add(w)
                    todo.append(w)
        if len(comp) != 8:
            continue
        c = sum((u.co for u in comp), Vector()) / 8
        ax = abs(c.x)
        if ux - 0.05 < ax < xg + ov + 0.15 and abs(abs(c.y) - ez * (ax - ux) / run) < 0.14 and abs(c.z - (r.z(c.x, c.y) + 0.035)) < 0.1:
            drop += comp
    if drop:
        bmesh.ops.delete(wd.bm, geom=drop, context="VERTS")
    top = irimoya(K, r, ex, ez, ux, xg, ov, rise)
    return r, ux, xg, top


def gable_roof(K, L, hw, wall_top, wy, rise, wx=None, kind="Shingle", gable="Plaster", t=0.1):
    """a plain gable along x centred on the builder's origin: two slabs, a ridge, barge boards, gable walls at +-wx up under the slabs.
    The walls end at wall_top on the eave sides (half-depth wy): the slabs' undersides rest on them. @returns the ridge top"""
    lod = K.lod
    mb, wd = K.m[kind], K.m["Wood"]
    sl = math.atan2(rise, hw)
    ln = math.hypot(hw, rise)
    ye = wall_top - rise * (1 - wy / hw) + t / math.cos(sl) + 0.01                 # the eave line of the slabs' top surface
    for s in (-1, 1):
        c = (0, s * hw / 2 - s * math.sin(sl) * t / 2, ye + rise / 2 - math.cos(sl) * t / 2)
        mb.box(c, (L, ln + 0.08, t), rx=-s * sl)
        if lod == 0:                                                                 # battens down the slope
            n = max(3, int(L / 0.45))
            for i in range(n + 1):
                x = -L / 2 + 0.06 + (L - 0.12) * i / n
                wd.box_along((x, 0, ye + rise + 0.02), (x, s * (hw + 0.02), ye + 0.02), 0.045, 0.035)
    wd.box((0, 0, ye + rise + 0.04), (L + 0.1, 0.28, 0.16))
    if lod < 2:
        wd.cylinder((0, 0, ye + rise + 0.16), (1, 0, 0), 0.08, L + 0.24, 6)
        for sx in (-1, 1):
            for s in (-1, 1):
                wd.box_along((sx * (L / 2 + 0.02), 0, ye + rise + 0.02), (sx * (L / 2 + 0.02), s * (hw + 0.03), ye - 0.03), 0.06, 0.22)
    if wx is not None and gable:
        for sx in (-1, 1):
            apex = wall_top + rise * wy / hw - 0.02
            face_up(K.m[gable], [(sx * wx, -wy, wall_top - 0.05), (sx * wx, wy, wall_top - 0.05), (sx * wx, 0, apex)], (sx, 0, 0))
    return ye + rise + 0.24


def pent_ring(K, ix, iy, ox, oy, zi, zo, zs):
    """a skirt roof (mokoshi) all round: from an inner rectangle at zi down to an outer one at zo, its soffit at zs"""
    tl, wd = K.m["Shingle"], K.m["Wood"]
    I = [(-ix, -iy), (ix, -iy), (ix, iy), (-ix, iy)]
    O = [(-ox, -oy), (ox, -oy), (ox, oy), (-ox, oy)]
    for k in range(4):
        a, b = k, (k + 1) % 4
        out = ((O[a][0] + O[b][0]) / 2, (O[a][1] + O[b][1]) / 2, 0)
        face_up(tl, [(I[a][0], I[a][1], zi), (I[b][0], I[b][1], zi), (O[b][0], O[b][1], zo), (O[a][0], O[a][1], zo)], (out[0] * 0.2, out[1] * 0.2, 1))
        face_up(wd, [(O[a][0], O[a][1], zo), (O[b][0], O[b][1], zo), (O[b][0], O[b][1], zs), (O[a][0], O[a][1], zs)], out)      # fascia
        face_up(wd, [(O[a][0], O[a][1], zs), (O[b][0], O[b][1], zs), (I[b][0], I[b][1], zs), (I[a][0], I[a][1], zs)], (0, 0, -1))  # soffit
        face_up(wd, [(I[a][0], I[a][1], zs), (I[b][0], I[b][1], zs), (I[b][0], I[b][1], zi), (I[a][0], I[a][1], zi)], (-out[0], -out[1], 0))
    if K.lod == 0:                                                                   # rafter ends under the skirt
        for k in range(4):
            a, b = k, (k + 1) % 4
            L = math.dist(O[a], O[b])
            n = max(2, int(L / 0.42))
            for i in range(1, n):
                f = i / n
                px, py = O[a][0] + (O[b][0] - O[a][0]) * f, O[a][1] + (O[b][1] - O[a][1]) * f
                qx, qy = I[a][0] + (I[b][0] - I[a][0]) * f, I[a][1] + (I[b][1] - I[a][1]) * f
                wd.box_along((qx, qy, zs - 0.05), (px * 0.995, py * 0.995, zs - 0.05), 0.07, 0.09)


# ------------------------------------------------------------------------------------------------------------------ the gate tower
def gate_tower(K, GY):
    lod, r = K.lod, K.r
    wd, pl = K.m["Wood"], K.m["Plaster"]
    PX, PD = 1.78, 0.9
    with K.at(T(0, GY)):
        for sx in (-1, 1):
            K.post("Wood", sx * PX, -PD, -0.3, 3.55, 0.34)                                         # the pillars
            K.post("Wood", sx * PX, PD, -0.3, 3.55, 0.26)                                          # the back posts
            if lod < 2:
                K.post("Wood", sx * PX, -PD, -0.05, 0.22, 0.44)                                    # their root plates
                wd.box((sx * PX, 0, 3.4), (0.24, 2 * PD + 0.4, 0.3))                               # side beams
                wd.box((sx * PX, 0, 2.95), (0.16, 2 * PD, 0.18))
            wd.box((sx * (PX + 0.13), 0, 2.15), (0.1, 2 * PD - 0.2, 2.1))                          # side boards over the stone-faced bank ends
        for yy in (-PD, PD):
            wd.box((0, yy, 3.33), (2 * PX + 0.5, 0.24, 0.36))                                      # lintels
        wd.box((0, -PD, 2.98), (2 * PX - 0.2, 0.16, 0.2))                                          # the kanuki under the front lintel
        K.aab("Wood", -PX, PX, -PD - 0.08, -PD + 0.08, -0.2, 0.1)                                  # threshold
        # the leaves, swung open inward
        a = math.radians(74)
        w, h = PX - 0.18, 2.8
        for sx in (-1, 1):
            hx, hy = sx * (PX - 0.17), -PD + 0.13
            d = Vector((-sx * math.cos(a), math.sin(a), 0))
            c = Vector((hx, hy, 0.12 + h / 2)) + d * (w / 2)
            rz = math.atan2(d.y, d.x)
            wd.box(tuple(c), (w, 0.09, h), rz=rz)
            if lod == 0:
                for zz in (0.5, 1.5, 2.5):
                    cc = Vector((hx, hy, 0.12 + zz)) + d * (w / 2) + Vector((d.y, -d.x, 0)) * (0.06 * sx)
                    wd.box(tuple(cc), (w - 0.1, 0.05, 0.12), rz=rz)
        # the platform, the skirt under it, the railing round it
        DX, DY, ZD = 2.15, 1.3, 3.62
        K.aab("Wood", -DX, DX, -DY, DY, ZD - 0.12, ZD)
        pent_ring(K, DX, DY, DX + 0.45, DY + 0.45, ZD - 0.08, ZD - 0.4, ZD - 0.48)
        if lod < 2:
            pts = [(-DX + 0.05, -DY + 0.05), (DX - 0.05, -DY + 0.05), (DX - 0.05, DY - 0.05), (-DX + 0.05, DY - 0.05)]
            for k in range(4):
                p0, p1 = pts[k], pts[(k + 1) % 4]
                railing(wd, (p0[0], p0[1], ZD), (p1[0], p1[1], ZD), h=0.78, post_every=0.95 if lod == 0 else 2.3, th=0.06)
        # the upper room: boards, lattice windows front and back, corner posts
        RX, RY, ZT = 1.55, 0.78, 5.48
        K.aab("Wood", -RX, RX, -RY, RY, ZD, ZT)
        for sx in (-1, 1):
            for sy in (-1, 1):
                K.post("Wood", sx * RX, sy * RY, ZD, ZT, 0.2)
        if lod < 2:
            for sy in (-1, 1):
                wd.box((0, sy * (RY + 0.03), 4.68), (2 * RX - 0.4, 0.04, 0.5))                     # (the dark behind the lattice is the boards)
                wd.box((0, sy * (RY + 0.06), 4.38), (2 * RX, 0.1, 0.1))
                wd.box((0, sy * (RY + 0.06), 4.98), (2 * RX, 0.1, 0.1))
                if lod == 0:
                    for i in range(12):
                        wd.box((-RX + 0.3 + (2 * RX - 0.6) * i / 11, sy * (RY + 0.08), 4.68), (0.04, 0.05, 0.6))
            pl.box((0, -(RY + 0.02), 5.22), (2 * RX - 0.3, 0.04, 0.32))                            # a plaster frieze under the eaves
            pl.box((0, RY + 0.02, 5.22), (2 * RX - 0.3, 0.04, 0.32))
        # the ladder up to the platform, inside the passage against the right posts
        if lod < 2:
            for x in (1.18, 1.58):
                wd.box_along((x, 2.35, -0.1), (x, PD + 0.05, ZD - 0.1), 0.06, 0.09)
            if lod == 0:
                for i in range(1, 12):
                    f = i / 12
                    wd.box((1.38, 2.35 + (PD + 0.05 - 2.35) * f, -0.1 + (ZD) * f), (0.4, 0.05, 0.05))
    top = placed(K, T(0, GY), shingle_irimoya, K, 2.35, 1.68, 5.55, 2.3, ridge_frac=0.6, gable=1.0, ov=0.22, lift=0.32, wall=(RX, RY))[3]
    return top


# ------------------------------------------------------------------------------------------------------------------ the hall
def hall(K):
    lod, r = K.lod, K.r
    wd, pl = K.m["Wood"], K.m["Plaster"]
    BX, BY, FZ, PZ, VW = 3.6, 2.35, 0.85, 3.18, 0.85
    with K.at(T(0, HY0)):
        # under the floor: the dark, well back from the sill
        K.aab("Wood", -BX + 0.4, BX - 0.4, -BY + 0.4, BY - 0.4, 0.0, FZ - 0.1)
        for y0, y1, x0, x1 in ((-BY - 0.09, -BY + 0.09, -BX, BX), (BY - 0.09, BY + 0.09, -BX, BX), (-BY, BY, -BX - 0.09, -BX + 0.09), (-BY, BY, BX - 0.09, BX + 0.09)):
            K.aab("Wood", x0, x1, y0, y1, FZ - 0.3, FZ - 0.02)                                     # sills
        # posts on their stones
        xs = [-BX, -BX / 2, 0.0, BX / 2, BX]
        posts = [(x, y) for x in xs for y in (-BY, BY)] + [(sx * BX, 0.0) for sx in (-1, 1)]
        for x, y in posts:
            K.post("Wood", x, y, 0.08, PZ, 0.21)
            if lod < 2:
                K.stone(x, y, 0.14, 0.3, flat=0.55)
        # the veranda: boards, its edge beam and short posts on stones, the railing, the steps
        ey = -BY - VW
        if lod == 0:
            nb = int(round(VW / 0.2))
            for i in range(nb):
                y0 = -BY - VW + VW * i / nb
                K.aab("Wood", -BX - VW, BX + VW, y0 + 0.006, y0 + VW / nb - 0.006, FZ - 0.07, FZ)
            for sx in (-1, 1):
                for i in range(nb):
                    x0 = BX + VW * i / nb
                    K.aab("Wood", sx * (x0 + 0.006), sx * (x0 + VW / nb - 0.006), -BY, BY + 0.1, FZ - 0.07, FZ)
        else:
            K.aab("Wood", -BX - VW, BX + VW, ey, -BY, FZ - 0.07, FZ)
            for sx in (-1, 1):
                K.aab("Wood", sx * BX, sx * (BX + VW), -BY, BY + 0.1, FZ - 0.07, FZ)
        if lod < 2:
            K.aab("Wood", -BX - VW, BX + VW, ey, ey + 0.12, FZ - 0.26, FZ - 0.07)
            for sx in (-1, 1):
                K.aab("Wood", sx * (BX + VW - 0.12), sx * (BX + VW), ey, BY + 0.1, FZ - 0.26, FZ - 0.07)
            vp = [(x, ey + 0.08) for x in (-BX - VW + 0.1, -BX / 2, BX / 2, BX + VW - 0.1)] + [(sx * (BX + VW - 0.08), y) for sx in (-1, 1) for y in (0.0, BY)]
            for x, y in vp:
                K.post("Wood", x, y, 0.08, FZ - 0.2, 0.15)
                K.stone(x, y, 0.12, 0.22, flat=0.6)
            e = 0.05
            for a_, b_ in (((-BX - VW + e, ey + e), (-0.95, ey + e)), ((0.95, ey + e), (BX + VW - e, ey + e)),
                           ((-BX - VW + e, ey + e), (-BX - VW + e, BY)), ((BX + VW - e, ey + e), (BX + VW - e, BY))):
                railing(wd, (a_[0], a_[1], FZ), (b_[0], b_[1], FZ), h=0.72, post_every=0.9 if lod == 0 else 2.0, th=0.06)
        for k in range(4):                                                                          # the steps
            z = FZ * (k + 1) / 5
            yy = ey - (3.5 - k) * 0.26
            K.aab("Wood", -0.85, 0.85, yy - 0.15, yy + 0.15, z - 0.06, z)
        if lod < 2:
            for sx in (-1, 1):
                wd.box_along((sx * 0.9, ey - 1.05, 0.0), (sx * 0.9, ey + 0.05, FZ), 0.07, 0.24)
            K.stone(0.0, ey - 1.3, 0.1, 0.5, flat=0.22)                                             # the stone one steps up from
        # the walls: front bays of shutters and doors, side bays, plaster at the back; a white frieze over the lintel all round
        ZL = FZ + 1.85
        for side in range(4):
            ang = side * math.pi / 2
            half, span = (BY, BX) if side in (0, 2) else (BX, BY)
            with K.at(Rz(ang)):
                nb = 4 if side in (0, 2) else 2
                bw = 2 * span / nb
                for i in range(nb):
                    c = -span + bw * (i + 0.5)
                    w = bw - 0.21
                    if side == 2 or lod == 2:                                                       # back: plaster panels (and every panel at LOD2)
                        K.aab("Plaster" if side == 2 else "Wood", c - w / 2, c + w / 2, -half - 0.05, -half + 0.05, FZ, ZL)
                    elif side == 0 and i in (1, 2):                                                 # sliding doors, one slid back
                        K.aab("Wood", c - w / 2, c + w / 2, -half + 0.1, -half + 0.16, FZ, ZL)
                        K.aab("Wood", c - w / 2, c, -half - 0.04, -half + 0.0, FZ, ZL)
                        if lod == 0:
                            for k in range(7):
                                zz = FZ + 0.15 + k * 0.26
                                K.aab("Wood", c - w / 2 + 0.03, c - 0.03, -half - 0.065, -half - 0.035, zz, zz + 0.035)
                    elif side == 0 or (side == 1 and c < 0) or (side == 3 and c > 0):                                  # shitomi: the lower panel fixed, the upper hooked open
                        zm = FZ + 0.9
                        K.aab("Wood", c - w / 2, c + w / 2, -half - 0.03, -half + 0.03, FZ, zm)
                        K.aab("Wood", c - w / 2, c + w / 2, -half + 0.14, -half + 0.2, zm, ZL)
                        hgt = ZL - zm
                        aa = math.radians(62)
                        hy, hz = -half - 0.05, ZL
                        K.m["Wood"].box((c, hy - math.sin(aa) * hgt / 2, hz - math.cos(aa) * hgt / 2), (w, 0.05, hgt), rx=-aa)
                        if lod == 0:
                            for k in range(1, 7):
                                xx = c - w / 2 + w * k / 7
                                K.aab("Wood", xx - 0.015, xx + 0.015, -half - 0.06, -half - 0.03, FZ + 0.05, zm - 0.05)
                            for k in range(1, 4):
                                zz = FZ + 0.9 * k / 4
                                K.aab("Wood", c - w / 2, c + w / 2, -half - 0.06, -half - 0.03, zz - 0.015, zz + 0.015)
                            K.m["Wood"].box_along((c, -half - math.sin(aa) * hgt, hz - math.cos(aa) * hgt), (c, -half - 0.02, zm + 0.1), 0.025, 0.025)
                    else:                                                                           # boards
                        K.aab("Wood", c - w / 2, c + w / 2, -half - 0.04, -half + 0.04, FZ, ZL)
                        if lod == 0:
                            m = int(w / 0.24)
                            for k in range(1, m):
                                xx = c - w / 2 + w * k / m
                                K.aab("Wood", xx - 0.02, xx + 0.02, -half - 0.06, -half - 0.03, FZ, ZL)
                K.aab("Plaster", -span, span, -half - 0.04, -half + 0.04, ZL, PZ - 0.12)                 # frieze
                if lod < 2:
                    K.aab("Wood", -span - 0.1, span + 0.1, -half - 0.08, -half + 0.02, ZL - 0.06, ZL + 0.1)   # lintel (nageshi)
                    K.aab("Wood", -span - 0.12, span + 0.12, -half - 0.1, -half + 0.04, PZ - 0.16, PZ)        # plate
    top = placed(K, T(0, HY0), shingle_irimoya, K, BX + 1.25, BY + 1.3, PZ + 0.07, 3.9, ridge_frac=0.62, gable=1.0, ov=0.32, lift=0.28, wall=(BX, BY))[3]
    if lod < 2:                                                                                     # crossed logs along the ridge
        n = 7 if lod == 0 else 4
        zr = top - 0.38
        for i in range(n):
            x = -2.6 + 5.2 * i / (n - 1)
            wd.cylinder((x, HY0, zr + 0.42), (0, 1, 0), 0.075, 0.62, 6 if lod == 0 else 4)
    return top


# ------------------------------------------------------------------------------------------------------------------ the yard
def kura(K, cx, cy):
    """a plastered storehouse on a stone footing, the door in its gable end toward the yard, a pent over it"""
    lod, r = K.lod, K.r
    wd, pl = K.m["Wood"], K.m["Plaster"]
    hx, hy, H = 1.3, 1.35, 2.95
    with K.at(T(cx, cy)):
        K.aab("Stone", -hx - 0.08, hx + 0.08, -hy - 0.08, hy + 0.08, -0.3, 0.5)
        K.aab("Plaster", -hx, hx, -hy, hy, 0.4, H)
        if lod < 2:
            K.aab("Plaster", -hx - 0.1, hx + 0.1, -hy - 0.1, hy + 0.1, H - 0.28, H)                     # the swelling cornice
            for sx in (-1, 1):
                for sy in (-1, 1):
                    K.stone(sx * (hx + 0.08), sy * (hy + 0.08), 0.3, 0.32, flat=0.6)
        with K.at(Matrix.Identity(4)):
            gable_roof(K, 2 * hx + 0.75, hy + 0.48, H, hy + 0.1, 1.05, wx=hx, gable="Plaster")
        # the door on +x: dark, a heavy plaster leaf swung out, a frame, the pent on brackets
        K.aab("Wood", hx - 0.02, hx + 0.03, -0.45, 0.45, 0.5, 2.1)
        if lod < 2:
            K.aab("Plaster", hx, hx + 0.16, -0.62, -0.45, 0.45, 2.2)
            K.aab("Plaster", hx, hx + 0.16, 0.45, 0.62, 0.45, 2.2)
            K.aab("Plaster", hx, hx + 0.18, -0.65, 0.65, 2.1, 2.32)
            for sy in (-1, 1):                                                                          # the two heavy leaves, folded back
                a_ = sy * 0.17
                pl.box((hx + 0.16 + 0.27 * math.cos(a_), sy * (0.62 + 0.27 * abs(math.sin(a_))), 1.3), (0.55, 0.12, 1.55), rz=a_)
            K.m["Shingle"].box((hx + 0.32, 0, 2.55), (0.75, 1.6, 0.07), ry=math.radians(24))
            for sy in (-1, 1):
                wd.box_along((hx + 0.02, sy * 0.68, 2.2), (hx + 0.58, sy * 0.68, 2.43), 0.06, 0.08)
            K.aab("Wood", hx - 0.01, hx + 0.03, -0.25, 0.25, 3.25, 3.55)                                # a small window in the gable
            K.aab("Wood", -0.24, 0.24, -hy - 0.03, -hy + 0.01, 1.9, 2.3)                                # and one on the front
            K.aab("Plaster", -0.36, 0.36, -hy - 0.12, -hy, 2.3, 2.42)
            if lod == 0:
                for i in range(4):
                    K.aab("Wood", -0.18 + 0.12 * i - 0.02, -0.18 + 0.12 * i + 0.02, -hy - 0.06, -hy - 0.02, 1.9, 2.3)


def shed(K, cx, cy):
    """the servants' shed: posts, boarded back and ends, open to the yard, a stall with a manger; thatched, the ridge along y"""
    lod, r = K.lod, K.r
    wd = K.m["Wood"]
    hx, hy, ZE = 1.15, 1.6, 2.1
    with K.at(T(cx, cy)):
        segs = (7, 5, 4)[lod]
        for x in (-hx, hx):
            for y in (-hy, 0.0, hy):
                wd.cone((x, y, (ZE - 0.25) / 2), (0, 0, 1), 0.1, 0.085, ZE + 0.25, segs)
                if lod < 2:
                    K.stone(x, y, 0.1, 0.22, flat=0.6)
        if lod < 2:
            for x in (-hx, hx):
                wd.box((x, 0, ZE - 0.05), (0.14, 2 * hy + 0.3, 0.16))                                   # plates
            for y in (-hy, 0.0, hy):
                wd.box((0, y, ZE - 0.05), (2 * hx + 0.3, 0.12, 0.14))                                   # tie beams
        # boards: the back (+x) and both ends; a low partition makes the stall
        if lod == 0:
            for (x0, x1, y0, y1, along) in ((hx - 0.03, hx + 0.03, -hy, hy, "y"), (-hx, hx, -hy - 0.03, -hy + 0.03, "x"), (-hx, hx, hy - 0.03, hy + 0.03, "x")):
                L = (y1 - y0) if along == "y" else (x1 - x0)
                n = int(L / 0.24)
                for i in range(n):
                    a, b = -L / 2 + L * i / n + 0.008, -L / 2 + L * (i + 1) / n - 0.008
                    zt = ZE - 0.12 + r.uniform(-0.04, 0.02)
                    if along == "y":
                        K.aab("Wood", x0, x1, a, b, 0.0, zt)
                    else:
                        K.aab("Wood", a, b, y0, y1, 0.0, zt)
        else:
            K.aab("Wood", hx - 0.03, hx + 0.03, -hy, hy, 0.0, ZE - 0.12)
            K.aab("Wood", -hx, hx, -hy - 0.03, -hy + 0.03, 0.0, ZE - 0.12)
            K.aab("Wood", -hx, hx, hy - 0.03, hy + 0.03, 0.0, ZE - 0.12)
        if lod < 2:
            K.aab("Wood", -hx, hx, -0.03, 0.03, 0.0, 1.15)                                              # the stall's partition
            K.aab("Wood", hx - 0.55, hx - 0.1, -hy + 0.1, -0.1, 0.55, 0.85)                            # the manger
            K.aab("Wood", -hx - 0.02, -hx + 0.02, -hy, -0.05, 1.0, 1.08)                               # the bar across the stall
        with K.at(Rz(math.pi / 2)):                                                                    # (thatch_roof's ridge runs along its x)
            thatch_roof(K, hy + 0.55, hx + 0.55, max(0.3, (hy + 0.55) - (hx + 0.55) * 0.62), ZE - 0.02, 1.8, thick=0.36, wall=(hy, hx))
    if lod < 2:                                                                                         # straw and bales in the stall, tools at the door
        gx, gz = cx, -cy
        bale(K, gx + 0.45, gz + 0.75, 0.0, 0.0, 0.25, 0.75)
        bale(K, gx + 0.45, gz + 1.15, 0.0, 0.0, 0.25, 0.75)
        bale(K, gx + 0.45, gz + 0.95, 0.47, 0.0, 0.25, 0.75) if lod == 0 else None
        K.rod("Wood", (gx - 1.25, 0.0, gz - 0.35), (gx - 1.05, 1.6, gz - 0.5), 0.022, 4)
        K.rod("Wood", (gx - 1.25, 0.0, gz - 0.6), (gx - 1.08, 1.5, gz - 0.66), 0.022, 4)


def well(K, cx, cy):
    lod, r = K.lod, K.r
    wd, st = K.m["Wood"], K.m["Stone"]
    with K.at(T(cx, cy)):
        st.cone((0, 0, 0.18), (0, 0, 1), 0.6, 0.55, 0.85, 14 if lod == 0 else 8)                     # the curb, its foot in the ground
        wd.cylinder((0, 0, 0.6), (0, 0, 1), 0.44, 0.02, 12 if lod == 0 else 6)                         # the dark of the shaft
        if lod < 2:
            n = 9 if lod == 0 else 5
            for i in range(n):
                a = 2 * math.pi * (i + 0.3) / n
                K.stone(math.cos(a) * 0.72, math.sin(a) * 0.72, r.uniform(0.08, 0.16), r.uniform(0.14, 0.2), flat=0.6)
        for sy in (-1, 1):
            K.post("Wood", 0, sy * 0.72, -0.2, 2.0, 0.11)
        wd.box((0, 0, 1.92), (0.12, 1.75, 0.12))
        if lod < 2:
            wd.cylinder((0, 0, 1.7), (1, 0, 0), 0.13, 0.07, 10)                                       # the pulley
            K.m["Thatch"].box((0.1, 0, 1.15), (0.012, 0.012, 1.05))                                    # the rope
            wd.cone((0.1, 0, 0.73), (0, 0, 1), 0.11, 0.13, 0.22, 8)                                    # the bucket
        with K.at(Rz(math.pi / 2)):
            gable_roof(K, 1.95, 0.62, 2.06, 0.05, 0.42, wx=None, gable=None, t=0.07)


def tree(K, x, y, h, crown, seed, lean=(0.0, 0.0)):
    """a broad-leaved tree (a camphor or an oak, as in the painting): a short crooked trunk that forks low, and a full, round crown of lumpy masses"""
    lod = K.lod
    rr = random.Random(seed)
    fx, fy, fz = x + lean[0] * h * 0.3, y + lean[1] * h * 0.3, h * 0.34
    K.m["Wood"].tube([(x, y, -0.4), (x + lean[0] * h * 0.12 + 0.05, y + lean[1] * h * 0.12, h * 0.16), (fx, fy, fz)], [0.27, 0.22, 0.18], sides=(8, 6, 4)[lod])
    limbs = []
    for k in range(3 if lod < 2 else 1):
        a = 2 * math.pi * k / 3 + rr.uniform(-0.4, 0.4)
        d = crown * (0.42 if lod < 2 else 0.0)
        tip = (fx + lean[0] * h * 0.4 + math.cos(a) * d, fy + lean[1] * h * 0.4 + math.sin(a) * d, h * rr.uniform(0.62, 0.74))
        mid = ((fx + tip[0]) / 2 + rr.uniform(-0.15, 0.15), (fy + tip[1]) / 2 + rr.uniform(-0.15, 0.15), (fz + tip[2]) / 2)
        K.m["Wood"].tube([(fx, fy, fz - 0.1), mid, tip], [0.15, 0.1, 0.05], sides=(6, 5, 4)[lod])
        limbs.append(tip)
    cx_, cy_ = sum(t[0] for t in limbs) / len(limbs), sum(t[1] for t in limbs) / len(limbs)
    nb = (10, 5, 1)[lod]
    sub = (2, 1, 1)[lod]
    for k in range(nb):
        if nb == 1:
            c, rad = (cx_, cy_, h * 0.66), (crown, crown, crown * 0.8)
        else:
            a = 2 * math.pi * k / (nb - 1) + rr.uniform(-0.25, 0.25)
            d = crown * (0.55 if k else 0.0)
            zc = h * (0.8 if k == 0 else rr.uniform(0.58, 0.74))
            c = (cx_ + math.cos(a) * d, cy_ + math.sin(a) * d, zc)
            sz = crown * (0.75 if k == 0 else rr.uniform(0.5, 0.66))
            rad = (sz, sz * rr.uniform(0.85, 1.1), sz * 0.78)
        K.blob("Grass", c, rad, sub, lump=0.1 if lod == 0 else 0.0, seed=seed + k)


def shrub(K, x, y, s, seed, z=0.0):
    lod = K.lod
    if lod == 2:
        return
    rr = random.Random(seed)
    n = 3 if lod == 0 else 1
    for k in range(n):
        a = rr.uniform(0, 2 * math.pi)
        d = s * 0.45 * (1 if k else 0)
        rad = s * rr.uniform(0.6, 0.85)
        K.blob("Grass", (x + math.cos(a) * d, y + math.sin(a) * d, z + rad * 0.45), (rad, rad * 0.9, rad * 0.7), 1, lump=0.1 if lod == 0 else 0.0, seed=seed + k)


def yard(K, R):
    lod, r = K.lod, K.r
    kura(K, -4.15, -3.25)
    shed(K, 4.65, -3.45)
    well(K, 1.9, -2.7)
    # firewood under the hall's west eave, barrels at the kura door and the shed, bales by the gate (game frame: x, z = -y)
    woodpile(K, -5.15, -(HY0 + 0.6), 2.4, 5, along_x=False)
    for (x, y, rad, h, lid) in ((-2.45, -2.3, 0.3, 0.72, True), (-2.4, -1.65, 0.28, 0.66, True), (-2.95, -1.75, 0.27, 0.6, False), (3.35, -1.5, 0.3, 0.65, False),
                                 (4.55, HY0 - 3.55, 0.32, 0.7, False)):
        barrel(K, x, -y, 0.0, rad, h, lid=lid)
    if lod < 2:
        bale(K, -2.25, 5.0, 0.0, 0.15)
        bale(K, -2.2, 4.42, 0.0, -0.1)
        bale(K, -2.25, 4.72, 0.47, 0.05) if lod == 0 else None
        jar(K, 2.7, 1.5, 0.0, 1.0)
        jar(K, 2.6, 1.95, 0.0, 0.8)
    # planting: shrubs where the bank meets the yard, two trees on the back corners of the bank (outside the fence)
    for (x, y, s, sd) in ((-3.3, -5.75, 0.75, 3), (-5.8, -0.9, 0.62, 7), (5.75, 0.9, 0.66, 9), (-1.4, 6.0, 0.6, 11)):
        shrub(K, x, y, s, sd)
    tree(K, -7.45, 7.35, 6.4, 1.8, 21, lean=(-0.03, 0.02))
    tree(K, 7.45, 7.1, 5.8, 1.62, 31, lean=(0.03, 0.02))
    for (x, y, s, sd) in ((-5.95, 4.5, 0.5, 51), (5.95, 4.2, 0.48, 53), (-6.0, -3.1, 0.45, 55)):
        shrub(K, x, y, s, sd, z=0.15)
    if lod == 0:                                                                                    # stones where the bank meets the yard
        for i in range(10):
            s_ = R.s0 + 2.5 + (R.s1 - R.s0 - 5.0) * (i + r.random() * 0.6) / 10
            p_, n_, _ = R.frame(s_)
            c_ = p_ + n_ * r.uniform(-1.12, -0.98)
            K.stone(c_.x, c_.y, r.uniform(0.06, 0.16), r.uniform(0.14, 0.24), flat=0.6)
    if lod < 2:                                                                                     # a kitchen plot under straw, by the gate
        for j, yy in enumerate((-5.35, -5.78)):
            K.aab("Thatch", 2.35, 4.6, yy - 0.17, yy + 0.17, -0.06, 0.05)
            if lod == 0:
                for i in range(5):
                    xx = 2.55 + i * 0.4 + 0.1 * (j % 2) + r.uniform(-0.04, 0.04)
                    K.blob("Grass", (xx, yy + r.uniform(-0.03, 0.03), 0.13), (0.17, 0.16, 0.12), 1, seed=40 + i + 7 * j)
        # stepping stones from the gate to the hall's steps
        y = -5.9
        i = 0
        while y < -2.25:
            sz = r.uniform(0.3, 0.38)
            K.stone((0.18 if i % 2 else -0.18) + r.uniform(-0.08, 0.08), y, 0.05, sz, flat=0.16)
            y += sz * 1.55 + r.uniform(0.05, 0.15)
            i += 1


# ------------------------------------------------------------------------------------------------------------------ assemble
def build(lod, mats, coll, R):
    K = Y(lod, 9001)
    earthwork(K, R)
    fence(K, R)
    GY = R.p(0.0).y
    gtop = gate_tower(K, GY)
    htop = hall(K)
    yard(K, R)
    objs = K.objects("yakata", mats, coll)
    return objs, {"gate_y": GY, "gate_top": gtop, "hall_top": htop}


def bounds(objs):
    lo, hi = Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for v in o.data.vertices:
            p = o.matrix_world @ v.co
            lo = Vector((min(lo.x, p.x), min(lo.y, p.y), min(lo.z, p.z)))
            hi = Vector((max(hi.x, p.x), max(hi.y, p.y), max(hi.z, p.z)))
    return lo, hi


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "fixtures", "samurai_yakata.blend")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    R = Ring()
    allobjs, info = {}, {}
    for lod in (0, 1, 2):
        coll = bpy.data.collections.new(f"yakata_LOD{lod}")
        bpy.context.scene.collection.children.link(coll)
        allobjs[lod], info[lod] = build(lod, mats, coll, R)
        tris = 0
        for o in allobjs[lod]:
            o.data.calc_loop_triangles()
            tris += len(o.data.loop_triangles)
        lo, hi = bounds(allobjs[lod])
        print(f"LOD{lod}: {tris:,} tris in {len(allobjs[lod])} objects; bounds {tuple(round(v, 2) for v in lo)} .. {tuple(round(v, 2) for v in hi)}")
    i0 = info[0]
    print(f"gate tower: centre (0, {i0['gate_y']:.2f}), top {i0['gate_top']:.2f} m; hall ridge top {i0['hall_top']:.2f} m; ring s0 {R.s0:.2f} s1 {R.s1:.2f} L {R.L:.2f}")
    assert i0["gate_y"] < 0 and HY0 > 0, "the gate must face -Y (the keep's front) and the hall stand behind the yard"
    lo, hi = bounds(allobjs[0])
    if max(-lo.x, hi.x, -lo.y, hi.y) > 10.2:
        for o in allobjs[0]:
            for v in o.data.vertices:
                if max(abs(v.co.x), abs(v.co.y)) > 10.2:
                    print("OUTSIDE", o.name, tuple(round(c, 2) for c in v.co))
                    break
    assert max(-lo.x, hi.x, -lo.y, hi.y) <= 10.2, f"outside the footprint: {lo} {hi}"
    if "--render" in argv:
        show = int(argv[argv.index("--lod") + 1]) if "--lod" in argv else 0
        for lod in (0, 1, 2):
            for o in allobjs[lod]:
                o.hide_render = lod != show
        views = [("front", (17, -27, 15), (0, -0.5, 2.2), 34), ("back", (-19, 25, 14), (0, 0.5, 2.2), 34), ("top", (0.0, -0.01, 46), (0, 0, 0), 32),
                 ("gate", (3.2, -17.5, 1.6), (0, -6.5, 3.4), 30), ("gable", (10.5, -6.5, 8.6), (2.8, 2.4, 5.8), 45), ("rts", (0, -30, 30), (0, 0, 0), 38),
                 ("yard", (-9.5, -9.0, 9.0), (1.0, 0.5, 1.5), 30)]
        if "--views" in argv:
            keep = argv[argv.index("--views") + 1].split(",")
            views = [v for v in views if v[0] in keep]
        render_preview(argv[argv.index("--render") + 1], views, ground_z=0.0)
        for o in list(bpy.data.objects):
            if o.type != "MESH" or not o.name.startswith("yakata_"):
                bpy.data.objects.remove(o)
        for objs in allobjs.values():
            for o in objs:
                o.hide_render = False
    if "--no-save" not in argv:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)
