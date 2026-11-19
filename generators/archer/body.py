"""The archer's body and clothes (A-pose rest): a bare face under the war hat, kosode with the sleeves tied back, one bare string arm and one bound bow arm,
pleated trousers gathered into gaiters, tabi and straw sandals. The hands, gaiters, feet and sandals are the samurai's (same skeleton)."""
import math

from mathutils import Vector

from samurai import armour as SA, body as SB, rig as SR
from samurai.kit import Part, catmull, lerp, param_surf, sstep

from .kitx import g, mrings, mtube

V = Vector


# ------------------------------------------------------------------------------------------------------------- shared surfaces
def face_radii(z):
    """(rx, ry, cy) of the bare head at height z: the samurai's skull with a slightly narrower jaw (shared with the hat cords, the head band and the hair)."""
    rx, ry, cy = SB.head_radii(z)
    return rx * (1.0 - 0.07 * sstep(1.632, 1.552, z)), ry, cy


def face_n(z):
    """Superellipse exponent of the head section at z: a round cranium, a squarer jaw (a jaw line and flat cheeks instead of an egg), a round chin."""
    return 2.0 + 0.70 * sstep(1.648, 1.596, z) * sstep(1.530, 1.560, z)


def head_xy(a, z, off=0.0):
    """(x, y) on the head section at angle a (radians; -90 deg is the front), `off` metres outside it."""
    rx, ry, cy = face_radii(z)
    x, y = SA.sup(a, rx + off, ry + off, face_n(z))
    return x, cy + y


def robe_at(z):
    """(rx, ry) of the kosode at height z: the samurai's torso section, continued over the shoulder yoke up to the neck."""
    if z <= 1.43:
        return SA.torso_at(z)
    if z <= 1.455:
        u = (z - 1.43) / 0.025
        return lerp(0.150, 0.116, u), lerp(0.104, 0.086, u)
    u = min((z - 1.455) / 0.023, 1.0)
    return lerp(0.116, 0.078, u), lerp(0.086, 0.070, u)


def robe_pt(a_deg, z, off=0.0):
    """A point on (or `off` outside) the kosode: a_deg = 270 is the front, 0 the left side, 90 the back."""
    rx, ry = robe_at(z)
    x, y = SA.sup(math.radians(a_deg), rx + off, ry + off)
    return V((x, -0.004 + y, z))


# ------------------------------------------------------------------------------------------------------------- head
FACE_Z = [1.529, 1.537, 1.545, 1.553, 1.561, 1.568, 1.5735, 1.5775, 1.5805, 1.5822, 1.5840, 1.5868, 1.5905, 1.595, 1.600, 1.605, 1.609, 1.613, 1.618,
          1.625, 1.633, 1.640, 1.646, 1.652, 1.658, 1.663, 1.668, 1.674, 1.682, 1.694, 1.708, 1.722, 1.738, 1.752]
FACE_A = [0, 30, 60, 90, 120, 150, 180, 195] + list(range(204, 337, 6)) + [345]


