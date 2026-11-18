"""Armour: do (cuirass), watagami, kusazuri, haidate, suneate, kote, sode, kabuto, menpo. All A-pose rest.

Lamellar tiers are `Part.strip` bands: plates with laced grooves between them; the procedural 'lamellar' material reads the
pattern UV (plate units, row) so cords and lacing bands line up with the geometry. Rigid parts name their one bone; the dō rows
are bound per row to spine / spine1 / chest so the torso can bend between rows without bending a plate.
"""
import math

from mathutils import Matrix, Vector

from . import body, rig as R
from .kit import Part, bezier, catmull, frame_from, lerp, param_surf, ring, sstep

V = Vector
MIRROR_X = Matrix.Scale(-1, 4, Vector((1, 0, 0)))


def AX(x, y):
    """Inner-axis reference for param_surf: a vertical axis through (x, y)."""
    return lambda p: V((x, y, p.z))


TORSO_AX = AX(0.0, -0.004)
HEAD_AX = AX(0.0, -0.014)

# kosode torso section (shared with body.torso_robe): the armour is an offset of it
ZS, RX, RY = R.TORSO_Z, R.TORSO_RX, R.TORSO_RY


def torso_at(z):
    z = min(max(z, ZS[0]), ZS[-1])
    for i in range(len(ZS) - 1):
        if z <= ZS[i + 1]:
            u = (z - ZS[i]) / (ZS[i + 1] - ZS[i])
            return lerp(RX[i], RX[i + 1], u), lerp(RY[i], RY[i + 1], u)
    return RX[-1], RY[-1]


def sup(a, rx, ry, p=2.5):
    c, s = math.cos(a), math.sin(a)
    e = 2.0 / p
    return rx * math.copysign(abs(c) ** e, c), ry * math.copysign(abs(s) ** e, s)


def row_bone(zc):
    return "chest" if zc > 1.27 else ("spine1" if zc > 1.15 else "spine")


# ------------------------------------------------------------------------------------------------------------- do
ARMHOLE = 40.0                 # degrees of the side opening on each flank for rows above the armpit


def do_arcs(full):
    """Angle ranges (degrees, a=270 is the front) of one dō row: a full ring, or front + back arcs that leave the armholes open."""
    if full:
        return [(-90.0 - 180.0, -90.0 + 180.0)]
    return [(180.0 + ARMHOLE, 360.0 - ARMHOLE), (ARMHOLE, 180.0 - ARMHOLE)]


def do_parts():
    parts = []
    N, top, rows = 32, 1.402, 7
    h = (top - 1.10) / rows
    for r in range(rows):
        z0, z1 = top - r * h, top - (r + 1) * h
        off = 0.016 + 0.0022 * r
        full = (z0 + z1) / 2 < 1.20
        for k, (a0, a1) in enumerate(do_arcs(full)):
            P = Part(f"armor_do_{r}_{k}", "lamellar" if r >= 2 else "lacquer", bone=row_bone((z0 + z1) / 2))
            smooth = r < 2
            n = max(2, round((48 if smooth else N) * (a1 - a0) / 360.0))

            def fn(s, v, off=off, a0=a0, a1=a1, n=n):
                a = math.radians(lerp(a0, a1, s / n))
                rx, ry = torso_at(v)
                x, y = sup(a, rx + off, ry + off)
                return V((x, -0.004 + y, v))

            closed = full
            if smooth:
                P.strip(param_surf(fn, inside=TORSO_AX), n, z0, z1, nv=1, relief=0.0, thick=0.006, groove=None, closed=closed, row=r)
            else:
                P.strip(param_surf(fn, inside=TORSO_AX), n, z0, z1, nv=1, relief=0.0028, thick=0.006, groove=0.15, closed=closed, row=r)
            parts.append(P)
    # gold trim top (arcs) and bottom (ring)
    for tag, zc, off, full in (("top", 1.402, 0.0185, False), ("bot", 1.10, 0.0185 + 0.0022 * 6, True)):
        for k, (a0, a1) in enumerate(do_arcs(full)):
            G = Part(f"armor_do_trim_{tag}_{k}", "gold", bone=row_bone(zc + (0.02 if tag == "top" else -0.02)))
            n = max(2, round(48 * (a1 - a0) / 360.0))

            def fn(s, v, off=off, a0=a0, a1=a1, n=n):
                a = math.radians(lerp(a0, a1, s / n))
                rx, ry = torso_at(v)
                x, y = sup(a, rx + off, ry + off)
                return V((x, -0.004 + y, v))

            G.strip(param_surf(fn, inside=TORSO_AX), n, zc - 0.007, zc + 0.007, nv=1, relief=0.0, thick=0.005, groove=None, closed=full)
            parts.append(G)
    # shoulder straps (watagami) lie ON the dō surface, over the shoulder, with gold buckles
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        S = Part(f"armor_watagami_{sd}", "lacquer", bone="chest")
        xs = 0.082
        fy = torso_at(1.34)[1] + 0.040
        by = torso_at(1.34)[1] + 0.040
        pts = [V((xs * sx, -0.004 - fy, 1.33)), V((xs * sx, -0.004 - fy * 0.72, 1.440)), V((xs * sx, -0.004, 1.497)),
               V((xs * sx, -0.004 + by * 0.72, 1.440)), V((xs * sx, -0.004 + by, 1.33))]
        S.tube(catmull(pts, 4), lambda t: (0.027, 0.0065, 4.0), 8, (True, True))
        parts.append(S)
        B = Part(f"armor_buckle_{sd}", "gold", bone="chest")
        B.box((xs * sx, -0.004 - fy - 0.004, 1.33), 0.020, 0.0045, 0.022)
        B.box((xs * sx, -0.004 + by + 0.004, 1.33), 0.020, 0.0045, 0.022)
        parts.append(B)
    return parts


