"""The archer's clips: each is (params(t), duration, loop?, meta). Locomotion is analytic (planted-foot cycles, the samurai's gait with the bow carried in the left hand);
the stance, the shot, hit and death are keyed poses of the BOW, the string hand and the body, blended with Catmull-Rom and solved to FK by anim.Solver.

The shot follows the simulation's `yumi_shot` action (samurai-vale content/actions.js): nock 0.35 s, draw 0.45 s, the arrow leaves at 0.80 s, follow-through to 1.1667 s.
Events: `arrow` = the nocked-arrow node appears (the string hand has just taken it from the quiver), `release` = it leaves the string (hide the node, the game's arrow flies).
"""
import math

from mathutils import Euler, Vector

from samurai import gait
from samurai.clips import keyed, lift_sliding_feet

from . import rig as R

V = Vector
TAU = math.tau
AZ = 0.092                      # planted ankle height
HIPS_C = V((0.0, 0.0, 0.93))


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def pw(keys, t, ease=True):
    """piecewise interpolation of [(time, value)] (smooth between keys)"""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            u = (t - t0) / max(t1 - t0, 1e-9)
            return lerp(v0, v1, smooth(u) if ease else u)
    return keys[-1][1]


def hw(hips, hrot, v):
    """hips space (= armature rest space of something carried on the hips) -> armature space for a hips pose"""
    Rm = Euler([math.radians(a) for a in hrot], "XYZ").to_matrix()
    return HIPS_C + Rm @ (V(v) - HIPS_C) + V(hips)


def hd(hrot, d):
    return Euler([math.radians(a) for a in hrot], "XYZ").to_matrix() @ V(d)


# ------------------------------------------------------------------------------------------------------------- pose pieces
def foot(x, y, yaw, pitch=0.0, toe=0.0, z=AZ, knee=None, kpole=None):
    d = dict(pos=V((x, y, z)), yaw=yaw, pitch=pitch, toe=toe, knee=yaw if knee is None else knee)
    if kpole is not None:
        d["kpole"] = V(kpole)
    return d


def bowd(G, U, W, pole=(0.5, 0.3, -0.8)):
    return dict(G=V(G), U=V(U), W=V(W), pole=V(pole))


def handd(pinch, dir, palm, pole=(-0.55, 0.45, -0.7)):
    return dict(pinch=V(pinch), dir=V(dir), palm=V(palm), pole=V(pole))


def nock_of(bow, draw=0.0):
    """where the string's nock point is for a bow key (the string hand's place)"""
    U = V(bow["U"]).normalized()
    W = V(bow["W"])
    W = (W - U * W.dot(U)).normalized()
    return V(bow["G"]) - U * (R.BRACE + draw * R.PULL) + W * R.NOCK_H


SLOT_O, SLOT_D = R.quiver_slot(-1)          # the arrow the string hand draws: nock position and direction, hips space


def pose(hips, hrot, spine, neck, fl, fr, bow, hand=None, curl=(0.85, 0.30), spole=(0.3, 0.8, -0.6), tilt=18.0, draw=0.0):
    b = bow
    if hand is None:                          # on the string
        n = nock_of(b, draw)
        hand = handd(n, b["U"], (0, 0, -1))
    return dict(hips_pos=V(hips), hips_rot=tuple(hrot), spine=tuple(spine), neck=tuple(neck), footL=fl, footR=fr, bow=b, handR=hand, curl_L=curl[0], curl_R=curl[1],
                string_pole=V(spole), string_tilt=tilt, arrow=dict(dir=hd(hrot, SLOT_D)))


def finish(P, nockw=0.0, draw=0.0, arrow_w=None):
    """after blending: the fields that are not blended (spaces, the string state)"""
    P["handR"]["space"] = "world"
    P["arrow"]["space"] = "world"
    P["nockw"], P["draw"] = nockw, draw
    P["arrow_w"] = nockw if arrow_w is None else arrow_w
    return P


def _keyed(ks, t):
    """blend keys [(seconds, pose)] at time t; a foot that travels between keys is lifted (a step, not a slide)"""
    P = keyed(ks, t)
    h = 0.03
    return lift_sliding_feet(P, keyed(ks, max(0.0, t - h)), keyed(ks, min(ks[-1][0], t + h)), 2 * h)


