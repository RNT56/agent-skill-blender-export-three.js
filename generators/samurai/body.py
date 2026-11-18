"""Soft body layers: head, hands, hemp under-robe, trousers, leg wraps, tabi + sandals, sash. All in A-pose rest."""
import math

from mathutils import Matrix, Vector

from . import rig as R
from .kit import Part, bezier, catmull, lerp, ring, sstep

V = Vector


def _norm(r):
    r = list(r)
    d = [None, None, None, 2.0, 0.0, 0.0]
    while len(r) < 6:
        r.append(d[len(r)])
    return r


def prof(*rows):
    """Piecewise-linear section profile: rows of (t, rx, ry[, p, ox, oy]) -> f(t) = (rx, ry, p, ox, oy)."""
    rows = [_norm(r) for r in rows]

    def f(t):
        if t <= rows[0][0]:
            return tuple(rows[0][1:])
        for a, b in zip(rows, rows[1:]):
            if t <= b[0]:
                u = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
                return tuple(lerp(a[i], b[i], u) for i in range(1, 6))
        return tuple(rows[-1][1:])
    return f


# ------------------------------------------------------------------------------------------------------------- head
HEAD_ROWS = ((0.00, 0.010, 0.018, -0.070), (0.05, 0.034, 0.046, -0.050), (0.14, 0.056, 0.066, -0.036), (0.28, 0.070, 0.086, -0.020),
             (0.45, 0.077, 0.098, -0.012), (0.70, 0.078, 0.100, -0.010), (0.90, 0.064, 0.086, -0.012), (1.00, 0.020, 0.030, -0.012))
HEAD_Z0, HEAD_Z1 = 1.522, 1.758


def head_radii(z):
    """(rx, ry, cy) of the bare head at height z (shared with the menpo so the mask hugs it)."""
    t = min(max((z - HEAD_Z0) / (HEAD_Z1 - HEAD_Z0), 0.0), 1.0)
    for a, b in zip(HEAD_ROWS, HEAD_ROWS[1:]):
        if t <= b[0]:
            u = (t - a[0]) / (b[0] - a[0])
            return tuple(lerp(a[i], b[i], u) for i in (1, 2, 3))
    return HEAD_ROWS[-1][1:]


def head_part():
    """Skin head + neck: a sculpted ellipsoid; the menpo and kabuto hide most of it, the brow/eye band stays visible."""
    P = Part("body_head", "skin", bone="head", sharp=80)
    # rows and columns are dense only where the face shows (brow / eye band 1.59-1.70 m, the front +-70 degrees): the mask, the visor and the bowl hide the rest
    zs = [HEAD_Z0 + 0.034 * k for k in range(1, 3)] + [1.590 + 0.007 * k for k in range(17)] + [1.730, 1.752]
    angles = [0, 40, 80, 120, 160, 190] + list(range(205, 336, 10)) + [350]
    rings = []
    for z in zs:
        rx, ry, cy = head_radii(z)
        ring_pts = []
        for ad in angles:
            a = math.radians(ad)
            ca, sa = math.cos(a), math.sin(a)          # a=0 -> +X (left), a=-90deg -> front (-Y)
            x, y = ca * rx, sa * ry
            front = max(0.0, -sa)
            brow = math.exp(-((z - 1.668) / 0.012) ** 2) * math.exp(-(x / 0.058) ** 2) * 0.010
            nose = math.exp(-((z - 1.622) / 0.020) ** 2) * math.exp(-(x / 0.011) ** 2) * 0.022
            bridge = math.exp(-((z - 1.655) / 0.018) ** 2) * math.exp(-(x / 0.012) ** 2) * 0.010
            socket = -(math.exp(-((z - 1.652) / 0.009) ** 2) * math.exp(-((abs(x) - 0.031) / 0.014) ** 2)) * 0.006
            cheek = math.exp(-((z - 1.605) / 0.022) ** 2) * math.exp(-((abs(x) - 0.052) / 0.016) ** 2) * 0.006
            y -= front * (brow + nose + bridge + socket + cheek)
            ring_pts.append(V((x, cy + y, z)))
        rings.append(ring_pts)
    P.loft(rings, True, (True, True), uvscale=(1.0, 1.0))
    P.tube([V((0, -0.002, 1.40)), V((0, -0.007, 1.54))], lambda t: (0.054, 0.056), 12, (True, True))
    return P