def face_d(x, z):
    """How far the face stands out of the head section at (x, z), metres: brow ridge, nose, lips, chin, cheek bones, eye sockets."""
    ax = abs(x)
    brow = g(z, 1.667, 0.0095) * g(x, 0, 0.060) * 0.0100 + g(z, 1.669, 0.0080) * g(ax, 0.034, 0.020) * 0.0038      # the ridge is heaviest over the eyes
    glab = -g(z, 1.6575, 0.0060) * g(x, 0, 0.010) * 0.0022                        # the dip at the root of the nose
    nt = min(max((1.656 - z) / 0.043, 0.0), 1.0)                                 # 0 at the root, 1 at the tip
    win = 1.0 if z >= 1.613 else g(z, 1.613, 0.0062)
    nose = (0.0052 + 0.0250 * nt ** 1.25) * (0.70 * g(x, 0, 0.0076 + 0.0050 * nt) + 0.30 * g(x, 0, 0.0140 + 0.0050 * nt)) * win * (1.0 if z <= 1.656 else g(z, 1.656, 0.009))
    wings = g(z, 1.6105, 0.0060) * g(ax, 0.0150, 0.0060) * 0.0092
    muzzle = g(z, 1.588, 0.016) * g(x, 0, 0.030) * 0.0072
    up_lip = g(z, 1.5872, 0.0036) * g(x, 0, 0.0210) * 0.0060 - g(z, 1.5940, 0.0045) * g(x, 0, 0.0045) * 0.0020      # with the philtrum
    lo_lip = g(z, 1.5768, 0.0044) * g(x, 0, 0.0185) * 0.0076
    mouth = -g(z, 1.5822, 0.0016) * g(x, 0, 0.0240) * 0.0050
    corner = -g(z, 1.582, 0.0050) * g(ax, 0.0265, 0.0065) * 0.0030
    under = -g(z, 1.5680, 0.0045) * g(x, 0, 0.018) * 0.0042
    chin = g(z, 1.5475, 0.0125) * g(x, 0, 0.0250) * 0.0120
    socket = -(g(z, 1.652, 0.0095) * g(ax, 0.032, 0.0150)) * 0.0078              # the eye parts sit in it
    cheek = g(z, 1.622, 0.017) * g(ax, 0.054, 0.017) * 0.0078
    hollow = -g(z, 1.585, 0.020) * g(ax, 0.050, 0.015) * 0.0042                  # under the cheek bones: a lean face
    temple = -g(z, 1.676, 0.016) * g(ax, 0.070, 0.012) * 0.0030
    return brow + glab + nose + wings + muzzle + up_lip + lo_lip + mouth + corner + under + chin + socket + cheek + hollow + temple


def head_parts():
    """Bare head (dense over the face only), ears, neck (soft: it turns inside the collar when he looks down the arrow)."""
    P = Part("body_head", "face", bone="head", sharp=80)
    rings = []
    for z in [1.5235] + FACE_Z:
        rx, ry, cy = face_radii(z)
        pts = []
        for ad in FACE_A:
            a = math.radians(ad)
            x, y = head_xy(a, z)
            y -= max(0.0, -math.sin(a)) * face_d(x, z)
            pts.append(V((x, y, z)))
        rings.append(pts)
    P.loft(rings, True, (True, True))
    E = Part("body_ears", "face", bone="head", sharp=80)
    for sx in (1, -1):
        rx, ry, cy = face_radii(1.642)
        c = V((sx * (rx + 0.0030), cy + 0.017, 1.642))
        E.sphere(c, 0.0052, 0.0125, 0.0255, 10, 7)                                           # the shell, lying back against the skull
        E.sphere(c + V((sx * 0.0024, 0.0020, -0.0215)), 0.0052, 0.0078, 0.0088, 7, 5)        # the lobe
        rim = [c + V((sx * 0.0046, dy, dz)) for dy, dz in ((-0.0085, -0.0100), (-0.0070, 0.0120), (0.0010, 0.0235), (0.0100, 0.0160), (0.0125, -0.0020), (0.0085, -0.0160))]
        E.tube(catmull(rim, 3), lambda t: (0.0030, 0.0034 - 0.0008 * t), 5, (True, True))     # the helix
    N = Part("body_neck", "skin", soft="neck", sharp=80)
    mtube(N, [V((0, -0.002, 1.385)), V((0, -0.004, 1.42)), V((0, -0.007, 1.455)), V((0, -0.010, 1.49)), V((0, -0.013, 1.52)), V((0, -0.016, 1.552))],
          lambda t: (0.0530 - 0.0085 * t + 0.0030 * g(t, 0.0, 0.25), 0.0560 - 0.0070 * t), 12, (True, True),
          mod=lambda t, a: 1.0 + 0.05 * g(t, 0.62, 0.22) * max(0.0, -math.sin(a)) ** 3)        # the throat
    return [P, E, N] + eyes_parts()


