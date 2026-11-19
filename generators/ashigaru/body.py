"""The ashigaru's body and clothes (A-pose rest): what he wears under ANY kit. Head, kosode and the lower legs are the archer's (same skeleton, same face); his own
are the arms (sleeves tied back, bare forearms, cloth over the backs of the hands) and narrow knee-breeches. Armour, hat, spear and side arm are separate pieces
(gear.py, spear.py) that go over this body: nothing here is cut away for them, so he is whole without any of them."""
import math

from mathutils import Vector

from samurai import armour as SA, body as SB, rig as SR
from samurai.kit import Part, catmull, lerp, param_surf, sstep
from archer import body as AB
from archer.kitx import mtube

V = Vector


def tekko_part(sd, mat, thick=0.003, lift=0.0):
    """Cloth (or a plate) over the back of a hand."""
    sh, el, wr, tip, d = SR._arm_points()
    sx = 1.0 if sd == "L" else -1.0
    w, tp = V((wr.x * sx, wr.y, wr.z)), V((tip.x * sx, tip.y, tip.z))
    hd = (tp - w).normalized()
    palm = V((-sx, 0.0, 0.0))
    nrm = (palm - hd * palm.dot(hd)).normalized()
    lat = hd.cross(nrm).normalized()
    T = Part(f"cloth_tekko_{sd}", mat, bone=f"hand.{sd}")

    def ft(u, v):
        c = w + hd * (0.004 + 0.070 * v)
        hw = lerp(0.030, 0.041, v)
        return c + lat * ((u - 0.5) * 2 * hw) - nrm * (0.0185 + lift + 0.007 * (1 - (2 * u - 1) ** 2))

    T.slab(param_surf(ft, inside=lambda p: w + hd * (p - w).dot(hd)), 4, 3, thick, chamfer=0.06, uvf=lambda u, v: (u * 0.08, v * 0.07))
    return T


def arm_parts():
    """Sleeves tied back above the elbow, bare forearms, cloth over the backs of the hands (the lent armour's dark sleeves and splints go over them: gear.kote_parts)."""
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
        A = Part(f"body_arm_{sd}", "skin", soft=f"arm.{sd}", sharp=80)
        mtube(A, [m(p) for p in arm_path()], SB.prof(*ARM_PROF), 10, (True, True))
        out.append(A)
        out.append(tekko_part(sd, "yugote"))
    return out


ARM_PROF = ((0.0, 0.044, 0.046), (0.14, 0.042, 0.044), (0.29, 0.039, 0.041), (0.43, 0.043, 0.046), (0.64, 0.038, 0.040), (0.84, 0.031, 0.031), (0.96, 0.028, 0.025), (1.0, 0.027, 0.024))


def arm_path():
    """the left forearm's centre line from mid upper arm to the hand (mirror x for the right)"""
    sh, el, wr, tip, d = SR._arm_points()
    return (sh.lerp(el, 0.50), sh.lerp(el, 0.80), el, el.lerp(wr, 0.22), el.lerp(wr, 0.55), el.lerp(wr, 0.85), wr, wr + d * 0.016)


def trouser_parts():
    """Momohiki: narrow breeches tied under the knee (the lent armour's greaves go over the gaiters below them)."""
    k = 0.82
    out = []
    T = Part("cloth_hakama_top", "hakama", soft="pelvis")
    rings = []
    for z, rx, ry in ((1.055, 0.150, 0.110), (1.00, 0.157, 0.114), (0.95, 0.165, 0.118), (0.90, 0.168, 0.121), (0.855, 0.160, 0.116)):
        pts = []
        for j in range(36):
            a = math.tau * j / 36
            front = max(0.0, -math.sin(a))
            kk = 1.0 + 0.012 * front * math.cos(8.0 * (a + math.pi / 2)) * sstep(1.06, 0.98, z)
            x, y = SA.sup(a, rx * kk, ry * kk, 2.0 + 0.5 * sstep(1.00, 0.90, z))
            pts.append(V((x, -0.004 + y, z)))
        rings.append(pts)
    T.loft(rings, True, (True, True))
    out.append(T)
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        P = Part(f"cloth_hakama_{sd}", "hakama", soft=f"leg.{sd}")
        zs = (0.93, 0.86, 0.78, 0.70, 0.62, 0.55, 0.505, 0.475, 0.455)
        path = [V((SR.leg_center(z)[0] * sx, SR.leg_center(z)[1], z)) for z in zs]
        mtube(P, path, SB.prof((0.0, 0.104, 0.108), (0.22, 0.110 * (0.5 + 0.5 * k), 0.116 * (0.5 + 0.5 * k)), (0.55, 0.115 * k, 0.121 * k), (0.78, 0.106 * k, 0.110 * k),
                               (0.90, 0.082 * (0.4 + 0.6 * k), 0.084 * (0.4 + 0.6 * k)), (1.0, 0.064, 0.066)), 18, (True, True),
              mod=lambda t, a, sx=sx: 1.0 + 0.020 * math.sin(5.0 * a + 3.0 * t + sx) * sstep(0.10, 0.45, t) * (1.0 - 0.5 * sstep(0.80, 1.0, t)))
        out.append(P)
    return out


def hand_parts(table):
    out = []
    for sd in ("L", "R"):
        out += SB.hand_parts(sd, table)
    return out


def all_soft(table):
    return AB.head_parts() + AB.hair_parts() + AB.kosode_parts() + arm_parts() + trouser_parts() + AB.leg_parts() + hand_parts(table)
