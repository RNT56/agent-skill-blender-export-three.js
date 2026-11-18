"""Roofs for the Samurai Vale kits: thatch, shingle and board roofs built as real surfaces (shared, smooth-shaded vertices, UVs that run with the slope) instead
of faceted prisms. Everything takes a Kit (wall_kit.Kit: K.m[kind] one-material builders, K.lod, K.r) and works in the GAME's frame: +x along the ridge, +y up,
+z the front. Blender is (x, -z, y).

  thatch_roof   kayabuki: a hipped roof whose hips and corners are ROUNDED (a super-ellipse in plan), a pillowed slope, a thick eave with a cut face and a
                soffit, pole rafters, and either a bound ridge (bark saddle, bamboo, crossed umanori logs) or, on a square plan, a gathered top-knot
  shingle_roof  kokerabuki: gen_common's curved height-field roof (upturned corners, a kick at the eave) laid with shingles: fascia, soffit, rafter ends,
                board hips, a ridge pole or a finial
  board_roof    itabuki: a gable of lapped boards of uneven length under hold-down poles and stones, purlin ends and barge boards at the gables
"""
import math

import bmesh
from mathutils import Matrix, Vector

import gen_common
from gen_common import Roof, sstep

# metres per repeat of the architecture textures (gamepipe/texgen_arch.py), by builder kind
gen_common.TILE.update({"Kaya": 2.4, "Shingle": 1.6, "Timber": 1.5, "TimberL": 1.5, "Nozura": 3.0, "Shikkui": 3.0, "Earth": 2.5, "Paper": 1.2})
TILE = gen_common.TILE


def G(x, y, z):
    return Vector((x, -z, y))


def _face(mb, pts, want, smooth=False):
    """a polygon of Blender points wound to face `want`"""
    vs = [mb.bm.verts.new(mb.M @ Vector(p)) for p in pts]
    try:
        f = mb.bm.faces.new(vs)
    except ValueError:
        return None
    f.normal_update()
    if f.normal.dot(mb.M.to_3x3() @ Vector(want)) < 0:
        f.normal_flip()
    f.smooth = smooth
    return f


def rock(K, x, y, z, s, kind="Stone", flat=0.6):
    """a field stone: a squashed, slightly skewed icosphere"""
    mb = K.m[kind]
    r = bmesh.ops.create_icosphere(mb.bm, subdivisions=1 if K.lod == 0 else 0, radius=1.0) if K.lod < 2 else bmesh.ops.create_cube(mb.bm, size=1.6)
    a = K.r.uniform(0, 3.1)
    m = mb.M @ Matrix.Translation(G(x, y + s * flat * 0.5, z)) @ Matrix.Rotation(a, 4, "Z") @ Matrix.Rotation(K.r.uniform(-0.25, 0.25), 4, "X") \
        @ Matrix.Diagonal((s * K.r.uniform(0.85, 1.3), s * K.r.uniform(0.7, 1.0), s * flat, 1.0))
    bmesh.ops.transform(mb.bm, matrix=m, verts=r["verts"])
    for v in r["verts"]:
        for f in v.link_faces:
            f.smooth = K.lod < 2