# ------------------------------------------------------------------------------------------------------------- kusazuri
def skirt_parts():
    parts = []
    centers = (-67.5, -22.5, 22.5, 67.5)
    bones = ("skirt_front", "skirt_side", "skirt_side", "skirt_back")
    for sd in ("L", "R"):
        for pi, (c, b) in enumerate(zip(centers, bones)):
            a0, a1 = math.radians(c - 21.0), math.radians(c + 21.0)
            for tier in range(4):
                z0 = 0.985 - tier * 0.060
                z1 = z0 - 0.066
                off = 0.018 + 0.0045 * tier
                P = Part(f"armor_skirt_{sd}{pi}_{tier}", "lamellar", bone=f"{b}.{sd}")

                def fn(s, v, off=off, a0=a0, a1=a1):
                    a = lerp(a0, a1, s / 5.0)
                    f = (0.985 - v) / 0.30
                    rx = 0.170 + 0.092 * f + off
                    ry = 0.126 + 0.010 * f + off
                    x, y = sup(a, rx, ry, 2.4)
                    return V((x, -0.004 + y, v))

                if sd == "R":
                    P.push(MIRROR_X)
                P.strip(param_surf(fn, inside=TORSO_AX), 5, z0, z1, nv=1, relief=0.0026, thick=0.0045, groove=0.15, row=tier + 8 * (1 if c < 0 else 0))
                if sd == "R":
                    P.pop()
                parts.append(P)
    return parts


def haidate_parts():
    parts = []
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        for tier in range(3):
            z0 = 0.742 - tier * 0.056
            z1 = z0 - 0.062
            off = 0.016 + 0.003 * tier
            P = Part(f"armor_haidate_{sd}_{tier}", "lamellar", bone=f"thigh.{sd}")

            def fn(s, v, off=off):
                a = math.radians(lerp(-160.0, -20.0, s / 7.0))
                cx, cy = R.leg_center(v)
                rx, ry = 0.106 + off, 0.112 + off
                x, y = sup(a, rx, ry, 2.2)
                return V((sx * cx + x * sx, cy - 0.006 + y, v))

            P.strip(param_surf(fn, inside=lambda p, sx=sx: V((sx * R.leg_center(p.z)[0], R.leg_center(p.z)[1] - 0.006, p.z))), 7, z0, z1, nv=1, relief=0.0026, thick=0.0045, groove=0.15, row=tier + 20)
            parts.append(P)
    return parts


