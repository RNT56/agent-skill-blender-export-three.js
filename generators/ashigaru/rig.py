"""Skeleton of the ashigaru (spear infantry): the samurai's body skeleton (same proportions: body parts, locomotion maths and the archer's head are shared) without
its sword and shoulder-guard bones, plus the spear. ONE skeleton carries every piece of kit the model has, so any armour, hat, spear and side arm go together:
62 bones. A-pose rest, metres, the character faces -Y, LEFT = +X.

The spear is modelled IN the right hand's grip, its shaft along the fist's axis with the head on the thumb side (forward in the A-pose). Two weapon bones hang on the
right hand, one per spear: `weapon_r` carries the su-yari (and its pennant), `weapon_r2` the long nagae-yari. Each SLIDES along its own shaft (a location key): the
hand holds a spear at different places (near the butt in the guard, at shoulder height when it stands on the ground), and the pike is held a hand's breadth further up
than the short spear so its thrust ends where the simulation says it reaches. Clips place the spear; both hands follow it (anim.py).

Also: the two tails of the head band, the six tassets' bones (the hara-ate uses the front two, the lent armour all six), the back banner's pole and flag.
"""
from mathutils import Vector

from samurai import rig as SR
from archer import consts as K, rig as AR

V = Vector
DROP = ("sode.", "sash_", "banner_", "flag_", "weapon_")

YARI_LEN, NAGAE_LEN = 2.30, 3.40        # butt to point: the armoury's `yari` (content/items.js: 2.3 m) and the pike of the spear wall
GRIP0 = 0.80                            # where the right hand holds a spear in the rest pose, metres from the butt
PENNANT_AT = YARI_LEN - 0.335           # the pennant's cord, metres from the butt
PENNANT_W, PENNANT_H = 0.085, 0.235

_S = {}


def spear_rest():
    """G: centre of the right fist's grip, D: along the shaft toward the head (the thumb's side), N: from the palm toward the shaft, F: the fingers' direction."""
    if not _S:
        wr, d, n, th = AR.hand_frame("R")
        _S.update(G=wr + d * 0.076 + n * 0.027, D=th.normalized(), N=n.copy(), F=d.copy())
    return _S


def grip_rest(side):
    """Grip centre of a rest hand and its frame (shaft axis toward the thumb, palm-to-shaft normal)."""
    wr, d, n, th = AR.hand_frame(side)
    return wr + d * 0.076 + n * 0.027, th.normalized(), n.copy(), wr


def sp(s, a=0.0, b=0.0):
    """A point of the rest spear: s metres from the butt along the shaft, a toward the palm normal, b along the fingers."""
    r = spear_rest()
    return r["G"] + r["D"] * (s - GRIP0) + r["N"] * a + r["F"] * b


def pennant_joints():
    a = sp(PENNANT_AT)
    return [a + V((0.0, 0.0, -0.016)), a + V((0.0, 0.0, -0.016 - PENNANT_H * 0.5)), a + V((0.0, 0.0, -0.016 - PENNANT_H))]


def bone_table():
    T = [(n, p, h.copy(), t.copy()) for n, p, h, t in SR.bone_table() if not n.startswith(DROP)]

    def add(n, p, h, t):
        T.append((n, p, V(h), V(t)))

    add("weapon_r", "hand.R", sp(GRIP0 - 0.10), sp(GRIP0 + 0.20))
    add("weapon_r2", "hand.R", sp(GRIP0 - 0.10, 0.0, 0.0), sp(GRIP0 + 0.20))
    pj = pennant_joints()
    add("pennant_1", "weapon_r", pj[0], pj[1])
    add("pennant_2", "pennant_1", pj[1], pj[2])
    for key in "ab":
        j = AR.tail_joints(key)
        add(f"tail_{key}1", "head", j[0], j[1])
        add(f"tail_{key}2", f"tail_{key}1", j[1], j[2])
    add("banner_1", "chest", AR.POLE[0], AR.POLE[1])
    add("banner_2", "banner_1", AR.POLE[1], AR.POLE[2])
    fj = AR.flag_joints()
    for i in range(3):
        add(f"flag_{i + 1}", "banner_2" if i == 0 else f"flag_{i}", fj[i], fj[i + 1])
    return T


def build_armature(coll):
    ob = SR.build_armature(coll, bone_table())
    ob.name = ob.data.name = "AshigaruRig"
    return ob
