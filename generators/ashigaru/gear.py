"""What the ashigaru is issued: every piece is its own node of the model, so an engine can dress a man from what his house has in store.

  body armour   hara-ate   the levy's laced belly guard, open at the back, two short tassets; with it the ration tube lies on the belly and he carries his gourd
                okegawa    lent armour (okashi gusoku): the riveted cuirass front and back, six laced tassets, dark sleeves with iron splints, iron hand plates,
                           splint greaves. The house's banner (its own node, for the wind) is worn with it
  head          jingasa    a narrow rawhide war hat
                tetsu      a wide iron war hat with the house's mark and a cloth neck curtain
  side arm      tanto      a short blade through the sash at the left hip
The body under them is whole (body.py): head band, tasuki cord and sash are his own. Both spears are in spear.py."""
import math

from mathutils import Matrix, Vector

from samurai import armour as SA, body as SB, rig as SR
from samurai.kit import Part, catmull, lerp, param_surf, sstep
from archer import gear as AG
from archer.body import head_xy, robe_pt
from archer.kitx import g, mtube

from . import body as BD

V = Vector

# ------------------------------------------------------------------------------------------------------------- head
HAT = {1: dict(c=V((0.0, -0.018, 1.710)), tilt=6.0, kr=0.90, kh=1.14), 2: dict(c=V((0.0, -0.020, 1.708)), tilt=7.0, kr=1.0, kh=1.0)}       # worn down on the head (the brim at the brows)


def hat_parts(kind):
    """The archer's war hat (pad and chin cords are the same) with this hat's crown: 1 = rawhide, 2 = iron. The shader paints by the PROFILE radius, so the bands follow the scaling."""
    h = HAT[kind]
    M = Matrix.Translation(h["c"]) @ Matrix.Rotation(math.radians(h["tilt"]), 4, "X")
    prof, n = AG.HAT_PROF, 32
    H = Part("armor_jingasa", "jingasa" if kind == 1 else "jingasa2", bone="head", sharp=50)
    H.push(M)
    rings = [[V((math.cos(math.tau * j / n) * r * h["kr"], math.sin(math.tau * j / n) * r * h["kr"], z * h["kh"])) for j in range(n)] for r, z in prof]
    H.loft(rings, True, (True, True), uv=lambda i, j: (j / n, prof[i][0]))
    H.pop()
    F = Part("armor_jingasa_knob", "brass", bone="head", sharp=50)
    F.push(M)
    z0 = (prof[0][1] - 0.0025) * h["kh"]
    F.cyl((0, 0, z0), (0, 0, z0 + 0.0070), 0.0125, 0.0105, 10)
    F.cyl((0, 0, z0 + 0.0070), (0, 0, z0 + 0.0125), 0.0060, 0.0045, 8)
    F.pop()
    rest = AG.hat_parts()[2:]                      # the padded ring and the chin cords
    return [H, F] + rest


def neckcloth_parts():
    """With the iron hat: a cloth curtain from the hat's band round the sides and the back of the head, down to the shoulders."""
    P = Part("cloth_shikoro", "necloth", soft="neck", sharp=60)

    def fn(u, v):
        a = math.radians(lerp(206.0, -26.0, u))                       # right temple, round the back, left temple
        z = lerp(1.690, 1.492, v)
        x, y = head_xy(a, max(z, 1.590), 0.026 + 0.052 * v + 0.006 * math.sin(u * 37.0) * v)
        return V((x, y + 0.010 * v, z))

    P.slab(param_surf(fn, inside=SA.HEAD_AX), 14, 4, 0.0034, chamfer=0.0, uvf=lambda u, v: (u * 0.50, v * 0.22), two_sided=True)
    return [P]


# ------------------------------------------------------------------------------------------------------------- tassets (both armours), the okegawa do
def tasset_parts(tier):
    """The samurai's laced skirt panels on the same bones: the hara-ate (1) has the two front panels, two lames each; the lent armour (2) all eight, three lames each."""
    out = []
    for p in SA.skirt_parts():
        sd_pi, row = p.name[len("armor_skirt_"):].split("_")
        pi, row = int(sd_pi[1]), int(row)
        if (tier == 1 and pi == 0 and row < 2) or (tier == 2 and row < 3):
            out.append(p)
    return out


DO_Z0, DO_ROW, DO_ROWS = 1.108, 0.0455, 5


def do_off(z):
    return 0.0175 + 0.0095 * g(z, 1.205, 0.085)                       # a barrel over the belly


