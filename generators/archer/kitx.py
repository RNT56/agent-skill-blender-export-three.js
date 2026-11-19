"""Extra mesh helpers for the archer on top of samurai.kit: modulated tubes (real cloth folds), thin vanes (fletching), closed cord loops."""
import math

from mathutils import Vector

from samurai.kit import TAU

V = Vector


def g(v, c, s):
    """gaussian bump"""
    return math.exp(-((v - c) / s) ** 2)


def mrings(path, section, n=12, mod=None, up=V((0, 0, 1))):
    """Rings of a superellipse swept along `path`; mod(t, angle) scales the radius (folds, pleats). section(t) -> (rx, ry[, p[, ox, oy]])."""
    pts = [V(p) for p in path]
    rings = []
    for k, p in enumerate(pts):
        t = k / max(len(pts) - 1, 1)
        a = pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]
        a.normalize()
        ex = a.cross(up if abs(a.dot(up)) < 0.95 else V((1, 0, 0)))
        ex.normalize()
        ey = a.cross(ex)
        ey.normalize()
        s = section(t)
        rx, ry = s[0], s[1]
        pw = s[2] if len(s) > 2 else 2.0
        ox, oy = (s[3], s[4]) if len(s) > 4 else (0.0, 0.0)
        c = p + ex * ox + ey * oy
        e = 2.0 / pw
        rg = []
        for j in range(n):
            ang = TAU * j / n
            ct, st = math.cos(ang), math.sin(ang)
            m = mod(t, ang) if mod else 1.0
            rg.append(c + ex * (rx * m * math.copysign(abs(ct) ** e, ct)) + ey * (ry * m * math.copysign(abs(st) ** e, st)))
        rings.append(rg)
    return rings


def mtube(P, path, section, n=12, caps=(True, True), mod=None, up=V((0, 0, 1)), uvscale=(1.0, 1.0)):
    return P.loft(mrings(path, section, n, mod, up), True, caps, uvscale=uvscale)


def loop(c, e1, e2, r, n=14):
    """closed circle path (first point repeated) around c in the plane (e1, e2)"""
    return [V(c) + V(e1) * (math.cos(TAU * k / n) * r) + V(e2) * (math.sin(TAU * k / n) * r) for k in range(n + 1)]


def vane(P, o, along, radial, s0, s1, h, th=0.0012):
    """One feather of a fletching: a thin closed prism on the shaft from s0 to s1 (metres from the nock `o` along `along`), standing `h` out along `radial`.
    UV: u = 0..1 along the feather, v = 0..1 from quill to edge (both faces alike, so the barring matches)."""
    along, radial = V(along).normalized(), V(radial).normalized()
    tg = along.cross(radial).normalized() * (th * 0.5)
    L = s1 - s0
    prof = ((0.0, 0.0), (0.05, 1.0), (0.62, 0.86), (1.0, 0.0))          # (u, v): cut square at the nock end, swept to a point toward the head
    quill = ((0.0, 0.0), (0.05, 0.0), (0.62, 0.0), (1.0, 0.0))
    top, bot = [], []
    for sgn in (1.0, -1.0):
        row_q = [P.v(V(o) + along * (s0 + L * u) + radial * 0.003 + tg * sgn) for u, _ in quill]
        row_e = [P.v(V(o) + along * (s0 + L * u) + radial * (0.003 + h * v) + tg * sgn) for u, v in prof]
        (top if sgn > 0 else bot).append((row_q, row_e))
    (q0, e0), (q1, e1) = top[0], bot[0]
    for i in range(3):
        u0, u1 = prof[i][0], prof[i + 1][0]
        v0, v1 = prof[i][1], prof[i + 1][1]
        P.face([q0[i], q0[i + 1], e0[i + 1], e0[i]], [(u0, 0), (u1, 0), (u1, v1), (u0, v0)])
        P.face([q1[i], e1[i], e1[i + 1], q1[i + 1]], [(u0, 0), (u0, v0), (u1, v1), (u1, 0)])
        P.face([e0[i], e0[i + 1], e1[i + 1], e1[i]], [(u0, v0), (u1, v1), (u1, v1), (u0, v0)])      # outer edge
        P.face([q0[i], q1[i], q1[i + 1], q0[i + 1]], [(u0, 0), (u0, 0), (u1, 0), (u1, 0)])          # quill side
    P.face([q0[0], e0[0], e1[0], q1[0]], [(0, 0), (0, 0), (0, 0), (0, 0)])
    P.face([q0[3], q1[3], e1[3], e0[3]], [(1, 0), (1, 0), (1, 0), (1, 0)])
