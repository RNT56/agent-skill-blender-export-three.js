"""Pure constants of the archer's back banner, shared by its geometry, shader, emblem region and cloth chains (no bpy / mathutils: usable from plain python)."""
CLOTH_W, CLOTH_H, TOP = 0.18, 0.44, 2.20                 # a smaller flag than the samurai's (rank), still above the war hat
X0 = 0.014                                                  # cloth starts just beside the pole
BOTTOM = TOP - 0.004 - CLOTH_H
ZP0, ZP1 = 1.25, 2.26                                       # pole base (in the socket on the back) and top
YP0, YP1 = 0.168, 0.300                                     # the pole LEANS back (7.5 degrees) so the brim of the war hat never touches it
YC = 0.302                                                  # cloth bar y (the pole's y at TOP + a few mm)


def pole_y(z):
    return YP0 + (YP1 - YP0) * (z - ZP0) / (ZP1 - ZP0)