def do_parts():
    parts = []
    for r in range(DO_ROWS + 1):                                       # five lames and the band under the arms
        z1 = DO_Z0 + r * DO_ROW
        z0 = z1 + DO_ROW + (0.006 if r < DO_ROWS else -0.012)
        lap = 0.0024 * r                                               # an upper lame overlaps the one below it
        P = Part(f"armor_do_{r}", "okegawa", bone=SA.row_bone((z0 + z1) / 2))

        def fn(s, v, lap=lap):
            return robe_pt(360.0 * s / 28.0, v, do_off(v) + lap)

        P.strip(param_surf(fn, inside=SA.TORSO_AX), 28, z0, z1, nv=1, relief=0.0022, thick=0.0050, groove=None, closed=True, row=r)
        parts.append(P)
    zt = DO_Z0 + (DO_ROWS + 1) * DO_ROW - 0.012
    for name, a0, a1, top in (("armor_do_mune", 228.0, 312.0, 1.412), ("armor_do_back", 48.0, 132.0, 1.432)):       # breast plate and back plate
        P = Part(name, "okegawa", bone="chest")
        P.strip(param_surf(lambda s, v, a0=a0, a1=a1: robe_pt(lerp(a0, a1, s / 8.0), v, do_off(v) + 0.0145), inside=SA.TORSO_AX), 8, top, zt - 0.008, nv=1, relief=0.0022, thick=0.0050,
                groove=None, row=DO_ROWS + 1)
        parts.append(P)
    for sd, sx in (("L", 1.0), ("R", -1.0)):                           # shoulder straps from the breast plate over to the back plate
        S = Part(f"armor_watagami_{sd}", "lacquer", soft="torso", sharp=60)
        pts = [(302, 1.400, 0.030), (312, 1.436, 0.020), (332, 1.462, 0.012), (352, 1.470, 0.010), (14, 1.470, 0.010), (34, 1.458, 0.012), (50, 1.436, 0.020), (58, 1.418, 0.030)]
        path = catmull([robe_pt(a if sx > 0 else 180.0 - a, z, off) for a, z, off in pts], 3)
        mtube(S, path, lambda t: (0.0048, 0.0200, 3.2), 6, (True, True))
        parts.append(S)
    return parts


# ------------------------------------------------------------------------------------------------------------- arms and legs of the lent armour
def kote_parts():
    """Shino-gote: a dark sleeve over the forearm (it goes ON the bare arm of the body, from under the tied-back jacket sleeve to the wrist), three iron splints along
    it, an iron plate on the back of the hand."""
    sh, el, wr, tip, d = SR._arm_points()
    parts = []
    sleeve = SB.prof(*[(t, a + 0.0050, b + 0.0050) for t, a, b in BD.ARM_PROF])
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        K_ = Part(f"cloth_kote_{sd}", "kote", soft=f"arm.{sd}", sharp=80)
        mtube(K_, [V((p.x * sx, p.y, p.z)) for p in BD.arm_path()[:-1]], lambda t, f=sleeve: f(min(t * 1.0, 1.0) * 0.96), 10, (True, True))
        parts.append(K_)
        e, w = V((el.x * sx, el.y, el.z)), V((wr.x * sx, wr.y, wr.z))
        axis = (w - e).normalized()
        side = V((sx, 0, 0))
        ex = (side - axis * side.dot(axis)).normalized()
        ey = axis.cross(ex).normalized()
        S = Part(f"armor_shino_{sd}", "iron", bone=f"forearm.{sd}", sharp=50)
        for deg in (-48.0, 0.0, 48.0):
            dv = ex * math.cos(math.radians(deg)) + ey * math.sin(math.radians(deg))
            pts = [e.lerp(w, f) + dv * (lerp(0.0490, 0.0340, f) + 0.0030) for f in (0.14, 0.38, 0.62, 0.88)]
            mtube(S, pts, lambda t: (0.0068, 0.0068), 5, (True, True))
        parts.append(S)
        B = Part(f"armor_shino_band_{sd}", "lacing", bone=f"forearm.{sd}", sharp=60)                 # the cords that hold them
        for f in (0.20, 0.52, 0.82):
            r = lerp(0.0490, 0.0340, f) + 0.0092
            mtube(B, [e.lerp(w, f - 0.007), e.lerp(w, f + 0.007)], lambda t, r=r: (r, r), 10, (True, True))
        parts.append(B)
        parts.append(BD.tekko_part(sd, "iron", thick=0.0042, lift=0.0015))
    return parts