def eyes_part():
    """Almond eyes: thin sclera, small iris, skin eyelids above and below, a dark brow ridge. Under the visor brim, above the mask."""
    P = Part("body_eyes", "eye", bone="head", sharp=80)
    I = Part("body_iris", "iris", bone="head", sharp=80)
    L = Part("body_lids", "skin", bone="head", sharp=80)
    Bw = Part("body_brow", "hair", bone="head", sharp=80)
    Ln = Part("body_lash", "iris", bone="head", sharp=80)
    for sx in (1, -1):
        cx, cy, cz = sx * 0.031, -0.099, 1.652
        P.sphere((cx, cy, cz), 0.0125, 0.0046, 0.0050, 8, 5)                        # sclera: 25 mm wide
        I.sphere((cx - sx * 0.0004, cy - 0.0030, cz - 0.0004), 0.0047, 0.0030, 0.0047, 7, 4)       # iris, partly hidden by the lids: a calm, hard stare
        L.sphere((cx, cy - 0.0018, cz + 0.0053), 0.0133, 0.0060, 0.0034, 6, 3)       # upper lid, covers the top quarter of the iris
        L.sphere((cx, cy - 0.0014, cz - 0.0049), 0.0125, 0.0052, 0.0024, 6, 3)       # lower lid
        lash = [V((sx * 0.0185, cy - 0.0050, cz + 0.0012)), V((sx * 0.0310, cy - 0.0069, cz + 0.0040)), V((sx * 0.0445, cy - 0.0046, cz + 0.0016))]
        Ln.tube(catmull(lash, 2), lambda t: (0.0011, 0.0011), 4, (True, True))      # dark lash line along the upper lid
        pts = [V((sx * 0.011, -0.1065, 1.665)), V((sx * 0.031, -0.1105, 1.676)), V((sx * 0.055, -0.1000, 1.682))]      # stern brow: low and thick at the nose, lifted at the temple
        Bw.tube(catmull(pts, 3), lambda t: (0.0058 - 0.0016 * t, 0.0036), 6, (True, True))
    return [P, I, L, Bw, Ln]


def _finger(F, h1, t1, t2, nrm, r0, lens=(0.5, 0.30, 0.20), curl=0.5):
    """One finger as a single smooth sweep: proximal / middle / distal phalanges, swelling at the knuckles, the distal segment curling toward the palm."""
    p1 = V(t1)
    seg = (V(t2) - p1)
    m = p1 + seg * (lens[1] / (lens[1] + lens[2]))
    tip = V(t2) + V(nrm) * (0.006 * curl)
    pts = catmull([V(h1), p1, m, tip], 3)
    n = len(pts)

    def sec(t):
        sw = 1.0 + 0.16 * math.exp(-((t - 0.33) / 0.07) ** 2) + 0.12 * math.exp(-((t - 0.64) / 0.06) ** 2)      # knuckle swelling
        r = r0 * (1.0 - 0.34 * t) * sw
        return (r, r * 0.86, 2.2)

    F.tube(pts, sec, 6, (True, True))
    F.sphere(tip, r0 * 0.60, r0 * 0.55, r0 * 0.55, 5, 3)                       # rounded fingertip pad


