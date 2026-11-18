"""Skeleton for the samurai: one table drives the Blender armature, the skin weights and the pose solver.

A-pose rest, metres, character faces -Y, LEFT = +X (bones .L at +X, .R mirrored). 55 bones, all deforming, so the
exported glTF skin is exactly this list. Rolls are aligned so a bone's local Z points forward; the pose code never
depends on roll because it works in armature-aligned rotation deltas (see pose.py).
"""
import math

import bpy
from mathutils import Vector

from . import cloth as C, katana as K

V = Vector
S_ARM = math.radians(24.0)          # A-pose abduction of the arm from vertical (matches the reference turnaround)

# the leg axis in the rest pose: hip joint -> knee -> ankle, legs spread ~6 degrees outward like the reference
LEG_PTS = ((0.90, 0.095, 0.000), (0.49, 0.148, -0.022), (0.088, 0.192, -0.012))

# kosode torso section (z, half-width, half-depth), shared by the robe and the armour that follows it
TORSO_Z = [0.86, 0.93, 1.00, 1.08, 1.16, 1.24, 1.32, 1.38, 1.43]
TORSO_RX = [0.165, 0.160, 0.152, 0.148, 0.156, 0.170, 0.182, 0.184, 0.150]
TORSO_RY = [0.118, 0.115, 0.108, 0.110, 0.120, 0.128, 0.138, 0.132, 0.104]


def leg_center(z):
    """(x, y) of the LEFT leg axis at height z (mirror x for the right leg)."""
    z = min(max(z, LEG_PTS[-1][0]), LEG_PTS[0][0])
    for a, b in zip(LEG_PTS, LEG_PTS[1:]):
        if z >= b[0]:
            u = (a[0] - z) / (a[0] - b[0])
            return a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u
    return LEG_PTS[-1][1], LEG_PTS[-1][2]


def _arm_points():
    sh = V((0.17, 0.0, 1.405))
    el = sh + V((math.sin(S_ARM), 0.004, -math.cos(S_ARM))) * 0.29
    wr = el + V((math.sin(S_ARM * 0.92), -0.12, -math.cos(S_ARM * 0.92))).normalized() * 0.26
    d = (wr - el).normalized()
    hand_tip = wr + d * 0.095
    return sh, el, wr, hand_tip, d


def grip_origin():
    """Drawn-katana kashira position and tip direction in the A-pose right hand (grip 0.20 m up the hilt)."""
    sh, el, wr, tip, d = _arm_points()
    dm = V((-d.x, d.y, d.z))                         # right hand: mirrored
    palm_n = V((1.0, 0.0, 0.0))
    g = V((-wr.x, wr.y, wr.z)) + dm * 0.078 + palm_n * 0.034      # the hilt lies in front of the palm, under the curled fingers
    t = V((0.0, -1.0, 0.0))
    return g - t * 0.20, t