# ------------------------------------------------------------------------------------------------------------- what he carries
def ration_parts(tier):
    """Uchigai-bukuro: a long cloth tube of rice, knotted into portions, worn from the right shoulder to the left hip and round the back."""
    of = 0.034 if tier == 1 else 0.046                 # in front it lies on the belly guard / on the cuirass
    ob = 0.024 if tier == 1 else 0.044
    front = [(203, 1.456, 0.018), (226, 1.418, of * 0.8), (250, 1.352, of), (275, 1.272, of), (300, 1.204, of), (325, 1.156, of), (350, 1.130, of * 0.9)]
    back = [(15, 1.132, ob), (40, 1.168, ob), (65, 1.228, ob), (90, 1.298, ob), (115, 1.366, ob), (140, 1.420, ob * 0.9), (165, 1.454, 0.020), (186, 1.464, 0.016)]
    pts = [robe_pt(a, z, off) for a, z, off in front + back]
    path = catmull(pts + [pts[0]], 3)
    P = Part("gear_ration", "ration", soft="torso", sharp=50)
    mtube(P, path, lambda t: (0.0200, 0.0200), 8, (False, False), mod=lambda t, a: 0.62 + 0.46 * (0.5 + 0.5 * math.cos(math.tau * 11.0 * t)) ** 0.6)
    return [P]


def sword_parts(tier):
    """Through the sash at the left hip: 1 = the short side arm (the node Side_Tanto), 2 = a long loan sword (not built into the model)."""
    gd = V((0.160, -0.150, 1.060))
    dv = V((0.087, 0.965, -0.246)).normalized()
    hl, sl, rg = (0.150, 0.330, 0.024) if tier == 1 else (0.215, 0.640, 0.034)
    S = Part("gear_saya", "saya", bone="hips", sharp=50)
    S.cyl(gd, gd + dv * sl, 0.0160, 0.0128, 8, ratio=0.72)
    S.sphere(gd + dv * sl, 0.0130, 0.0130, 0.0130, 6, 4)
    T = Part("gear_tsuka", "tsuka", bone="hips", sharp=50)
    T.cyl(gd - dv * 0.012, gd - dv * hl, 0.0148, 0.0136, 8, ratio=0.78)
    T.sphere(gd - dv * hl, 0.0150, 0.0150, 0.0120, 6, 4)
    G = Part("gear_tsuba", "iron", bone="hips", sharp=50)
    G.cyl(gd - dv * 0.012, gd - dv * 0.0055, rg, rg, 10)
    return [S, T, G]


def gourd_parts():
    """A water gourd on a cord at the right hip (the levy brings his own; the lent armour's side tasset hangs there instead)."""
    c = V((-0.196, 0.046, 0.925))
    P = Part("gear_gourd", "gourd", bone="hips", sharp=40)
    P.sphere(c, 0.044, 0.042, 0.050, 9, 6)
    P.sphere(c + V((0.0, 0.0, 0.060)), 0.027, 0.026, 0.030, 8, 5)
    P.cyl(c + V((0.0, 0.0, 0.086)), c + V((0.0, 0.0, 0.104)), 0.0080, 0.0095, 6)
    C = Part("gear_gourd_cord", "cord", bone="hips", sharp=70)
    mtube(C, [c + V((0.0, 0.0, 0.036)), c + V((0.012, -0.004, 0.085)), V((-0.172, 0.030, 1.050))], lambda t: (0.0030, 0.0030), 5, (True, True))
    return [P, C]


def sash_parts():
    S = SB.sash_part()
    S.mat = "obi"
    return [S]


def base_gear():
    """What is his own under any kit: the sash, the head band with its two free tails, the cord that ties his sleeves back."""
    return sash_parts() + AG.hachimaki_parts() + AG.tasuki_parts()


def haraate_set():
    return AG.haraate_parts() + tasset_parts(1) + ration_parts(1) + gourd_parts()


def okegawa_set():
    return do_parts() + tasset_parts(2) + kote_parts() + SA.suneate_parts() + ration_parts(2)


def helmet_parts(kind):
    return hat_parts(kind) + (neckcloth_parts() if kind == 2 else [])


def side_parts():
    return sword_parts(1)


def banner_parts():
    return AG.banner_parts()


# node -> the parts it is made of (build.py joins them; the body is body.all_soft + base_gear)
def nodes():
    from . import spear
    return (("Armour_HaraAte", haraate_set), ("Armour_Okegawa", okegawa_set), ("Helmet_Jingasa", lambda: helmet_parts(1)), ("Helmet_Tetsu", lambda: helmet_parts(2)),
            ("Yari", spear.yari_parts), ("Yari_Long", spear.nagae_parts), ("Side_Tanto", side_parts), ("Sashimono", banner_parts))