def eyes_parts():
    """The samurai's almond eyes (same sockets) with a finer, less severe brow: this face is not hidden behind a mask."""
    P = Part("body_eyes", "eye", bone="head", sharp=80)
    I = Part("body_iris", "iris", bone="head", sharp=80)
    L = Part("body_lids", "face", bone="head", sharp=80)
    Bw = Part("body_brow", "hair", bone="head", sharp=80)
    Ln = Part("body_lash", "iris", bone="head", sharp=80)
    for sx in (1, -1):
        cx, cy, cz = sx * 0.031, -0.099, 1.652
        P.sphere((cx, cy, cz), 0.0122, 0.0046, 0.0047, 8, 5)
        I.sphere((cx - sx * 0.0006, cy - 0.0030, cz - 0.0003), 0.0053, 0.0030, 0.0053, 8, 5)
        L.sphere((cx, cy - 0.0020, cz + 0.0061), 0.0140, 0.0064, 0.0037, 8, 4)                # the upper lid covers the top of the iris: a level gaze, not a stare
        L.sphere((cx, cy - 0.0012, cz - 0.0050), 0.0128, 0.0052, 0.0024, 6, 3)
        lash = [V((sx * 0.0180, cy - 0.0052, cz + 0.0006)), V((sx * 0.0310, cy - 0.0074, cz + 0.0019)), V((sx * 0.0452, cy - 0.0048, cz + 0.0008))]
        Ln.tube(catmull(lash, 2), lambda t: (0.0010, 0.0010), 4, (True, True))
        pts = [V((sx * 0.0125, -0.1085, 1.6690)), V((sx * 0.0310, -0.1105, 1.6755)), V((sx * 0.0540, -0.1010, 1.6735))]
        Bw.tube(catmull(pts, 3), lambda t: (0.0034 - 0.0014 * t, 0.0026), 5, (True, True))
    return [P, I, L, Bw, Ln]


def hair_parts():
    """Dark hair at the temples, the sides and the nape (the war hat and the hachimaki hide the crown), drawn back tight."""
    H = Part("body_hair", "hair", bone="head", sharp=70)

    def fn(u, v):
        a = math.radians(lerp(-34.0, 214.0, u))
        z0 = 1.590 + 0.070 * abs(2.0 * u - 1.0) ** 2.6                        # the hairline dips to the nape and rises to the temples
        z = lerp(z0, 1.716, v)
        x, y = head_xy(a, z, 0.0046)
        return V((x, y, z))

    H.slab(param_surf(fn, inside=SA.HEAD_AX), 14, 4, 0.0044, chamfer=0.02, uvf=lambda u, v: (u * 0.42, v * 0.12))
    rings = []
    for z in (1.726, 1.744, 1.759, 1.766):
        rx, ry, cy = face_radii(min(z, 1.757))
        k = 1.0 if z < 1.76 else 0.55
        rings.append([V((math.cos(math.tau * j / 12) * (rx + 0.0046) * k, cy + math.sin(math.tau * j / 12) * (ry + 0.0046) * k, z)) for j in range(12)])
    H.loft(rings, True, (True, True))
    rx, ry, cy = face_radii(1.652)
    H.sphere((0.0, cy + ry + 0.012, 1.650), 0.030, 0.024, 0.027, 8, 5)                       # the hair gathered in a knot at the nape, under the hat's brim
    return [H]


# ------------------------------------------------------------------------------------------------------------- kosode
ROBE_Z = [0.99, 1.04, 1.10, 1.16, 1.24, 1.32, 1.38, 1.43, 1.455, 1.478]
ROBE_N = 36


def robe_front(x, z, off=0.0):
    """The point on the front of the kosode at (x, z)."""
    rx, ry = robe_at(z)
    t = min(abs(x) / (rx + off), 0.999)
    return V((x, -0.004 - (ry + off) * (1.0 - t ** 2.5) ** 0.4, z))


