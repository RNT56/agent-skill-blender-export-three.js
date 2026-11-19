"""The ashigaru's two spears, modelled along the rest shaft (rig.sp): the su-yari (2.3 m, a straight double-edged head, a pennant in the house's colour under it) and
the nagae-yari (3.4 m pike: a longer, heavier shaft lacquered black with a vermilion upper length, a short head). Pattern UV: (around, metres from the butt)."""
import math

from mathutils import Vector

from samurai.kit import Part

from . import rig as R

V = Vector


def _frame():
    r = R.spear_rest()
    return r["D"], r["N"], r["F"]


def _ring(s, ra, rb, n, phase=0.0):
    D, N, F = _frame()
    c = R.sp(s)
    return [c + N * (math.cos(math.tau * j / n + phase) * ra) + F * (math.sin(math.tau * j / n + phase) * rb) for j in range(n)]


def _shaft(P, stations, n=8):
    """stations: [(s, radius)]"""
    rings = [_ring(s, r, r, n) for s, r in stations]
    P.loft(rings, True, (True, True), uv=lambda i, j: (j / n, stations[i][0]))


def _head(P, s0, length, width, thick):
    """A straight double-edged spear head: a diamond section that swells a little above the neck and runs to the point."""
    prof = ((0.0, 0.42, 0.85), (0.10, 0.62, 1.0), (0.30, 1.0, 1.0), (0.72, 0.74, 0.80), (0.93, 0.34, 0.45), (1.0, 0.02, 0.05))
    rings = [_ring(s0 + length * t, width * 0.5 * kw, thick * 0.5 * kt, 4) for t, kw, kt in prof]
    P.loft(rings, True, (True, True))


def yari_parts(low=False):
    """`yari_*` parts make the node Yari (bone weapon_r)."""
    L = R.YARI_LEN
    S = Part("yari_shaft", "shaft", bone="weapon_r", sharp=50)
    _shaft(S, ((0.045, 0.0138), (0.30, 0.0140), (0.90, 0.0138), (1.50, 0.0130), (L - 0.40, 0.0120), (L - 0.262, 0.0116)), 6 if low else 8)
    B = Part("yari_butt", "iron", bone="weapon_r", sharp=50)
    _shaft(B, ((0.0, 0.0095), (0.012, 0.0150), (0.060, 0.0152), (0.066, 0.0138)), 6 if low else 8)
    C = Part("yari_collar", "brass", bone="weapon_r", sharp=50)
    _shaft(C, ((L - 0.268, 0.0128), (L - 0.262, 0.0146), (L - 0.226, 0.0138), (L - 0.218, 0.0100)), 6 if low else 8)
    H = Part("yari_head", "steel", bone="weapon_r", sharp=40)
    _head(H, L - 0.220, 0.220, 0.034, 0.0105)
    out = [S, B, C, H]
    # the pennant: a strip of cloth in the house's colour on a cord under the head (rest: it hangs straight down from the level shaft)
    D, N, F = _frame()
    a = R.sp(R.PENNANT_AT)
    K_ = Part("yari_pennant_cord", "cord", bone="weapon_r", sharp=60)
    _shaft(K_, ((R.PENNANT_AT - 0.012, 0.0142), (R.PENNANT_AT - 0.008, 0.0162), (R.PENNANT_AT + 0.008, 0.0162), (R.PENNANT_AT + 0.012, 0.0142)), 6)
    out.append(K_)
    Pn = Part("yari_pennant", "pennant", soft="pennant", sharp=60)

    def surf(u, v):
        w = R.PENNANT_W * (1.0 - 0.35 * v)                         # it narrows to a blunt tail
        return a + D * ((u - 0.5) * w) + V((0.0, 0.0, -0.016 - R.PENNANT_H * v)), N

    Pn.slab(surf, 2, 5, 0.0026, chamfer=0.0, uvf=lambda u, v: (u * R.PENNANT_W, v * R.PENNANT_H), two_sided=True)
    out.append(Pn)
    return out


def nagae_parts(low=False):
    """`nagae_*` parts make the node Yari_Long (bone weapon_r2)."""
    L = R.NAGAE_LEN
    S = Part("nagae_shaft", "pike", bone="weapon_r2", sharp=50)
    _shaft(S, ((0.050, 0.0152), (0.40, 0.0156), (1.20, 0.0152), (2.10, 0.0140), (L - 0.60, 0.0128), (L - 0.200, 0.0118)), 6 if low else 8)
    B = Part("nagae_butt", "iron", bone="weapon_r2", sharp=50)
    _shaft(B, ((0.0, 0.0100), (0.014, 0.0166), (0.070, 0.0168), (0.078, 0.0152)), 6 if low else 8)
    C = Part("nagae_collar", "brass", bone="weapon_r2", sharp=50)
    _shaft(C, ((L - 0.206, 0.0130), (L - 0.200, 0.0148), (L - 0.166, 0.0138), (L - 0.158, 0.0100)), 6 if low else 8)
    H = Part("nagae_head", "steel", bone="weapon_r2", sharp=40)
    _head(H, L - 0.160, 0.160, 0.028, 0.0100)
    return [S, B, C, H]
