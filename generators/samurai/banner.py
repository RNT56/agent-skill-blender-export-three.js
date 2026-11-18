"""Sashimono: the team banner on the back (pole, cross bar, cloth with a mon). A separate node (`Sashimono`), baked into LOD1/2.
Soft-weighted to the two banner bones (chest -> banner_1 -> banner_2) that the clips flutter."""
import math

from mathutils import Vector

from .kit import Part

V = Vector
from .consts import BOTTOM, CLOTH_H, CLOTH_W, TOP, X0, YC, YP, YP0  # noqa: F401  (geometry constants live in consts.py)


def banner_parts():
    pole = Part("banner_pole", "lacquer", soft="banner", sharp=60)
    # the pole leaves the bracket, swings back behind the neck guard (shikoro: its back face is at y ~0.19 near z 1.5) and rises straight; measured clearance >= 9 mm in every clip
    pole.tube([V((0, YP0, 1.30)), V((0, YP, 1.50)), V((0, YP, 1.70)), V((0, YP + 0.002, 2.10)), V((0, YP + 0.005, TOP + 0.04))], lambda t: (0.0075, 0.0075), 6, (True, True))
    pole.tube([V((0, YC, TOP)), V((CLOTH_W + 0.02, YC, TOP))], lambda t: (0.0050, 0.0050), 5, (True, True))          # cross bar
    br = Part("banner_bracket", "iron", bone="chest", sharp=60)
    br.box((0, 0.150, 1.315), 0.034, 0.012, 0.038)                                                                          # plate on the back armour
    br.box((0, 0.172, 1.315), 0.014, 0.016, 0.022)                                                                          # standoff from the plate to the pole base
    cloth = Part("banner_cloth", "banner", soft="flag", sharp=60)

    def surf(u, v):
        return V((X0 + CLOTH_W * u, YC + 0.0045, TOP - 0.004 - CLOTH_H * v)), V((0, 1, 0))

    cloth.slab(surf, 3, 8, 0.0030, chamfer=0.0, uvf=lambda u, v: (u * CLOTH_W, v * CLOTH_H), two_sided=True)
    return [pole, br, cloth]
