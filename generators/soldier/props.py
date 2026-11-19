"""The rigid pieces of a soldier's kit, from image-to-3D meshes: hats, spear heads, the side arm.

Each source is a ~2 M triangle Tripo mesh in an arbitrary frame and scale. Here it is put into a CANONICAL frame and real size, cleaned of what cannot be rigid
(the hats' dangling chin cords), reduced, unwrapped and baked (soldier.bake: albedo, normal, ORM with metal). One .blend per piece in <work>/<unit>/props/:

    hat     the rim's circle in the plane z = 0, centred on the axis, the apex up (+Z), the front toward -Y; scaled to `diameter`
    pole    a spear's upper end: the shaft along +Y, its cut end at y = 0, the point at y = L; the blade's flat in the XY plane; scaled so the shaft is `shaft_d`
            thick. Image-to-3D makes a blade seen from the side as wide as it guesses: it is brought back to a spear's section (`blade_w`, `blade_t` x shaft).
            The low mesh is the head piece + ONE 8-sided shaft segment laid over the real shaft (the master): assemble.py repeats that segment down to the butt.
    blade   a sheathed short blade: along +Y, the pommel at y = 0, scaled to `length`

    blender -b --factory-startup -P generators/soldier_unit.py -- --unit ashigaru --stage props [--only jingasa,tanto] --work <dir>
"""
import json
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from villager import ingest, lowpoly, qa

from . import bake

V = Vector

PROPS = {
    "ashigaru": {
        "jingasa": dict(kind="hat", diameter=0.400, cords="slab", tris=1100, px=768),
        "tetsu_jingasa": dict(kind="hat", diameter=0.450, cords="colour", tris=900, px=768, lathe=True),
        "yari_head": dict(kind="pole", shaft_d=0.028, blade_w=1.25, blade_t=0.42, tris=240, px=512),
        "nagae_head": dict(kind="pole", shaft_d=0.030, blade_w=1.20, blade_t=0.40, tris=240, px=512),
        "tanto": dict(kind="blade", length=0.34, tris=260, px=512),
    },
    "archer": {
        "jingasa": dict(kind="hat", diameter=0.400, cords="slab", tris=1100, px=768),
        "ebira": dict(kind="blade", length=0.66, tris=1400, px=768, flip=True),          # the quiver with its arrows: a long piece, origin at its foot, +Y to the nocks
    },
}
SHAFT_SIDES = 8
HEAD_KEEP = 0.10           # m of shaft below the blade that stays with the head piece (collar, cord binding)
MASTER_LEN = 0.36          # m of real shaft the master segment lies over (and so the period of the shaft's texture, mirrored: 0.72 m)


def _co(me):
    a = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def _set_co(me, co):
    me.vertices.foreach_set("co", np.ascontiguousarray(co, dtype=np.float64).ravel())
    me.update()


def _vert_colours(ob):
    """sRGB albedo of the source texture at every vertex (through any one of its loops' UVs): what a piece is made of, vertex by vertex."""
    me = ob.data
    nt, bsdf, n_col, n_nrm, n_orm = lowpoly._src_nodes(me.materials[0])
    img = n_col.image
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    nl = len(me.loops)
    uv = np.empty(nl * 2, dtype=np.float64)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    lv = np.empty(nl, dtype=np.int64)
    me.loops.foreach_get("vertex_index", lv)
    vu = np.zeros((len(me.vertices), 2))
    vu[lv] = uv
    x = np.clip((vu[:, 0] % 1.0) * w, 0, w - 1).astype(int)
    y = np.clip((vu[:, 1] % 1.0) * h, 0, h - 1).astype(int)
    return px[y, x, :3]


def _hsv(rgb):
    mx, mn = rgb.max(1), rgb.min(1)
    d = mx - mn
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    hue = np.zeros(len(rgb))
    m = d > 1e-6
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    i = m & (mx == r)
    hue[i] = ((g[i] - b[i]) / d[i]) % 6
    i = m & (mx == g) & ~(mx == r)
    hue[i] = (b[i] - r[i]) / d[i] + 2
    i = m & (mx == b) & ~(mx == r) & ~(mx == g)
    hue[i] = (r[i] - g[i]) / d[i] + 4
    return hue * 60.0, s, mx


