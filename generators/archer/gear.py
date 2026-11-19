"""The light archer's kit: jingasa (war hat) with chin cords, hachimaki with two free tails, a thin leather hara-ate (belly wrap) on straps, the tasuki cord that
ties the sleeves back, sash, a spare-string reel, the quiver with its arrows, and the small back banner. All A-pose rest."""
import math

from mathutils import Matrix, Vector

from samurai import armour as SA, body as SB
from samurai.kit import Part, catmull, lerp, param_surf, sstep

from . import bow as BW, consts as K, rig as R
from .body import face_radii, head_xy, robe_pt
from .kitx import loop, mtube

V = Vector

# ------------------------------------------------------------------------------------------------------------- jingasa
HAT_C = V((0.0, -0.020, 1.730))
HAT_TILT = math.radians(7.0)                 # worn tipped forward: the brim shades the eyes
HAT_PROF = ((0.006, 0.0890), (0.030, 0.0842), (0.070, 0.0664), (0.110, 0.0458), (0.150, 0.0242), (0.178, 0.0088), (0.1895, 0.0012), (0.1915, -0.0030),
            (0.186, -0.0048), (0.150, 0.0152), (0.110, 0.0368), (0.070, 0.0574), (0.030, 0.0752), (0.006, 0.0800))


def hat_matrix():
    return Matrix.Translation(HAT_C) @ Matrix.Rotation(HAT_TILT, 4, "X")


def hat_parts():
    M = hat_matrix()
    H = Part("armor_jingasa", "jingasa", bone="head", sharp=50)
    n = 32
    H.push(M)
    rings = [[V((math.cos(math.tau * j / n) * r, math.sin(math.tau * j / n) * r, h)) for j in range(n)] for r, h in HAT_PROF]
    H.loft(rings, True, (True, True), uv=lambda i, j: (j / n, HAT_PROF[i][0]))            # v = radius: the shader paints rim, rings and the team band by it
    H.pop()
    F = Part("armor_jingasa_knob", "brass", bone="head", sharp=50)
    F.push(M)
    F.cyl((0, 0, 0.0865), (0, 0, 0.0935), 0.0125, 0.0105, 10)
    F.cyl((0, 0, 0.0935), (0, 0, 0.0990), 0.0060, 0.0045, 8)
    F.pop()
    # padded ring the hat sits on (seen from below the brim)
    L = Part("cloth_jingasa_pad", "juban", bone="head", sharp=60)
    L.push(M)
    mtube(L, loop((0, 0.006, 0.014), (1, 0, 0), (0, 1.16, 0), 0.074, 16), lambda t: (0.011, 0.011), 6, (True, True))
    L.pop()
    # chin cords: from the pad down in front of the ears, tied under the chin
    C = Part("cord_jingasa", "cord", bone="head", sharp=70)
    for sx in (1, -1):
        pts = []
        for z, a, off in ((1.752, -22.0, 0.006), (1.700, -27.0, 0.0050), (1.650, -33.0, 0.0048), (1.605, -44.0, 0.0090), (1.565, -60.0, 0.0065), (1.535, -78.0, 0.0060), (1.5215, -90.0, 0.0050)):
            x, y = head_xy(math.radians(a), z, off)
            pts.append(V((sx * x, y, z)))
        mtube(C, catmull(pts, 3), lambda t: (0.0034, 0.0034), 5, (True, True))
    C.sphere((0, face_radii(1.5215)[2] - face_radii(1.5215)[1] - 0.006, 1.517), 0.0080, 0.0060, 0.0060, 6, 4)       # the knot
    for sx in (1, -1):
        c0 = V((0, face_radii(1.5215)[2] - face_radii(1.5215)[1] - 0.007, 1.515))
        mtube(C, [c0, c0 + V((sx * 0.008, -0.004, -0.022)), c0 + V((sx * 0.013, -0.002, -0.046))], lambda t: (0.0030, 0.0030), 5, (True, True))
    return [H, F, L, C]


