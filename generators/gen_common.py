"""Shared building blocks for the procedural architecture generators (samurai_keep, minka, teahouse).

MB       one-material mesh builder with a transform stack, boxes/cylinders/cones/tubes, world-space planar UVs
Roof     height-field roof (curved hip/ridge profile, upturned eave corners); build_roof() turns it into a tiled roof with fascia,
         soffit, eave tiles, rafters and hip ridges (square or rectangular wall footprints)
D        level-of-detail switches   window()  lattice window   render_preview()  QA renders (look at them!)
Units: metres, +Z up (Blender). UVs are world-space projections so texel density is constant (TILE metres per texture repeat).
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "gamepipe"))
from recipes import _common as C  # noqa: E402,F401

TEXDIR = os.path.join(ROOT, "out", "textures")
TILE = {"Stone": 3.0, "Plaster": 3.0, "Wood": 1.5, "Tile": 1.6, "Gold": 1.0, "Thatch": 2.0, "WoodL": 1.5}


def sstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------------------------------------ mesh builder
class MB:
    """Mesh builder for ONE material. Primitives honour a transform stack so sub-assemblies are built in local space."""

    def __init__(self, kind):
        self.kind = kind
        self.bm = bmesh.new()
        self.uvl = self.bm.loops.layers.uv.new("UVMap")
        self.cu = self.bm.faces.layers.int.new("custom")
        self.M = Matrix.Identity(4)
        self._stack = []

    def push(self, m):
        self._stack.append(self.M)
        self.M = self.M @ m

    def pop(self):
        self.M = self._stack.pop()

    def at(self, m):
        mb = self

        class _Ctx:
            def __enter__(s):
                mb.push(m)

            def __exit__(s, *a):
                mb.pop()
        return _Ctx()

    # --- primitives
    def face(self, pts, smooth=False, uvs=None):
        vs = [self.bm.verts.new(self.M @ Vector(p)) for p in pts]
        try:
            f = self.bm.faces.new(vs)
        except ValueError:
            return None
        f.smooth = smooth
        if uvs:
            for lp, uv in zip(f.loops, uvs):
                lp[self.uvl].uv = uv
            f[self.cu] = 1
        return f

    def box(self, c, size, rz=0.0, rx=0.0, ry=0.0):
        r = bmesh.ops.create_cube(self.bm, size=1.0)
        m = self.M @ Matrix.Translation(Vector(c)) @ Matrix.Rotation(rz, 4, "Z") @ Matrix.Rotation(ry, 4, "Y") \
            @ Matrix.Rotation(rx, 4, "X") @ Matrix.Diagonal((size[0], size[1], size[2], 1.0))
        bmesh.ops.transform(self.bm, matrix=m, verts=r["verts"])

    def box_along(self, p0, p1, w, h):
        a, b = Vector(p0), Vector(p1)
        d = b - a
        if d.length < 1e-6:
            return
        q = d.to_track_quat("X", "Z")
        m = self.M @ Matrix.Translation((a + b) / 2) @ q.to_matrix().to_4x4() @ Matrix.Diagonal((d.length, w, h, 1.0))
        r = bmesh.ops.create_cube(self.bm, size=1.0)
        bmesh.ops.transform(self.bm, matrix=m, verts=r["verts"])

    def cylinder(self, p, direction, radius, length, segs=5):
        r = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segs, radius1=radius, radius2=radius, depth=length)
        q = Vector((0, 0, 1)).rotation_difference(Vector(direction).normalized())
        m = self.M @ Matrix.Translation(Vector(p)) @ q.to_matrix().to_4x4()
        bmesh.ops.transform(self.bm, matrix=m, verts=r["verts"])

    def cone(self, p, direction, r1, r2, length, segs=6):
        r = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r1, radius2=r2, depth=length)
        q = Vector((0, 0, 1)).rotation_difference(Vector(direction).normalized())
        m = self.M @ Matrix.Translation(Vector(p)) @ q.to_matrix().to_4x4()
        bmesh.ops.transform(self.bm, matrix=m, verts=r["verts"])

    def tube(self, pts, radii, sides=7, smooth=True):
        """Swept tube along pts (parallel transport) with per-point radii."""
        rings, u, v, dprev = [], None, None, None
        for i, p in enumerate(pts):
            p = Vector(p)
            d = (Vector(pts[i + 1]) - p).normalized() if i < len(pts) - 1 else (p - Vector(pts[i - 1])).normalized()
            if dprev is None:
                ref = Vector((1, 0, 0)) if abs(d.x) < 0.9 else Vector((0, 1, 0))
                u = d.cross(ref).normalized()
                v = d.cross(u).normalized()
            else:
                ax = dprev.cross(d)
                if ax.length > 1e-6:
                    R = Matrix.Rotation(dprev.angle(d), 3, ax.normalized())
                    u, v = R @ u, R @ v
            dprev = d
            ring = [self.bm.verts.new(self.M @ (p + (u * math.cos(2 * math.pi * s / sides) + v * math.sin(2 * math.pi * s / sides)) * radii[i]))
                    for s in range(sides)]
            rings.append(ring)
        for i in range(len(rings) - 1):
            for s in range(sides):
                s2 = (s + 1) % sides
                try:
                    f = self.bm.faces.new((rings[i][s], rings[i][s2], rings[i + 1][s2], rings[i + 1][s]))
                    f.smooth = smooth
                except ValueError:
                    pass
        for ring in (rings[0][::-1], rings[-1]):
            try:
                self.bm.faces.new(ring)
            except ValueError:
                pass

    # --- finalise
    def to_object(self, name, material, coll):
        bm = self.bm
        bm.normal_update()
        tile = TILE[self.kind]
        for f in bm.faces:
            if f[self.cu]:
                if f.normal.z < -1e-4:          # open roof surfaces always face up
                    f.normal_flip()
                continue
            n = f.normal
            for lp in f.loops:
                p = lp.vert.co
                if abs(n.z) > 0.7:
                    uv = (p.x / tile, p.y / tile)
                elif abs(n.x) > abs(n.y):
                    uv = (p.y / tile, p.z / tile)
                else:
                    uv = (p.x / tile, p.z / tile)
                lp[self.uvl].uv = uv
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(material)
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        return ob


def Rz(a):
    return Matrix.Rotation(a, 4, "Z")



def tileable(name, tex):
    def load(fname, cs):
        im = bpy.data.images.load(os.path.join(TEXDIR, fname))
        im.colorspace_settings.name = cs
        im.name = fname
        return im
    maps = {"albedo": load(f"{tex}_albedo.jpg", "sRGB"), "normal": load(f"{tex}_normal.png", "Non-Color"),
            "orm": load(f"{tex}_orm.png", "Non-Color")}
    return C.pbr_material(name, maps, double_sided=False)



class D:
    """Level-of-detail switches."""
    def __init__(self, lod):
        self.lod = lod
        self.step = (0.14, 0.34, 0.9)[lod]          # roof grid spacing
        self.amp = (0.032, 0.0, 0.0)[lod]           # geometric tile-ridge relief
        self.base_res = (1.0, 0.5, 0.25)[lod]
        self.quoins = lod == 0
        self.rafters = lod == 0
        self.eave_tiles = lod <= 1
        self.bars = lod == 0
        self.window_frames = lod <= 1
        self.hips = lod <= 1
        self.ornaments = lod <= 1
        self.dormers = True



def window(wd, ang, half, zc, along, w, h, d):
    with wd.at(Rz(ang)):
        y = -(half + 0.07)
        wd.box((along, y, zc - h / 2 - 0.08), (w + 0.34, 0.22, 0.16))
        wd.box((along, y, zc + h / 2 + 0.08), (w + 0.34, 0.22, 0.16))
        for sx in (-1, 1):
            wd.box((along + sx * (w / 2 + 0.08), y, zc), (0.16, 0.22, h + 0.16))
        wd.box((along, -(half + 0.02), zc), (w, 0.08, h))                  # dark opening
        if d.bars:
            n = 8
            for k in range(n):
                wd.box((along - w / 2 + (k + 0.5) * w / n, -(half + 0.1), zc), (0.04, 0.07, h))
            wd.box((along, -(half + 0.1), zc), (w, 0.07, 0.04))



class Roof:
    def __init__(self, z0, ex, ey, ux, uy, H, lift, power=1.55, kick=0.30):
        self.z0, self.ex, self.ey, self.ux, self.uy, self.H, self.lift = z0, ex, ey, ux, uy, H, lift
        self.power, self.kick = power, kick

    def dd(self, x, y):
        dx = max(abs(x) - self.ux, 0.0) / (self.ex - self.ux)
        dy = max(abs(y) - self.uy, 0.0) / (self.ey - self.uy)
        return dx, dy

    def h(self, x, y):
        dx, dy = self.dd(x, y)
        d = min(max(dx, dy), 1.0)
        h = self.H * (1 - d) ** self.power + self.kick * sstep(0.80, 1.0, d) ** 2
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
    wx, wy = wall_half if isinstance(wall_half, (tuple, list)) else (wall_half, wall_half)
    co = [(-r.ex, -r.ey), (r.ex, -r.ey), (r.ex, r.ey), (-r.ex, r.ey)]
    ci = [(-wx, -wy), (wx, -wy), (wx, wy), (-wx, wy)]
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
                ln = r.ey - wy
                wd.box((k, sgn * (wy + ln / 2), zs - 0.07), (0.09, ln, 0.11))
            k += sp
        k = -r.ey + 0.2
        while k < r.ey - 0.1:
            for sgn in (-1, 1):
                ln = r.ex - wx
                wd.box((sgn * (wx + ln / 2), k, zs - 0.07), (ln, 0.09, 0.11))
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



def render_preview(path, views, ground_z=-0.8):
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
    bpy.ops.mesh.primitive_plane_add(size=120, location=(0, 0, ground_z))
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




# ------------------------------------------------------------------------------------------------ shared architecture helpers
def walls_rect(pl, hx, hy, zb, roof, trough=0.02, n=14):
    """Plaster walls of a RECTANGULAR footprint (half sizes hx, hy) from zb up to the roof surface (top edge follows the roof)."""
    for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
        ca, sa = math.cos(ang), math.sin(ang)
        half, span = (hy, hx) if ang in (0, math.pi) else (hx, hy)
        top = []
        for i in range(n + 1):
            a = -span + 2 * span * i / n
            x, y = a * ca + half * sa, a * sa - half * ca
            top.append((a, -half, roof.z(x, y) - trough))
        with pl.at(Rz(ang)):
            pl.face([(-span, -half, zb), (span, -half, zb)] + top[::-1])


def shoji(pl, wd, d, ang, half, zc, along, w, h, grid=True):
    """Sliding lattice screen: translucent paper panel (plaster material) in a timber frame with a kumiko grid."""
    with pl.at(Rz(ang)), wd.at(Rz(ang)):
        y = -(half + 0.04)
        pl.box((along, y, zc), (w - 0.06, 0.03, h - 0.06))
        t = 0.06
        for sz in (-1, 1):
            wd.box((along, y - 0.015, zc + sz * (h / 2 - t / 2)), (w, 0.07, t))
        for sx in (-1, 1):
            wd.box((along + sx * (w / 2 - t / 2), y - 0.015, zc), (t, 0.07, h))
        if grid and d.bars:
            for k in range(1, 4):
                wd.box((along - w / 2 + k * w / 4, y - 0.03, zc), (0.025, 0.04, h - 0.1))
            for k in range(1, 6):
                wd.box((along, y - 0.03, zc - h / 2 + k * h / 6), (w - 0.1, 0.04, 0.025))


def railing(wd, p0, p1, h=0.85, post_every=1.3, th=0.07):
    """Wooden rail between two points: posts, top rail, mid rail."""
    a, b = Vector(p0), Vector(p1)
    L = (b - a).length
    n = max(1, int(round(L / post_every)))
    for i in range(n + 1):
        p = a.lerp(b, i / n)
        wd.box((p.x, p.y, p.z + h / 2), (th * 1.4, th * 1.4, h))
    wd.box_along((a.x, a.y, a.z + h), (b.x, b.y, b.z + h), th * 1.6, th * 1.1)
    wd.box_along((a.x, a.y, a.z + h * 0.5), (b.x, b.y, b.z + h * 0.5), th, th * 0.8)