def _pca(co):
    c = co.mean(0)
    w, v = np.linalg.eigh(np.cov((co - c).T))
    order = np.argsort(-w)
    return c, v[:, order].T, w[order]            # rows: axes by falling variance


def _delete_verts(ob, mask):
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return 0
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in idx], context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    return len(idx)


def _frame(ob, origin, ax, ay, az, scale):
    """re-express the mesh in the frame (origin; ax, ay, az), times scale"""
    R = np.array([ax, ay, az], dtype=np.float64)
    if np.linalg.det(R) < 0:
        R[0] = -R[0]
    co = (_co(ob.data) - np.asarray(origin)) @ R.T * scale
    _set_co(ob.data, co)
    return co


# ------------------------------------------------------------------------------------------------------------------- hats
def _circle(pts):
    """least-squares circle through 2D points (Kasa): centre, radius. Right even when the points cover only an arc."""
    A = np.c_[2 * pts[:, 0], 2 * pts[:, 1], np.ones(len(pts))]
    b = (pts ** 2).sum(1)
    cx, cy, k = np.linalg.lstsq(A, b, rcond=None)[0]
    return np.array((cx, cy)), float(math.sqrt(max(k + cx * cx + cy * cy, 1e-12)))


def canon_hat(ob, cfg, log=print):
    """Image-to-3D keeps a photographed hat upright, so the start is +Z; the rim (the widest ring) then gives the true axis, centre and size."""
    co = _co(ob.data)
    up = np.array((0.0, 0.0, 1.0))
    centre = co.mean(0)
    rad = 1.0
    for it in range(6):
        a = np.cross(up, (1.0, 0.0, 0.0))
        if np.linalg.norm(a) < 0.3:
            a = np.cross(up, (0.0, 1.0, 0.0))
        a /= np.linalg.norm(a)
        b = np.cross(up, a)
        q = co - centre
        h = q @ up
        p2 = np.c_[q @ a, q @ b]
        r = np.linalg.norm(p2, axis=1)
        rim = r > 0.955 * np.quantile(r, 0.9995)
        if it:                                                     # the rim is ONE ring: keep the points near its plane (a neck curtain's hem may be as far out)
            hm = np.median(h[rim])
            rim &= np.abs(h - hm) < 0.06 * rad
        pts = p2[rim]
        if len(pts) > 20000:
            pts = pts[:: len(pts) // 20000]
        c2, rad = _circle(pts)
        pr = co[rim]
        if len(pr) > 4000:                                         # (a few thousand points define a plane; and NEVER a full SVD of n x 3: its U is n x n)
            pr = pr[:: len(pr) // 4000]
        pc = pr.mean(0)
        nrm = np.linalg.eigh(np.cov((pr - pc).T))[1][:, 0]         # the plane's normal: the direction of least spread
        if nrm @ up < 0:
            nrm = -nrm
        up = nrm / np.linalg.norm(nrm)
        centre = centre + a * c2[0] + b * c2[1] + up * float(np.median(h[rim]))
    q = co - centre
    h = q @ up
    perp = q - np.outer(h, up)
    r = np.linalg.norm(perp, axis=1)
    if h.max() < -h.min() and (r[h > 0.5 * h.max()].mean() > r[h < 0.5 * h.min()].mean()):      # the apex is up: the high end is the narrow one
        pass
    # the front: a neck curtain hangs at the BACK, so the front is away from the mass below the rim; a hat without one is round (any front)
    below = h < -0.15 * rad
    fwd = None
    if below.sum() > 200:
        m = perp[below].mean(0)
        if np.linalg.norm(m) > 0.06 * rad:
            fwd = -m / np.linalg.norm(m)
    if fwd is None:
        fwd = np.cross(up, (1.0, 0.0, 0.0))
        fwd /= np.linalg.norm(fwd)
    fwd = fwd - up * (fwd @ up)
    fwd /= np.linalg.norm(fwd)
    left = np.cross(-fwd, up)                                      # x = left of a wearer facing -Y
    s = cfg["diameter"] * 0.5 / rad
    co = _frame(ob, centre, left, -fwd, up, s)
    # ---- the chin cords cannot hang rigidly from a moving head: off
    col = _vert_colours(ob)
    r = np.hypot(co[:, 0], co[:, 1])
    z = co[:, 2]
    R = cfg["diameter"] * 0.5
    kill = np.zeros(len(co), dtype=bool)
    if cfg["cords"] == "slab":                                     # below the rim, a height where the surface no longer goes all the way round is cord only
        ang = (np.degrees(np.arctan2(co[:, 1], co[:, 0])) % 360 / 10).astype(int)
        zc = None
        for z0 in np.arange(-0.004, float(z.min()) - 0.004, -0.004):
            sl = (z < z0) & (z >= z0 - 0.004)
            if sl.sum() < 12 or len(np.unique(ang[sl])) < 15:
                zc = z0
                break
        if zc is not None:
            kill = z < zc
        log(f"  cords: everything below z = {zc if zc is None else round(float(zc), 3)} m ({int(kill.sum())} vertices)")
    else:                                                          # hemp-coloured and below the rim (the curtain is indigo, the hat black)
        hue, sat, val = _hsv(col)
        tan = (hue > 18) & (hue < 62) & (sat > 0.16) & (sat < 0.70) & (val > 0.38)
        kill = tan & (z < -0.004) & (r < R * 0.985)
        # grow by a little so the dark creases of the rope go with it
        log(f"  cords: {int(kill.sum())} hemp-coloured vertices below the rim")
    n = _delete_verts(ob, kill)
    cl = ingest.clean(ob, min_shell_frac=0.004)                     # what the cut left hanging in the air (knots, stubs of cord)
    n += cl["small_shell_verts_removed"]
    # the front, measured on what is left: a neck curtain leaves the face free, so the middle of the widest gap in the cloth below the rim looks forward (-Y)
    co = _co(ob.data)
    lowv = co[:, 2] < -0.05
    turned = None
    if lowv.sum() > 300:
        nb = 72
        cnt = np.bincount(((np.arctan2(co[lowv, 1], co[lowv, 0]) + math.pi) / (2 * math.pi) * nb).astype(int) % nb, minlength=nb)
        empty = cnt < 0.15 * np.median(cnt[cnt > 0])
        best, at = 0, None
        for i in range(nb):
            if empty[i] and not empty[i - 1]:
                run = 0
                while empty[(i + run) % nb] and run < nb:
                    run += 1
                if run > best:
                    best, at = run, i
        if at is not None and best >= 4:
            mid = -math.pi + (at + best * 0.5) * (2 * math.pi / nb)             # the gap's middle, as an angle
            turn = -math.pi / 2 - mid                                           # ... goes to -Y
            c, sn = math.cos(turn), math.sin(turn)
            co[:, 0], co[:, 1] = co[:, 0] * c - co[:, 1] * sn, co[:, 0] * sn + co[:, 1] * c
            _set_co(ob.data, co)
            turned = round(math.degrees(turn), 1)
            log(f"  front: the curtain's gap ({best * 5} degrees wide) turned to -Y by {turned} degrees")
    facts = {"diameter": cfg["diameter"], "scale": round(s, 5), "cord_verts": n, "turned": turned, "curtain": bool(fwd is not None and below.sum() > 200 and np.linalg.norm(perp[below].mean(0)) > 0.06 * rad)}
    co = _co(ob.data)
    facts["height_above_rim"] = round(float(co[:, 2].max()), 4)
    facts["depth_below_rim"] = round(float(-co[:, 2].min()), 4)
    return facts


# ------------------------------------------------------------------------------------------------------------------- spear heads
def canon_pole(ob, cfg, log=print):
    co = _co(ob.data)
    c, ax, var = _pca(co)
    along = ax[0]
    t = (co - c) @ along
    col = _vert_colours(ob)
    hue, sat, val = _hsv(col)
    lo, hi = t < np.quantile(t, 0.15), t > np.quantile(t, 0.85)
    if sat[lo].mean() < sat[hi].mean():                            # steel has no colour: the point is the grey end
        along = -along
        t = -t
    t0 = float(t.min())
    L = float(t.max() - t0)
    # the blade's flat: the wide axis of the last fifth
    tipv = (co - c)[t - t0 > 0.80 * L]
    tipv = tipv - np.outer(tipv @ along, along)
    w, v = np.linalg.eigh(np.cov(tipv.T))
    wide = v[:, int(np.argmax(w))]
    wide = wide - along * (wide @ along)
    wide /= np.linalg.norm(wide)
    thin = np.cross(wide, along)
    axis_pt = c + along * t0 + ((co - c) - np.outer((co - c) @ along, along))[(t - t0 > 0.05 * L) & (t - t0 < 0.45 * L)].mean(0)
    co = _frame(ob, axis_pt, wide, along, thin, 1.0)
    # sections along the shaft
    n = 200
    ys = np.linspace(0, L, n + 1)
    k = np.clip((co[:, 1] / L * n).astype(int), 0, n - 1)
    wx, wz = np.zeros(n), np.zeros(n)
    for i in range(n):
        m = k == i
        if m.sum() > 6:
            wx[i] = co[m, 0].max() - co[m, 0].min()
            wz[i] = co[m, 2].max() - co[m, 2].min()
    shaft = slice(int(n * 0.08), int(n * 0.45))
    d0 = float(np.median((wx[shaft] + wz[shaft]) * 0.5))
    s = cfg["shaft_d"] / d0
    # where the blade begins: from the point back, the first section that is as round as the shaft again (the collar)
    asp = wx / np.maximum(wz, 1e-6)
    ib = n - 1
    for i in range(n - 2, int(n * 0.45), -1):
        if asp[i] < 1.35 and wx[i] < d0 * 1.6:
            ib = i + 1
            break
    y_blade = float(ys[ib])
    # bring the blade back to a spear's section (it widens a little from the collar, then tapers to the point as the source does)
    f = np.clip((co[:, 1] - y_blade) / (0.02 * L) + 0.0, 0.0, 1.0)
    f = f * f * (3 - 2 * f)
    bw = float(np.quantile(np.abs(co[co[:, 1] > y_blade, 0]), 0.995) * 2) if (co[:, 1] > y_blade).any() else d0
    bt = float(np.quantile(np.abs(co[co[:, 1] > y_blade, 2]), 0.995) * 2) if (co[:, 1] > y_blade).any() else d0
    kx = cfg["blade_w"] * d0 / max(bw, 1e-6)
    kz = cfg["blade_t"] * d0 / max(bt, 1e-6)
    co[:, 0] *= 1.0 + (kx - 1.0) * f
    co[:, 2] *= 1.0 + (kz - 1.0) * f
    co *= s
    _set_co(ob.data, co)
    facts = {"length": round(L * s, 4), "shaft_d": cfg["shaft_d"], "scale": round(s, 5), "blade_from": round(y_blade * s, 4), "blade_len": round((L - y_blade) * s, 4),
             "blade_was": [round(bw * s, 4), round(bt * s, 4)], "blade_is": [round(cfg["blade_w"] * cfg["shaft_d"], 4), round(cfg["blade_t"] * cfg["shaft_d"], 4)]}
    log("  pole " + json.dumps(facts))
    return facts


def pole_low(high, name, cfg, facts, coll):
    """the head piece (everything from 0.12 m below the blade) decimated + the master shaft segment (an 8-gon prism over the real shaft, MASTER_LEN long)"""
    y_cut = facts["blade_from"] - HEAD_KEEP
    y_m0 = max(0.03, y_cut - MASTER_LEN)                           # (the source's own cut end is ragged: the master stays 3 cm clear of it)
    assert y_cut - y_m0 > 0.12, "the source shows too little shaft for the master segment"
    facts["master_len"] = round(y_cut - y_m0, 4)
    # head piece
    me = high.data.copy()
    bm = bmesh.new()
    bm.from_mesh(me)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, y_cut, 0), plane_no=(0, 1, 0), clear_inner=True, clear_outer=False)
    bm.to_mesh(me)
    bm.free()
    tmp = bpy.data.objects.new("_head_src", me)
    coll.objects.link(tmp)
    head = lowpoly.decimate(tmp, name + "_head", cfg["tris"], coll, weights=False)
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(me)
    # master segment
    r = cfg["shaft_d"] * 0.5 / math.cos(math.pi / SHAFT_SIDES) * 0.985          # the flats lie just inside the real shaft, the corners just outside
    bm = bmesh.new()
    rings = []
    for y in (y_m0, y_cut):
        rings.append([bm.verts.new((r * math.cos(2 * math.pi * i / SHAFT_SIDES), y, r * math.sin(2 * math.pi * i / SHAFT_SIDES))) for i in range(SHAFT_SIDES)])
    for i in range(SHAFT_SIDES):
        j = (i + 1) % SHAFT_SIDES
        f = bm.faces.new((rings[0][i], rings[1][i], rings[1][j], rings[0][j]))
        f.smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mm = bpy.data.meshes.new(name + "_shaft")
    bm.to_mesh(mm)
    bm.free()
    shaft = bpy.data.objects.new(name + "_shaft", mm)
    coll.objects.link(shaft)
    facts["y_cut"], facts["y_m0"], facts["shaft_r"] = round(y_cut, 4), round(y_m0, 4), round(r, 5)
    return head, shaft


