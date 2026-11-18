"""Pure constants shared by the banner geometry, its shader, the emblem sheet and the cloth chains (no bpy / mathutils: usable from plain python)."""
CLOTH_W, CLOTH_H, TOP = 0.22, 0.56, 2.42                 # the cloth stands above the helmet crest (1.84 m): it must not hide the head from behind
X0 = 0.014                                                  # cloth starts just beside the pole
BOTTOM = TOP - 0.004 - CLOTH_H
YP0, YP, YC = 0.185, 0.215, 0.225                           # pole axis y at the bracket / above the neck guard; cloth bar y