def hand_parts(side, rig_table):
    """Palm (rigid) + five soft fingers built from the rig's own bone positions (so skinning and mesh agree)."""
    P = Part(f"body_hand_{side}", "skin", bone=f"hand.{side}", sharp=80)
    sx = 1.0 if side == "L" else -1.0
    bones = {n: (h, t) for n, p, h, t in rig_table}
    wr, tip = bones[f"hand.{side}"]
    d = (tip - wr).normalized()
    nrm = V((-sx, 0, 0)) - d * (V((-sx, 0, 0)).dot(d))
    nrm.normalize()
    lat = d.cross(nrm).normalized()
    ln = (tip - wr).length
    rings = []
    for t, hw, th, dorsal in ((0.0, 0.029, 0.017, 0.0), (0.22, 0.036, 0.021, 0.002), (0.55, 0.042, 0.021, 0.003), (0.85, 0.045, 0.018, 0.004), (1.0, 0.044, 0.015, 0.003)):
        c = wr + d * (ln * t) - nrm * dorsal
        rings.append(ring(c, lat, nrm, hw, th, 10, 2.5))
    P.loft(rings, True, (True, True))
    th1, _ = bones[f"thumb_01.{side}"]
    P.sphere(wr.lerp(th1, 0.62) + nrm * 0.006, 0.020, 0.020, 0.016, 8, 5)       # thenar mass at the thumb base
    out = [P]
    radii = {"index": 0.0098, "middle": 0.0102, "ring": 0.0096, "pinky": 0.0084}
    lens = {"index": (0.5, 0.30, 0.20), "middle": (0.5, 0.31, 0.19), "ring": (0.5, 0.30, 0.20), "pinky": (0.5, 0.29, 0.21)}
    for fn in ("index", "middle", "ring", "pinky"):
        h1, t1 = bones[f"{fn}_01.{side}"]
        h2, t2 = bones[f"{fn}_02.{side}"]
        F = Part(f"body_{fn}_{side}", "skin", soft=f"fing:{fn}.{side}", sharp=80)
        _finger(F, h1, t1, t2, nrm, radii[fn], lens[fn])
        out.append(F)
    h1, t1 = bones[f"thumb_01.{side}"]
    h2, t2 = bones[f"thumb_02.{side}"]
    F = Part(f"body_thumb_{side}", "skin", soft=f"fing:thumb.{side}", sharp=80)
    _finger(F, h1, t1, t2, nrm, 0.0125, (0.55, 0.25, 0.20), curl=0.8)
    out.append(F)
    return out


# ------------------------------------------------------------------------------------------------------------- cloth
def torso_robe():
    """Kosode: torso tube + two sleeves + collar. Dark indigo hemp."""
    P = Part("cloth_robe", "hemp", soft="torso")
    rings = []
    for z, a, b in zip(R.TORSO_Z, R.TORSO_RX, R.TORSO_RY):
        rings.append(ring(V((0, -0.004, z)), V((1, 0, 0)), V((0, 1, 0)), a, b, 18, 2.5))
    P.loft(rings, True, (True, True), uvscale=(1.0, 1.0))
    # collar band
    P.tube([V((0, -0.006, 1.395)), V((0, -0.012, 1.475))], lambda t: (0.066 - 0.008 * t, 0.07 - 0.008 * t), 12, (True, True))
    return P


def sleeve_part(side):
    P = Part(f"cloth_sleeve_{side}", "hemp", soft=f"arm.{side}")
    sx = 1.0 if side == "L" else -1.0
    sh, el, wr, tip, d = R._arm_points()
    path = catmull([V((0.115, 0.0, 1.415)), sh, el, wr + d * 0.02], 5)
    path = [V((p.x * sx, p.y, p.z)) for p in path]
    P.tube(path, prof((0.0, 0.070, 0.074), (0.3, 0.066, 0.068), (0.62, 0.056, 0.058), (1.0, 0.049, 0.050)), 12, (True, True))
    return P


def sash_part():
    """Obi: wrapped hemp band with a knot and two short tails at the left front."""
    P = Part("cloth_sash", "sash", soft="torso")
    rings = []
    for z, wob in ((0.985, 0.0), (1.00, 1.0), (1.03, 0.6), (1.06, 0.8), (1.085, 0.5), (1.10, 0.0)):
        base_rx, base_ry = 0.165, 0.121
        rr = []
        for j in range(24):
            a = math.tau * j / 24
            k = 1.0 + 0.020 * wob * math.sin(a * 5 + z * 40)
            rr.append(V((math.cos(a) * base_rx * k, -0.004 + math.sin(a) * base_ry * k, z)))
        rings.append(rr)
    P.loft(rings, True, (True, True))
    # knot (left-front); the two tails are their own parts (sash_tail_parts)
    P.sphere((0.075, -0.132, 1.04), 0.046, 0.030, 0.040, 10, 6)
    return P


def sash_tail_parts():
    """The two obi tails (separate parts: the cloth simulation drives them). Five rings on two bones: each bone owns two ring spans, so the tail bends instead of kinking."""
    from . import cloth as C
    out = []
    for key in "ab":
        j0, j1, j2 = C.sash_joints(key)
        T = Part(f"cloth_sash_tail_{key}", "sash", soft=f"tail:{key}")
        T.tube([j0, (j0 + j1) * 0.5, j1, (j1 + j2) * 0.5, j2], lambda t: (0.020 - 0.004 * t, 0.006), 6, (True, True))
        out.append(T)
    return out


