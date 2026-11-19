"""Skeleton of the light archer: the samurai's body skeleton (same proportions, so body parts and locomotion maths are shared) without its armour / sword bones,
plus the bow (grip, two flexing bones per limb, the string's nock point), the nocked arrow, the hachimaki tails and the back banner. 59 bones, all deforming.

A-pose rest, metres, character faces -Y, LEFT = +X. The bow is modelled IN the left hand's grip (thumb toward the upper limb, fingers toward the target), so the
hand.L -> weapon_l relation never changes: clips place the bow and the hand follows rigidly (anim.py).
"""
import math

from mathutils import Vector

from samurai import rig as SR
from samurai.kit import sstep

from . import consts as K

V = Vector
DROP = ("sode.", "skirt_", "sash_", "banner_", "flag_", "weapon_")

# ---------------------------------------------------------------------------------------------------- the yumi (bow-local: u toward the target, w up the bow, s to the arrow side)
BRACE = 0.150                  # string to grip at rest
PULL = 0.62                    # how far the nock point travels at full draw (to the front of the right shoulder: see clips.py)
NOCK_H = 0.036                 # the arrow sits just above the bow hand
BOW_UP, BOW_DN = 1.47, 0.74    # asymmetric: the grip is a third of the way up (2.21 m in all)
BOW_J = (0.10, 0.78, -0.10, -0.40)      # w of the limb joints: upper 1 / 2, lower 1 / 2
ARROW_LEN = 0.92

# ---------------------------------------------------------------------------------------------------- the quiver on the right hip (hips space = armature rest space)
QUIVER_BASE = V((-0.105, 0.172, 0.655))
QUIVER_AXIS = V((-0.105, 0.130, 1.0)).normalized()
QUIVER_LEN = 0.40

# ---------------------------------------------------------------------------------------------------- cloth chains
TAILS = {"a": (0.015, 0.26), "b": (-0.013, 0.20)}          # x of the hachimaki tail at the knot, length
TAIL_Y, TAIL_Z = 0.098, 1.700


def tail_joints(key):
    x, ln = TAILS[key]
    return [V((x, TAIL_Y, TAIL_Z)), V((x * 1.7, TAIL_Y + 0.026, TAIL_Z - ln * 0.5)), V((x * 2.4, TAIL_Y + 0.040, TAIL_Z - ln))]


POLE = [V((0.0, K.YP0, K.ZP0)), V((0.0, K.pole_y(1.76), 1.76)), V((0.0, K.YP1, K.ZP1))]


def flag_joints():
    z = K.TOP - 0.004 - K.CLOTH_H * 0.5
    return [V((K.X0 + K.CLOTH_W * i / 3.0, K.YC + 0.003, z)) for i in range(4)]


# ---------------------------------------------------------------------------------------------------- hands and the bow's rest frame
def hand_frame(side):
    """(wrist, finger direction, palm normal (toward the body in the A-pose), thumb direction) of a rest hand."""
    sh, el, wr, tip, d = SR._arm_points()
    sx = 1.0 if side == "L" else -1.0
    wr, d = V((wr.x * sx, wr.y, wr.z)), V((d.x * sx, d.y, d.z))
    n = V((-sx, 0.0, 0.0))
    n = (n - d * n.dot(d)).normalized()
    th = V((0.0, -1.0, 0.0))
    th = (th - d * th.dot(d) - n * th.dot(n)).normalized()
    return wr, d, n, th


def pinch_rest(side="R"):
    """Where the string hand holds the nock: between thumb and fingers, in front of the palm."""
    wr, d, n, th = hand_frame(side)
    return wr + d * 0.088 + n * 0.026 + th * 0.016


def bow_f(w):
    """u offset of the strung bow's centre line at height w: both tips sit on the string line (u = -BRACE), the tips recurve."""
    ln = BOW_UP if w >= 0 else BOW_DN
    t = min(abs(w) / ln, 1.0)
    return -(BRACE + 0.030) * (0.85 * t * t + 0.15 * t) + 0.030 * sstep(0.86, 1.0, t)


_BOW = {}


def bow_rest():
    """G grip centre, U toward the target, W up the bow (the thumb's side), S the arrow side (the palm faces it)."""
    if not _BOW:
        wr, d, n, th = hand_frame("L")
        a = math.radians(18.0)                      # the string plane passes the palm side of the forearm, not through it
        _BOW.update(G=wr + d * 0.076 + n * 0.030, U=(d * math.cos(a) - n * math.sin(a)).normalized(), W=th.copy(),
                    S=(n * math.cos(a) + d * math.sin(a)).normalized())
    return _BOW


def bp(u, w, s=0.0):
    b = bow_rest()
    return b["G"] + b["U"] * u + b["W"] * w + b["S"] * s


def nock0():
    return bp(-BRACE, NOCK_H)


def arrow_rest():
    return bp(0.0, NOCK_H, 0.017)                   # the shaft lies on the thumb, on the arrow side of the bow


def arrow_dir0():
    return (arrow_rest() - nock0()).normalized()


def quiver_slot(k):
    """(nock position, direction toward the head) of arrow k in the quiver; k = -1 is the slot the string hand draws from (the nocked arrow appears there)."""
    ax = QUIVER_AXIS
    e1 = ax.cross(V((0, 1, 0))).normalized()
    e2 = ax.cross(e1).normalized()
    if k < 0:
        ang, rr, dl = math.radians(200.0), 0.030, 0.012
    else:
        ang, rr, dl = math.radians(18.0 + 61.0 * k), 0.016 + 0.014 * ((k * 7) % 3) / 2.0, 0.018 * math.sin(k * 2.3)
    off = e1 * (math.cos(ang) * rr) + e2 * (math.sin(ang) * rr)
    d = (-ax + off * 0.55).normalized()             # the shafts fan out of the mouth a little
    mouth = QUIVER_BASE + ax * QUIVER_LEN + off
    return mouth - d * (0.54 + dl), d


def bone_table():
    T = [(n, p, h.copy(), t.copy()) for n, p, h, t in SR.bone_table() if not n.startswith(DROP)]

    def add(n, p, h, t):
        T.append((n, p, V(h), V(t)))

    for key in "ab":
        j = tail_joints(key)
        add(f"tail_{key}1", "head", j[0], j[1])
        add(f"tail_{key}2", f"tail_{key}1", j[1], j[2])
    add("banner_1", "chest", POLE[0], POLE[1])
    add("banner_2", "banner_1", POLE[1], POLE[2])
    fj = flag_joints()
    for i in range(3):
        add(f"flag_{i + 1}", "banner_2" if i == 0 else f"flag_{i}", fj[i], fj[i + 1])
    u1, u2, l1, l2 = BOW_J
    add("weapon_l", "hand.L", bp(0.0, l1), bp(0.0, u1))
    add("bow_u1", "weapon_l", bp(bow_f(u1), u1), bp(bow_f(u2), u2))
    add("bow_u2", "bow_u1", bp(bow_f(u2), u2), bp(bow_f(BOW_UP), BOW_UP))
    add("bow_l1", "weapon_l", bp(bow_f(l1), l1), bp(bow_f(l2), l2))
    add("bow_l2", "bow_l1", bp(bow_f(l2), l2), bp(bow_f(-BOW_DN), -BOW_DN))
    add("bow_nock", "weapon_l", nock0(), nock0() - bow_rest()["U"] * 0.08)
    add("arrow", "root", nock0(), nock0() + arrow_dir0() * 0.30)
    return T


def build_armature(coll, table=None):
    ob = SR.build_armature(coll, table or bone_table())
    ob.name = ob.data.name = "ArcherRig"
    return ob
