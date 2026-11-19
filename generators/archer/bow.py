"""The yumi (asymmetric war bow) with its string, and arrows. Bow-local axes come from rig.bow_rest(): u toward the target, w up the bow, s to the arrow side.
The limbs are one loft weighted softly to weapon_l / bow_u1 / bow_u2 / bow_l1 / bow_l2 (they flex when drawn); the string is two straight strands from the tips to
the nock bone, so it forms the V of a drawn bow by itself."""
import math

from mathutils import Vector

from samurai.kit import Part, lerp, ring, sstep

from . import rig as R
from .kitx import vane

V = Vector


def _limb_w():
    lo = [-R.BOW_DN * (1.0 - k / 13.0) for k in range(13)]
    up = [R.BOW_UP * k / 24.0 for k in range(25)]
    return lo + up


def bow_parts(low=False):
    """low=True: the far-LOD bow (4-sided limbs, 13 rings, no grip or serving): it is joined into the LOD2 body AFTER decimation, which would shred a thin bow."""
    b = R.bow_rest()
    U, W, S = b["U"], b["W"], b["S"]
    if low:
        P = Part("lowbow_limbs", "yumi", soft="bow", sharp=55)
        ws = [-R.BOW_DN * (1.0 - k / 4.0) for k in range(4)] + [R.BOW_UP * k / 8.0 for k in range(9)]
        rings = []
        for w in ws:
            t = abs(w) / (R.BOW_UP if w >= 0 else R.BOW_DN)
            tg = (R.bp(R.bow_f(w + 0.01), w + 0.01) - R.bp(R.bow_f(w - 0.01), w - 0.01)).normalized()
            rings.append(ring(R.bp(R.bow_f(w), w), S, S.cross(tg).normalized(), lerp(0.0150, 0.0095, t), lerp(0.0115, 0.0070, t), 4, 2.0))
        P.loft(rings, True, (True, True), uv=lambda i, j: (j / 4.0 * 0.07, ws[min(i, len(ws) - 1)]))
        St = Part("lowbow_string", "string", soft="string", sharp=80)
        n0 = R.nock0()
        for tip_w in (R.BOW_UP - 0.012, -R.BOW_DN + 0.012):
            tip = R.bp(R.bow_f(tip_w) - 0.0065, tip_w)
            a_, c_ = (tip, n0) if tip_w > 0 else (n0, tip)
            St.loft([ring(a_, S, U, 0.0030, 0.0030, 3), ring(c_, S, U, 0.0030, 0.0030, 3)], True, (True, True))
        return [P, St]
    P = Part("bow_limbs", "yumi", soft="bow", sharp=55)
    ws = _limb_w()
    rings = []
    for w in ws:
        ln = R.BOW_UP if w >= 0 else R.BOW_DN
        t = abs(w) / ln
        c = R.bp(R.bow_f(w), w)
        tg = (R.bp(R.bow_f(w + 0.01), w + 0.01) - R.bp(R.bow_f(w - 0.01), w - 0.01)).normalized()
        eu = S.cross(tg).normalized()
        k = 1.0 - 0.72 * sstep(0.955, 1.0, t)                                     # the tips close in
        hw = lerp(0.0138, 0.0082, t ** 1.2) * k
        ht = lerp(0.0102, 0.0058, t ** 1.1) * k
        rings.append(ring(c, S, eu, hw, ht, 8, 3.0))
    P.loft(rings, True, (True, True), uv=lambda i, j: (j / 8.0 * 0.07, ws[min(i, len(ws) - 1)]))       # v = metres from the grip: the shader places the rattan bindings by it
    G = Part("bow_grip", "leather", bone="weapon_l", sharp=60)
    rg = []
    for w, k in ((-0.070, 0.80), (-0.058, 1.0), (0.0, 1.06), (0.062, 1.0), (0.074, 0.80)):
        rg.append(ring(R.bp(R.bow_f(w), w), S, U, 0.0163 * k, 0.0128 * k, 10, 2.6))
    G.loft(rg, True, (True, True))
    St = Part("bow_string", "string", soft="string", sharp=80)
    n0 = R.nock0()
    for tip_w in (R.BOW_UP - 0.012, -R.BOW_DN + 0.012):
        tip = R.bp(R.bow_f(tip_w) - 0.0065, tip_w)
        a, c = (tip, n0) if tip_w > 0 else (n0, tip)
        St.loft([ring(a, S, U, 0.0015, 0.0015, 4), ring(c, S, U, 0.0015, 0.0015, 4)], True, (True, True))
    Sv = Part("bow_serving", "cord", bone="bow_nock", sharp=80)                     # the reinforced centre of the string where the arrow is nocked
    Sv.loft([ring(n0 - W * 0.030, S, U, 0.0024, 0.0024, 5), ring(n0 + W * 0.045, S, U, 0.0024, 0.0024, 5)], True, (True, True))
    return [P, G, St, Sv]


def arrow_into(Sh, Fl, Hd, o, d, length, spin=0.0):
    """One arrow from its nock at `o` along `d`: shaft (into part Sh), three feathers (Fl), and a head (Hd, or None when it is hidden in the quiver)."""
    o, d = V(o), V(d).normalized()
    e1 = d.cross(V((0, 0, 1)) if abs(d.z) < 0.9 else V((1, 0, 0))).normalized()
    e2 = d.cross(e1).normalized()
    Sh.loft([ring(o + d * s, e1, e2, r, r, 5) for s, r in ((0.0, 0.0030), (0.010, 0.0044), (0.028, 0.0040), (length, 0.0040))], True, (True, True),
            uv=lambda i, j: (j / 5.0 * 0.025, (0.0, 0.010, 0.028, length)[i]))
    for k in range(3):
        ang = spin + math.tau * k / 3.0
        vane(Fl, o, d, e1 * math.cos(ang) + e2 * math.sin(ang), 0.030, 0.165, 0.0155)
    if Hd is not None:
        tip = o + d * length
        Hd.loft([ring(tip - d * 0.012, e1, e2, 0.0050, 0.0050, 4), ring(tip + d * 0.004, e1, e2, 0.0058, 0.0034, 4), ring(tip + d * 0.026, e1, e2, 0.0074, 0.0022, 4),
                 ring(tip + d * 0.058, e1, e2, 0.0010, 0.0008, 4)], True, (True, True))


def arrow_parts():
    """The nocked arrow (node Arrow_Nocked, bone `arrow`): shown from the moment the string hand takes it out of the quiver until the release."""
    o, d = R.nock0(), R.arrow_dir0()
    Sh = Part("arrow_shaft", "shaft", bone="arrow", sharp=60)
    Fl = Part("arrow_fletch", "fletch", bone="arrow", sharp=80)
    Hd = Part("arrow_head", "steel", bone="arrow", sharp=40)
    arrow_into(Sh, Fl, Hd, o, d, R.ARROW_LEN - 0.058)
    return [Sh, Fl, Hd]