# ------------------------------------------------------------------------------------------------------------- at ease, locomotion
IDLE_FL, IDLE_FR = (0.135, 0.03, 9.0), (-0.135, -0.02, -9.0)
BOW_EASE = bowd((0.270, -0.290, 1.130), (-0.06, -0.99, -0.10), (0.10, -0.10, 0.99), pole=(0.6, 0.5, -0.6))        # upright in the left hand, the forearm level
HAND_HANG = handd((-0.393, -0.088, 0.832), (-0.37, -0.12, -0.92), (0.93, -0.05, -0.37))


def ease_pose(dz=0.0, sway=0.0, breath=0.0, look=0.0):
    b = bowd(V(BOW_EASE["G"]) + V((0.004 * sway, 0.0, dz + 0.004 * breath)), V(BOW_EASE["U"]), V(BOW_EASE["W"]) + V((0.012 * sway, 0.010 * breath, 0.0)), BOW_EASE["pole"])
    h = handd(V(HAND_HANG["pinch"]) + V((0.006 * sway, 0.004 * breath, dz + 0.003 * breath)), HAND_HANG["dir"], HAND_HANG["palm"], HAND_HANG["pole"])
    return pose((0.010 * sway, 0.0, -0.014 + dz), (0, 0, 2.0 * sway), (1.2 + 0.9 * breath, 0.6 * sway, 0.0), (-1.0 * breath, 0.0, 3.5 * sway + look),
                foot(*IDLE_FL), foot(*IDLE_FR), b, h, curl=(0.85, 0.22))


def idle(t):
    ph = TAU * t / 8.0                                                       # a breath every 4 s; now and then he looks down the field
    look = 14.0 * smooth((math.sin(ph) - 0.55) / 0.45)                       # now and then he looks down the field
    return finish(ease_pose(0.004 * math.sin(ph * 2), math.sin(ph), math.sin(ph * 2 + 0.6), look))


def locomotion(t, G, lean, swing, arm_bend=0.0, bow=None, crouch=0.0):
    """Planted-foot cycle (samurai.gait.cycle: G = dict(T, ahead, behind, duty, lift, bob, sink, ...); forward = -Y). The bow rides in the left hand, steady; the right arm swings."""
    feet, hips, ph2 = gait.cycle(t, **G)
    fl, fr = feet["L"], feet["R"]
    sink = G["sink"]
    tw = math.sin(ph2 + 0.2)
    sw = swing * tw
    Gb, U, W, pole = bow
    b = bowd(V(Gb) + hips + V((0.0, 0.04 * sw, 0.012 * math.cos(2 * ph2))), U, V(W) + V((0.03 * math.sin(ph2), 0.0, 0.0)), pole)
    P = dict(hips_pos=hips, hips_rot=(lean * 0.4, 0.0, 7.0 * tw), spine=(lean * 0.8 + crouch, -9.0 * tw * (1 - 0.5 * min(crouch / 20.0, 1.0)), 2.5 * math.sin(ph2)),
             neck=(-lean * 0.6 - crouch * 0.9, 4.0 * tw, 0.0),
             footL=foot(fl["pos"].x, fl["pos"].y, fl["yaw"], fl["pitch"], fl["toe"], fl["pos"].z), footR=foot(fr["pos"].x, fr["pos"].y, fr["yaw"], fr["pitch"], fr["toe"], fr["pos"].z), bow=b,
             handR=dict(pos=V((-0.285 - 0.02 * arm_bend, -0.02 - sw, 0.93 + 0.15 * arm_bend - 0.25 * sink * min(crouch / 20.0, 1.0))), pole=V((-0.5, 0.6, -0.5)), space="hips"),
             curl_L=0.85, curl_R=0.30, nockw=0.0, draw=0.0, arrow_w=0.0)
    return P