def kosode_parts():
    P = Part("cloth_kosode", "kosode", soft="torso")
    rings = []
    for z in ROBE_Z:
        fold = sstep(1.30, 1.12, z) * 0.011                                    # the cloth bunches above the sash
        rings.append([robe_pt(360.0 * j / ROBE_N, z) for j in range(ROBE_N)])
        if fold > 0:
            c = V((0, -0.004, z))
            rings[-1] = [c + (p - c) * (1.0 + fold * math.sin(7 * math.tau * j / ROBE_N + z * 23.0)) for j, p in enumerate(rings[-1])]
    P.loft(rings, True, (True, True))
    out = [P]
    # the collar: two bands from the nape round the neck that cross on the chest, left over right, with the white under-robe showing at the throat
    def band(sx, off, zs, x_of, shrink=1.0):
        pts = [V((0.0, 0.0625 * shrink, 1.490)), V((sx * 0.046 * shrink, 0.040 * shrink, 1.489)), V((sx * 0.0655 * shrink, -0.006, 1.484))]
        for z in zs:
            pts.append(robe_front(sx * x_of(z), z, off))
        return catmull(pts, 3)

    zt = (1.462, 1.430, 1.390, 1.345, 1.300, 1.250)
    zu = (1.462, 1.430, 1.390, 1.352, 1.322)
    xv = lambda z: 0.058 * (z - 1.318) / (1.462 - 1.318)                     # the V: the bands meet at z = 1.318 and the upper one runs on across
    for name, mat, path, wid in (("cloth_collar_top", "kosode", band(1.0, 0.0068, zt, xv), 0.0200), ("cloth_collar_under", "kosode", band(-1.0, 0.0040, zu, xv), 0.0200),
                                 ("cloth_juban_top", "juban", band(1.0, 0.0050, zt[:4], lambda z: xv(z) * 0.60 - 0.004, 0.93), 0.0150),
                                 ("cloth_juban_under", "juban", band(-1.0, 0.0030, zu[:4], lambda z: xv(z) * 0.60 - 0.004, 0.93), 0.0150)):
        C = Part(name, mat, soft="torso", sharp=60)
        mtube(C, path, lambda t, wid=wid: (0.0042, wid * (1.0 - 0.25 * sstep(0.8, 1.0, t)), 3.0), 6, (True, True))
        out.append(C)
    return out


def arm_parts():
    """Sleeves tied back above the elbow (tasuki), a bare string arm (right), a tightly bound bow arm (left: the string must not catch a sleeve)."""
    sh, el, wr, tip, d = SR._arm_points()
    out = []
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        def m(v, sx=sx):
            return V((v.x * sx, v.y, v.z))

        S = Part(f"cloth_sleeve_{sd}", "kosode", soft=f"arm.{sd}")
        path = [m(p) for p in catmull([V((0.105, 0.0, 1.418)), sh, sh.lerp(el, 0.34), sh.lerp(el, 0.66)], 4)]
        mtube(S, path, SB.prof((0.0, 0.068, 0.072), (0.30, 0.075, 0.079), (0.62, 0.072, 0.075), (0.88, 0.061, 0.063), (1.0, 0.050, 0.051)), 16, (True, True),
              mod=lambda t, a, sx=sx: 1.0 + (0.020 + 0.040 * t) * math.sin(4.0 * a + 5.0 * t + sx) * sstep(0.05, 0.30, t))
        out.append(S)
        path = [m(p) for p in (sh.lerp(el, 0.50), sh.lerp(el, 0.80), el, el.lerp(wr, 0.22), el.lerp(wr, 0.55), el.lerp(wr, 0.85), wr, wr + d * 0.016)]
        if sd == "R":
            A = Part("body_arm_R", "skin", soft="arm.R", sharp=80)
            mtube(A, path, SB.prof((0.0, 0.044, 0.046), (0.14, 0.042, 0.044), (0.29, 0.039, 0.041), (0.43, 0.043, 0.046), (0.64, 0.038, 0.040), (0.84, 0.031, 0.031),
                                   (0.96, 0.028, 0.025), (1.0, 0.027, 0.024)), 10, (True, True))
            out.append(A)
            e, w = m(el), m(wr)
            G = Part("glove_cuff_R", "glove", bone="forearm.R", sharp=60)                     # the yugake's long cuff
            mtube(G, [e.lerp(w, 0.63), e.lerp(w, 0.80), w, w + m(d) * 0.024], SB.prof((0.0, 0.0385, 0.0395), (0.45, 0.0345, 0.0345), (0.9, 0.0315, 0.0290), (1.0, 0.0320, 0.0285)), 10, (True, True))
            out.append(G)
            C = Part("cord_glove_R", "teamcord", bone="forearm.R", sharp=60)                  # its cord, wound round the wrist
            for k, f in enumerate((0.735, 0.775, 0.815)):
                r = lerp(0.0385, 0.0335, (f - 0.63) / 0.30) + 0.0022
                mtube(C, [e.lerp(w, f - 0.011), e.lerp(w, f + 0.011)], lambda t, r=r: (r, r), 10, (True, True))
            out.append(C)
        else:
            A = Part("cloth_yugote_L", "yugote", soft="arm.L")
            mtube(A, path, SB.prof((0.0, 0.047, 0.049), (0.14, 0.045, 0.047), (0.29, 0.043, 0.045), (0.43, 0.046, 0.049), (0.64, 0.041, 0.043), (0.84, 0.034, 0.034),
                                   (0.96, 0.031, 0.028), (1.0, 0.030, 0.027)), 10, (True, True))
            out.append(A)
            e, w = m(el), m(wr)
            C = Part("cord_yugote_L", "leather", bone="forearm.L", sharp=60)                  # bindings below the elbow and at the wrist
            for f, r in ((0.10, 0.0492), (0.90, 0.0345)):
                mtube(C, [e.lerp(w, f - 0.012), e.lerp(w, f + 0.012)], lambda t, r=r: (r, r), 10, (True, True))
            out.append(C)
            T = Part("cloth_tekko_L", "yugote", bone="hand.L")                               # cloth over the back of the bow hand
            hd = (tip - wr).normalized()
            palm = V((-1.0, 0.0, 0.0))
            nrm = (palm - hd * palm.dot(hd)).normalized()
            lat = hd.cross(nrm).normalized()

            def ft(u, v, hd=hd, nrm=nrm, lat=lat):
                c = wr + hd * (0.004 + 0.070 * v)
                hw = lerp(0.030, 0.041, v)
                return c + lat * ((u - 0.5) * 2 * hw) - nrm * (0.0185 + 0.007 * (1 - (2 * u - 1) ** 2))

            T.slab(param_surf(ft, inside=lambda p, hd=hd: wr + hd * (p - wr).dot(hd)), 4, 3, 0.003, chamfer=0.06, uvf=lambda u, v: (u * 0.08, v * 0.07))
            out.append(T)
    return out