# ------------------------------------------------------------------------------------------------------------------- the side arm
def canon_blade(ob, cfg, log=print):
    co = _co(ob.data)
    c, ax, var = _pca(co)
    along = ax[0]
    t = (co - c) @ along
    # the hilt end has the guard: the widest section lies nearer the pommel
    perp = (co - c) - np.outer(t, along)
    r = np.linalg.norm(perp, axis=1)
    L = float(t.max() - t.min())
    tg = float(t[np.argsort(-r)[:400]].mean())
    if tg - t.min() > 0.5 * L:
        along = -along
        t = -t
    w, v = np.linalg.eigh(np.cov(perp.T))
    wide = v[:, int(np.argmax(w))]
    wide = wide - along * (wide @ along)
    wide /= np.linalg.norm(wide)
    if cfg.get("flip"):
        along = -along
        t = -t
    s = cfg["length"] / L
    o = c + along * float(t.min())
    _frame(ob, o, wide, along, np.cross(wide, along), s)
    return {"length": cfg["length"], "scale": round(s, 5)}


def lathe_hat(high, name, coll, seg=28, rings=12, rows=5, log=print):
    """A thin-walled iron hat with a cloth neck curtain does not survive collapse decimation (two surfaces a few millimetres apart fold through each other, a
    cloth sheet tears). Its low mesh is BUILT instead, on the source's measured outer surface: the crown as a lathe of the radial profile (with a rim lip), the
    curtain as a sheet over the angles where cloth hangs, down to its own hem. Drawn two-sided; everything else (hammer marks, rivets, the cord, the gilt disc,
    the weave) is in the bake. UVs: the crown seen from above in a circle, the curtain unrolled in a strip under it."""
    co = _co(high.data)
    r = np.hypot(co[:, 0], co[:, 1])
    th = np.arctan2(co[:, 1], co[:, 0])
    z = co[:, 2]
    R = float(np.quantile(r[np.abs(z) < 0.02], 0.999))
    rs = np.linspace(0.0, R, rings)
    prof = []
    for rr in rs:
        m = (np.abs(r - rr) < R / (rings - 1) * 0.5) & (z > -0.02)
        prof.append(float(np.quantile(z[m], 0.97)) if m.sum() > 50 else (prof[-1] if prof else 0.0))
    prof[0] = float(z[r < R * 0.04].max()) if (r < R * 0.04).any() else prof[0]
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.verify()
    UV = {}

    def vert(p, uv):
        v = bm.verts.new(p)
        UV[v] = uv
        return v

    def face(vs):
        f = bm.faces.new(vs)
        f.smooth = True
        for l in f.loops:
            l[uvl].uv = UV[l.vert]

    cu, cv, cr = 0.32, 0.68, 0.30
    apex = vert((0, 0, prof[0]), (cu, cv))
    ring_v = []
    for i in range(1, rings):
        ring_v.append([vert((rs[i] * math.cos(2 * math.pi * k / seg), rs[i] * math.sin(2 * math.pi * k / seg), prof[i]),
                            (cu + cr * 0.965 * rs[i] / R * math.cos(2 * math.pi * k / seg), cv + cr * 0.965 * rs[i] / R * math.sin(2 * math.pi * k / seg))) for k in range(seg)])
    for k in range(seg):
        face((apex, ring_v[0][k], ring_v[0][(k + 1) % seg]))
    for i in range(len(ring_v) - 1):
        for k in range(seg):
            n = (k + 1) % seg
            face((ring_v[i][k], ring_v[i + 1][k], ring_v[i + 1][n], ring_v[i][n]))
    # the rim's lip: down its thickness and a little way in underneath
    zl = prof[-1] - 0.012
    lip1 = [vert((R * math.cos(2 * math.pi * k / seg), R * math.sin(2 * math.pi * k / seg), zl), (cu + cr * 0.985 * math.cos(2 * math.pi * k / seg), cv + cr * 0.985 * math.sin(2 * math.pi * k / seg))) for k in range(seg)]
    lip2 = [vert((R * 0.88 * math.cos(2 * math.pi * k / seg), R * 0.88 * math.sin(2 * math.pi * k / seg), zl + 0.002), (cu + cr * 1.0 * math.cos(2 * math.pi * k / seg), cv + cr * 1.0 * math.sin(2 * math.pi * k / seg))) for k in range(seg)]
    for k in range(seg):
        n = (k + 1) % seg
        face((ring_v[-1][k], lip1[k], lip1[n], ring_v[-1][n]))
        face((lip1[k], lip2[k], lip2[n], lip1[n]))
    # the curtain: the angles where cloth hangs below the rim
    nb = 48
    b = ((th + math.pi) / (2 * math.pi) * nb).astype(int) % nb
    low = z < -0.04
    cnt = np.bincount(b[low], minlength=nb)
    has = cnt > 0.25 * np.median(cnt[cnt > 0]) if (cnt > 0).any() else np.zeros(nb, bool)
    cols = 0
    if has.any() and not has.all():
        start = next(i for i in range(nb) if has[i] and not has[i - 1])            # the first bin of the (one) run of cloth, going round
        run = 0
        while has[(start + run) % nb] and run < nb:
            run += 1
        K = max(6, int(round(run / 2)))
        grid = []
        for c in range(K + 1):
            a = -math.pi + (start + run * c / K) * (2 * math.pi / nb)
            da = np.abs(((th - a + math.pi) % (2 * math.pi)) - math.pi)
            mcol = da < (2 * math.pi / nb) * 1.2
            hem = float(np.quantile(z[mcol & low], 0.03)) if (mcol & low).sum() > 30 else -0.15
            col = []
            for j in range(rows + 1):
                zz = -0.004 + (hem + 0.004) * j / rows
                mm = mcol & (np.abs(z - zz) < abs(hem) / rows * 0.6) & (z < 0.0)
                rr = float(np.quantile(r[mm], 0.92)) if mm.sum() > 20 else (col[-1][0] if col else R * 0.9)
                rr = min(rr, R * 0.97)
                col.append((rr, zz))
            grid.append((a, col))
        vv = [[vert((rr * math.cos(a), rr * math.sin(a), zz), (0.02 + 0.96 * c / K, 0.33 - 0.30 * j / rows)) for j, (rr, zz) in enumerate(col)] for c, (a, col) in enumerate(grid)]
        for c in range(K):
            for j in range(rows):
                face((vv[c][j], vv[c][j + 1], vv[c + 1][j + 1], vv[c + 1][j]))
        cols = K
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.uv_layers[0].name = "UVMap"
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    log(f"  lathe: rim radius {R:.3f} m, apex {prof[0]:.3f} m, curtain over {cols} columns")
    return ob