# ------------------------------------------------------------------------------------------------------------- suneate / kote
def shin_at(z):
    t = min(max((0.47 - z) / 0.38, 0.0), 1.0)
    cx, cy = R.leg_center(z)
    keys = ((0.0, 0.056, 0.058), (0.35, 0.058, 0.064), (0.75, 0.048, 0.048), (1.0, 0.043, 0.045))
    for a, b in zip(keys, keys[1:]):
        if t <= b[0]:
            u = (t - a[0]) / (b[0] - a[0])
            return cx, cy, lerp(a[1], b[1], u), lerp(a[2], b[2], u)
    return cx, cy, keys[-1][1], keys[-1][2]


def suneate_parts():
    parts = []
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        P = Part(f"armor_suneate_{sd}", "iron", bone=f"shin.{sd}")

        def fn(s, v):
            a = math.radians(lerp(-165.0, -15.0, s / 6.0))
            cx, cy, rx, ry = shin_at(v)
            x, y = sup(a, rx + 0.011, ry + 0.011, 2.2)
            return V((sx * cx + sx * x, cy + y, v))

        P.strip(param_surf(fn, inside=lambda p, sx=sx: V((sx * shin_at(p.z)[0], shin_at(p.z)[1], p.z))), 6, 0.105, 0.445, nv=3, relief=0.0035, thick=0.0045, groove=0.12)
        parts.append(P)
        # cord bands + knee flare
        for k, zc in enumerate((0.385, 0.255, 0.135)):
            B = Part(f"armor_suneate_tie_{sd}{k}", "lacing", bone=f"shin.{sd}")

            def fb(s, v, zc=zc):
                a = -math.pi / 2 + s / 28 * math.tau
                cx, cy, rx, ry = shin_at(v)
                x, y = sup(a, rx + 0.016, ry + 0.016, 2.2)
                return V((sx * cx + sx * x, cy + y, v))

            B.strip(param_surf(fb, inside=lambda p, sx=sx: V((sx * shin_at(p.z)[0], shin_at(p.z)[1], p.z))), 28, zc - 0.008, zc + 0.008, nv=1, relief=0.0, thick=0.004, groove=None, closed=True)
            parts.append(B)
    return parts


def kote_parts():
    parts = []
    sh, el, wr, tip, d = R._arm_points()
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        e = V((el.x * sx, el.y, el.z))
        w = V((wr.x * sx, wr.y, wr.z))
        axis = (w - e).normalized()
        out = V((sx, 0, 0))
        ex = (out - axis * out.dot(axis)).normalized()        # outward
        ey = axis.cross(ex).normalized()
        P = Part(f"armor_kote_{sd}", "lacquer", bone=f"forearm.{sd}")

        def fn(s, v):
            a = math.radians(lerp(-96.0, 96.0, s / 6.0))
            c = e + (w - e) * v
            r0 = lerp(0.060, 0.050, v)
            return c + ex * (math.cos(a) * (r0 + 0.0065)) + ey * (math.sin(a) * (r0 + 0.0065) * 0.95)

        P.strip(param_surf(fn, inside=lambda p, e=e, axis=axis: e + axis * (p - e).dot(axis)), 6, 0.07, 0.95, nv=3, relief=0.0026, thick=0.0040, groove=0.14)
        parts.append(P)
        # elbow cup + wrist cord wraps
        C = Part(f"armor_kote_cup_{sd}", "lacing", bone=f"forearm.{sd}")
        for v0, v1 in ((0.012, 0.075), (0.90, 0.985)):
            def fw(s, v):
                a = s / 24 * math.tau
                c = e + (w - e) * v
                r0 = lerp(0.060, 0.052, v)
                return c + ex * (math.cos(a) * (r0 + 0.007)) + ey * (math.sin(a) * (r0 + 0.007))
            C.strip(param_surf(fw, inside=lambda p, e=e, axis=axis: e + axis * (p - e).dot(axis)), 24, v0, v1, nv=1, relief=0.0, thick=0.004, groove=None, closed=True)
        parts.append(C)
        # tekko: back-of-hand plate
        T = Part(f"armor_tekko_{sd}", "lacquer", bone=f"hand.{sd}")
        hd = (tip - wr).normalized()
        hd = V((hd.x * sx, hd.y, hd.z))
        palm = V((-sx, 0, 0))
        nrm = (palm - hd * palm.dot(hd)).normalized()
        back = -nrm
        lat = hd.cross(nrm).normalized()
        wp = V((wr.x * sx, wr.y, wr.z))

        def ft(u, v):
            c = wp + hd * (0.030 + 0.072 * v)
            hw = lerp(0.030, 0.042, v)
            bulge = 0.010 * (1 - (2 * u - 1) ** 2)
            return c + lat * ((u - 0.5) * 2 * hw) + back * (0.020 + bulge)

        T.slab(param_surf(ft, inside=lambda p, wp=wp, hd=hd: wp + hd * (p - wp).dot(hd)), 4, 3, 0.004, chamfer=0.06)
        parts.append(T)
    return parts