BOW_WALK = ((0.335, -0.225, 1.035), (0.04, -0.80, -0.60), (-0.07, -0.60, 0.80), (0.6, 0.5, -0.6))          # the top leans forward as he walks
BOW_RUN = ((0.345, -0.170, 1.010), (0.05, -0.64, -0.77), (-0.08, -0.77, 0.64), (0.6, 0.5, -0.6))            # and further when he runs
BOW_SNEAK = ((0.215, -0.300, 0.985), (0.10, -0.62, -0.78), (0.86, -0.46, 0.22), (0.5, 0.4, -0.7))           # held low and level across the front, under the grass tops

# a march of 120 steps a minute at 1.2 m/s; a run of 167 at the archer's 3.2 m/s; a creep of 110 at the sim's 1.2 m/s for a crouched man (the game plays a clip at
# measured speed / stride speed, so at the unit's own speed these play as authored)
WALK_V, RUN_V, SNEAK_V = 1.20, 3.20, 1.20
WALK_G = dict(T=1.00, ahead=0.300, behind=0.444, duty=gait.duty_for(WALK_V, 1.00, 0.300, 0.444), lift=0.080, bob=0.020, sink=0.045, rise=0.070)
RUN_G = dict(T=0.72, ahead=0.240, behind=0.432, duty=gait.duty_for(RUN_V, 0.72, 0.240, 0.432), lift=0.180, bob=0.042, sink=0.080, rise=0.105, spacing=0.085, run=True, toe=46.0)
SNEAK_G = dict(T=1.10, ahead=0.340, behind=0.400, duty=gait.duty_for(SNEAK_V, 1.10, 0.340, 0.400), lift=0.060, bob=0.012, sink=0.300, rise=0.050, spacing=0.110)


def walk(t):
    return locomotion(t, WALK_G, 3.0, 0.18, bow=BOW_WALK)


def run(t):
    return locomotion(t, RUN_G, 9.0, 0.28, arm_bend=1.0, bow=BOW_RUN)


def sneak(t):
    return locomotion(t, SNEAK_G, 10.0, 0.08, arm_bend=0.6, bow=BOW_SNEAK, crouch=22.0)


# ------------------------------------------------------------------------------------------------------------- the stance and the shot
ST_HIPS, ST_HROT = (0.0, -0.010, -0.050), (0.0, 0.0, -72.0)          # side-on to the target (which is ahead, -Y): the left shoulder leads
ST_FL, ST_FR = (0.045, -0.270, -48.0), (-0.025, 0.270, -96.0)        # ashibumi: the feet on the line of the shot, toes turned out
# A foot archer under a war hat cannot draw to the ear: the string would cut the brim. He draws to the front of the right shoulder with the bow canted
# (top to his right, 20 degrees), so the upper strand rises clear of the hat and the lower one runs along the belly wrap.
BOW_READY = bowd((-0.060, -0.500, 1.080), (-0.03, -0.98, -0.20), (-0.06, -0.20, 0.975), pole=(0.4, 0.1, -0.9))
BOW_NOCK = bowd((-0.095, -0.530, 1.170), (-0.02, -1.00, -0.05), (-0.22, -0.05, 0.975), pole=(0.4, 0.1, -0.9))
BOW_RAISE = bowd((-0.130, -0.615, 1.395), (0.00, -0.999, 0.04), (-0.32, 0.04, 0.946), pole=(0.5, 0.0, -0.9))
BOW_AIM = bowd((-0.135, -0.700, 1.378), (0.00, -0.9995, 0.03), (-0.34, 0.03, 0.940), pole=(0.5, 0.0, -0.9))
BOW_LOOSE = bowd((-0.135, -0.716, 1.374), (0.00, -0.9995, 0.03), (-0.32, -0.11, 0.940), pole=(0.5, 0.0, -0.9))
BOW_AFTER = bowd((-0.135, -0.710, 1.366), (0.00, -0.9995, 0.02), (-0.30, -0.18, 0.935), pole=(0.5, 0.0, -0.9))
REL_T = 0.80
SHOT_T = 35.0 / 30.0
READY_T = 0.70                 # into and out of the stance
DEATH_T = 1.25                 # real time (the game no longer speeds it up): the blow, the knees go, the ground at 1.0 s, a settle