def _lc(z, sx):
    x, y = R.leg_center(z)
    return V((x * sx, y, z))


def trouser_part(side):
    """Baggy trousers gathered below the knee, one leg."""
    P = Part(f"cloth_trouser_{side}", "hemp", soft=f"leg.{side}")
    sx = 1.0 if side == "L" else -1.0
    path = [_lc(z, sx) for z in (0.93, 0.80, 0.64, 0.53, 0.485, 0.455)]
    P.tube(path, prof((0.0, 0.106, 0.110), (0.22, 0.112, 0.118), (0.55, 0.114, 0.120), (0.80, 0.104, 0.108), (0.92, 0.078, 0.080), (1.0, 0.064, 0.066)),
           12, (True, True))
    return P


def leg_wrap_part(side):
    """Kyahan leg wrap + gather tie: tapered calf tube from knee to ankle."""
    P = Part(f"cloth_wrap_{side}", "hemp", soft=f"leg.{side}")
    sx = 1.0 if side == "L" else -1.0
    path = [_lc(z, sx) for z in (0.47, 0.33, 0.20, 0.09)]
    P.tube(path, prof((0.0, 0.054, 0.056), (0.35, 0.055, 0.060), (0.75, 0.046, 0.046), (1.0, 0.042, 0.044)), 10, (True, True))
    P.tube([_lc(0.462, sx), _lc(0.448, sx)], lambda t: (0.071, 0.073), 14, (True, True))
    return P


def foot_part(side):
    """Tabi (cloth sock) foot."""
    P = Part(f"cloth_foot_{side}", "hemp", bone=f"foot.{side}", sharp=60)
    sx = 1.0 if side == "L" else -1.0
    fx = R.LEG_PTS[-1][1] * sx
    path = [V((fx, 0.050, 0.075)), V((fx, 0.000, 0.060)), V((fx, -0.070, 0.048)), V((fx, -0.130, 0.040)), V((fx, -0.200, 0.028))]
    P.tube(path, prof((0.0, 0.040, 0.045, 2.2, 0, 0.012), (0.3, 0.043, 0.040, 2.3, 0, 0.004), (0.65, 0.047, 0.027, 2.6),
                      (0.9, 0.044, 0.020, 2.8), (1.0, 0.030, 0.016, 2.6)), 10, (True, True))
    return P


def sandal_parts(side):
    """Waraji: straw sole + rope ties."""
    sx = 1.0 if side == "L" else -1.0
    fx = R.LEG_PTS[-1][1]
    S = Part(f"straw_sole_{side}", "straw", bone=f"foot.{side}", sharp=50)
    rings = []
    ys = (0.085, 0.06, 0.0, -0.08, -0.15, -0.225, -0.255)
    ws = (0.036, 0.050, 0.058, 0.060, 0.058, 0.046, 0.016)
    for y, w in zip(ys, ws):
        rings.append(ring(V((fx * sx, y, 0.008)), V((1, 0, 0)), V((0, 0, 1)), w, 0.008, 10, 3.0))
    S.loft(rings, True, (True, True), uvscale=(6.0, 6.0))
    T = Part(f"straw_ties_{side}", "straw", bone=f"foot.{side}", sharp=60)
    for a, b, c in (((-0.050, 0.050, 0.010), (-0.035, 0.035, 0.070), (0.0, 0.018, 0.098)),
                    ((0.050, 0.050, 0.010), (0.038, 0.035, 0.070), (0.0, 0.018, 0.098)),
                    ((-0.015, -0.150, 0.012), (-0.008, -0.120, 0.052), (0.0, -0.090, 0.058)),
                    ((0.015, -0.150, 0.012), (0.008, -0.120, 0.052), (0.0, -0.090, 0.058))):
        pts = [V(((fx + p[0]) * sx, p[1], p[2])) for p in (a, b, c)]
        T.tube(catmull(pts, 4), lambda t: (0.0055, 0.0055), 6, (True, True))
    return [S, T]


def all_soft(rig_table):
    parts = [head_part()] + eyes_part() + [torso_robe(), sash_part()] + sash_tail_parts()
    for sd in ("L", "R"):
        parts += hand_parts(sd, rig_table)
        parts += [sleeve_part(sd), trouser_part(sd), leg_wrap_part(sd), foot_part(sd)]
        parts += sandal_parts(sd)
    return parts