# ------------------------------------------------------------------------------------------------------------------- run
def _unwrap(ob, margin=0.012, keep=None):
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    if not ob.data.uv_layers:
        ob.data.uv_layers.new(name="UVMap")
    ob.data.uv_layers[0].name = "UVMap"
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    if keep is None:
        bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=margin, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.select_all(action="SELECT")
    try:
        bpy.ops.uv.pack_islands(rotate=True, margin=margin, shape_method="CONCAVE")
    except TypeError:
        bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


def run_one(unit, name, src, work, log=print):
    cfg = PROPS[unit][name]
    out = os.path.join(work, unit, "props")
    os.makedirs(out, exist_ok=True)
    ingest.reset_scene()
    high = ingest.import_glb(src)
    sc = bpy.context.scene
    coll = sc.collection
    facts = {"name": name, "kind": cfg["kind"], "tris_in": len(high.data.polygons)}
    # an image-to-3D mesh is split along every UV seam (thousands of islands): unwelded it decimates into shards
    cl = ingest.clean(high, min_shell_frac=0.0)
    facts["welded"] = [cl["verts_in"], cl["verts_welded"]]
    if cfg["kind"] == "hat":
        facts.update(canon_hat(high, cfg, log))
    elif cfg["kind"] == "pole":
        facts.update(canon_pole(high, cfg, log))
    else:
        facts.update(canon_blade(high, cfg, log))
    for p in high.data.polygons:
        p.use_smooth = True
    node = "".join(w.capitalize() for w in name.split("_"))
    if cfg["kind"] == "pole":
        head, shaft = pole_low(high, node, cfg, facts, coll)
        _unwrap(head)
        # the shaft's rectangle: u around, v along (its own island, scaled like the rest by the packer)
        shaft.data.uv_layers.new(name="UVMap")
        uvl = shaft.data.uv_layers["UVMap"].data
        circ = 2 * math.pi * facts["shaft_r"]
        for p in shaft.data.polygons:
            for li, vi in zip(p.loop_indices, p.vertices):
                v = shaft.data.vertices[vi].co
                a = (math.atan2(v.z, v.x) / (2 * math.pi)) % 1.0
                uvl[li].uv = (a * circ, v.y)
        # the seam: faces that wrap from the last side to the first
        for p in shaft.data.polygons:
            us = [uvl[li].uv.x for li in p.loop_indices]
            if max(us) - min(us) > circ * 0.5:
                for li in p.loop_indices:
                    if uvl[li].uv.x < circ * 0.5:
                        uvl[li].uv.x += circ
        for o in bpy.context.view_layer.objects:
            if o is not None:
                o.select_set(False)
        head.select_set(True)
        shaft.select_set(True)
        bpy.context.view_layer.objects.active = head
        nh = len(head.data.polygons)
        bpy.ops.object.join()
        low = head
        low.name = low.data.name = node
        fm = low.data.attributes.new("master", "INT", "FACE")       # 1 on the master shaft segment's faces
        vals = np.zeros(len(low.data.polygons), dtype=np.int32)
        vals[nh:] = 1
        fm.data.foreach_set("value", vals)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.select_all(action="SELECT")
        bpy.ops.uv.average_islands_scale()
        bpy.ops.uv.pack_islands(rotate=True, margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
    else:
        if cfg.get("lathe"):
            low = lathe_hat(high, node, coll, log=log)
        else:
            low = lowpoly.decimate(high, node, cfg["tris"], coll, weights=False)
            _unwrap(low)
    facts["tris"] = sum(len(p.vertices) - 2 for p in low.data.polygons)
    tex = os.path.join(out, name + "_tex")
    old_cage, old_ray = bake.CAGE, bake.RAY
    maps, bstats = bake.bake_all(high, low, tex, px=cfg["px"], ao_samples=32, log=lambda *_: None)
    facts["bake"] = bstats
    from recipes import _common as C
    mat = C.pbr_material("prop_" + name, maps, double_sided=cfg["kind"] == "hat")
    low.data.materials.clear()
    low.data.materials.append(mat)
    lo, hi = qa.bounds([low])
    facts["bounds"] = {"min": [round(v, 4) for v in lo], "max": [round(v, 4) for v in hi]}
    qa.VIEWS.update({"pa": (0.8, -1, 0.5), "pb": (-0.8, 1, 0.4), "pc": (0.3, -0.2, -1), "pd": (0, -1, 0.02), "pe": (1, 0, 0.02), "pf": (0, 0, 1)})
    views = ("pa", "pb", "pc", "pd") if cfg["kind"] == "hat" else ("pf", "pe", "pa")
    hi_shots = qa.shots([high], os.path.join(out, "qa", name + "_high"), views=views, size=700)
    lo_shots = qa.shots([low], os.path.join(out, "qa", name + "_low"), views=views, size=700)
    qa.sheet(hi_shots + lo_shots, os.path.join(out, "qa", name + "_sheet.jpg"), cols=len(views))
    for p in hi_shots + lo_shots:
        os.remove(p)
    bpy.data.objects.remove(high, do_unlink=True)
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, name + ".blend"), compress=True)
    with open(os.path.join(out, name + ".json"), "w") as fh:
        json.dump(facts, fh, indent=1)
    log("PROP " + json.dumps(facts))
    return facts


def run(cfg, work, only=None, rel=lambda p: p, log=print):
    for name, p in cfg["props"].items():
        if only and name not in only:
            continue
        run_one(cfg["unit"], name, rel(os.path.join(cfg["src_dir"], p["src"])), work, log)