def ready_pose(dz=0.0, sway=0.0):
    b = bowd(V(BOW_READY["G"]) + V((0.004 * sway, 0.0, dz)), BOW_READY["U"], V(BOW_READY["W"]) + V((0.010 * sway, 0.0, 0.0)), BOW_READY["pole"])
    return pose(V(ST_HIPS) + V((0.004 * sway, 0.0, dz)), ST_HROT, (3.0, 0.0, -6.0), (2.0, 0.0, 66.0), foot(*ST_FL), foot(*ST_FR), b, curl=(0.85, 0.55))


def combat_idle(t):
    ph = TAU * t / 4.0                                                       # in the stance: a breath every 2 s
    return finish(ready_pose(0.005 * math.sin(ph * 2), math.sin(ph)), nockw=1.0)


def _shot_keys(kneel=None):
    """The shot's keys. kneel = (dz, footL, footR, first/last pose): the same shot from one knee (the yumi's short lower limb is made for it)."""
    dz = kneel[0] if kneel else 0.0
    fl, fr = (kneel[1], kneel[2]) if kneel else (foot(*ST_FL), foot(*ST_FR))

    def lower(b):
        return bowd(V(b["G"]) + V((0, 0, dz)), b["U"], b["W"], b["pole"])

    def k(hips, spine, neck, bow, hand=None, curl=(0.85, 0.55), spole=(0.3, 0.8, -0.6), draw=0.0):
        hp = V(hips) + V((0, 0, dz))
        if hand is not None:
            hand = handd(V(hand["pinch"]) + V((0, 0, dz)), hand["dir"], hand["palm"], hand["pole"])
        return pose(hp, ST_HROT, spine, neck, fl, fr, lower(bow), hand, curl=curl, spole=spole, draw=draw)

    h_q = (0.0, -0.005, -0.050)
    grab = handd(hw(h_q, ST_HROT, SLOT_O) - V((0, 0, 0.0)), hd(ST_HROT, (-0.15, 0.70, 0.70)), hd(ST_HROT, (0.55, -0.45, 0.70)), pole=hd(ST_HROT, (-0.85, 0.25, 0.45)))
    carry = handd((-0.260, 0.060, 1.300), (-0.25, -0.90, 0.25), (0.10, 0.25, -0.95), pole=(-0.1, 0.9, -0.3))
    back1 = handd((-0.165, 0.370, 1.400), (0.10, -0.97, 0.05), (0.0, 0.10, -1.0), pole=(0.3, 0.6, -0.7))
    back2 = handd((-0.175, 0.570, 1.375), (0.05, -0.99, 0.00), (0.0, 0.05, -1.0), pole=(0.3, 0.5, -0.8))
    first = kneel[3] if kneel else k(ST_HIPS, (3, 0, -6), (2, 0, 66), BOW_READY)
    return [
        (0.00, first),
        (0.13, k(h_q, (2, 0, -3), (2, 0, 62), BOW_READY, grab, curl=(0.85, 0.80))),
        (0.24, k(ST_HIPS, (3, 0, -6), (2, 0, 66), BOW_NOCK, carry, curl=(0.85, 0.80))),
        (0.35, k(ST_HIPS, (3, 0, -6), (1, 0, 68), BOW_NOCK, curl=(0.88, 0.75))),
        (0.47, k((0.0, -0.020, -0.045), (0, 2, -8), (1, 0, 70), BOW_RAISE, curl=(0.90, 0.78), spole=(0.3, 1.0, -0.15), draw=0.18)),
        (0.70, k((0.0, -0.030, -0.050), (0, 3, -8), (3, 0, 72), BOW_AIM, curl=(0.92, 0.78), spole=(0.35, 1.0, -0.10), draw=1.0)),
        (REL_T, k((0.0, -0.030, -0.050), (0, 3, -8), (3, 0, 72), BOW_AIM, curl=(0.92, 0.78), spole=(0.35, 1.0, -0.10), draw=1.0)),
        (0.8334, k((0.0, -0.034, -0.050), (0, 3, -9), (3, 0, 72), BOW_LOOSE, back1, curl=(0.80, 0.15), spole=(0.35, 1.0, -0.10))),
        (0.94, k((0.0, -0.034, -0.052), (0, 3, -10), (3, 0, 72), BOW_AFTER, back2, curl=(0.80, 0.12))),
        (SHOT_T, first),
    ]


