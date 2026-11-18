"""Procedural samurai-era castle keep (tenshu) on an ishigaki stone base. Blender 5.x, headless:

    blender -b --factory-startup -P generators/samurai_keep.py -- [--out fixtures/samurai_keep.blend] [--render out/_keep.png]

Needs the tileable textures:  bin/gp textures specs/biomes.json   (stone_wall, plaster_white, wood_dark, roof_tile)

Output: LOD0/LOD1/LOD2 object sets, one object per material:  keep_LOD<n>_{Stone,Plaster,Wood,Tile,Gold}
Units: metres, origin at the ground centre of the stone base, +Z up, front (entrance) faces -Y.

Method (standard production approach): modelled geometry carries the silhouette and large forms; tileable PBR textures at a fixed
world-scale texel density carry surface detail. UVs are world-space planar projections (stone/plaster 3 m per repeat, wood 1.5 m,
roof tiles 1.6 m), so texel density is consistent across the whole building.

Architecture modelled (all dimensions in metres):
  * ishigaki base 18 m -> 13.8 m, 6 m high, concave "sori" batter, alternating long/short corner quoins (sangi-zumi), gate porch
  * three plastered storeys (shikkui) with lower board band, lintel boards and lattice windows (renji-mado)
  * irimoya-style tiled roofs: concave slope, upturned eave corners (hane), round-ended eave tiles (nokimarugawara), exposed rafters,
    ridge cap (munagawara), hip-ridge tiles, onigawara end blocks, gold shachihoko finials
  * chidori gables on the lowest roof, karahafu (ogee) gables on the middle roof
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
from gen_common import *  # noqa: E402,F401,F403  (MB, Roof, build_roof, window, D, tileable, render_preview, TILE, sstep, Rz...)
from gen_common import Rz, C  # noqa: E402

# ------------------------------------------------------------------------------------------------ materials
def make_materials():
    m = {"Stone": tileable("keep_stone", "stone_wall"), "Plaster": tileable("keep_plaster", "plaster_white"),
         "Wood": tileable("keep_wood", "wood_dark"), "Tile": tileable("keep_tile", "roof_tile")}
    g = bpy.data.materials.new("keep_gold")
    g.use_nodes = True
    b = g.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.86, 0.60, 0.14, 1)
    b.inputs["Metallic"].default_value = 0.92
    b.inputs["Roughness"].default_value = 0.34
    m["Gold"] = g
    return m


# ------------------------------------------------------------------------------------------------ dimensions
WB, WT, BH = 9.0, 6.9, 6.0                         # base half-width bottom/top, base height


def base_hw(t):
    return WT + (WB - WT) * (1 - t) ** 2.2        # concave sori batter: flares at the bottom, vertical at the top


# ------------------------------------------------------------------------------------------------ ishigaki
def build_base(st, wd, d):
    na, nt = max(8, int(36 * d.base_res)), max(4, int(16 * d.base_res))
    for side in range(4):
        R = Rz(side * math.pi / 2)
        verts = []
        for i in range(na + 1):
            col = []
            a = -1 + 2 * i / na
            for j in range(nt + 1):
                t = j / nt
                w = base_hw(t)
                col.append(st.bm.verts.new(R @ Vector((a * w, -w, t * BH - 0.8 if j == 0 else t * BH))))   # footing sunk 0.8 m below grade
            verts.append(col)
        out = R @ Vector((0, -1, 0))
        for i in range(na):
            for j in range(nt):
                vs = [verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]]
                try:
                    f = st.bm.faces.new(vs)
                except ValueError:
                    continue
                f.normal_update()
                if f.normal.dot(out) < 0:
                    f.normal_flip()
                f.smooth = True
    st.face([(-WT, -WT, BH), (WT, -WT, BH), (WT, WT, BH), (-WT, WT, BH)])
    if d.quoins:
        nc = 12
        ch = BH / nc * 0.93
        for k in range(nc):
            t = (k + 0.5) / nc
            z, w = t * BH, base_hw(t)
            l1, l2 = (1.35, 0.7) if k % 2 == 0 else (0.7, 1.35)
            alpha = math.atan((WB - WT) * 2.2 * (1 - t) ** 1.2 / BH)       # local wall batter angle
            for sx in (-1, 1):
                for sy in (-1, 1):
                    st.box((sx * (w - l1 / 2), sy * (w + 0.02), z), (l1, 0.46, ch), rx=sy * alpha)
                    st.box((sx * (w + 0.02), sy * (w - l2 / 2), z), (0.46, l2, ch), ry=-sx * alpha)
    # gate porch on the -Y face: stone mass, lintel, door in a timber frame, steps, small tiled roof
    py = -(WB + 0.6)
    st.box((0, py + 1.5, 2.1), (5.0, 3.1, 4.2))
    st.box((0, py - 0.05, 3.55), (3.4, 0.5, 0.7))                         # lintel stone
    for sx in (-1, 1):
        st.box((sx * 1.75, py - 0.03, 1.5), (0.55, 0.45, 3.0))            # jamb stones
    for k in range(3):
        st.box((0, py - 0.35 - k * 0.45, 0.14 + k * 0.0 + 0.1 * (2 - k)), (3.2 + (2 - k) * 0.3, 0.5, 0.28 * (3 - k)))
    tl_porch = (0, py + 1.0, 4.55)
    st.box((0, py + 1.5, 4.45), (5.4, 3.3, 0.35))                         # porch roof slab (stone coping under tile)
    wd.box((0, py + 0.04, 1.55), (2.5, 0.22, 3.1))                        # door leaf
    for sx in (-1, 1):
        wd.box((sx * 1.3, py - 0.04, 1.6), (0.18, 0.3, 3.3))              # frame posts
    wd.box((0, py - 0.04, 3.2), (2.8, 0.3, 0.2))
    for bx in (-0.9, 0.0, 0.9):
        for bz in (0.6, 1.4, 2.2, 2.8):                                   # iron-bound door studs (wood material, darker via AO)
            wd.box((bx, py - 0.1, bz), (0.12, 0.06, 0.12))


# ------------------------------------------------------------------------------------------------ walls & windows
def storey(pl, wd, d, half, zb, zt, roof, win_zc, win_w, win_h, wins):
    """Plastered walls from zb up to the roof surface (top edge FOLLOWS the roof, so hip/ridge roofs get proper gable-ends and nothing
    pokes through). Boards, windows and corner posts on all four faces."""
    n = 12
    trough = d.amp + 0.012
    for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
        ca, sa = math.cos(ang), math.sin(ang)
        top = []
        for i in range(n + 1):
            a = -half + 2 * half * i / n
            x, y = a * ca + half * sa, a * sa - half * ca              # world position of local (a, -half) rotated by ang
            top.append((a, -half, roof.z(x, y) - trough))
        with pl.at(Rz(ang)):
            pl.face([(-half, -half, zb), (half, -half, zb)] + top[::-1])
        with wd.at(Rz(ang)):
            wd.box((0, -(half + 0.03), zb + 0.35), (2 * half + 0.1, 0.1, 0.7))             # lower board band
            wd.box((0, -(half + 0.04), zt - 0.14), (2 * half + 0.1, 0.12, 0.28))           # eave board
        for a_ in wins:
            window(wd, ang, half, win_zc, a_, win_w, win_h, d)
    for sx in (-1, 1):
        for sy in (-1, 1):
            wd.box((sx * (half + 0.04), sy * (half + 0.04), (zb + zt) / 2), (0.2, 0.2, zt - zb))


# ------------------------------------------------------------------------------------------------ roofs
class Roof:
    def __init__(self, z0, ex, ey, ux, uy, H, lift):
        self.z0, self.ex, self.ey, self.ux, self.uy, self.H, self.lift = z0, ex, ey, ux, uy, H, lift

    def dd(self, x, y):
        dx = max(abs(x) - self.ux, 0.0) / (self.ex - self.ux)
        dy = max(abs(y) - self.uy, 0.0) / (self.ey - self.uy)
        return dx, dy

    def h(self, x, y):
        dx, dy = self.dd(x, y)
        d = min(max(dx, dy), 1.0)
        h = self.H * (1 - d) ** 1.55 + 0.30 * sstep(0.80, 1.0, d) ** 2
        edge = abs(x) / self.ex if dy >= dx else abs(y) / self.ey
        return h + self.lift * (edge ** 5) * (d ** 3), d, dy >= dx

    def z(self, x, y):
        return self.z0 + self.h(x, y)[0]


def build_roof(tl, wd, d, r, wall_half):
    step = d.step
    nx = max(4, int(round(2 * r.ex / step)))
    ny = max(4, int(round(2 * r.ey / step)))
    period = 0.26
    grid = {}
    meta = {}

    def vert(i, j):
        if (i, j) in grid:
            return grid[(i, j)]
        x = -r.ex + 2 * r.ex * i / nx
        y = -r.ey + 2 * r.ey * j / ny
        h, dist, along_x = r.h(x, y)
        if d.amp:
            u = x if along_x else y
            h += d.amp * math.sin(2 * math.pi * u / period) * sstep(0.02, 0.12, dist)
        v = tl.bm.verts.new(tl.M @ Vector((x, y, r.z0 + h)))
        grid[(i, j)] = v
        meta[(i, j)] = (x, y, dist, along_x)
        return v

    run_x, run_y = r.ex - r.ux, r.ey - r.uy
    for i in range(nx):
        for j in range(ny):
            ids = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            pts = []
            for a, b in ids:
                x = -r.ex + 2 * r.ex * a / nx
                y = -r.ey + 2 * r.ey * b / ny
                pts.append(r.h(x, y)[1])
            if max(pts) < 1e-6:
                continue
            vs = [vert(a, b) for a, b in ids]
            try:
                f = tl.bm.faces.new(vs)
            except ValueError:
                continue
            f.smooth = True
            f[tl.cu] = 1
            for lp, (a, b) in zip(f.loops, ids):
                x, y, dist, along_x = meta[(a, b)]
                if along_x:
                    lp[tl.uvl].uv = (x / TILE["Tile"], (1 - dist) * run_y * 1.12 / TILE["Tile"] * (1 if y > 0 else 1))
                else:
                    lp[tl.uvl].uv = (y / TILE["Tile"], (1 - dist) * run_x * 1.12 / TILE["Tile"])
    # fascia (wood): vertical band from the eave top edge down to soffit level, then the soffit ring itself (faces down)
    zs = r.z0 - 0.06
    ring = [(i, 0) for i in range(nx)] + [(nx, j) for j in range(ny)] + [(i, ny) for i in range(nx, 0, -1)] + [(0, j) for j in range(ny, 0, -1)]
    ring.append(ring[0])
    for (a_, b_), (c_, e_) in zip(ring[:-1], ring[1:]):
        pa, pb = vert(a_, b_).co, vert(c_, e_).co
        mid = (pa + pb) / 2
        out = Vector((mid.x, mid.y, 0)).normalized()
        q = [pa, pb, Vector((pb.x, pb.y, zs)), Vector((pa.x, pa.y, zs))]
        if (q[1] - q[0]).cross(q[3] - q[0]).dot(out) < 0:
            q = q[::-1]
        wd.face([tuple(p) for p in q])
    w = wall_half
    co = [(-r.ex, -r.ey), (r.ex, -r.ey), (r.ex, r.ey), (-r.ex, r.ey)]
    ci = [(-w, -w), (w, -w), (w, w), (-w, w)]
    for k in range(4):
        a_o, b_o = co[k], co[(k + 1) % 4]
        a_i, b_i = ci[k], ci[(k + 1) % 4]
        q = [(a_o[0], a_o[1], zs), (b_o[0], b_o[1], zs), (b_i[0], b_i[1], zs), (a_i[0], a_i[1], zs)]
        if (Vector(q[1]) - Vector(q[0])).cross(Vector(q[3]) - Vector(q[0])).z > 0:
            q = q[::-1]                                              # soffit faces DOWN
        wd.face(q)

    # eave end tiles (nokimarugawara) around the perimeter
    if d.eave_tiles:
        sp = 0.34 if d.lod == 0 else 0.7
        def eave_pt(x, y, nx_, ny_):
            z = r.z(x, y)
            tl.cylinder((x + nx_ * 0.04, y + ny_ * 0.04, z - 0.03), (nx_ * 0.97, ny_ * 0.97, -0.25), 0.07, 0.2, 5)
        k = -r.ex + sp / 2
        while k < r.ex:
            eave_pt(k, -r.ey, 0, -1); eave_pt(k, r.ey, 0, 1)
            k += sp
        k = -r.ey + sp / 2
        while k < r.ey:
            eave_pt(-r.ex, k, -1, 0); eave_pt(r.ex, k, 1, 0)
            k += sp
    # exposed rafters under the eave
    if d.rafters:
        sp = 0.36
        k = -r.ex + 0.2
        while k < r.ex - 0.1:
            for sgn in (-1, 1):
                ln = r.ey - w
                wd.box((k, sgn * (w + ln / 2), zs - 0.07), (0.09, ln, 0.11))
            k += sp
        k = -r.ey + 0.2
        while k < r.ey - 0.1:
            for sgn in (-1, 1):
                ln = r.ex - w
                wd.box((sgn * (w + ln / 2), k, zs - 0.07), (ln, 0.09, 0.11))
            k += sp
    # hip ridge tiles
    if d.hips:
        n = max(6, int(max(r.ex - r.ux, r.ey - r.uy) / 0.45))
        for sx in (-1, 1):
            for sy in (-1, 1):
                prev = None
                for kk in range(n + 1):
                    s = kk / n
                    x = sx * (r.ux + (r.ex - r.ux) * s)
                    y = sy * (r.uy + (r.ey - r.uy) * s)
                    p = (x, y, r.z(x, y) + 0.06)
                    if prev:
                        tl.box_along(prev, p, 0.30, 0.22)
                    prev = p
    return r


# ------------------------------------------------------------------------------------------------ ridge, ornaments
def ridge_and_finials(tl, gd, d, r):
    a = r.ux
    zr = r.z0 + r.H
    tl.box((0, 0, zr + 0.12), (2 * a + 0.6, 0.62, 0.30))
    tl.cylinder((0, 0, zr + 0.40), (1, 0, 0), 0.26, 2 * a + 0.6, 8)
    if not d.ornaments:
        return
    for sx in (-1, 1):
        x = sx * (a + 0.28)
        tl.box((x, 0, zr + 0.45), (0.55, 0.9, 1.0))                                 # onigawara block
        tl.box((x + sx * 0.12, 0, zr + 1.2), (0.3, 0.6, 0.55))
        tl.box((x + sx * 0.05, 0, zr + 0.10), (0.9, 1.0, 0.25))
        # shachihoko: head low and outward, body arching up and curling inward, fins along the back
        pts, rad = [], []
        n = 16
        for k in range(n + 1):
            t = k / n
            pts.append((x + sx * (0.25 - 0.35 * math.sin(math.pi * t * 0.75) + 0.30 * t * t), 0.0, zr + 1.0 + 1.55 * t))
            rad.append(0.13 + 0.22 * math.sin(math.pi * (t ** 0.8)) + (0.07 if t < 0.14 else 0.0))
        gd.tube(pts, rad, 7)
        for k in range(3, n, 2):
            p = Vector(pts[k])
            gd.cone((p.x + sx * rad[k] * 1.1, 0, p.z + 0.02), (sx * 0.6, 0, 0.8), 0.11, 0.01, 0.32 + 0.1 * math.sin(k), 4)
        gd.box((pts[0][0] + sx * 0.2, 0, pts[0][2] - 0.02), (0.55, 0.46, 0.42))       # head
        tail_top = Vector(pts[-1])
        gd.box((tail_top.x - sx * 0.1, 0, tail_top.z + 0.14), (0.62, 0.07, 0.55), rz=0.0)   # tail fluke


# ------------------------------------------------------------------------------------------------ gables
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


def dormer(pl, wd, tl, d, rf, ang, f, w, hg, depth, kara):
    zb = rf.z(0, -f) - 0.04
    n = 14 if kara else 2
    if d.lod >= 2:
        n = 8 if kara else 2
    out = ogee_outline(w, hg, kara, n)
    with pl.at(Rz(ang)), wd.at(Rz(ang)), tl.at(Rz(ang)):
        y = -f
        # front gable wall (plaster), down to the roof surface
        face_pts = [(x, y, zb + z) for x, z in out] + [(w / 2, y, zb - 0.25), (-w / 2, y, zb - 0.25)]
        pl.face(face_pts[::-1] if True else face_pts)
        # bargeboards: boxes along the outline, plus dormer roof sweep
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
            wd.box_along((out[i][0], y - 0.1, zb + out[i][1] + 0.1), (out[i + 1][0], y - 0.1, zb + out[i + 1][1] + 0.1), 0.16, 0.34)
        # roof: strip outline -> offset outline, swept back along +Y
        ny_ = 3
        for i in range(len(offs) - 1):
            for j in range(ny_):
                y0 = y - 0.30 + (depth + 0.30) * j / ny_
                y1 = y - 0.30 + (depth + 0.30) * (j + 1) / ny_
                p = [(offs[i][0], y0, zb + offs[i][1] + 0.05), (offs[i + 1][0], y0, zb + offs[i + 1][1] + 0.05),
                     (offs[i + 1][0], y1, zb + offs[i + 1][1] + 0.05), (offs[i][0], y1, zb + offs[i][1] + 0.05)]
                u0 = i * 0.5 / TILE["Tile"]
                tl.face(p[::-1] if (offs[i][0] < 0) else p, smooth=True,
                        uvs=[(u0, j * 0.6), (u0 + 0.3, j * 0.6), (u0 + 0.3, j * 0.6 + 0.6), (u0, j * 0.6 + 0.6)])
        # ridge tiles along the dormer ridge
        zr = zb + out[len(out) // 2][1] + 0.16
        tl.box((0, y + depth / 2 - 0.1, zr + 0.05), (0.36, depth + 0.3, 0.30))
        if d.ornaments:
            tl.box((0, y - 0.28, zr + 0.12), (0.5, 0.3, 0.5))                         # dormer onigawara
    return zb


# ------------------------------------------------------------------------------------------------ assemble
def build_keep(lod, mats, coll):
    d = D(lod)
    mb = {k: MB(k) for k in ("Stone", "Plaster", "Wood", "Tile", "Gold")}
    st, pl, wd, tl, gd = mb["Stone"], mb["Plaster"], mb["Wood"], mb["Tile"], mb["Gold"]

    build_base(st, wd, d)

    # storey 1 + roof 1 (hip skirt around storey 2)
    s1, z1b, z1e = 5.2, BH - 0.1, 9.4
    r1 = Roof(z1e, 6.7, 6.7, 4.2, 4.2, 1.9, 0.45)
    storey(pl, wd, d, s1, z1b, z1e, r1, 7.9, 1.25, 1.1, (-2.7, 0.0, 2.7))
    build_roof(tl, wd, d, r1, s1)

    # storey 2 + roof 2
    s2, z2e = 4.2, 14.2
    r2 = Roof(z2e, 5.7, 5.7, 3.2, 3.2, 1.6, 0.40)
    storey(pl, wd, d, s2, z1e + 0.5, z2e, r2, 12.5, 1.15, 1.0, (-1.7, 1.7))
    build_roof(tl, wd, d, r2, s2)

    # storey 3 + roof 3 (hip with ridge, finials)
    s3, z3e = 3.2, 18.2
    r3 = Roof(z3e, 5.0, 4.9, 1.9, 0.0, 3.0, 0.40)
    storey(pl, wd, d, s3, z2e + 0.3, z3e, r3, 16.9, 1.0, 1.25, (-1.45, 1.45))
    build_roof(tl, wd, d, r3, s3)
    ridge_and_finials(tl, gd, d, r3)

    # gables: chidori on roof 1 (all four sides), karahafu on roof 2 (front/back)
    if d.dormers:
        for k in range(4):
            dormer(pl, wd, tl, d, r1, k * math.pi / 2, 5.35, 3.4, 1.25, 1.3, False)
        for k in (0, 2):
            dormer(pl, wd, tl, d, r2, k * math.pi / 2, 4.45, 3.0, 1.7, 1.1, True)

    objs = []
    for kind, b in mb.items():
        if len(b.bm.faces) == 0:
            b.bm.free()
            continue
        objs.append(b.to_object(f"keep_LOD{lod}_{kind}", mats[kind], coll))
    return objs


def render_preview(path, views):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 1400, 1000
    sc.view_settings.view_transform = "AgX"
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.62, 0.72, 0.9, 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    sc.world = w
    sd = bpy.data.lights.new("sun", "SUN")
    sd.energy = 4.5
    sd.color = (1.0, 0.86, 0.68)
    sun = bpy.data.objects.new("sun", sd)
    sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(52), 0, math.radians(-32))
    bpy.ops.mesh.primitive_plane_add(size=120, location=(0, 0, -0.8))
    g = bpy.context.active_object
    gm = bpy.data.materials.new("g")
    gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.16, 0.2, 0.08, 1)
    g.data.materials.append(gm)
    cd = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    for tag, loc, tgt, lens in views:
        cd.lens = lens
        cam.location = loc
        cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = path.replace(".png", f"_{tag}.png")
        bpy.ops.render.render(write_still=True)
        print("rendered", sc.render.filepath)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "fixtures", "samurai_keep.blend")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    allobjs = {}
    for lod in (0, 1, 2):
        coll = bpy.data.collections.new(f"keep_LOD{lod}")
        bpy.context.scene.collection.children.link(coll)
        allobjs[lod] = build_keep(lod, mats, coll)
        tris = 0
        for o in allobjs[lod]:
            me = o.data
            me.calc_loop_triangles()
            tris += len(me.loop_triangles)
        print(f"LOD{lod}: {tris:,} tris in {len(allobjs[lod])} objects")
    if "--render" in argv:
        rp = argv[argv.index("--render") + 1]
        for lod in (1, 2):                                   # hide other LODs for the preview
            for o in allobjs[lod]:
                o.hide_render = True
        render_preview(rp, [("front", (30, -52, 14), (0, 0, 10), 40), ("roofs", (13, -22, 19), (0, 0, 16), 55),
                            ("base", (12, -20, 4), (0, -2, 5), 40)])
    if "--no-save" not in argv:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        print("saved", out)