def bone_table():
    """Ordered (parents first) list of (name, parent, head, tail). Left side is mirrored to the right."""
    T = []

    def add(n, p, h, t):
        T.append((n, p, V(h), V(t)))

    add("root", None, (0, 0, 0), (0, 0, 0.14))
    add("hips", "root", (0, 0, 0.93), (0, 0, 1.03))
    add("spine", "hips", (0, 0, 1.03), (0, 0, 1.15))
    add("spine1", "spine", (0, 0, 1.15), (0, 0, 1.28))
    add("chest", "spine1", (0, 0, 1.28), (0, 0, 1.42))
    add("neck", "chest", (0, 0, 1.42), (0, -0.004, 1.54))
    add("head", "neck", (0, -0.004, 1.54), (0, -0.004, 1.76))

    sh, el, wr, tip, d = _arm_points()
    for sd, sx in (("L", 1.0), ("R", -1.0)):
        def m(v):
            return V((v.x * sx, v.y, v.z))
        add(f"shoulder.{sd}", "chest", m(V((0.035, 0.0, 1.395))), m(sh))
        add(f"upper_arm.{sd}", f"shoulder.{sd}", m(sh), m(el))
        add(f"forearm.{sd}", f"upper_arm.{sd}", m(el), m(wr))
        add(f"hand.{sd}", f"forearm.{sd}", m(wr), m(tip))
        # fingers: palm faces the body (-X for the left hand), thumb forward (-Y), pinky back (+Y)
        palm_n = V((-1.0, 0.0, 0.0))
        for k, fn in enumerate(("index", "middle", "ring", "pinky")):
            off = V((0.0, (k - 1.5) * 0.0215, 0.0))
            base = tip + off
            ln = (0.046, 0.052) if fn != "pinky" else (0.036, 0.042)
            if fn == "middle":
                ln = (0.050, 0.056)
            d1 = (d + palm_n * 0.20).normalized()
            d2 = (d + palm_n * 0.55).normalized()
            p1 = base + d1 * ln[0]
            p2 = p1 + d2 * ln[1]
            add(f"{fn}_01.{sd}", f"hand.{sd}", m(base), m(p1))
            add(f"{fn}_02.{sd}", f"{fn}_01.{sd}", m(p1), m(p2))
        tb = wr + d * 0.035 + V((0.0, -0.032, 0.0)) + palm_n * 0.012
        td = (V((0.0, -1.0, 0.0)) * 0.8 + d * 0.5 + palm_n * 0.35).normalized()
        t1 = tb + td * 0.040
        t2 = t1 + (td + palm_n * 0.3).normalized() * 0.036
        add(f"thumb_01.{sd}", f"hand.{sd}", m(tb), m(t1))
        add(f"thumb_02.{sd}", f"thumb_01.{sd}", m(t1), m(t2))

        hp = V((LEG_PTS[0][1], LEG_PTS[0][2], LEG_PTS[0][0]))
        kn = V((LEG_PTS[1][1], LEG_PTS[1][2], LEG_PTS[1][0]))
        an = V((LEG_PTS[2][1], LEG_PTS[2][2], LEG_PTS[2][0]))
        add(f"thigh.{sd}", "hips", m(hp), m(kn))
        add(f"shin.{sd}", f"thigh.{sd}", m(kn), m(an))
        add(f"foot.{sd}", f"shin.{sd}", m(an), m(V((an.x, -0.125, 0.045))))
        add(f"toe.{sd}", f"foot.{sd}", m(V((an.x, -0.125, 0.045))), m(V((an.x, -0.215, 0.030))))

        add(f"sode.{sd}", "chest", m(V((0.205, 0.005, 1.44))), m(V((0.265, 0.005, 1.27))))
        add(f"skirt_front.{sd}", "hips", m(V((0.065, -0.150, 0.975))), m(V((0.070, -0.168, 0.74))))
        add(f"skirt_side.{sd}", "hips", m(V((0.175, -0.015, 0.975))), m(V((0.195, -0.015, 0.75))))
        add(f"skirt_back.{sd}", "hips", m(V((0.070, 0.150, 0.975))), m(V((0.075, 0.168, 0.74))))
    # cloth chains (cloth.py simulates them per clip and bakes the result): obi tails on the hips, the sashimono pole on the chest, the flag along the cloth
    for key in "ab":
        j = C.sash_joints(key)
        add(f"sash_{key}1", "hips", j[0], j[1])
        add(f"sash_{key}2", f"sash_{key}1", j[1], j[2])
    add("banner_1", "chest", C.POLE[0], C.POLE[1])
    add("banner_2", "banner_1", C.POLE[1], C.POLE[2])
    fj = C.flag_joints()
    for i in range(3):
        add(f"flag_{i + 1}", "banner_2" if i == 0 else f"flag_{i}", fj[i], fj[i + 1])
    add("weapon_hip", "hips", K.HIP_ORIGIN, K.HIP_ORIGIN + K.HIP_DIR * 0.30)
    go, gt = grip_origin()
    add("weapon_r", "hand.R", go, go + gt * 0.30)
    return T


def build_armature(coll, table=None):
    table = table or bone_table()
    arm = bpy.data.armatures.new("SamuraiRig")
    ob = bpy.data.objects.new("SamuraiRig", arm)
    coll.objects.link(ob)
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = {}
    for name, parent, head, tail in table:
        b = arm.edit_bones.new(name)
        b.head, b.tail = head, tail
        b.use_deform = True
        if parent:
            b.parent = eb[parent]
        eb[name] = b
        v = (tail - head).normalized()
        fwd = V((0, -1, 0)) if abs(v.dot(V((0, -1, 0)))) < 0.9 else V((0, 0, 1))
        b.align_roll(fwd)
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.display_type = "OCTAHEDRAL"
    for pb in ob.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return ob