def _shot(t, ks):
    P = _keyed(ks, t)
    nockw = pw([(0.0, 1.0), (0.045, 0.0), (0.20, 0.0), (0.335, 1.0), (REL_T, 1.0), (REL_T + 0.012, 0.0), (1.00, 0.0), (SHOT_T, 1.0)], t)
    arrow_w = pw([(0.0, 0.0), (0.14, 0.0), (0.33, 1.0), (SHOT_T, 1.0)], t)
    if t <= REL_T + 1e-6:
        draw = pw([(0.0, 0.0), (0.35, 0.0), (0.47, 0.18), (0.70, 1.0), (REL_T, 1.0)], t)
        draw += 0.006 * math.sin(TAU * 9.0 * t) * smooth((t - 0.70) / 0.05)          # the held bow trembles
    else:                                                        # the string snaps forward and rings
        draw = -0.045 * math.exp(-(t - REL_T) / 0.07) * math.cos(TAU * 11.0 * (t - REL_T))
    return finish(P, nockw, draw, arrow_w)


_SHOT_KEYS = None


def shoot(t):
    global _SHOT_KEYS
    if _SHOT_KEYS is None:
        _SHOT_KEYS = _shot_keys()
    return _shot(t, _SHOT_KEYS)


def aim(t):
    """Held at full draw (a volley waiting for the signal): the same pose as the shot's last instant, breathing."""
    ph = TAU * t / 3.0
    b = bowd(V(BOW_AIM["G"]) + V((0.002 * math.sin(ph), 0.0, 0.004 * math.sin(ph * 2))), BOW_AIM["U"], BOW_AIM["W"], BOW_AIM["pole"])
    P = pose((0.0, -0.030, -0.050 + 0.003 * math.sin(ph * 2)), ST_HROT, (0, 3, -8), (3, 0, 72), foot(*ST_FL), foot(*ST_FR), b, curl=(0.92, 0.78), spole=(0.35, 1.0, -0.10), draw=1.0)
    return finish(P, 1.0, 1.0 + 0.005 * math.sin(TAU * 4.0 * t) + 0.004 * math.sin(ph * 2 + 1.0), 1.0)


def ready(t):
    """From standing at ease into the shooting stance: a step, the turn side-on, the string hand goes to the string."""
    T = READY_T
    mid = pose((0.0, -0.006, -0.040), (0, 0, -40.0), (2.5, 0, -3), (1, 0, 36), foot(0.095, -0.150, -26.0), foot(-0.085, 0.140, -55.0),
               bowd((0.110, -0.420, 1.110), (-0.05, -0.99, -0.15), (0.10, -0.15, 0.98), pole=(0.5, 0.3, -0.8)),
               handd((-0.200, -0.180, 1.020), (0.10, -0.80, -0.55), (0.60, 0.10, -0.80)), curl=(0.85, 0.40))
    keys = [(0.0, ease_pose()), (0.5 * T, mid), (T, ready_pose())]
    return finish(_keyed(keys, t), nockw=pw([(0.0, 0.0), (0.50 * T, 0.0), (0.93 * T, 1.0)], t))


def stand_down(t):
    return ready(READY_T - t)


def hit(t):
    T = 0.6
    r = ready_pose()

    def k(hips, hrot, spine, neck, dg, w):
        b = bowd(V(BOW_READY["G"]) + V(dg), BOW_READY["U"], V(BOW_READY["W"]) + V(w), BOW_READY["pole"])
        return pose(hips, hrot, spine, neck, foot(*ST_FL), foot(*ST_FR), b, curl=(0.9, 0.5))

    keys = [(0.0, r), (0.18 * T, k((0.02, 0.085, -0.075), (0, 5, -64), (-6, 10, -2), (-10, -8, 56), (0.03, 0.10, 0.03), (0.10, 0.16, 0.0))),
            (0.42 * T, k((0.01, 0.050, -0.070), (0, 3, -68), (-2, 6, -4), (-5, -4, 62), (0.02, 0.06, 0.02), (0.05, 0.08, 0.0))), (T, r)]
    return finish(_keyed(keys, t), nockw=1.0)