# ------------------------------------------------------------------------------------------------------------- trousers
def hakama_parts():
    """Pleated trousers: a top over the hips and two baggy legs gathered below the knee into the gaiters."""
    out = []
    T = Part("cloth_hakama_top", "hakama", soft="pelvis")
    rings = []
    for z, rx, ry in ((1.055, 0.150, 0.110), (1.00, 0.157, 0.114), (0.95, 0.167, 0.119), (0.90, 0.173, 0.123), (0.855, 0.166, 0.119)):
        pts = []
        for j in range(40):
            a = math.tau * j / 40
            front = max(0.0, -math.sin(a))
            k = 1.0 + 0.016 * front * math.cos(8.0 * (a + math.pi / 2)) * sstep(1.06, 0.98, z)       # three pleats a side, opening downward
            x, y = SA.sup(a, rx * k, ry * k, 2.0 + 0.5 * sstep(1.00, 0.90, z))          # round under the sash (an ellipse), squarer over the hips
            pts.append(V((x, -0.004 + y, z)))
        rings.append(pts)
    T.loft(rings, True, (True, True))
    out.append(T)
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        P = Part(f"cloth_hakama_{sd}", "hakama", soft=f"leg.{sd}")
        zs = (0.93, 0.86, 0.78, 0.70, 0.62, 0.55, 0.505, 0.475, 0.455)
        path = [V((SR.leg_center(z)[0] * sx, SR.leg_center(z)[1], z)) for z in zs]
        mtube(P, path, SB.prof((0.0, 0.106, 0.110), (0.22, 0.113, 0.119), (0.55, 0.115, 0.121), (0.78, 0.106, 0.110), (0.90, 0.082, 0.084), (1.0, 0.064, 0.066)), 20, (True, True),
              mod=lambda t, a, sx=sx: 1.0 + 0.024 * math.sin(5.0 * a + 3.0 * t + sx) * sstep(0.10, 0.45, t) * (1.0 - 0.5 * sstep(0.80, 1.0, t)))
        out.append(P)
    return out


def leg_parts():
    out = []
    for sd in ("L", "R"):
        w = SB.leg_wrap_part(sd)
        w.mat = "kyahan"
        f = SB.foot_part(sd)
        f.mat = "tabi"
        out += [w, f] + SB.sandal_parts(sd)
    return out


def hand_parts(table):
    out = []
    for sd in ("L", "R"):
        hp = SB.hand_parts(sd, table)
        if sd == "R":                           # the yugake: a deerskin glove on the string hand
            for p in hp:
                p.mat = "glove"
        out += hp
    return out


def all_soft(table):
    return head_parts() + hair_parts() + kosode_parts() + arm_parts() + hakama_parts() + leg_parts() + hand_parts(table)