# ------------------------------------------------------------------------------------------------------------------ thatch
def thatch_roof(K, ex, ez, rx, ye, rise, thick=0.42, q=3.4, wall=None, ridge="bound", sag=0.06, kind="Thatch", cx=0.0, cz=0.0):
    """ex, ez: half-size of the eave; rx: half-length of the ridge (0 = a pyramid); ye: height of the eave's underside; rise: ridge above ye.
    wall = (half x, half z) of the wall under it (the soffit reaches in to it). @returns the height of the ridge"""
    lod, mb = K.lod, K.m[kind]
    T = TILE[mb.kind]
    bm = mb.bm
    seg, arc, rings = (0.36, 0.8, 9e9)[lod], (9, 5, 2)[lod], (7, 4, 2)[lod]
    rx = max(0.0, rx)
    spokes = []                                                              # (ridge x, eave x, eave z)

    def end(sign):
        n = arc * 2
        for i in range(n + 1):
            th = -math.pi / 2 + math.pi * i / n
            c, s = math.cos(th), math.sin(th)
            dx, dz = abs(c) ** (2 / q), abs(s) ** (2 / q)
            spokes.append((sign * rx, sign * (rx + (ex - rx) * dx), sign * (1 if s >= 0 else -1) * ez * dz))

    ns = max(1, int(round(2 * rx / seg))) if rx > 0.05 else 0
    end(1)
    for i in range(1, ns):
        x = rx - 2 * rx * i / ns
        spokes.append((x, x, ez))
    end(-1)
    for i in range(1, ns):
        x = -rx + 2 * rx * i / ns
        spokes.append((x, x, -ez))
    uniq = []                                                                # (a pyramid's two ends meet: drop the doubled spokes)
    for sp in spokes:
        if not uniq or math.hypot(sp[1] - uniq[-1][1], sp[2] - uniq[-1][2]) > 1e-5:
            uniq.append(sp)
    if len(uniq) > 1 and math.hypot(uniq[0][1] - uniq[-1][1], uniq[0][2] - uniq[-1][2]) < 1e-5:
        uniq.pop()
    spokes = uniq
    N = len(spokes)
    amp = (0.035, 0.03, 0.0)[lod]
    lump = lambda x, z: amp * (math.sin(1.7 * x + 0.6 * z + 1.3) * math.sin(1.1 * z - 0.8 * x + 0.4) + 0.5 * math.sin(3.1 * x - 2.3 * z))
    prof = lambda t: (1 - t) + 0.085 * math.sin(math.pi * t ** 0.9)          # a pillowed slope: thatch bulges low down
    yr = ye + rise

    def pt(i, t):
        xr, xe, ze = spokes[i]
        x, z = xr + (xe - xr) * t, ze * t
        y = ye + thick + (rise - thick) * prof(t)
        if rx > 0.3:
            y -= sag * (1 - (xr / rx) ** 2) * (1 - t) ** 2                   # an old ridge sags in the middle
        y += lump(x, z) * math.sin(math.pi * min(1.0, t * 1.15))
        if t > 0.98:
            x += 0.03 * math.sin(2.3 * x + 1.9 * z) * (1 if amp else 0)      # the eave line is not ruled either
        return x + cx, y, z + cz

    ts = [(j / rings) ** 0.9 for j in range(rings + 1)]
    cum = [0.0]
    for i in range(N):
        a, b = spokes[i], spokes[(i + 1) % N]
        cum.append(cum[-1] + math.hypot(b[1] - a[1], b[2] - a[2]))
    grid, apex = {}, {}

    def vert(i, j):
        i %= N
        if j == 0:                                                           # the spokes of a rounded end share one point of the ridge
            key = round(spokes[i][0], 4)
            if key not in apex:
                apex[key] = bm.verts.new(mb.M @ G(*pt(i, 0.0)))
            return apex[key]
        if (i, j) not in grid:
            grid[(i, j)] = bm.verts.new(mb.M @ G(*pt(i, ts[j])))
        return grid[(i, j)]

    def uv(i, j, wrap):
        xr, xe, ze = spokes[i % N]
        slope = math.hypot(math.hypot(xe - xr, ze), rise - thick)
        return ((cum[N] if wrap and i % N == 0 else cum[i % N]) / T, slope * (1 - ts[j]) / T)

    for i in range(N):
        for j in range(rings):
            ids = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            vs, uvs = [], []
            for a, b in ids:
                v = vert(a, b)
                if v not in vs:
                    vs.append(v)
                    uvs.append(uv(a, b, a == N))
            if len(vs) < 3:
                continue
            try:
                f = bm.faces.new(vs)
            except ValueError:
                continue
            f.smooth = True
            f[mb.cu] = 1
            for lp, u in zip(f.loops, uvs):
                lp[mb.uvl].uv = u
    # the eave: the cut face of the thatch (leaning in as it goes down) and the soffit behind it
    wx, wz = wall if wall else (ex * 0.6, ez * 0.6)
    low, inn = [], []
    for i in range(N):
        xr, xe, ze = spokes[i]
        l = math.hypot(xe - xr, ze) or 1.0
        nx, nz = (xe - xr) / l, ze / l
        low.append((xe - nx * 0.13 + cx, ye, ze - nz * 0.13 + cz))
        inn.append((max(-wx, min(wx, xe)) + cx, ye + 0.02, max(-wz, min(wz, ze)) + cz))
    for i in range(N):
        k = (i + 1) % N
        a, b = grid[(i, rings)].co, grid[(k, rings)].co
        la, lb = G(*low[i]), G(*low[k])
        out = Vector(((a.x + b.x) / 2 - cx, (a.y + b.y) / 2 + cz, 0))
        f = _face(mb, [mb.M.inverted() @ a, mb.M.inverted() @ b, lb, la], (out.x, out.y, -0.2 * out.length))
        if lod < 2:
            _face(mb, [la, lb, G(*inn[k]), G(*inn[i])], (0, 0, -1))
    yr_out = yr
    # pole rafters under the eave
    if lod == 0:
        step = max(1, int(round(0.62 / max(0.05, cum[N] / N))))
        for i in range(0, N, step):
            a, b = inn[i], low[i]
            K.rod("WoodL", (a[0], a[1] - 0.05, a[2]), (b[0] * 0.985 + cx * 0.015, b[1] - 0.03, b[2] * 0.985 + cz * 0.015), 0.04, 5)
    # the ridge
    if rx > 0.3 and ridge == "bound":
        rr = 0.26
        n = max(2, int(rx / 0.9)) if lod < 2 else 1
        pts = []
        for i in range(-n, n + 1):
            x = (rx + 0.28) * i / n
            pts.append(G(x + cx, yr + 0.02 - sag * (1 - min(1, abs(x) / rx) ** 2), cz))
        K.m[kind].tube(pts, [rr * 0.82 if abs(i) == n else rr for i in range(-n, n + 1)], sides=(10, 7, 5)[lod])
        if lod < 2:
            sl = math.atan2(rise - thick, ez)                                # the pitch of the long slopes
            for s in (-1, 1):                                                # a bark saddle under the bundle, held by a bamboo pole
                d = 0.62
                p0 = (cx, yr - 0.02, cz + s * 0.12)
                p1 = (cx, yr - 0.02 - d * math.sin(sl), cz + s * (0.12 + d * math.cos(sl)))
                mid = ((p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2)
                K.box("Wood", 2 * rx + 0.3, 0.035, d, cx, mid[0] + 0.03, mid[1], rx=s * sl)
                K.rod("WoodL", (cx - rx - 0.3, p1[1] + 0.09, p1[2] - s * 0.06), (cx + rx + 0.3, p1[1] + 0.09, p1[2] - s * 0.06), 0.038, 5)
            m = max(3, int(round(2 * rx / 1.05)) + 1)
            for i in range(m):                                               # umanori: crossed logs riding the ridge
                x = cx - rx + 2 * rx * i / (m - 1)
                for s in (-1, 1):
                    K.rod("Wood", (x, yr + 0.6, cz - s * 0.2), (x, yr - 0.42, cz + s * 0.72), 0.052, 5)
                if lod == 0:
                    K.box("Thatch" if kind == "Thatch" else kind, 0.07, 0.07, 0.5, x, yr + 0.26, cz)                 # the straw rope that binds them
            K.rod("WoodL", (cx - rx - 0.45, yr + 0.5, cz), (cx + rx + 0.45, yr + 0.5, cz), 0.05, 6)
        yr_out = yr + 0.6
    elif ridge:                                                              # a pyramid: the thatch is gathered into a bound sheaf under a cap
        segs = (10, 7, 5)[lod]
        mb.cone(G(cx, yr + 0.06, cz), (0, 0, 1), 0.34, 0.15, 0.4, segs)
        mb.cone(G(cx, yr + 0.36, cz), (0, 0, 1), 0.15, 0.22, 0.2, segs)
        if lod < 2:
            for y, rr in ((yr - 0.02, 0.3), (yr + 0.24, 0.165)):
                K.m["WoodL"].cylinder(G(cx, y, cz), (0, 0, 1), rr, 0.045, segs)                                     # the rope bindings
            K.m["Wood"].cone(G(cx, yr + 0.52, cz), (0, 0, 1), 0.26, 0.04, 0.13, segs)
            K.m["WoodL"].cylinder(G(cx, yr + 0.66, cz), (0, 0, 1), 0.035, 0.22, 5)
        yr_out = yr + 0.75
    return yr_out


# ------------------------------------------------------------------------------------------------------------------ shingles
def shingle_roof(K, ex, ez, ux, uz, ye, rise, lift=0.3, kick=0.2, power=1.4, wall=None, kind="Shingle", finial=True):
    """a curved hip roof of shingles (the Roof height field of gen_common). ux, uz: half-size of the ridge / upper plateau. @returns its top"""
    lod, tl, wd = K.lod, K.m[kind], K.m["Wood"]
    T = TILE[tl.kind]
    r = Roof(ye, ex, ez, ux, uz, rise, lift, power=power, kick=kick)
    step = (0.22, 0.5, 1.2)[lod]
    nx, ny = max(4, int(round(2 * ex / step))), max(4, int(round(2 * ez / step)))
    grid, meta = {}, {}

    def vert(i, j):
        if (i, j) not in grid:
            x, y = -ex + 2 * ex * i / nx, -ez + 2 * ez * j / ny
            h, dist, along_x = r.h(x, y)
            grid[(i, j)] = tl.bm.verts.new(tl.M @ Vector((x, y, ye + h)))
            meta[(i, j)] = (x, y, dist, along_x)
        return grid[(i, j)]

    run_x, run_y = ex - ux, ez - uz
    for i in range(nx):
        for j in range(ny):
            ids = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            if max(r.h(-ex + 2 * ex * a / nx, -ez + 2 * ez * b / ny)[1] for a, b in ids) < 1e-6:
                continue
            vs = [vert(a, b) for a, b in ids]
            cxm = sum(meta[k][0] for k in ids) / 4
            cym = sum(meta[k][1] for k in ids) / 4
            ax = r.h(cxm, cym)[2]                                            # one face, one slope: the rows of shingles do not shear across a hip
            try:
                f = tl.bm.faces.new(vs)
            except ValueError:
                continue
            f.smooth = True
            f[tl.cu] = 1
            for lp, k in zip(f.loops, ids):
                x, y, dist, _ = meta[k]
                if ax:
                    dd = min(1.0, abs(y) / ez if uz == 0 else max(abs(y) - uz, 0.0) / (ez - uz))
                    lp[tl.uvl].uv = (x / T, (1 - dd) * math.hypot(run_y, rise) / T)
                else:
                    dd = min(1.0, max(abs(x) - ux, 0.0) / (ex - ux))
                    lp[tl.uvl].uv = (y / T, (1 - dd) * math.hypot(run_x, rise) / T)
    if ux > 0 or uz > 0:                                                     # the flat between two ridges, if any, is closed
        _face(tl, [(-ux, -uz, ye + rise), (ux, -uz, ye + rise), (ux, uz, ye + rise), (-ux, uz, ye + rise)], (0, 0, 1)) if ux > 0.02 and uz > 0.02 else None
    # eave: a doubled starter course (a thick lip), the fascia board, the soffit
    zs = ye - 0.07
    ring = [(i, 0) for i in range(nx)] + [(nx, j) for j in range(ny)] + [(i, ny) for i in range(nx, 0, -1)] + [(0, j) for j in range(ny, 0, -1)]
    ring.append(ring[0])
    for (a_, b_), (c_, e_) in zip(ring[:-1], ring[1:]):
        pa, pb = vert(a_, b_).co, vert(c_, e_).co
        mid = (pa + pb) / 2
        out = Vector((mid.x if abs(abs(mid.x) - ex) < 1e-3 else 0, mid.y if abs(abs(mid.y) - ez) < 1e-3 else 0, 0))
        _face(tl, [tuple(pa), tuple(pb), (pb.x, pb.y, pb.z - 0.06), (pa.x, pa.y, pa.z - 0.06)], tuple(out))
        _face(wd, [(pa.x * 0.985, pa.y * 0.985, pa.z - 0.06), (pb.x * 0.985, pb.y * 0.985, pb.z - 0.06), (pb.x * 0.985, pb.y * 0.985, zs), (pa.x * 0.985, pa.y * 0.985, zs)], tuple(out))
    wx, wy = wall if wall else (ex * 0.6, ez * 0.6)
    co = [(-ex, -ez), (ex, -ez), (ex, ez), (-ex, ez)]
    ci = [(-wx, -wy), (wx, -wy), (wx, wy), (-wx, wy)]
    for k in range(4):
        a_o, b_o, a_i, b_i = co[k], co[(k + 1) % 4], ci[k], ci[(k + 1) % 4]
        _face(wd, [(a_o[0] * 0.985, a_o[1] * 0.985, zs), (b_o[0] * 0.985, b_o[1] * 0.985, zs), (b_i[0], b_i[1], zs), (a_i[0], a_i[1], zs)], (0, 0, -1))
    if lod < 2:                                                              # rafter ends under the eave
        sp = 0.34 if lod == 0 else 0.8
        k = -ex + 0.18
        while k < ex - 0.1:
            for s in (-1, 1):
                ln = ez - wy
                wd.box((k, s * (wy + ln / 2), zs - 0.06), (0.08, ln, 0.1))
            k += sp
        k = -ez + 0.18
        while k < ez - 0.1:
            for s in (-1, 1):
                ln = ex - wx
                wd.box((s * (wx + ln / 2), k, zs - 0.06), (ln, 0.08, 0.1))
            k += sp
        n = max(5, int(max(run_x, run_y) / 0.5))                             # hip boards
        for sx in (-1, 1):
            for sy in (-1, 1):
                prev = None
                for kk in range(n + 1):
                    s = kk / n
                    x, y = sx * (ux + run_x * s), sy * (uz + run_y * s)
                    p = (x, y, r.z(x, y) + 0.035)
                    if prev:
                        wd.box_along(prev, p, 0.2, 0.06)
                    prev = p
    top = ye + rise
    if ux > 0.2 and lod < 2:                                                 # a ridge of two boards under a pole
        K.box("Wood", 2 * ux + 0.5, 0.07, 0.34, 0, top - 0.01, 0)
        K.rod("Wood", (-ux - 0.32, top + 0.12, 0), (ux + 0.32, top + 0.12, 0), 0.07, 6)
        top += 0.2
    elif finial and lod < 2:                                                 # roban and hoju: the square seat and the jewel that close a pyramid roof
        K.box("Wood", 0.62, 0.12, 0.62, 0, top - 0.04, 0)
        K.box("Wood", 0.42, 0.2, 0.42, 0, top + 0.08, 0)
        K.m["Wood"].cone(G(0, top + 0.46, 0), (0, 0, 1), 0.2, 0.05, 0.36, 8 if lod == 0 else 5)
        K.m["Wood"].cone(G(0, top + 0.22, 0), (0, 0, 1), 0.12, 0.2, 0.12, 8 if lod == 0 else 5)
        top += 0.64
    elif finial:
        K.box("Wood", 0.4, 0.4, 0.4, 0, top - 0.04, 0)
    return top


# ------------------------------------------------------------------------------------------------------------------ boards
def board_roof(K, L, hw, ye, rise, x0=0.0, z0=0.0, wall_hw=None, kind="Wood"):
    """a gable along x: L long, eaves hw either side of z0 at ye, the ridge `rise` above"""
    lod, r = K.lod, K.r
    sl = math.atan2(rise, hw)
    run = math.hypot(hw, rise)
    K.prism(kind, L - 0.06, x0, [(z0 - hw + 0.03, ye), (z0 + hw - 0.03, ye), (z0 + hw - 0.03, ye + 0.06), (z0, ye + rise + 0.06), (z0 - hw + 0.03, ye + 0.06)])
    if lod == 0:
        n = max(4, int(round(L / 0.3)))
        for s in (-1, 1):
            for i in range(n):
                x = x0 - L / 2 + L * (i + 0.5) / n
                over = i % 2
                ext = r.uniform(0.0, 0.12)                                   # boards of uneven length at the eave
                ln = run + 0.04 + ext
                cy = ye + rise / 2 + 0.075 + (0.03 if over else 0.0) - math.sin(sl) * ext / 2
                cz_ = z0 + s * (hw / 2 + math.cos(sl) * ext / 2)
                K.box("WoodL" if (i * 7 + (s > 0)) % 6 == 0 else kind, L / n * (1.04 if over else 0.92), 0.03, ln, x, cy - 0.015, cz_, rx=s * sl)
    if lod < 2:
        for s in (-1, 1):                                                    # hold-down poles and the stones on them
            for f in (0.3, 0.72):
                y, z = ye + rise * (1 - f) + 0.16, z0 + s * hw * f
                K.rod("WoodL", (x0 - L / 2 - 0.12, y, z), (x0 + L / 2 + 0.12, y, z), 0.045, 5)
                if lod == 0:
                    for i in range(max(2, int(L / 1.5))):
                        rock(K, x0 - L / 2 + 0.5 + (L - 1.0) * r.random(), y + 0.02, z - s * 0.12, r.uniform(0.13, 0.2))
        K.box(kind, L + 0.1, 0.05, 0.3, x0, ye + rise + 0.07, z0)            # the ridge: a cap board under a pole
        K.rod(kind, (x0 - L / 2 - 0.2, ye + rise + 0.2, z0), (x0 + L / 2 + 0.2, ye + rise + 0.2, z0), 0.07, 6)
        wh = wall_hw if wall_hw else hw - 0.5
        for sx in (-1, 1):                                                   # purlin ends and barge boards at the gables
            x = x0 + sx * (L / 2 - 0.02)
            for z in (-wh, -wh * 0.5, 0.0, wh * 0.5, wh):
                K.m[kind].cylinder(G(x - sx * 0.2, ye + rise * (1 - abs(z) / hw) - 0.06, z0 + z), (1, 0, 0), 0.07, 0.5, 6)
            for s in (-1, 1):
                K.beam("WoodL", (x + sx * 0.03, ye + rise + 0.04, z0), (x + sx * 0.03, ye + 0.02, z0 + s * (hw + 0.02)), 0.05, 0.2)
    return ye + rise + 0.27