def death(t):
    """Struck: he staggers back off the line, the knees go, he falls on his back; the bow drops from the open hand's reach."""
    T = DEATH_T
    r = ready_pose()
    k1 = pose((0.02, 0.120, -0.090), (-8, 4, -56), (-12, 8, -2), (-14, -6, 40), foot(0.060, -0.200, -40.0), foot(-0.040, 0.300, -90.0),
              bowd((0.060, -0.420, 1.060), (-0.05, -0.95, -0.30), (0.25, -0.25, 0.93)), handd((-0.300, 0.150, 1.050), (-0.40, 0.20, -0.90), (0.80, 0.10, -0.50)), curl=(0.6, 0.3))
    k2 = pose((0.04, 0.240, -0.480), (-30, 4, -36), (-16, 6, 0), (-12, 0, 20), foot(0.100, -0.120, -24.0), foot(-0.100, 0.260, -70.0),
              bowd((0.330, -0.250, 0.620), (0.10, -0.75, -0.65), (0.55, -0.55, 0.63)), handd((-0.400, 0.300, 0.560), (-0.60, 0.30, -0.75), (0.60, 0.00, -0.80)), curl=(0.35, 0.2))
    k3 = pose((0.05, 0.340, -0.790), (-74, 2, -18), (-12, 2, 0), (-8, 0, 8), foot(0.150, -0.050, -8.0), foot(-0.140, 0.140, -30.0),
              bowd((0.560, 0.220, 0.085), (0.25, -0.20, -0.95), (0.75, -0.66, 0.02)), handd((-0.520, 0.560, 0.085), (-0.75, 0.60, -0.25), (0.15, 0.10, -0.98)), curl=(0.2, 0.15))
    k4 = dict(k3, hips_pos=V(k3["hips_pos"]) + V((0.0, 0.008, 0.006)), spine=(-9, 2, 0))          # the body settles
    keys = [(0.0, r), (0.19 * T, k1), (0.50 * T, k2), (0.80 * T, k3), (T, k4)]
    return finish(keyed(keys, t), nockw=pw([(0.0, 1.0), (0.10, 0.0)], t))


# ------------------------------------------------------------------------------------------------------------- hidden in the grass
KN_DZ = -0.415
KN_FL = foot(0.030, -0.330, -30.0, knee=-20.0)
KN_FR = foot(0.085, 0.455, -60.0, pitch=72.0, toe=-40.0, z=0.075, kpole=(-0.25, -0.45, -1.0))


def crouch_pose(breath=0.0, sway=0.0):
    b = bowd(V((0.060, -0.430, 0.700)) + V((0.003 * sway, 0.0, 0.004 * breath)), (0.05, -0.70, -0.71), (0.84, -0.50, 0.22), pole=(0.4, 0.2, -0.9))
    return pose(V(ST_HIPS) + V((0.0, 0.02, KN_DZ - 0.035 + 0.004 * breath)), (10.0, 0.0, -52.0), (24.0 + 1.5 * breath, 0.0, 8.0), (-22.0, 0.0, 44.0 + 4.0 * sway), KN_FL, KN_FR, b,
                curl=(0.85, 0.55), spole=(0.2, 0.6, -0.8))


def crouch_idle(t):
    ph = TAU * t / 5.0
    return finish(crouch_pose(math.sin(ph * 2), math.sin(ph)), nockw=1.0)


_KSHOT_KEYS = None


def crouch_shoot(t):
    global _KSHOT_KEYS
    if _KSHOT_KEYS is None:
        _KSHOT_KEYS = _shot_keys((KN_DZ, KN_FL, KN_FR, crouch_pose()))
    return _shot(t, _KSHOT_KEYS)



# ------------------------------------------------------------------------------------------------------------- taking up a piece of kit
EQUIP_T, EQUIP_TAKE = 1.6, 0.85                 # an engine changes the piece he carries at EQUIP_TAKE: the moment the free hand closes on it