# ------------------------------------------------------------------------------------------------------------- hachimaki
def hachimaki_parts():
    B = Part("cloth_hachimaki", "teamcloth", bone="head", sharp=60)

    def fn(s, v):
        a = s / 24.0 * math.tau
        x, y = head_xy(a, v, 0.0068)
        return V((x, y, v))

    B.strip(param_surf(fn, inside=SA.HEAD_AX), 24, 1.702, 1.732, nv=1, relief=0.0, thick=0.0042, groove=None, closed=True)
    rx, ry, cy = face_radii(R.TAIL_Z)
    B.sphere((0.001, cy + ry + 0.0105, R.TAIL_Z), 0.0170, 0.0095, 0.0140, 8, 5)                                   # the knot at the back
    out = [B]
    for key in "ab":
        j0, j1, j2 = R.tail_joints(key)
        T = Part(f"cloth_hachimaki_tail_{key}", "teamcloth", soft=f"tail:{key}", sharp=60)
        mtube(T, [j0, (j0 + j1) * 0.5, j1, (j1 + j2) * 0.5, j2], lambda t: (0.0030, 0.0135 - 0.0015 * t, 3.0), 6, (True, True))
        out.append(T)
    return out


# ------------------------------------------------------------------------------------------------------------- hara-ate, straps, tasuki
HARA_TOP, HARA_BOT, HARA_ROWS = 1.312, 1.096, 4
HARA_A0, HARA_A1 = 166.0, 374.0              # it wraps the front and the flanks; the back is open (straps and a cord)


def haraate_parts():
    parts = []
    h = (HARA_TOP - HARA_BOT) / HARA_ROWS
    for r in range(HARA_ROWS):
        z0, z1 = HARA_TOP - r * h, HARA_TOP - (r + 1) * h - 0.006
        off = 0.0125 + 0.0026 * r
        P = Part(f"armor_haraate_{r}", "haraate", bone=SA.row_bone((z0 + z1) / 2))

        def fn(s, v, off=off):
            return robe_pt(lerp(HARA_A0, HARA_A1, s / 16.0), v, off)

        P.strip(param_surf(fn, inside=SA.TORSO_AX), 16, z0, z1, nv=1, relief=0.0020, thick=0.0045, groove=0.13, row=r)
        parts.append(P)
    T = Part("armor_haraate_trim", "leather", bone="chest")
    T.strip(param_surf(lambda s, v: robe_pt(lerp(HARA_A0, HARA_A1, s / 26.0), v, 0.0150), inside=SA.TORSO_AX), 26, HARA_TOP - 0.004, HARA_TOP + 0.016, nv=1, relief=0.0, thick=0.005, groove=None)
    parts.append(T)
    # straps: from the top corners over the shoulders and down the back to the waist cord
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        S = Part(f"armor_strap_{sd}", "leather", soft="torso", sharp=60)
        pts = [(293, 1.318), (303, 1.392), (322, 1.446), (350, 1.464), (22, 1.464), (48, 1.446), (64, 1.392), (73, 1.300), (77, 1.200), (79, 1.104)]
        path = catmull([robe_pt(a if sx > 0 else 180.0 - a, z, 0.0085) for a, z in pts], 3)
        mtube(S, path, lambda t: (0.0036, 0.0145, 3.2), 6, (True, True))
        parts.append(S)
    Cd = Part("cord_haraate_back", "leather", soft="torso", sharp=60)
    mtube(Cd, catmull([robe_pt(a, 1.104, 0.0070) for a in (14, 40, 65, 90, 115, 140, 166)], 3), lambda t: (0.0042, 0.0042), 6, (True, True))
    parts.append(Cd)
    return parts


def tasuki_parts():
    """The cord that ties the sleeves back: a ring round each shoulder and an X across the back."""
    from samurai import rig as SR
    sh = SR._arm_points()[0]
    parts = []
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        Rg = Part(f"cord_tasuki_{sd}", "teamcord", soft=f"arm.{sd}", sharp=70)
        c = V((0.140 * sx, 0.0, 1.411))
        ax = V((sx, 0.0, -0.20)).normalized()
        e1 = V((0, 1, 0))
        e2 = ax.cross(e1).normalized()
        mtube(Rg, loop(c, e1, e2, 0.0815, 16), lambda t: (0.0052, 0.0052), 6, (True, True))
        parts.append(Rg)
    X = Part("cord_tasuki_x", "teamcord", soft="torso", sharp=70)
    for k, sgn in enumerate((1.0, -1.0)):
        pts = [(36, 1.452), (62, 1.418), (90, 1.378), (118, 1.346), (146, 1.334)]
        path = catmull([robe_pt(a if sgn > 0 else 180.0 - a, z, 0.0125 + 0.0050 * k) for a, z in pts], 3)
        mtube(X, path, lambda t: (0.0050, 0.0050), 6, (True, True))
    parts.append(X)
    return parts