# ------------------------------------------------------------------------------------------------------------- sode
def sode_parts():
    """Shoulder guards: six laced tiers hanging as a shell AROUND the upper-arm axis (so they clear the sleeve by construction)."""
    parts = []
    tiers = 6
    sh, el, wr, tip, d = R._arm_points()
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        S0 = V((sh.x * sx, sh.y, sh.z))
        E0 = V((el.x * sx, el.y, el.z))
        axis = (E0 - S0).normalized()
        out = V((sx, 0.0, 0.0))
        ex = (out - axis * out.dot(axis)).normalized()
        ey = axis.cross(ex).normalized()
        H = 0.275

        def sleeve_r(pos):
            return lerp(0.074, 0.060, min(max(pos / 0.29, 0.0), 1.0))

        def shell(s, v, k=0, plates=7, extra=0.0):
            pos = -0.035 + v * H
            top = 1 - min(max(v, 0.0) * 3.0, 1.0)                    # the first tier arches over the shoulder
            phi = math.radians(lerp(-108.0 - 10.0 * top, 108.0 + 10.0 * top, s / plates))
            r = sleeve_r(max(pos, 0.0)) + 0.022 + 0.020 * v + 0.0035 * k + extra
            c = S0 + axis * pos
            return c + ex * (math.cos(phi) * r) + ey * (math.sin(phi) * r * 1.22) + V((0, 0, 0.010 * top))

        inside_axis = lambda p, S0=S0, axis=axis: S0 + axis * (p - S0).dot(axis)
        for k in range(tiers):
            v0, v1 = k / tiers, (k + 1) / tiers + 0.025
            P = Part(f"armor_sode_{sd}_{k}", "lamellar", bone=f"sode.{sd}")
            P.strip(param_surf(lambda s, v, k=k: shell(s, v, k), inside=inside_axis), 7, v0, v1, nv=1, relief=0.0028, thick=0.0045,
                    groove=0.15, row=30 + k)
            parts.append(P)
        G = Part(f"armor_sode_trim_{sd}", "gold", bone=f"sode.{sd}")
        G.strip(param_surf(lambda s, v: shell(s, 1.0 + v * 0.0, 5, 14, 0.006) + V((0, 0, -0.0)) + axis * (v * 1.0), inside=inside_axis),
                14, -0.007, 0.007, nv=1, relief=0.0, thick=0.004, groove=None)
        parts.append(G)
    return parts


# ------------------------------------------------------------------------------------------------------------- kabuto
HB_Z, HB_CY = 1.668, -0.014


