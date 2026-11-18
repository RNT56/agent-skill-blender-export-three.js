"""Katana: blade with hamon-ready steel, tsuba, wrapped tsuka, scabbard (saya) with sageo cord.

Local frame of the sword: origin at the kashira (pommel), +Y toward the tip, +X toward the cutting edge, +Z the flat side.
Two placements share the same hilt+blade parts: `katana_hip` (blade hidden in the saya, hilt visible, bone weapon_hip) and
`katana_hand` (drawn, bone weapon_r). The saya stays on the hip in both states.
"""
import math

from mathutils import Matrix, Vector

from .kit import Part, catmull, lerp

V = Vector

TSUKA = 0.285          # grip length
BLADE = 0.705          # nagasa
TSUBA_Y = TSUKA + 0.004

# hip carry: kashira at the front-left of the sash, edge up, tip behind and slightly down
HIP_ORIGIN = V((0.150, -0.235, 1.085))
HIP_DIR = V((0.085, 0.965, -0.245)).normalized()
HIP_EDGE = V((0.0, 0.245, 0.965)).normalized()          # cutting edge up (perpendicular to the axis)


def placement(origin, axis, edge):
    """Matrix taking the sword's local frame into armature space."""
    y = axis.normalized()
    x = (edge - y * edge.dot(y)).normalized()
    z = x.cross(y).normalized()
    M = Matrix.Identity(4)
    M.col[0], M.col[1], M.col[2], M.col[3] = x.to_4d(), y.to_4d(), z.to_4d(), origin.to_4d()
    M[3][3] = 1.0
    return M


def blade_part(name, bone, M):
    P = Part(name, "steel", bone=bone, sharp=50)
    P.push(M)
    n = 24
    rings = []
    for i in range(n + 1):
        t = i / n
        y = TSUBA_Y + 0.020 + t * (BLADE - 0.020)
        w = lerp(0.0315, 0.0215, t)                         # width kasane/ha
        th = lerp(0.0068, 0.0042, t)                        # thickness
        bow = 0.013 * 4 * t * (1 - t)                        # sori: the middle bows toward the edge
        if t > 0.93:                                         # kissaki: the tip closes in
            k = (t - 0.93) / 0.07
            w *= 1 - 0.85 * k
            th *= 1 - 0.7 * k
        cx = bow
        pts = [V((cx + w * 0.5, y, 0)), V((cx + w * 0.10, y, th * 0.5)), V((cx - w * 0.5, y, th * 0.42)),
               V((cx - w * 0.5, y, -th * 0.42)), V((cx + w * 0.10, y, -th * 0.5))]
        rings.append(pts)
    P.loft(rings, True, (True, True), uv=lambda i, j: (j / 5.0 * 0.03, i / n * BLADE))
    P.pop()
    return P


def hilt_parts(prefix, bone, M):
    parts = []
    G = Part(f"{prefix}_fittings", "gold", bone=bone)
    G.push(M)
    # tsuba (round guard with raised rim) + seppa, fuchi collar, kashira cap
    G.tube([V((0, TSUBA_Y - 0.004, 0)), V((0, TSUBA_Y + 0.004, 0))], lambda t: (0.0425, 0.0425), 20, (True, True))
    G.tube([V((0, TSUBA_Y - 0.006, 0)), V((0, TSUBA_Y + 0.006, 0))], lambda t: (0.0255, 0.0245), 14, (True, True))
    G.tube([V((0, TSUKA - 0.014, 0)), V((0, TSUKA + 0.002, 0))], lambda t: (0.0192, 0.0158), 12, (True, True))
    G.tube([V((0, -0.0075, 0)), V((0, 0.012, 0))], lambda t: (0.0185 - 0.003 * t, 0.0152 - 0.002 * t), 12, (True, True))
    G.tube([V((0, TSUBA_Y + 0.004, 0)), V((0, TSUBA_Y + 0.020, 0))], lambda t: (0.0165, 0.0058), 8, (True, True))   # habaki
    G.pop()
    parts.append(G)
    W = Part(f"{prefix}_wrap", "hemp", bone=bone)
    W.push(M)
    path = [V((0, 0.012, 0)), V((0, 0.10, 0)), V((0, 0.19, 0)), V((0, TSUKA - 0.014, 0))]
    W.tube(path, lambda t: (0.0185 + 0.0015 * math.sin(t * math.pi), 0.0150 + 0.0012 * math.sin(t * math.pi), 2.6), 12, (True, True),
           uvscale=(1.0, 1.0))
    W.pop()
    parts.append(W)
    return parts


def saya_parts(bone="weapon_hip"):
    M = placement(HIP_ORIGIN, HIP_DIR, HIP_EDGE)
    S = Part("katana_saya", "lacquer", bone=bone, sharp=50)
    S.push(M)
    n = 14
    rings = []
    y0, y1 = TSUBA_Y + 0.006, TSUBA_Y + 0.006 + 0.735
    for i in range(n + 1):
        t = i / n
        y = lerp(y0, y1, t)
        w = lerp(0.0205, 0.0165, t)
        th = lerp(0.0125, 0.0105, t)
        bow = 0.012 * 4 * t * (1 - t)
        from .kit import ring
        rings.append(ring(V((bow, y, 0)), V((1, 0, 0)), V((0, 0, 1)), w, th, 12, 2.5))
    S.loft(rings, True, (True, True))
    S.pop()
    G = Part("katana_saya_fittings", "gold", bone=bone)
    G.push(M)
    G.tube([V((0, y0 - 0.004, 0)), V((0, y0 + 0.020, 0))], lambda t: (0.0225, 0.0140), 12, (True, True))             # koiguchi
    G.tube([V((0, y1 - 0.030, 0)), V((0, y1 + 0.008, 0))], lambda t: (0.0172 - 0.004 * t, 0.0112 - 0.003 * t), 10, (True, True))  # kojiri
    G.box((0.016, TSUBA_Y + 0.12, 0.0), 0.004, 0.009, 0.0125)                                                         # kurikata knob
    G.pop()
    C = Part("katana_sageo", "lacing2", bone=bone, sharp=70)
    C.push(M)
    k0 = V((0.020, TSUBA_Y + 0.12, 0.0))
    path = catmull([k0, V((0.040, TSUBA_Y + 0.10, 0.020)), V((0.032, TSUBA_Y + 0.04, 0.046)), V((0.012, TSUBA_Y - 0.01, 0.052)),
                    V((-0.010, TSUBA_Y - 0.05, 0.040))], 4)
    C.tube(path, lambda t: (0.0042, 0.0042), 6, (True, True))
    C.pop()
    return [S, G, C]


def hip_katana():
    M = placement(HIP_ORIGIN, HIP_DIR, HIP_EDGE)
    return hilt_parts("katana_hip", "weapon_hip", M)


def hand_katana(M):
    return [blade_part("katana_hand_blade", "weapon_r", M)] + hilt_parts("katana_hand", "weapon_r", M)