def waist_parts():
    """Sash (the samurai's obi, plain here) and the tsurumaki: a wicker reel with a spare bowstring at the left hip."""
    S = SB.sash_part()
    S.mat = "obi"
    T = Part("gear_tsurumaki", "wicker", bone="hips", sharp=60)
    c = V((0.186, 0.020, 0.952))
    mtube(T, loop(c, (0.12, 1.0, 0.0), (0.0, 0.0, 1.0), 0.047, 14), lambda t: (0.0125, 0.0105), 6, (True, True))
    C = Part("gear_tsurumaki_cord", "cord", bone="hips", sharp=70)
    mtube(C, [c + V((0.0, 0.0, 0.047)), V((0.178, 0.012, 1.02)), V((0.168, 0.004, 1.062))], lambda t: (0.0030, 0.0030), 5, (True, True))
    return [S, T, C]


# ------------------------------------------------------------------------------------------------------------- quiver
def quiver_parts():
    ax, base = R.QUIVER_AXIS, R.QUIVER_BASE
    Q = Part("gear_quiver", "quiver", bone="hips", sharp=50)
    path = [base + ax * (R.QUIVER_LEN * t) for t in (0.0, 0.06, 0.30, 0.62, 0.90, 0.985, 1.0)]
    mtube(Q, path, SB.prof((0.0, 0.034, 0.030), (0.06, 0.046, 0.039), (0.30, 0.050, 0.042), (0.62, 0.054, 0.045), (0.90, 0.060, 0.050), (0.985, 0.063, 0.053), (1.0, 0.056, 0.046)),
          12, (True, True), uvscale=(1.0, 1.0))
    St = Part("gear_quiver_strap", "leather", bone="hips", sharp=60)
    for f in (0.42, 0.86):                                                       # two straps to the sash
        p = base + ax * (R.QUIVER_LEN * f)
        mtube(St, [p + V((0.0, -0.030, 0.0)), V((p.x * 0.55, 0.128, 1.035)), V((p.x * 0.25, 0.124, 1.050))], lambda t: (0.0105, 0.0030, 3.0), 6, (True, True))
    Sh = Part("gear_quiver_shafts", "shaft", bone="hips", sharp=60)
    Fl = Part("gear_quiver_fletch", "fletch", bone="hips", sharp=80)
    for k in range(6):
        o, d = R.quiver_slot(k)
        BW.arrow_into(Sh, Fl, None, o, d, 0.52, spin=k * 0.9)                   # only what stands out of the quiver
    return [Q, St, Sh, Fl]


# ------------------------------------------------------------------------------------------------------------- back banner
def banner_parts():
    pole = Part("banner_pole", "bamboo", soft="banner", sharp=60)
    zs = (K.ZP0 - 0.05, 1.50, 1.76, 2.00, K.TOP + 0.045)
    pole.tube([V((0, K.pole_y(z), z)) for z in zs], lambda t: (0.0072, 0.0072), 6, (True, True))
    pole.tube([V((0, K.YC, K.TOP)), V((K.CLOTH_W + 0.02, K.YC, K.TOP))], lambda t: (0.0048, 0.0048), 5, (True, True))          # cross bar
    br = Part("banner_bracket", "leather", bone="chest", sharp=60)
    yb = robe_pt(90, 1.27).y
    br.box((0, yb + 0.014, 1.265), 0.050, 0.008, 0.060)                                                                         # leather back plate hung on the straps
    br.box((0, K.pole_y(1.235), 1.235), 0.0125, 0.0125, 0.040)                                                                  # the socket the pole stands in
    br.box((0, (yb + K.pole_y(1.30)) * 0.5 + 0.008, 1.300), 0.010, (K.pole_y(1.30) - yb) * 0.5, 0.008)                          # upper stay
    cloth = Part("banner_cloth", "banner", soft="flag", sharp=60)

    def surf(u, v):
        return V((K.X0 + K.CLOTH_W * u, K.YC + 0.0045, K.TOP - 0.004 - K.CLOTH_H * v)), V((0, 1, 0))

    cloth.slab(surf, 3, 7, 0.0030, chamfer=0.0, uvf=lambda u, v: (u * K.CLOTH_W, v * K.CLOTH_H), two_sided=True)
    return [pole, br, cloth]


def all_gear():
    return hat_parts() + hachimaki_parts() + haraate_parts() + tasuki_parts() + waist_parts() + quiver_parts()