def kabuto_parts():
    parts = []
    # bowl with 24 ridged plates
    Pb = Part("armor_kabuto_bowl", "lacquer", bone="head")
    zt = 1.795

    def fb(s, v):
        a = -math.pi / 2 + (s - 0.5) / 24 * math.tau
        phi = v * (math.pi / 2) * 0.93
        k = math.cos(phi)
        x, y = sup(a, 0.094 * k + 0.0 * v, 0.114 * k, 2.15)
        return V((x, HB_CY + y, HB_Z + (zt - HB_Z) * math.sin(phi)))

    Pb.strip(param_surf(fb, inside=HEAD_AX), 24, 0.0, 1.0, nv=6, relief=0.0045, thick=0.006, groove=0.22)
    parts.append(Pb)
    cap = Part("armor_kabuto_tehen", "gold", bone="head")
    cap.cyl((0, HB_CY, zt - 0.004), (0, HB_CY, zt + 0.014), 0.024, 0.020, 14)
    cap.cyl((0, HB_CY, zt + 0.014), (0, HB_CY, zt + 0.022), 0.012, 0.009, 10)
    parts.append(cap)
    rim = Part("armor_kabuto_rim", "gold", bone="head")

    def fr(s, v):
        a = -math.pi / 2 + (s - 0.5) / 48 * math.tau
        x, y = sup(a, 0.0985, 0.1195, 2.15)
        return V((x, HB_CY + y, v))

    rim.strip(param_surf(fr, inside=HEAD_AX), 48, HB_Z - 0.008, HB_Z + 0.006, nv=1, relief=0.0, thick=0.006, groove=None, closed=True)
    parts.append(rim)

    # shikoro: five flaring tiers around the back and sides (front stays open for the face)
    for tier in range(5):
        P = Part(f"armor_shikoro_{tier}", "lamellar", bone="head")
        z0 = HB_Z - 0.004 - tier * 0.031
        z1 = z0 - 0.035

        def fs(s, v, tier=tier):
            a = math.radians(lerp(-48.0, 228.0, s / 24.0))
            f = (HB_Z - v) / 0.17
            rx = 0.100 + 0.118 * f ** 1.0 + 0.003 * tier
            ry = 0.118 + 0.062 * f ** 1.0 + 0.003 * tier
            x, y = sup(a, rx, ry, 2.3)
            return V((x, HB_CY + 0.012 * f + y, v))

        P.strip(param_surf(fs, inside=HEAD_AX), 24, z0, z1, nv=1, relief=0.0028, thick=0.0045, groove=0.15, row=40 + tier)
        parts.append(P)

    # fukigaeshi wings with gold rosettes + visor
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        W = Part(f"armor_wing_{sd}", "lacquer", bone="head")
        n = V((0.70 * sx, -0.66, 0.28)).normalized()
        u = V((0, 0, 1)).cross(n).normalized()
        w = n.cross(u).normalized()
        C = V((0.124 * sx, HB_CY - 0.078, 1.708))

        def fw(a, b, n=n, u=u, w=w, C=C):
            return C + u * ((a - 0.5) * 0.078) + w * ((b - 0.5) * 0.088) + n * (0.008 * (1 - (2 * a - 1) ** 2) + 0.010 * b)

        W.slab(param_surf(fw, inside=HEAD_AX), 4, 3, 0.010, chamfer=0.05)
        parts.append(W)
        G = Part(f"armor_rosette_{sd}", "gold", bone="head")
        c0 = C + n * 0.016
        G.cyl(c0, c0 + n * 0.006, 0.014, 0.014, 10)
        for k in range(8):
            ang = k / 8 * math.tau
            pc = c0 + (u * math.cos(ang) + w * math.sin(ang)) * 0.023 + n * 0.004
            G.sphere(pc, 0.0085, 0.0085, 0.0045, 6, 3)
        parts.append(G)
    Vz = Part("armor_visor", "lacquer", bone="head")

    def fv(a, b):
        ang = math.radians(lerp(-130.0, -50.0, a))
        x, y = sup(ang, 0.100 + 0.030 * b, 0.121 + 0.034 * b, 2.2)
        return V((x, HB_CY + y, HB_Z + 0.022 + 0.010 * b))

    Vz.slab(param_surf(fv, inside=HEAD_AX), 8, 2, 0.0065, chamfer=0.04)
    parts.append(Vz)

    # maedate: gold crescent on a mount block
    M = Part("armor_maedate", "gold", bone="head")
    C = V((0, HB_CY - 0.118, 1.738))
    rings = []
    n = 14
    for i in range(n + 1):
        th_ = math.radians(lerp(14.0, 166.0, i / n))
        w = 0.026 * math.sin(math.pi * i / n) ** 0.75 + 0.0025
        ro = 0.100
        o = C + V((math.cos(th_) * ro, 0, math.sin(th_) * ro))
        inn = C + V((math.cos(th_) * (ro - w), 0, math.sin(th_) * (ro - w)))
        rings.append([o + V((0, 0.0042, 0)), inn + V((0, 0.0042, 0)), inn - V((0, 0.0042, 0)), o - V((0, 0.0042, 0))])
    M.loft(rings, True, (True, True))
    M.box((0, HB_CY - 0.108, 1.726), 0.011, 0.016, 0.022)
    parts.append(M)
    return parts


