"""Mesh kit for the samurai unit: closed, UV'd, bone-tagged parts built from lofts, tubes, slabs and lamellar strips.

Conventions: metres, Blender +Z up, the character faces -Y (glTF +Z after export), character LEFT = +X.
Every Part is a CLOSED solid (so normals can be recalculated and the validator's manifold rule holds) with a
procedural-pattern UV layer "pat" whose units are chosen per part (plate units for lamellar, metres for cloth).
Rigid parts carry the name of the one bone that owns them; soft parts carry a region tag used by skin.py.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

TAU = math.tau


def sstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0) if b != a else 0.0
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def lerpv(a, b, t):
    return Vector(a) * (1 - t) + Vector(b) * t


def clamp(x, a=0.0, b=1.0):
    return min(max(x, a), b)


class Part:
    """One bmesh with one procedural material. `at()` pushes a local transform (sub-assemblies, mirrored copies)."""

    def __init__(self, name, mat, bone=None, soft=None, sharp=38.0):
        self.name, self.mat, self.bone, self.soft, self.sharp = name, mat, bone, soft, sharp
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("pat")
        self.hl = self.bm.faces.layers.int.new("hid")          # 1 = never visible (plate undersides); dropped before baking
        self.M = Matrix.Identity(4)
        self._stack = []

    # ---------------------------------------------------------------- transform stack
    def push(self, M):
        self._stack.append(self.M)
        self.M = self.M @ M

    def pop(self):
        self.M = self._stack.pop()

    def v(self, co):
        return self.bm.verts.new(self.M @ Vector(co))

    def face(self, vs, uvs=None, hid=False):
        try:
            f = self.bm.faces.new(vs)
        except ValueError:
            return None
        if hid:
            f[self.hl] = 1
        if uvs:
            for lp, uv in zip(f.loops, uvs):
                lp[self.uv].uv = uv
        return f

    # ---------------------------------------------------------------- lofts
    def loft(self, rings, closed=True, caps=(True, True), uv=None, uvscale=(1.0, 1.0)):
        """Skin `rings` (list of equally long vertex rings, each a list of Vectors) into a tube.

        uv(i, j) -> (u, v) overrides the default (u = arc length around, v = distance along) in metres * uvscale."""
        n = len(rings[0])
        vr = [[self.v(p) for p in ring] for ring in rings]
        # default UV: metres along the surface
        vcoord = [0.0]
        for i in range(1, len(rings)):
            c0 = sum((Vector(p) for p in rings[i - 1]), Vector()) / n
            c1 = sum((Vector(p) for p in rings[i]), Vector()) / n
            vcoord.append(vcoord[-1] + (c1 - c0).length)
        ucoord = []
        for ring in rings:
            acc, us = 0.0, [0.0]
            for j in range(1, n + 1):
                acc += (Vector(ring[j % n]) - Vector(ring[j - 1])).length
                us.append(acc)
            ucoord.append(us)

        def UV(i, j):
            if uv:
                return uv(i, j)
            return (ucoord[i][j] * uvscale[0], vcoord[i] * uvscale[1])

        jmax = n if closed else n - 1
        for i in range(len(rings) - 1):
            for j in range(jmax):
                j2 = (j + 1) % n
                self.face([vr[i][j], vr[i][j2], vr[i + 1][j2], vr[i + 1][j]],
                          [UV(i, j), UV(i, j + 1 if closed else j2), UV(i + 1, j + 1 if closed else j2), UV(i + 1, j)])
        for idx, cap in ((0, caps[0]), (len(rings) - 1, caps[1])):
            if cap and closed:
                ring = vr[idx]
                c = sum((Vector(p) for p in rings[idx]), Vector()) / n
                cv = self.v(c)
                for j in range(n):
                    self.face([cv, ring[(j + 1) % n], ring[j]] if idx == 0 else [cv, ring[j], ring[(j + 1) % n]],
                              [(0, 0), (0.01, 0), (0, 0.01)])
        return vr

    def tube(self, path, section, n=10, closed_caps=(True, True), uvscale=(1.0, 1.0), up=Vector((0, 0, 1))):
        """Sweep a superellipse along `path` (list of Vectors). section(t) -> (rx, ry[, p[, ox, oy]]) with t in 0..1 along the path."""
        pts = [Vector(p) for p in path]
        rings = []
        for k, p in enumerate(pts):
            t = k / max(len(pts) - 1, 1)
            a = pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]
            a.normalize()
            ex = a.cross(up if abs(a.dot(up)) < 0.95 else Vector((1, 0, 0)))
            ex.normalize()
            ey = a.cross(ex)
            ey.normalize()
            s = section(t)
            rx, ry = s[0], s[1]
            pw = s[2] if len(s) > 2 else 2.0
            ox, oy = (s[3], s[4]) if len(s) > 4 else (0.0, 0.0)
            rings.append(ring(p + ex * ox + ey * oy, ex, ey, rx, ry, n, pw))
        return self.loft(rings, True, closed_caps, uvscale=uvscale)

    # ---------------------------------------------------------------- primitives
    def box(self, c, sx, sy, sz, rot=None, taper=1.0):
        """Axis aligned box centred on c (half extents sx, sy, sz); optional rotation matrix and top taper."""
        R = rot if rot is not None else Matrix.Identity(3)
        c = Vector(c)
        corners = []
        for z in (-1, 1):
            k = taper if z > 0 else 1.0
            for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                corners.append(self.v(c + R @ Vector((x * sx * k, y * sy * k, z * sz))))
        f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        for q in f:
            self.face([corners[i] for i in q], [(0, 0), (1, 0), (1, 1), (0, 1)])

    def sphere(self, c, rx, ry, rz, nu=10, nv=6, rot=None):
        R = rot if rot is not None else Matrix.Identity(3)
        c = Vector(c)
        rings = []
        for i in range(1, nv):
            th = math.pi * i / nv
            z = math.cos(th) * rz
            rr = math.sin(th)
            rings.append([c + R @ Vector((math.cos(TAU * j / nu) * rx * rr, math.sin(TAU * j / nu) * ry * rr, z)) for j in range(nu)])
        self.loft(rings, True, (True, True))

    def cyl(self, a, b, r0, r1=None, n=10, caps=(True, True), ratio=1.0):
        a, b = Vector(a), Vector(b)
        r1 = r0 if r1 is None else r1
        self.tube([a, b], lambda t: (lerp(r0, r1, t), lerp(r0, r1, t) * ratio), n, caps)

    # ---------------------------------------------------------------- slabs and lamellar strips
    def slab(self, surf, nu, nv, thick, chamfer=0.0, uvf=None, flip=False):
        """A curved plate of thickness `thick` hanging below the surface surf(u, v) -> (point, normal), u,v in 0..1.

        The top surface is inset by `chamfer` (in u/v) so the rim is a sloped bevel. Closed solid."""
        def P(u, v, inset):
            u2 = lerp(chamfer, 1 - chamfer, u) if inset else u
            v2 = lerp(chamfer, 1 - chamfer, v) if inset else v
            p, nrm = surf(u2, v2)
            return Vector(p), Vector(nrm)

        top = [[None] * (nu + 1) for _ in range(nv + 1)]
        bot = [[None] * (nu + 1) for _ in range(nv + 1)]
        for j in range(nv + 1):
            for i in range(nu + 1):
                v, u = j / nv, i / nu
                pt, nt = P(u, v, chamfer > 0)
                pb, nb = P(u, v, False)
                top[j][i] = self.v(pt + nt * (0.0 if chamfer == 0 else 0.0))
                bot[j][i] = self.v(pb - nb * thick)
        # rim shares the outer boundary of the un-inset surface for a slanted edge: rebuild top boundary slightly outwards
        # (top is inset, bottom full size => the connecting faces below slope outwards and downwards)
        def uvx(u, v):
            return uvf(u, v) if uvf else (u, v)

        for j in range(nv):
            for i in range(nu):
                self.face([top[j][i], top[j][i + 1], top[j + 1][i + 1], top[j + 1][i]],
                          [uvx(i / nu, j / nv), uvx((i + 1) / nu, j / nv), uvx((i + 1) / nu, (j + 1) / nv), uvx(i / nu, (j + 1) / nv)])
                self.face([bot[j][i], bot[j + 1][i], bot[j + 1][i + 1], bot[j][i + 1]], [(0, 0)] * 4, hid=True)
        for i in range(nu):
            self.face([top[0][i], bot[0][i], bot[0][i + 1], top[0][i + 1]], [(0, 0)] * 4)
            self.face([top[nv][i + 1], bot[nv][i + 1], bot[nv][i], top[nv][i]], [(0, 0)] * 4)
        for j in range(nv):
            self.face([top[j][0], top[j + 1][0], bot[j + 1][0], bot[j][0]], [(0, 0)] * 4)
            self.face([top[j + 1][nu], top[j][nu], bot[j][nu], bot[j + 1][nu]], [(0, 0)] * 4)

    def strip(self, surf, plates, v0, v1, nv=1, relief=0.0025, thick=0.004, groove=0.14, closed=False, row=0.0,
              uv_rows=1.0, drop=None):
        """A tier of `plates` laced plates following surf(s, v) -> (point, normal); s in 0..plates (plate units), v in v0..v1.

        Each plate is 3 columns (groove ramp, face, groove ramp) so the grooves read as lacing channels. The pattern UV is
        (plate units, row + v) so the procedural lacing aligns with the geometry. `drop(s)` lowers the lower edge (scalloped tiers)."""
        cols = []  # (s, relief factor)
        for k in range(plates):
            if groove is None:                      # plain band: one column per plate, no grooves
                cols.append((k, 0.0))
            else:
                cols += [(k, 0.0), (k + groove, 1.0), (k + 1 - groove, 1.0)]
        if not closed:
            cols.append((plates, 0.0))
        ncol = len(cols)
        topv = [[None] * ncol for _ in range(nv + 1)]
        botv = [[None] * ncol for _ in range(nv + 1)]
        for j in range(nv + 1):
            for i, (s, rf) in enumerate(cols):
                v = lerp(v0, v1, j / nv)
                if drop is not None and j == nv:
                    v = v + drop(s)
                p, n = surf(s, v)
                p, n = Vector(p), Vector(n)
                topv[j][i] = self.v(p + n * (thick * 0.5 + relief * rf))
                botv[j][i] = self.v(p - n * thick * 0.5)

        def UV(i, j):
            s = cols[i % ncol][0] if i < ncol else plates
            return (s if i < ncol else float(plates), row + (j / nv) * uv_rows)

        last = ncol if closed else ncol - 1
        for j in range(nv):
            for i in range(last):
                i2 = (i + 1) % ncol
                u0 = cols[i][0]
                u1 = cols[i2][0] if i2 != 0 else float(plates)
                self.face([topv[j][i], topv[j][i2], topv[j + 1][i2], topv[j + 1][i]],
                          [(u0, row + j / nv * uv_rows), (u1, row + j / nv * uv_rows),
                           (u1, row + (j + 1) / nv * uv_rows), (u0, row + (j + 1) / nv * uv_rows)])
                self.face([botv[j][i], botv[j + 1][i], botv[j + 1][i2], botv[j][i2]], [(0, 0)] * 4, hid=True)
        for i in range(last):
            i2 = (i + 1) % ncol
            self.face([topv[0][i], botv[0][i], botv[0][i2], topv[0][i2]], [(0, 0)] * 4)
            self.face([topv[nv][i2], botv[nv][i2], botv[nv][i], topv[nv][i]], [(0, 0)] * 4)
        if not closed:
            for j in range(nv):
                self.face([topv[j][0], topv[j + 1][0], botv[j + 1][0], botv[j][0]], [(0, 0)] * 4)
                self.face([topv[j + 1][-1], topv[j][-1], botv[j][-1], botv[j + 1][-1]], [(0, 0)] * 4)

    # ---------------------------------------------------------------- finish
    def to_object(self, coll):
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-6)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        thr = math.radians(self.sharp)
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > thr:
                e.smooth = False
        for f in bm.faces:
            f.smooth = True
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(self.name, me)
        coll.objects.link(ob)
        ob["gp_mat"] = self.mat
        ob["gp_bone"] = self.bone or ""
        ob["gp_soft"] = self.soft or ""
        return ob


def param_surf(fn, flip=1.0, d=0.004, inside=None):
    """Wrap a position function fn(s, v) -> Vector into surf(s, v) -> (point, unit normal) by finite differences.

    Normals must point OUT of the body: pass inside=callable(p)->Vector (a point on the part's inner axis) and the sign is
    chosen automatically on the first call; otherwise `flip` is used as given."""
    state = {"flip": flip, "set": inside is None}

    def surf(s, v):
        p = Vector(fn(s, v))
        ps = Vector(fn(s + d, v)) - Vector(fn(s - d, v))
        pv = Vector(fn(s, v + d * 0.1)) - Vector(fn(s, v - d * 0.1))
        n = ps.cross(pv)
        if n.length < 1e-12:
            n = Vector((0, 0, 1))
        n.normalize()
        if not state["set"]:
            ref = inside(p) if callable(inside) else Vector(inside)
            state["flip"] = 1.0 if n.dot(p - ref) >= 0 else -1.0
            state["set"] = True
        return p, n * state["flip"]
    return surf


def ring(c, ex, ey, rx, ry, n, p=2.0, phase=0.0):
    """Superellipse ring around c in the plane (ex, ey). p=2 is an ellipse, larger is squarer."""
    out = []
    e = 2.0 / p
    for j in range(n):
        t = TAU * j / n + phase
        ct, st = math.cos(t), math.sin(t)
        x = rx * math.copysign(abs(ct) ** e, ct)
        y = ry * math.copysign(abs(st) ** e, st)
        out.append(Vector(c) + ex * x + ey * y)
    return out


def bezier(pts, n):
    """De Casteljau curve through control points `pts`, n samples."""
    out = []
    for k in range(n):
        t = k / max(n - 1, 1)
        q = [Vector(p) for p in pts]
        while len(q) > 1:
            q = [q[i] * (1 - t) + q[i + 1] * t for i in range(len(q) - 1)]
        out.append(q[0])
    return out


def catmull(pts, per=6):
    """Catmull-Rom spline through pts (smooth path for tubes)."""
    P = [Vector(p) for p in pts]
    P = [P[0] * 2 - P[1]] + P + [P[-1] * 2 - P[-2]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for s in range(per):
            t = s / per
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2])
    return out


def frame_from(a, b, up=Vector((0, 0, 1))):
    """Orthonormal frame (x, y, z) with y along b-a."""
    y = (Vector(b) - Vector(a)).normalized()
    x = y.cross(up if abs(y.dot(up)) < 0.95 else Vector((1, 0, 0))).normalized()
    z = x.cross(y).normalized()
    return x, y, z


def basis_matrix(x, y, z):
    M = Matrix.Identity(3)
    M.col[0], M.col[1], M.col[2] = x, y, z
    return M
