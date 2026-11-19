"""The ashigaru's clips: each is (params(t), duration, loop?, meta). Locomotion is analytic (planted-foot cycles, the samurai's gait with the spear sloped on the right
shoulder); the guard, the thrusts, hit and death are keyed poses of the SPEAR and the body, blended with Catmull-Rom and solved to FK by anim.Solver.

The thrust follows the simulation's `yari_thrust` action (samurai-vale content/actions.js): wind-up 0.45 s, the point arrives at 0.45 s, recovery to 0.9667 s (29 frames;
the action says 0.95 s: inside one frame). Event: `impact`. Both tiers and both spears play the same clips: the pike is held `pike_up` further from its butt wherever
the spear is levelled, so its point ends half a metre beyond the short spear's, which is what the nagae-yari technique adds to the unit's reach.
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


# ------------------------------------------------------------------------------------------------------------- pose pieces
def foot(x, y, yaw, pitch=0.0, toe=0.0, z=AZ, knee=None, kpole=None):
    d = dict(pos=V((x, y, z)), yaw=yaw, pitch=pitch, toe=toe, knee=yaw if knee is None else knee)
    if kpole is not None:
        d["kpole"] = V(kpole)
    return d


def spear(B, D, nR, nL=(0.0, 0.0, 1.0), poleR=(-0.55, 0.50, -0.65), poleL=(0.55, 0.30, -0.75)):
    """B: where the right hand holds the shaft, D: toward the head, nR / nL: from each palm toward the shaft (how the hand is turned about it)"""
    return dict(B=V(B), D=V(D).normalized(), nR=V(nR), nL=V(nL), poleR=V(poleR), poleL=V(poleL))


HANG_L = dict(pos=V((0.287, -0.030, 0.887)), pole=V((0.55, 0.45, -0.7)))


def pose(hips, hrot, spine, neck, fl, fr, sp, grip, slide=None, pike_up=0.0, handL=None, curl=(0.9, 1.0)):
    """slide = metres from the right hand to the left along the shaft (None: the left hand is free and goes to handL, hips space)"""
    P = dict(hips_pos=V(hips), hips_rot=tuple(hrot), spine=tuple(spine), neck=tuple(neck), footL=fl, footR=fr, spear=sp, gripR=float(grip), pike_up=float(pike_up),
             curl_L=curl[0], curl_R=curl[1], handL=dict(pos=V((handL or HANG_L)["pos"]), pole=V((handL or HANG_L)["pole"])), lhand=0.0 if slide is None else 1.0,
             slide=0.50 if slide is None else float(slide))
    return P


def _keyed(ks, t):
    """blend keys [(seconds, pose)] at time t; a foot that travels between keys is lifted (a step, not a slide)"""
    P = keyed(ks, t)
    h = 0.03
    return lift_sliding_feet(P, keyed(ks, max(0.0, t - h)), keyed(ks, min(ks[-1][0], t + h)), 2 * h)


# ------------------------------------------------------------------------------------------------------------- at ease: the spear stands on the ground
IDLE_FL, IDLE_FR = (0.135, 0.03, 9.0), (-0.135, -0.02, -9.0)
BUTT = V((-0.325, -0.090, 0.0))                 # where the butt stands, beside the right foot
EASE_GRIP = 1.06                                # the right hand's height on the upright shaft
EASE_NR = (0.50, -0.86, 0.0)                    # the palm is behind the shaft, on its outer side


def ease_pose(dz=0.0, sway=0.0, breath=0.0, look=0.0):
    D = V((0.028 + 0.010 * sway, 0.042 + 0.006 * breath, 1.0)).normalized()
    g = (EASE_GRIP + dz) / D.z
    sp = spear(BUTT + D * g, D, EASE_NR, poleR=(-0.30, 0.95, -0.35))
    hl = dict(pos=V(HANG_L["pos"]) + V((0.006 * sway, 0.004 * breath, 0.003 * breath)), pole=HANG_L["pole"])
    return pose((0.010 * sway, 0.0, -0.014 + dz), (0, 0, 2.0 * sway), (1.2 + 0.9 * breath, 0.6 * sway, 0.0), (-1.0 * breath, 0.0, 3.5 * sway + look),
                foot(*IDLE_FL), foot(*IDLE_FR), sp, g, handL=hl, curl=(0.25, 1.0))


def idle(t):
    ph = TAU * t / 8.0                                                       # a breath every 4 s
    look = -12.0 * smooth((math.sin(ph) - 0.55) / 0.45)                      # now and then he looks down the line
    return ease_pose(0.004 * math.sin(ph * 2), math.sin(ph), math.sin(ph * 2 + 0.6), look)


# ------------------------------------------------------------------------------------------------------------- marching: the spear sloped on the right shoulder
CARRY_B = V((-0.262, -0.150, 0.985))
CARRY_GRIP = 0.42
CARRY_NR = (0.20, 0.90, 0.35)                   # the palm cups the shaft from the front, the thumb up it


def locomotion(t, G, lean, swing, arm_bend=0.0, slope=0.30):
    """Planted-foot cycle (samurai.gait.cycle: G = dict(T, ahead, behind, duty, lift, bob, sink, ...); forward = -Y). The right hand keeps the spear against the shoulder; the left arm swings."""
    feet, hips, ph2 = gait.cycle(t, **G)
    fl, fr = feet["L"], feet["R"]
    tw = math.sin(ph2 + 0.2)
    sw = swing * tw
    D = V((0.020 + 0.015 * math.sin(ph2), slope + 0.03 * math.cos(2 * ph2), 0.95)).normalized()
    sp = spear(CARRY_B + hips + V((0.0, -0.01 * lean / 9.0, 0.010 * math.cos(2 * ph2))), D, CARRY_NR, poleR=(-0.70, 0.55, -0.35))
    hl = dict(pos=V((0.285 + 0.02 * arm_bend, -0.02 + sw, 0.93 + 0.15 * arm_bend)), pole=V((0.5, 0.6, -0.5)))
    return pose(hips, (lean * 0.4, 0.0, 7.0 * tw), (lean * 0.8, -6.0 * tw, 2.5 * math.sin(ph2)), (-lean * 0.6, 4.0 * tw, 0.0),
                foot(fl["pos"].x, fl["pos"].y, fl["yaw"], fl["pitch"], fl["toe"], fl["pos"].z), foot(fr["pos"].x, fr["pos"].y, fr["yaw"], fr["pitch"], fr["toe"], fr["pos"].z),
                sp, CARRY_GRIP, handL=hl, curl=(0.30, 1.0))


# a march of 120 steps a minute at 1.2 m/s; a run of 171 at the ashigaru's 3.4 m/s (the game plays a clip at measured speed / stride speed)
WALK_V, RUN_V = 1.20, 3.40
WALK_G = dict(T=1.00, ahead=0.300, behind=0.444, duty=gait.duty_for(WALK_V, 1.00, 0.300, 0.444), lift=0.080, bob=0.020, sink=0.045, rise=0.070)
RUN_G = dict(T=0.70, ahead=0.250, behind=0.447, duty=gait.duty_for(RUN_V, 0.70, 0.250, 0.447), lift=0.185, bob=0.044, sink=0.080, rise=0.108, spacing=0.085, run=True, toe=47.0)


def walk(t):
    return locomotion(t, WALK_G, 3.0, 0.18)


def run(t):
    return locomotion(t, RUN_G, 9.0, 0.28, arm_bend=1.0, slope=0.40)


# ------------------------------------------------------------------------------------------------------------- the guard
GD_HIPS, GD_HROT = (0.0, -0.010, -0.075), (0.0, 0.0, -38.0)          # half-turned: the left shoulder and the left foot lead
GD_FL, GD_FR = (0.085, -0.300, -12.0), (-0.115, 0.250, -62.0)
GD_B = V((-0.215, 0.165, 0.985))                                     # the right hand, by the right hip
GD_AIM = V((0.020, -1.170, 1.090))                                   # where the point of the short spear sits in the guard
GD_GRIP, GD_SLIDE, PIKE_UP = 0.95, 0.56, 0.60
GD_NR, GD_NL = (0.80, 0.0, -0.60), (-0.30, 0.0, 0.95)                # the rear hand over the shaft, the leading hand under it


def guard_pose(dz=0.0, sway=0.0, tip=(0.0, 0.0, 0.0)):
    B = GD_B + V((0.004 * sway, 0.0, dz))
    sp = spear(B, GD_AIM + V(tip) - B, GD_NR, GD_NL, poleR=(-0.65, 0.60, -0.20), poleL=(0.60, 0.20, -0.80))
    return pose(V(GD_HIPS) + V((0.004 * sway, 0.0, dz)), GD_HROT, (4.0, 0.0, -4.0), (0.0, 0.0, 34.0), foot(*GD_FL), foot(*GD_FR), sp, GD_GRIP, GD_SLIDE, PIKE_UP)


def combat_idle(t):
    ph = TAU * t / 4.0                                                       # on guard: a breath every 2 s
    return guard_pose(0.005 * math.sin(ph * 2), math.sin(ph), (0.012 * math.sin(ph), 0.0, 0.010 * math.sin(ph * 2 + 0.5)))


def ready(t):
    """From standing at ease into the guard: a step, the half turn, the spear comes down off the ground into both hands."""
    T = READY_T
    D = V((0.10, -0.62, 0.78)).normalized()
    mid = pose((0.0, -0.006, -0.040), (0, 0, -20.0), (3.0, 0, -2), (0, 0, 18), foot(0.105, -0.150, -4.0), foot(-0.125, 0.130, -36.0),
               spear((-0.235, 0.050, 1.020), D, (0.70, -0.45, -0.55), GD_NL, poleR=(-0.65, 0.65, -0.25), poleL=(0.60, 0.20, -0.80)), 1.00, 0.46, PIKE_UP * 0.5)
    keys = [(0.0, ease_pose()), (0.5 * T, mid), (T, guard_pose())]
    P = _keyed(keys, t)
    P["lhand"] = pw([(0.0, 0.0), (0.27 * T, 0.0), (0.73 * T, 1.0)], t)
    return P


def stand_down(t):
    return ready(READY_T - t)


# ------------------------------------------------------------------------------------------------------------- the thrust
IMPACT_T = 0.45
THRUST_T = 29.0 / 30.0
READY_T = 0.80                 # the spear comes off the ground into both hands: not a snap
DEATH_T = 1.25                 # real time (the game no longer speeds it up): the blow, the knees go, the ground at 1.0 s, a settle


def _thrust_keys(aim, lunge, sink):
    """aim: where the point of the short spear ends; lunge: how far the leading foot and the hips go; sink: how deep he drops into it"""
    g = guard_pose()

    def k(hips, hrot, spine, neck, fl, fr, B, tip, slide):
        sp = spear(B, V(tip) - V(B), GD_NR, GD_NL, poleR=(-0.65, 0.60, -0.20), poleL=(0.60, 0.20, -0.80))
        return pose(hips, hrot, spine, neck, fl, fr, sp, GD_GRIP, slide, PIKE_UP)

    aim = V(aim)
    back = k((0.0, 0.035, -0.098), (0, 0, -47.0), (5.0, 0.0, -9.0), (0.0, 0.0, 42.0), foot(*GD_FL), foot(*GD_FR), (-0.238, 0.262, 1.000), GD_AIM + V((0.0, 0.11, 0.02)), 0.64)
    go = k((0.0, -0.090, -0.100 - 0.4 * sink), (0, 0, -30.0), (8.0, 0.0, 2.0), (-3.0, 0.0, 24.0), foot(GD_FL[0], GD_FL[1] - 0.5 * lunge, GD_FL[2]), foot(*GD_FR, pitch=8.0),
           (-0.150, -0.130, 1.050), GD_AIM.lerp(aim, 0.55), 0.40)
    hit_ = k((0.0, -0.085 - lunge, -0.118 - sink), (0, 0, -20.0), (14.0, 0.0, 9.0), (-8.0, 0.0, 12.0), foot(GD_FL[0], GD_FL[1] - lunge, GD_FL[2]), foot(*GD_FR, pitch=20.0, toe=-12.0),
             V((-0.062, -0.300 - lunge, 1.135 - 0.6 * sink)), aim, 0.17)
    # the point must be furthest out AT the impact: the key after it is the same pose a hair back, so the spline has nowhere to carry its speed
    hold = k((0.0, -0.079 - lunge, -0.116 - sink), (0, 0, -20.5), (13.5, 0.0, 8.5), (-7.5, 0.0, 12.5), foot(GD_FL[0], GD_FL[1] - lunge, GD_FL[2]), foot(*GD_FR, pitch=19.0, toe=-11.0),
             V((-0.064, -0.286 - lunge, 1.133 - 0.6 * sink)), aim + V((0.0, 0.02, -0.005)), 0.172)
    out = k((0.0, -0.040 - 0.4 * lunge, -0.092 - 0.3 * sink), (0, 0, -31.0), (7.0, 0.0, -1.0), (-2.0, 0.0, 26.0), foot(GD_FL[0], GD_FL[1] - 0.45 * lunge, GD_FL[2]), foot(*GD_FR, pitch=4.0),
            (-0.165, 0.000, 1.030), GD_AIM.lerp(aim, 0.30), 0.44)
    return [(0.0, g), (0.20, back), (0.36, go), (IMPACT_T, hit_), (0.50, hold), (0.74, out), (THRUST_T, g)]


_TK = {}


def _thrust(t, name, aim, lunge, sink):
    if name not in _TK:
        _TK[name] = _thrust_keys(aim, lunge, sink)
    return _keyed(_TK[name], t)


def thrust_high(t):
    """to the chest: the rear hand drives the shaft through the leading hand as the leading foot goes out"""
    return _thrust(t, "high", (0.000, -1.900, 1.240), 0.24, 0.02)


def thrust_low(t):
    """under the guard, to the thigh: a longer step and a deeper knee"""
    return _thrust(t, "low", (0.020, -1.900, 0.780), 0.30, 0.09)


# ------------------------------------------------------------------------------------------------------------- closing with the enemy: the spear levelled at the run
def run_ready(t):
    T = RUN_G["T"]
    P = locomotion(t, RUN_G, 11.0, 0.0)
    ph2 = TAU * (t % T) / T
    hips = P["hips_pos"]
    B = V((-0.225, 0.120, 0.990)) + hips + V((0.0, 0.012 * math.sin(ph2), 0.0))
    P["spear"] = spear(B, V((0.020, -1.250, 1.060 + 0.020 * math.cos(2 * ph2))) + hips - B, GD_NR, GD_NL, poleR=(-0.65, 0.60, -0.20), poleL=(0.60, 0.20, -0.80))
    P["gripR"], P["slide"], P["pike_up"], P["lhand"], P["curl_L"] = GD_GRIP, 0.54, PIKE_UP, 1.0, 0.9
    P["hips_rot"] = (P["hips_rot"][0], 0.0, -22.0 + 5.0 * math.sin(ph2 + 0.2))
    P["spine"] = (P["spine"][0], 0.0, 4.0)
    P["neck"] = (P["neck"][0], 0.0, 18.0)
    return P


# ------------------------------------------------------------------------------------------------------------- struck, killed
def hit(t):
    T = 0.6
    g = guard_pose()

    def k(hips, hrot, spine, neck, db, tip, slide):
        B = GD_B + V(db)
        sp = spear(B, GD_AIM + V(tip) - B, GD_NR, GD_NL, poleR=(-0.65, 0.60, -0.20), poleL=(0.60, 0.20, -0.80))
        return pose(hips, hrot, spine, neck, foot(*GD_FL), foot(*GD_FR), sp, GD_GRIP, slide, PIKE_UP)

    keys = [(0.0, g), (0.18 * T, k((0.02, 0.080, -0.090), (0, 5, -32), (-8, 10, -2), (-10, -8, 26), (0.03, 0.09, 0.05), (0.10, 0.0, 0.34), 0.52)),
            (0.42 * T, k((0.01, 0.045, -0.082), (0, 3, -36), (-2, 6, -4), (-5, -4, 30), (0.02, 0.05, 0.03), (0.05, 0.0, 0.16), 0.55)), (T, g)]
    return _keyed(keys, t)


def death(t):
    """Struck: the leading hand lets go, he staggers back, the knees go, he falls on his back with the spear across him."""
    T = DEATH_T
    g = guard_pose()
    k1 = pose((0.02, 0.110, -0.100), (-8, 4, -30), (-12, 8, -2), (-14, -6, 20), foot(0.090, -0.230, -10.0), foot(-0.110, 0.290, -60.0),
              spear((-0.250, 0.150, 1.050), (0.20, -0.80, 0.56), GD_NR, GD_NL), GD_GRIP, 0.50, PIKE_UP, handL=dict(pos=V((0.300, -0.180, 1.080)), pole=V((0.6, 0.3, -0.6))), curl=(0.5, 0.9))
    k2 = pose((0.04, 0.240, -0.480), (-30, 4, -20), (-16, 6, 0), (-12, 0, 10), foot(0.110, -0.130, -8.0), foot(-0.110, 0.260, -50.0),
              spear((-0.330, 0.180, 0.640), (0.30, -0.55, 0.78), GD_NR, GD_NL), GD_GRIP, 0.50, PIKE_UP, handL=dict(pos=V((0.400, 0.100, 0.900)), pole=V((0.6, 0.3, -0.6))), curl=(0.3, 0.7))
    k3 = pose((0.05, 0.340, -0.790), (-74, 2, -10), (-12, 2, 0), (-8, 0, 6), foot(0.150, -0.050, -4.0), foot(-0.150, 0.140, -24.0),
              spear((-0.470, 0.560, 0.095), (0.34, -0.94, 0.045), (0.30, 0.0, -0.95), GD_NL), GD_GRIP, 0.50, PIKE_UP, handL=dict(pos=V((0.520, 0.560, 0.200)), pole=V((0.6, 0.3, -0.2))), curl=(0.2, 0.45))
    k4 = dict(k3, hips_pos=V(k3["hips_pos"]) + V((0.0, 0.008, 0.006)), spine=(-9, 2, 0))          # the body settles
    keys = [(0.0, g), (0.19 * T, k1), (0.50 * T, k2), (0.80 * T, k3), (T, k4)]
    P = keyed(keys, t)
    P["lhand"] = pw([(0.0, 1.0), (0.14, 0.0)], t)
    return P


# ------------------------------------------------------------------------------------------------------------- hidden in the grass
# The sim draws a crouched man 0.95 m tall: nothing may stand above the grass. The spear is held LOW and LEVEL in the right hand, trailing at his side with the point
# forward (the long pike `pike_up` further up, as wherever it is levelled); the shaft never rises, the pennant hangs off it.
KN_DZ = -0.550                                                       # down on the right knee, sitting back toward the heel
KN_FL = foot(0.120, -0.300, -8.0)                                    # the left foot forward, the knee up
KN_FR = foot(-0.110, 0.248, -6.0, pitch=142.0, z=0.098, kpole=(0.0, -0.45, -1.0))     # the right knee on the ground, the shin along it, the instep down
KN_B = V((-0.300, -0.220, 0.320))                                    # the right hand on the shaft, beside the knee on the ground
KN_D = V((0.030, -1.0, -0.010))                                      # level, the point forward
LOW_GRIP = 1.05                                                      # near the balance point of the short spear
LOW_NR = (0.70, 0.0, -0.70)                                          # the hand over the shaft, on its outer side (a trail carry)


def crouch_pose(breath=0.0, sway=0.0):
    sp = spear(KN_B + V((0.002 * sway, 0.0, 0.003 * breath)), KN_D, LOW_NR, poleR=(-0.50, 0.80, -0.10))
    hl = dict(pos=V((0.150, -0.370, 0.470)) + V((0.0, 0.0, 0.003 * breath)), pole=V((0.7, 0.5, -0.2)))
    P = pose((0.0, 0.100, KN_DZ + 0.004 * breath), (26.0, 0.0, -6.0), (40.0 + 1.5 * breath, 0.0, 2.0), (-22.0, 0.0, 4.0 * sway), KN_FL, KN_FR, sp, LOW_GRIP,
             pike_up=PIKE_UP, handL=hl, curl=(0.55, 1.0))
    P["handL"]["space"] = "world"
    return P


def crouch_idle(t):
    ph = TAU * t / 5.0                                                       # a slow breath; now and then a slight sway
    return crouch_pose(math.sin(ph * 2), math.sin(ph))


# a creep of 110 steps a minute at the sim's 1.2 m/s for a crouched man (the archer's), lower: the hips 0.40 m down, the back bent well forward
SNEAK_V = 1.20
SNEAK_G = dict(T=1.10, ahead=0.340, behind=0.400, duty=gait.duty_for(SNEAK_V, 1.10, 0.340, 0.400), lift=0.060, bob=0.012, sink=0.400, rise=0.050, spacing=0.110)
SN_B = V((-0.300, -0.120, 0.950))                                    # the right hand on the shaft at his side (moves with the hips)
SN_D = V((0.030, -1.0, -0.010))


def sneak(t):
    feet, hips, ph2 = gait.cycle(t, **SNEAK_G)
    fl, fr = feet["L"], feet["R"]
    tw = math.sin(ph2 + 0.2)
    B = SN_B + hips + V((0.0, 0.012 * tw, 0.006 * math.cos(2 * ph2)))
    sp = spear(B, SN_D, LOW_NR, poleR=(-0.50, 0.80, -0.10))
    hl = dict(pos=V((0.270, -0.120 - 0.05 * tw, 0.720)), pole=V((0.5, 0.6, -0.5)))
    return pose(hips, (28.0, 0.0, 6.0 * tw), (42.0, -5.0 * tw, 2.0 * math.sin(ph2)), (-22.0, 3.0 * tw, 0.0),
                foot(fl["pos"].x, fl["pos"].y, fl["yaw"], fl["pitch"], fl["toe"], fl["pos"].z), foot(fr["pos"].x, fr["pos"].y, fr["yaw"], fr["pitch"], fr["toe"], fr["pos"].z),
                sp, LOW_GRIP, pike_up=PIKE_UP, handL=hl, curl=(0.45, 1.0))



# ------------------------------------------------------------------------------------------------------------- taking up a piece of kit
EQUIP_T, EQUIP_TAKE = 1.6, 0.85                 # an engine changes the piece he carries at EQUIP_TAKE: the moment the free hand closes on it


def _equip_pose(reach, lift, look=0.0):
    """Standing at ease with the spear grounded. reach 0..1: he leans to the rack and the free hand goes out to it; lift 0..1: he brings the piece up to himself."""
    lean = reach * (1.0 - lift)
    D = V((0.028, 0.042 + 0.030 * lean, 1.0)).normalized()
    g = (EASE_GRIP - 0.030 * lean) / D.z
    sp = spear(BUTT + D * g, D, EASE_NR, poleR=(-0.30, 0.95, -0.35))
    p = V(HANG_L["pos"]).lerp(V((0.205, -0.450, 0.960)), reach).lerp(V((0.130, -0.215, 1.330)), lift)
    hl = dict(pos=p, pole=V((0.55, 0.45 - 0.55 * lift, -0.7 + 0.25 * lift)))
    return pose((0.0, -0.040 * lean, -0.014 - 0.045 * lean), (0, 0, -7.0 * lean), (1.2 + 15.0 * lean, 0.0, -6.0 * lean), (5.0 * lean - 9.0 * lift, 0.0, look - 10.0 * lean),
                foot(*IDLE_FL), foot(*IDLE_FR), sp, g, handL=hl, curl=(0.25 + 0.65 * max(lift, reach * reach), 1.0))


def equip(t):
    """At a rack: he reaches out with the free hand, takes the piece (EQUIP_TAKE), lifts it to himself and stands at ease again."""
    keys = [(0.0, _equip_pose(0.0, 0.0)), (0.42, _equip_pose(0.80, 0.0)), (EQUIP_TAKE, _equip_pose(1.0, 0.0)), (1.22, _equip_pose(1.0, 1.0)), (EQUIP_T, _equip_pose(0.0, 0.0))]
    return _keyed(keys, min(t, EQUIP_T))


CLIPS = {
    "equip": dict(fn=equip, duration=EQUIP_T, loop=False, weapon="none", events={"take": EQUIP_TAKE}),
    "idle": dict(fn=idle, duration=8.0, loop=True, weapon="none"),
    "walk": dict(fn=walk, duration=WALK_G["T"], loop=True, weapon="none", speed=WALK_V),
    "run": dict(fn=run, duration=RUN_G["T"], loop=True, weapon="none", speed=RUN_V),
    "ready": dict(fn=ready, duration=READY_T, loop=False, weapon="none"),
    "stand_down": dict(fn=stand_down, duration=READY_T, loop=False, weapon="none"),
    "combat_idle": dict(fn=combat_idle, duration=4.0, loop=True, weapon="none"),
    "run_ready": dict(fn=run_ready, duration=RUN_G["T"], loop=True, weapon="none", speed=RUN_V),
    "thrust_high": dict(fn=thrust_high, duration=THRUST_T, loop=False, weapon="none", events={"impact": IMPACT_T}),
    "thrust_low": dict(fn=thrust_low, duration=THRUST_T, loop=False, weapon="none", events={"impact": IMPACT_T}),
    "hit": dict(fn=hit, duration=0.6, loop=False, weapon="none"),
    "death": dict(fn=death, duration=DEATH_T, loop=False, weapon="none"),
    "crouch_idle": dict(fn=crouch_idle, duration=5.0, loop=True, weapon="none"),
    "sneak": dict(fn=sneak, duration=SNEAK_G["T"], loop=True, weapon="none", speed=SNEAK_V),
}