def _equip_pose(reach, lift, look=0.0):
    """Standing at ease, the bow upright in the left hand. reach 0..1: he leans to the rack and the right hand goes out; lift 0..1: he brings the piece up to himself."""
    lean = reach * (1.0 - lift)
    b = bowd(V(BOW_EASE["G"]) + V((0.0, -0.020 * lean, -0.030 * lean)), V(BOW_EASE["U"]), V(BOW_EASE["W"]), BOW_EASE["pole"])
    pinch = V(HAND_HANG["pinch"]).lerp(V((-0.205, -0.455, 0.960)), reach).lerp(V((-0.130, -0.225, 1.340)), lift)
    d = V(HAND_HANG["dir"]).lerp(V((0.10, -0.95, -0.25)), reach).lerp(V((0.45, -0.35, 0.80)), lift).normalized()
    pm = V(HAND_HANG["palm"]).lerp(V((0.95, 0.10, -0.25)), reach).lerp(V((0.75, 0.55, -0.30)), lift).normalized()
    h = handd(pinch, d, pm, V(HAND_HANG["pole"]) + V((0.0, -0.45 * lift, 0.25 * lift)))
    return pose((0.0, -0.040 * lean, -0.014 - 0.045 * lean), (0, 0, 7.0 * lean), (1.2 + 15.0 * lean, 0.0, 6.0 * lean), (5.0 * lean - 9.0 * lift, 0.0, look + 10.0 * lean),
                foot(*IDLE_FL), foot(*IDLE_FR), b, h, curl=(0.85, 0.22 + 0.60 * max(lift, reach * reach)))


def equip(t):
    """At a rack: he reaches out with the string hand, takes the piece (EQUIP_TAKE), lifts it to himself and stands at ease again."""
    keys = [(0.0, _equip_pose(0.0, 0.0)), (0.42, _equip_pose(0.80, 0.0)), (EQUIP_TAKE, _equip_pose(1.0, 0.0)), (1.22, _equip_pose(1.0, 1.0)), (EQUIP_T, _equip_pose(0.0, 0.0))]
    return finish(_keyed(keys, min(t, EQUIP_T)))


CLIPS = {
    "equip": dict(fn=equip, duration=EQUIP_T, loop=False, weapon="none", events={"take": EQUIP_TAKE}),
    "idle": dict(fn=idle, duration=8.0, loop=True, weapon="none"),
    "walk": dict(fn=walk, duration=WALK_G["T"], loop=True, weapon="none", speed=WALK_V),
    "run": dict(fn=run, duration=RUN_G["T"], loop=True, weapon="none", speed=RUN_V),
    "ready": dict(fn=ready, duration=READY_T, loop=False, weapon="none"),
    "stand_down": dict(fn=stand_down, duration=READY_T, loop=False, weapon="none"),
    "combat_idle": dict(fn=combat_idle, duration=4.0, loop=True, weapon="none"),
    "shoot": dict(fn=shoot, duration=SHOT_T, loop=False, weapon="none", events={"arrow": 0.1333, "release": REL_T}),
    "aim": dict(fn=aim, duration=3.0, loop=True, weapon="arrow"),
    "crouch_idle": dict(fn=crouch_idle, duration=5.0, loop=True, weapon="none"),
    "sneak": dict(fn=sneak, duration=SNEAK_G["T"], loop=True, weapon="none", speed=SNEAK_V),
    "crouch_shoot": dict(fn=crouch_shoot, duration=SHOT_T, loop=False, weapon="none", events={"arrow": 0.1333, "release": REL_T}),
    "hit": dict(fn=hit, duration=0.6, loop=False, weapon="none"),
    "death": dict(fn=death, duration=DEATH_T, loop=False, weapon="none"),
}


def arrow_at(name, t):
    """is the nocked-arrow node visible at time t of a clip?"""
    c = CLIPS[name]
    ev = c.get("events", {})
    if "arrow" in ev:
        return ev["arrow"] <= t < ev["release"]
    return c["weapon"] == "arrow"
