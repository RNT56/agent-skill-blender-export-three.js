"""Tachi: the first age's sword (bloom iron). Longer and more deeply curved than the katana, and worn SLUNG, edge DOWN, hanging from the sash by two
cords tied to bands on the scabbard (the katana is thrust through the sash edge up).

The same local frame and the same hilt as the katana (katana.py), and the pommel hangs where the katana's sits at the hip, so every clip that takes the
hand to the hilt (draw, sheathe, equip) meets it. Nodes: Tachi_Drawn (bone weapon_r), Tachi_Sheathed (the hilt at the hip, weapon_hip), Tachi_Saya
(scabbard, its two hanger bands and the cords up to the sash, weapon_hip).
Plain where the katana is fine: blackened iron fittings (no gold) and a greyer bloom-iron blade with a faint temper line.
"""
from mathutils import Vector

from . import katana as K
from .kit import Part, catmull

V = Vector
BLADE, SORI = 0.780, 0.030          # nagasa, and how far the middle bows
SAYA_LEN = BLADE + 0.035
HANG = 0.030                        # it hangs this far below where the katana is thrust through the sash
SASH_X, SASH_Z = 0.158, 1.072      # where the sash is at the left hip (armature space)
ASHI = (0.115, 0.300)               # the two hanger bands, metres along the scabbard from its mouth


def hip_matrix():
    return K.placement(K.HIP_ORIGIN + V((0.012, 0.0, -HANG)), (K.HIP_DIR + V((0.0, 0.0, 0.06))).normalized(), -K.HIP_EDGE)       # edge down, a little more level


def hand_tachi(M):
    return [K.blade_part("tachi_hand_blade", "weapon_r", M, blade=BLADE, sori=SORI, mat="bloom")] + K.hilt_parts("tachi_hand", "weapon_r", M, trim="iron")


def hip_tachi():
    return K.hilt_parts("tachi_hip", "weapon_hip", hip_matrix(), trim="iron")


def saya_parts():
    M = hip_matrix()
    parts = K.saya_parts(M=M, prefix="tachi", length=SAYA_LEN, sori=SORI * 0.95, sageo=False, mat="rawhide", trim="iron")
    y0 = K.TSUBA_Y + 0.006
    B = Part("tachi_saya_ashi", "iron", bone="weapon_hip")
    C = Part("tachi_cords", "lacing2", bone="weapon_hip", sharp=70)
    B.push(M)
    C.push(M)
    Mi = M.inverted()
    up = (Mi.to_3x3() @ V((0.0, 0.0, 1.0))).normalized()            # armature up, in the sword's frame (the back of the blade, more or less)
    inn = (Mi.to_3x3() @ V((-1.0, 0.0, 0.0))).normalized()          # toward the body
    tied = []
    for s in ASHI:
        t = s / SAYA_LEN
        bow = SORI * 0.95 * 4 * t * (1 - t)
        c = V((bow, y0 + s, 0.0))
        B.tube([c - V((0, 0.007, 0)), c + V((0, 0.007, 0))], lambda t_: (0.0235, 0.0150), 12, (True, True))
        top = c + up * 0.016
        cw = M @ top                                                 # each cord goes up and IN to the sash at the left hip (not straight up into the air)
        knot = Mi @ V((SASH_X, min(max(cw.y, -0.07), 0.085), SASH_Z))
        C.tube(catmull([top, top.lerp(knot, 0.35) + up * 0.012, top.lerp(knot, 0.8), knot], 4), lambda t_: (0.0040, 0.0040), 6, (True, True))
        tied.append(knot)
    # the cord runs on between the two knots along the sash, and its end hangs
    C.tube(catmull([tied[0], (tied[0] + tied[1]) * 0.5 - inn * 0.006, tied[1]], 4), lambda t_: (0.0040, 0.0040), 6, (True, True))
    C.tube(catmull([tied[0], tied[0] - up * 0.05 - inn * 0.012, tied[0] - up * 0.12 - inn * 0.016], 4), lambda t_: (0.0040, 0.0034), 6, (True, True))
    B.pop()
    C.pop()
    return parts + [B, C]