# ------------------------------------------------------------------------------------------------------------- menpo
def mask_xy(z, a, off=0.011):
    rx, ry, cy = body.head_radii(z)
    c, s = math.cos(a), math.sin(a)
    x, y = c * (rx + off), s * (ry + off)
    front = max(0.0, -s)
    cheek = math.exp(-((z - 1.592) / 0.022) ** 2) * math.exp(-((abs(x) - 0.054) / 0.018) ** 2) * 0.013
    nose = math.exp(-((z - 1.612) / 0.017) ** 2) * math.exp(-(x / 0.013) ** 2) * 0.030
    stache = math.exp(-((z - 1.568) / 0.010) ** 2) * math.exp(-(x / 0.050) ** 2) * 0.009
    groove = -math.exp(-((z - 1.546) / 0.0065) ** 2) * math.exp(-(x / 0.048) ** 2) * 0.008
    chin = math.exp(-((z - 1.527) / 0.014) ** 2) * math.exp(-(x / 0.020) ** 2) * 0.012
    y -= front * (cheek + nose + stache + groove + chin)
    return x, cy + y


def menpo_parts():
    parts = []
    M = Part("armor_menpo", "iron", bone="head", sharp=48)
    rings = []
    zs = [1.512 + 0.0128 * i for i in range(10)]
    for z in zs:
        rings.append([V((*mask_xy(z, math.tau * j / 28 + 0.0), z)) for j in range(28)])
    M.loft(rings, True, (True, True))
    parts.append(M)
    T = Part("armor_menpo_teeth", "teeth", bone="head")
    for i in range(10):
        x = lerp(-0.040, 0.040, i / 9)
        # find the mask front at this x: approximate with angle from x
        z = 1.546
        rx, ry, cy = body.head_radii(z)
        yy = -(ry + 0.011) * math.sqrt(max(0.0, 1 - (x / (rx + 0.011)) ** 2)) + cy + 0.006
        T.box((x, yy - 0.0035, z), 0.0034, 0.0030, 0.0055)
    parts.append(T)
    H = Part("armor_menpo_stache", "white", bone="head", sharp=70)
    for sd in (1, -1):
        for k, (dz, dx) in enumerate(((0.000, 0.060), (-0.006, 0.066), (0.006, 0.054))):
            z0 = 1.570 + dz
            pts = [V((sd * 0.006, mask_xy(z0, -math.pi / 2)[1] - 0.004, z0)), V((sd * 0.030, mask_xy(z0, -math.pi / 2 + sd * 0.35)[1] - 0.006, z0 + 0.004)),
                   V((sd * dx, mask_xy(z0 - 0.012, -math.pi / 2 + sd * 0.8)[1] - 0.004, z0 - 0.004)),
                   V((sd * (dx + 0.012), mask_xy(z0 - 0.025, -math.pi / 2 + sd * 1.0)[1] - 0.002, z0 - 0.020))]
            H.tube(catmull(pts, 3), lambda t: (0.0065 * (1 - 0.7 * t), 0.0055 * (1 - 0.7 * t)), 5, (True, True))
    parts.append(H)
    K = Part("armor_menpo_cords", "lacing", bone="head", sharp=70)
    for sd in (1, -1):
        pts = [V((sd * 0.079, -0.020, 1.640)), V((sd * 0.078, -0.060, 1.575)), V((sd * 0.052, -0.086, 1.540)), V((sd * 0.012, -0.098, 1.520))]
        K.tube(catmull(pts, 4), lambda t: (0.0045, 0.0045), 6, (True, True))
    parts.append(K)
    return parts


def all_armour(table):
    parts = []
    for f in (do_parts, skirt_parts, haidate_parts, suneate_parts, kote_parts, sode_parts, kabuto_parts, menpo_parts):
        parts += f()
    return parts
