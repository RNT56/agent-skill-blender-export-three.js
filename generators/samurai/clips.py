"""Clip definitions: each clip is (params(t) function, duration seconds, loop?, meta). Locomotion is analytic (planted-foot cycles);
combat clips are keyed poses of the SWORD and stance, blended with Catmull-Rom and solved to FK by anim.Solver.
Stride speeds are recorded in `meta` (m/s at the authored playback rate) so the game can match playback to movement speed."""
import math

from . import gait
from mathutils import Vector

from . import katana as K


def V(*a):
    return Vector(a[0] if len(a) == 1 else a)

TAU = math.tau
AZ = 0.092                      # planted ankle height


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


# ------------------------------------------------------------------------------------------------------------- key blending
def _comb(items, ws):
    a = items[0]
    if isinstance(a, dict):
        return {k: _comb([i[k] for i in items], ws) for k in a}
    if isinstance(a, (tuple, list)):
        return tuple(sum(w * i[n] for w, i in zip(ws, items)) for n in range(len(a)))
    return sum(w * i for w, i in zip(ws, items))


def keyed(ks, t, loop=False):
    """Catmull-Rom blend of keys [(time, dict)]; dict values may be floats, tuples, Vectors or nested dicts."""
    n = len(ks)
    times = [k[0] for k in ks]
    t = min(max(t, times[0]), times[-1])
    i = 0
    while i < n - 2 and t > times[i + 1]:
        i += 1
    u = (t - times[i]) / max(times[i + 1] - times[i], 1e-9)
    ids = [i - 1, i, i + 1, i + 2]
    if loop:
        ids = [j % (n - 1) for j in ids]
    else:
        ids = [min(max(j, 0), n - 1) for j in ids]
    u2, u3 = u * u, u * u * u
    ws = [(-u3 + 2 * u2 - u) / 2, (3 * u3 - 5 * u2 + 2) / 2, (-3 * u3 + 4 * u2 + u) / 2, (u3 - u2) / 2]
    items = [ks[j][1] for j in ids]
    out = _comb([_vecfix(x) for x in items], ws)
    return out


def _vecfix(d):
    if isinstance(d, dict):
        return {k: _vecfix(v) for k, v in d.items()}
    if isinstance(d, Vector):
        return tuple(d)
    return d


def _unvec(d):
    """Turn blended tuples back into Vectors for the position-like fields the solver expects."""
    for k in ("pos", "O", "A", "E", "hips_pos"):
        pass
    return d


def fix(P):
    """Post-process blended params: tuples -> Vectors for solver fields; normalise sword axes."""
    for k in ("hips_pos",):
        if k in P:
            P[k] = V(P[k])
    for k in ("footL", "footR", "handL", "handR"):
        if P.get(k):
            P[k]["pos"] = V(P[k]["pos"])
            for q in ("dir", "hint", "pole"):
                if q in P[k]:
                    P[k][q] = V(P[k][q])
    if P.get("sword"):
        s = P["sword"]
        s["O"], s["A"], s["E"] = V(s["O"]), V(s["A"]).normalized(), V(s["E"])
    return P


# ------------------------------------------------------------------------------------------------------------- sheathed clips
LHAND_SAYA = dict(pos=(0.215, -0.105, 1.095), dir=(0.10, -0.75, -0.65), hint=(-0.9, 0.0, 0.4), pole=(0.8, 0.6, -0.2))


def idle(t):
    T = 8.0                         # a breath every 4 s, the weight shifts once in 8 (the first version breathed 40 times a minute)
    ph = TAU * t / T
    P = dict(
        hips_pos=V(0.010 * math.sin(ph), 0.0, -0.014 + 0.004 * math.sin(ph * 2)),
        hips_rot=(0.0, 0.0, 2.0 * math.sin(ph)),
        spine=(1.2 + 0.9 * math.sin(ph * 2 + 0.6), 0.6 * math.sin(ph), 0.0),
        neck=(-1.0 * math.sin(ph * 2 + 1.2), 3.5 * math.sin(ph), 0.0),
        footL=dict(pos=V(0.135, 0.03, AZ), yaw=9.0),
        footR=dict(pos=V(-0.135, -0.02, AZ), yaw=-9.0),
        handL=LHAND_SAYA, curl_L=0.5, curl_R=0.22,
    )
    return fix(P)


def locomotion(t, G, lean, swing, arm_bend=0.0, sword_hand=False):
    """Planted-foot cycle (gait.cycle: G = dict(T, ahead, behind, duty, lift, bob, sink, ...)). The left hand steadies the scabbard; the right arm swings."""
    feet, hips, ph2 = gait.cycle(t, **G)
    tw = math.sin(ph2 + 0.2)
    P = dict(
        hips_pos=V(hips.x, 0.0, hips.z),
        hips_rot=(lean * 0.4, 0.0, 7.0 * tw),
        spine=(lean * 0.8, -9.0 * tw, 2.5 * math.sin(ph2)),
        neck=(-lean * 0.6, 4.0 * tw, 0.0),
        footL=feet["L"], footR=feet["R"],
        handL=LHAND_SAYA, curl_L=0.5, curl_R=0.30,
    )
    # right arm swings opposite to the right leg; hand targets are chest/hips-relative
    sw = swing * tw
    P["handR"] = dict(pos=(-0.285 - 0.02 * arm_bend, -0.02 - sw, 0.93 + 0.15 * arm_bend), pole=(-0.5, 0.6, -0.5))
    if sword_hand:                      # katana carried in the right hand beside the hip, point forward and up; the left arm pumps
        P["sword"] = dict(O=V(-0.30, -0.20 - 0.03 * tw, 1.02 + hips.z), A=V(-0.22, -0.60, 0.32), E=V(0, 0, -1), one_hand=1.0)
        P["handL"] = dict(pos=(0.285 + 0.02 * arm_bend, -0.02 + sw, 0.93 + 0.15 * arm_bend), pole=(0.5, 0.6, -0.5))
        P["curl_R"] = 0.9
        P["curl_L"] = 0.25
    return fix(P)


# a march of 120 steps a minute at 1.2 m/s; a run of 171 at the samurai's 3.7 m/s (sim/types.js): the game plays a clip at measured speed / stride speed
WALK_V, RUN_V = 1.20, 3.70
WALK_G = dict(T=1.00, ahead=0.300, behind=0.444, duty=gait.duty_for(WALK_V, 1.00, 0.300, 0.444), lift=0.080, bob=0.020, sink=0.045, rise=0.070)
RUN_G = dict(T=0.70, ahead=0.260, behind=0.470, duty=gait.duty_for(RUN_V, 0.70, 0.260, 0.470), lift=0.190, bob=0.045, sink=0.080, rise=0.110, spacing=0.085, run=True, toe=48.0)


def walk(t):
    return locomotion(t, WALK_G, 3.0, 0.20)


def run(t):
    return locomotion(t, RUN_G, 9.0, 0.30, arm_bend=1.0)


def run_drawn(t):
    return locomotion(t, RUN_G, 9.0, 0.30, arm_bend=1.0, sword_hand=True)

E_DOWN = V((0, 0, -1))
E_UP = V((0, 0, 1))


def S(O, A, E, one_hand=0.0):
    return dict(O=V(O), A=V(A), E=V(E), one_hand=one_hand)


def stance(sw, hips=(0, -0.04, -0.07), hrot=(0, 0, -10), spine=(4, 0, 6), neck=(0, 0, 0), fl=(0.13, 0.16), fr=(-0.11, -0.20), lyaw=-6, ryaw=8, curl=0.9):
    return dict(
        hips_pos=V(*hips), hips_rot=hrot, spine=spine, neck=neck,
        footL=dict(pos=V(fl[0], fl[1], AZ), yaw=lyaw, pitch=0.0, toe=0.0),
        footR=dict(pos=V(fr[0], fr[1], AZ), yaw=ryaw, pitch=0.0, toe=0.0),
        sword=sw, curl_L=curl, curl_R=curl)


CHUDAN = S((0.0, -0.17, 1.08), (0.0, -0.96, 0.28), E_DOWN)


def combat_idle(t):
    T = 4.0                         # on guard: a breath every 2 s
    ph = TAU * t / T
    sw = S((0.004 * math.sin(ph), -0.17 + 0.006 * math.sin(ph * 2), 1.08 + 0.008 * math.sin(ph * 2 + 1.0)), (0.0, -0.96, 0.28 + 0.02 * math.sin(ph * 2)), E_DOWN)
    P = stance(sw, hips=(0.006 * math.sin(ph), -0.04, -0.075 + 0.006 * math.sin(ph * 2)), spine=(4 + 0.8 * math.sin(ph * 2), 0, 6))
    return fix(P)


def _attack(keys_list, T):
    ks = [(k[0] * T, stance(*k[1:3], **k[3])) if len(k) == 4 else (k[0] * T, stance(*k[1:3])) for k in keys_list]
    return lambda t: fix(keyed(ks, t))


FOOT_SLIDE_FROM = 0.20        # m/s of horizontal foot speed above which a foot is considered to be stepping, not planted


def lift_sliding_feet(P, Pa, Pb, dt):
    """A keyed foot that travels is a step: lift it (and point the toe) in proportion to its speed, so a lunge never skates along the ground."""
    for foot in ("footL", "footR"):
        if not P.get(foot):
            continue
        d = V(Pb[foot]["pos"]) - V(Pa[foot]["pos"])
        d.z = 0.0
        lift = min(0.08, max(0.0, (d.length / dt - FOOT_SLIDE_FROM) * 0.06))
        if lift > 0:
            p = V(P[foot]["pos"])
            P[foot]["pos"] = V(p.x, p.y, p.z + lift)
            P[foot]["pitch"] = P[foot].get("pitch", 0.0) + lift * 380.0 * (1.0 if d.y < 0 else 0.35)    # toe leads when stepping forward
    return P


def _make(keylist, T):
    ks = [(a * T, b) for a, b in keylist]

    def f(t):
        P = fix(keyed(ks, t))
        h = 0.03
        return lift_sliding_feet(P, fix(keyed(ks, max(0.0, t - h))), fix(keyed(ks, min(T, t + h))), 2 * h)
    return f


def attack_overhead(t):
    T = 1.0
    keys = [
        (0.00, stance(CHUDAN)),
        (0.22, stance(S((0.0, -0.05, 1.50), (0.0, -0.45, 0.89), E_DOWN), hips=(0, -0.02, -0.04), spine=(-4, 0, 4), fl=(0.13, 0.16), fr=(-0.11, -0.22))),
        (0.40, stance(S((0.0, 0.04, 1.62), (0.0, 0.40, 0.92), V(0, -1, 0)), hips=(0, 0.0, -0.02), spine=(-12, 0, 3), neck=(-6, 0, 0), fl=(0.13, 0.17), fr=(-0.11, -0.22), curl=0.9)),
        (0.54, stance(S((0.0, -0.18, 1.54), (0.0, -0.80, 0.60), V(0, 0, -1)), hips=(0, -0.10, -0.12), spine=(8, 0, 2), neck=(4, 0, 0), fl=(0.13, 0.12), fr=(-0.11, -0.42))),
        (0.62, stance(S((0.0, -0.36, 1.10), (0.0, -0.99, -0.14), V(0, 0, -1)), hips=(0, -0.20, -0.17), hrot=(2, 0, -12), spine=(14, 0, 4), neck=(8, 0, 0), fl=(0.14, 0.04), fr=(-0.10, -0.55))),
        (0.80, stance(S((0.0, -0.34, 1.06), (0.0, -0.98, 0.00), V(0, 0, -1)), hips=(0, -0.20, -0.16), hrot=(2, 0, -10), spine=(10, 0, 4), fl=(0.14, 0.04), fr=(-0.10, -0.55))),
        (1.00, stance(CHUDAN)),
    ]
    return _make(keys, T)(t)


def attack_diagonal(t):
    T = 1.05
    keys = [
        (0.00, stance(CHUDAN)),
        (0.25, stance(S((-0.13, -0.05, 1.56), (0.35, -0.40, 0.84), V(0, -1, 0)), hips=(0, -0.01, -0.05), hrot=(0, 0, -16), spine=(-6, -14, 10), neck=(0, 12, 0), fl=(0.13, 0.17), fr=(-0.11, -0.20))),
        (0.40, stance(S((-0.17, -0.04, 1.60), (0.55, 0.10, 0.83), V(0, -1, 0)), hips=(0, 0.0, -0.04), hrot=(0, 0, -22), spine=(-10, -22, 12), neck=(-2, 18, 0), fl=(0.13, 0.18), fr=(-0.11, -0.20))),
        (0.55, stance(S((-0.08, -0.26, 1.40), (0.20, -0.85, -0.20), V(0.3, -0.5, -0.8)), hips=(0, -0.10, -0.12), hrot=(0, 0, 8), spine=(8, 16, -4), neck=(3, -8, 0), fl=(0.13, 0.10), fr=(-0.11, -0.42))),
        (0.64, stance(S((0.20, -0.30, 1.00), (-0.45, -0.88, -0.14), V(0, -0.4, -1)), hips=(0, -0.18, -0.16), hrot=(2, 0, 20), spine=(12, 26, -8), neck=(6, -14, 0), fl=(0.13, 0.05), fr=(-0.10, -0.54))),
        (0.82, stance(S((0.24, -0.30, 1.00), (-0.50, -0.85, -0.10), V(0, -0.4, -1)), hips=(0, -0.18, -0.15), hrot=(2, 0, 18), spine=(10, 22, -6), fl=(0.13, 0.05), fr=(-0.10, -0.54))),
        (1.00, stance(CHUDAN)),
    ]
    return _make(keys, T)(t)


def attack_horizontal(t):
    T = 1.0
    keys = [
        (0.00, stance(CHUDAN)),
        (0.28, stance(S((-0.26, -0.08, 1.18), (-0.75, -0.55, 0.05), V(0, 0, -1)), hips=(-0.02, 0.0, -0.09), hrot=(0, 0, -26), spine=(2, -30, 12), neck=(0, 22, 0), fl=(0.14, 0.20), fr=(-0.12, -0.18), ryaw=-16)),
        (0.46, stance(S((-0.30, -0.12, 1.20), (-0.88, -0.30, 0.08), V(0, 0, -1)), hips=(-0.03, 0.02, -0.10), hrot=(0, 0, -32), spine=(2, -38, 14), neck=(0, 28, 0), fl=(0.14, 0.20), fr=(-0.12, -0.16), ryaw=-22)),
        (0.60, stance(S((0.04, -0.34, 1.16), (0.10, -0.99, 0.02), V(0, 0, -1)), hips=(0.0, -0.12, -0.13), hrot=(0, 0, 4), spine=(6, 6, -4), neck=(2, -4, 0), fl=(0.14, 0.12), fr=(-0.12, -0.46), ryaw=0)),
        (0.72, stance(S((0.30, -0.30, 1.14), (0.80, -0.60, 0.04), V(0, 0, -1)), hips=(0.02, -0.14, -0.13), hrot=(0, 0, 24), spine=(6, 30, -10), neck=(2, -20, 0), fl=(0.14, 0.10), fr=(-0.12, -0.48), ryaw=14)),
        (0.88, stance(S((0.32, -0.28, 1.12), (0.88, -0.45, 0.04), V(0, 0, -1)), hips=(0.02, -0.14, -0.13), hrot=(0, 0, 26), spine=(6, 32, -10), fl=(0.14, 0.10), fr=(-0.12, -0.48), ryaw=16)),
        (1.00, stance(CHUDAN)),
    ]
    return _make(keys, T)(t)


def attack_thrust(t):
    T = 0.9
    keys = [
        (0.00, stance(CHUDAN)),
        (0.30, stance(S((0.10, 0.02, 1.16), (0.0, -0.96, 0.22), V(0.2, 0, -1)), hips=(0.0, 0.04, -0.10), hrot=(0, 0, 10), spine=(0, 12, 2), neck=(0, -8, 0), fl=(0.14, 0.22), fr=(-0.11, -0.12))),
        (0.46, stance(S((0.10, 0.02, 1.16), (0.0, -0.96, 0.22), V(0.2, 0, -1)), hips=(0.0, 0.05, -0.12), hrot=(0, 0, 12), spine=(0, 14, 2), neck=(0, -10, 0), fl=(0.14, 0.22), fr=(-0.11, -0.10))),
        (0.58, stance(S((0.04, -0.42, 1.22), (0.0, -0.99, 0.10), V(0.1, 0, -1)), hips=(0.0, -0.24, -0.16), hrot=(2, 0, -8), spine=(12, -6, 0), neck=(6, 6, 0), fl=(0.14, 0.04), fr=(-0.10, -0.62))),
        (0.80, stance(S((0.04, -0.44, 1.22), (0.0, -0.99, 0.10), V(0.1, 0, -1)), hips=(0.0, -0.24, -0.16), hrot=(2, 0, -8), spine=(12, -6, 0), fl=(0.14, 0.04), fr=(-0.10, -0.62))),
        (1.00, stance(CHUDAN)),
    ]
    return _make(keys, T)(t)


def block(t):
    T = 0.8
    keys = [
        (0.00, stance(CHUDAN)),
        (0.22, stance(S((0.12, -0.14, 1.50), (-0.12, -0.20, 0.97), V(-0.1, 0, -1)), hips=(0, -0.02, -0.08), spine=(-6, 0, 4), neck=(-8, 0, 0))),
        (0.55, stance(S((0.12, -0.16, 1.50), (-0.14, -0.20, 0.97), V(-0.1, 0, -1)), hips=(-0.01, 0.0, -0.09), hrot=(0, 0, -12), spine=(-8, 0, 5), neck=(-8, 0, 0))),
        (1.00, stance(CHUDAN)),
    ]
    return _make(keys, T)(t)


def hit(t):
    T = 0.6
    keys = [
        (0.00, stance(CHUDAN)),
        (0.18, stance(S((0.0, -0.05, 1.04), (0.0, -0.90, 0.40), E_DOWN), hips=(0, 0.10, -0.06), hrot=(-6, 0, 14), spine=(-14, 10, -6), neck=(-14, -10, 0), fl=(0.13, 0.20), fr=(-0.11, -0.12), curl=0.8)),
        (0.40, stance(S((0.0, -0.10, 1.06), (0.0, -0.93, 0.34), E_DOWN), hips=(0, 0.06, -0.08), hrot=(-3, 0, 8), spine=(-8, 6, -2), neck=(-8, -6, 0), fl=(0.13, 0.18), fr=(-0.11, -0.14), curl=0.85)),
        (1.00, stance(CHUDAN)),
    ]
    return _make(keys, T)(t)


def death(t):
    T = 1.25                        # real time (the game no longer speeds it up): the blow, the knees go, the ground at 1.0 s, a settle
    base = stance(CHUDAN)
    keys = [
        (0.00, base),
        (0.19, stance(S((0.0, -0.02, 1.06), (0.0, -0.80, 0.55), E_DOWN), hips=(0, 0.12, -0.08), hrot=(-6, 0, 10), spine=(-16, 10, -4), neck=(-14, 0, 0), fl=(0.13, 0.22), fr=(-0.11, -0.10), curl=0.6)),
        (0.50, stance(S((0.05, 0.08, 0.96), (0.4, -0.40, 0.80), E_DOWN), hips=(0, 0.22, -0.45), hrot=(-22, 0, 8), spine=(-20, 8, 0), neck=(-16, 0, 0), fl=(0.14, 0.20), fr=(-0.12, -0.02), curl=0.3)),
        (0.80, stance(S((0.17, 0.21, 0.31), (0.5, -0.30, 0.25), E_DOWN), hips=(0, 0.30, -0.78), hrot=(-70, 0, 6), spine=(-14, 4, 0), neck=(-10, 0, 0), fl=(0.16, 0.30), fr=(-0.12, 0.06), curl=0.15)),
        (1.00, stance(S((0.17, 0.21, 0.31), (0.5, -0.30, 0.25), E_DOWN), hips=(0, 0.31, -0.775), hrot=(-70, 0, 6), spine=(-11, 3, 0), neck=(-10, 0, 0), fl=(0.16, 0.30), fr=(-0.12, 0.06), curl=0.15)),
    ]
    ks = [(a * T, b) for a, b in keys]

    def f(tt):
        P = fix(keyed(ks, tt))
        return P
    return f(t)


HIP_S = S(K.HIP_ORIGIN, K.HIP_DIR, K.HIP_EDGE, one_hand=1.0)        # the drawn sword exactly where the sheathed one sits (pop-free swap)
IDLE_FEET = dict(fl=(0.135, 0.03), fr=(-0.135, -0.02), lyaw=9, ryaw=-9)


def _draw_stance(sw, hips=(0, 0, -0.014), hrot=(0, 0, 0), spine=(1.2, 0, 0), neck=(0, 0, 0), curl=0.6, **feet):
    d = stance(sw, hips=hips, hrot=hrot, spine=spine, neck=neck, curl=curl, **(feet or IDLE_FEET))
    d["handL"] = dict(LHAND_SAYA)
    d["curl_L"] = 0.5
    return d


def draw(t):
    T = 0.8
    keys = [
        (0.00, _draw_stance(HIP_S, curl=0.7)),
        (0.25, _draw_stance(HIP_S, hips=(0, -0.01, -0.04), hrot=(0, 0, -6), spine=(3, 0, 4), curl=0.9)),
        (0.50, _draw_stance(S((-0.10, -0.30, 1.08), (0.55, -0.55, 0.10), (0.3, 0.3, 0.9), 1.0), hips=(0, -0.03, -0.06), hrot=(0, 0, -10), spine=(3, 0, 6), curl=0.9)),
        (0.75, _draw_stance(S((-0.03, -0.22, 1.08), (0.08, -0.93, 0.25), (0.7, 0, -0.7), 0.7), hips=(0, -0.04, -0.07), hrot=(0, 0, -10), spine=(4, 0, 6), curl=0.9,
                            fl=(0.13, 0.16), fr=(-0.11, -0.20), lyaw=-6, ryaw=8)),
        (1.00, _draw_stance(CHUDAN, hips=(0, -0.04, -0.07), hrot=(0, 0, -10), spine=(4, 0, 6), curl=0.9, fl=(0.13, 0.16), fr=(-0.11, -0.20), lyaw=-6, ryaw=8)),
    ]
    return _make(keys, T)(t)


def sheathe(t):
    return draw(0.8 - t)


def weapon_at(name, t):
    """'drawn' or 'sheathed': which katana node is visible at time t of a clip (swap events included)."""
    c = CLIPS[name]
    start, end = c["weapon"], c.get("weapon_end", c["weapon"])
    sw = c.get("events", {}).get("swap_weapon")
    return start if sw is None or t < sw else end


# ------------------------------------------------------------------------------------------------------------- taking up a piece of kit
EQUIP_T, EQUIP_TAKE = 1.6, 0.85                 # an engine changes the piece he carries at EQUIP_TAKE: the moment the free hand closes on it
RHAND_HANG = dict(pos=(-0.385, -0.060, 0.845), dir=(-0.30, -0.20, -0.93), hint=(0.9, 0.0, 0.4), pole=(-0.8, 0.6, -0.2))


def _equip_pose(reach, lift):
    """Standing at ease, the left hand on the scabbard. reach 0..1: he leans to the rack and the right hand goes out; lift 0..1: he brings the piece up to himself."""
    lean = reach * (1.0 - lift)
    h = RHAND_HANG
    pos = V(h["pos"]).lerp(V((-0.205, -0.455, 0.960)), reach).lerp(V((-0.130, -0.230, 1.340)), lift)
    d = V(h["dir"]).lerp(V((0.10, -0.95, -0.25)), reach).lerp(V((0.45, -0.35, 0.80)), lift).normalized()
    return dict(hips_pos=V((0.0, -0.040 * lean, -0.014 - 0.045 * lean)), hips_rot=(0.0, 0.0, 7.0 * lean), spine=(1.2 + 15.0 * lean, 0.0, 6.0 * lean), neck=(5.0 * lean - 9.0 * lift, 0.0, 10.0 * lean),
                footL=dict(pos=V((0.135, 0.03, AZ)), yaw=9.0), footR=dict(pos=V((-0.135, -0.02, AZ)), yaw=-9.0), handL=LHAND_SAYA,
                handR=dict(pos=pos, dir=d, hint=h["hint"], pole=V(h["pole"]) + V((0.0, -0.45 * lift, 0.25 * lift))), curl_L=0.5, curl_R=0.22 + 0.60 * max(lift, reach * reach))


def equip(t):
    """At a rack: he reaches out with the sword hand, takes the piece (EQUIP_TAKE), lifts it to himself and stands at ease again."""
    keys = [(0.0, _equip_pose(0.0, 0.0)), (0.42, _equip_pose(0.80, 0.0)), (EQUIP_TAKE, _equip_pose(1.0, 0.0)), (1.22, _equip_pose(1.0, 1.0)), (EQUIP_T, _equip_pose(0.0, 0.0))]
    return fix(keyed(keys, min(t, EQUIP_T)))


# ------------------------------------------------------------------------------------------------------------- hidden in the grass
# The sim draws a crouched man 0.95 m tall, and a samurai may hide only out of his armour (robe, no helmet). He kneels as a swordsman does (tatehiza): the LEFT
# knee on the ground, the right knee up, so the hilt at his left hip clears the raised thigh and he can rise and draw from it. The left hand holds the scabbard at its
# mouth (koiguchi), the thumb on the guard; bent forward, the scabbard's end would rise behind him like a tail: the hand turns it back down (anim.Solver.saya), so
# the sword lies back and low. The right hand rests on the right knee.
def _koiguchi_hand(fingers=(-0.243, 0.0, -0.970), thumb=(-0.085, -0.965, 0.245)):
    """The left hand on the scabbard's mouth, in weapon_hip's REST frame (it rides the scabbard): the palm on the outer side, the fingers round under it, the thumb
    forward along it onto the guard."""
    d, z = V(fingers).normalized(), V(thumb)
    z = (z - d * z.dot(d)).normalized()
    n = d.cross(z).normalized()                                     # the palm's normal (toward the scabbard)
    g = K.HIP_ORIGIN + K.HIP_DIR.normalized() * (K.TSUBA_Y + 0.034)     # the grip centre, a thumb's width behind the guard
    return dict(pos=g - d * 0.076 - n * 0.027, dir=d, hint=z, pole=V((0.80, 0.50, 0.30)), space="weapon_hip")


LHAND_KOI = _koiguchi_hand()
CR_DZ = -0.550                                                       # down on the left knee, sitting back toward the heel
CR_FL = dict(pos=V((0.110, 0.248, 0.098)), yaw=6.0, pitch=142.0, toe=0.0, kpole=V((0.0, -0.45, -1.0)), instep=True)     # the left knee on the ground, the instep down
CR_FR = dict(pos=V((-0.120, -0.300, AZ)), yaw=8.0, pitch=0.0, toe=0.0)                                                 # the right foot forward, the knee up
CR_SAYA = (-22.0, 0.0, 4.0)                                          # the scabbard turned in the obi: its end down behind him (the hips are pitched 26 deg)
CR_HANDR = dict(pos=V((-0.150, -0.360, 0.560)), dir=V((0.05, -0.55, -0.83)), hint=V((0.9, -0.2, 0.3)), pole=V((-0.6, 0.6, 0.2)), space="world")


def crouch_pose(breath=0.0, sway=0.0):
    hr = dict(CR_HANDR, pos=V(CR_HANDR["pos"]) + V((0.0, 0.0, 0.003 * breath)))
    # he breathes with his chest, not his hips: the legs are still and the knee on the ground does not slide (a 4 mm hip bob moved it 4.6 mm)
    return fix(dict(hips_pos=V((0.0, 0.100, CR_DZ)), hips_rot=(26.0, 0.0, 6.0), spine=(40.0 + 1.8 * breath, 0.0, -2.0), neck=(-22.0, 0.0, 4.0 * sway),
                    footL=dict(CR_FL), footR=dict(CR_FR), saya=CR_SAYA, handL=dict(LHAND_KOI), handR=hr, curl_L=0.75, curl_R=0.35))


def crouch_idle(t):
    ph = TAU * t / 5.0                                                       # a slow breath; now and then a slight sway of the head
    return crouch_pose(math.sin(ph * 2), math.sin(ph))


# a creep of 110 steps a minute at the sim's 1.2 m/s for a crouched man (the archer's and the ashigaru's cadence): the hips 0.34 m down (at 0.40 the trailing knee
# brushed the ground), the stance a little ahead of the hips, the back bent well forward, the heel's rise walk's (at 0.05 the toe dug 6 cm into the ground at
# push-off; walk's 4 cm). The left hand steadies the scabbard at its mouth (turned down behind him as in the kneel); the right arm hangs low and swings a little
SNEAK_V = 1.20
SNEAK_G = dict(T=1.10, ahead=0.380, behind=0.360, duty=gait.duty_for(SNEAK_V, 1.10, 0.380, 0.360), lift=0.060, bob=0.012, sink=0.340, rise=0.070, spacing=0.110)
SN_SAYA = (-24.0, 0.0, 6.0)


def sneak(t):
    feet, hips, ph2 = gait.cycle(t, **SNEAK_G)
    tw = math.sin(ph2 + 0.2)
    hz = 0.93 + hips.z
    hr = dict(pos=V((-0.250, -0.300 - 0.060 * tw, hz - 0.080)), pole=V((-0.6, 0.6, -0.2)), space="world")
    return fix(dict(hips_pos=V((hips.x, 0.0, hips.z)), hips_rot=(30.0, 0.0, 6.0 * tw), spine=(46.0, -5.0 * tw, 2.0 * math.sin(ph2)), neck=(-24.0, 3.0 * tw, 0.0),
                    footL=feet["L"], footR=feet["R"], saya=SN_SAYA, handL=dict(LHAND_KOI), handR=hr, curl_L=0.75, curl_R=0.35))


# ------------------------------------------------------------------------------------------------------------- variety (2026-11-20): <base>__<style> clips (view/anim/variety.js)
RHAND_TSUKA = dict(pos=(0.110, -0.215, 1.115), dir=(0.20, -0.45, -0.87), hint=(0.85, 0.15, 0.50), pole=(-0.5, 0.8, -0.35))      # palm down over the pommel, fingers draped forward


def idle_hilt(t):
    """watchful: the right hand on the hilt, the weight on the right leg, the head turning slowly across the field"""
    T = 10.0
    ph = TAU * t / T
    P = dict(
        hips_pos=V(-0.016, 0.0, -0.016 + 0.003 * math.sin(ph * 2)),
        hips_rot=(0.0, 0.0, -4.0 + 1.0 * math.sin(ph)),
        spine=(2.0 + 0.8 * math.sin(ph * 2 + 0.6), 0.0, 3.0),
        neck=(-1.0, 0.0, 20.0 * math.sin(ph)),
        footL=dict(pos=V(0.150, 0.020, AZ), yaw=12.0),
        footR=dict(pos=V(-0.130, -0.050, AZ), yaw=-16.0),
        handL=LHAND_SAYA, handR=dict(RHAND_TSUKA), curl_L=0.5, curl_R=0.55,
    )
    return fix(P)


def idle_easy(t):
    """at rest: the right arm hanging loose, the weight on the left leg, a long breath and a look down and up"""
    T = 9.0
    ph = TAU * t / T
    P = dict(
        hips_pos=V(0.018, 0.0, -0.020 + 0.004 * math.sin(ph * 2)),
        hips_rot=(0.0, 0.0, 4.0),
        spine=(1.0 + 1.2 * math.sin(ph * 2 + 0.6), 0.0, -2.0),
        neck=(6.0 * math.sin(ph) - 2.0, 0.0, -6.0),
        footL=dict(pos=V(0.140, -0.040, AZ), yaw=14.0),
        footR=dict(pos=V(-0.150, 0.030, AZ), yaw=-10.0),
        handL=LHAND_SAYA, handR=dict(pos=(-0.300, 0.010, 0.880), pole=(-0.5, 0.6, -0.6)), curl_L=0.5, curl_R=0.30,
    )
    return fix(P)


def walk_hilt(t):
    """the march with the right hand on the hilt (the left steadies the scabbard): no arm swings"""
    P = locomotion(t, WALK_G, 3.0, 0.20)
    P["handR"] = dict(RHAND_TSUKA)
    P["curl_R"] = 0.55
    return fix(P)


CLIPS = {
    "equip": dict(fn=equip, duration=EQUIP_T, loop=False, weapon="sheathed", events={"take": EQUIP_TAKE}),
    "idle": dict(fn=idle, duration=8.0, loop=True, weapon="sheathed"),
    "walk": dict(fn=walk, duration=WALK_G["T"], loop=True, weapon="sheathed", speed=WALK_V),
    "run": dict(fn=run, duration=RUN_G["T"], loop=True, weapon="sheathed", speed=RUN_V),
    "run_drawn": dict(fn=run_drawn, duration=RUN_G["T"], loop=True, weapon="drawn", speed=RUN_V),
    "draw": dict(fn=draw, duration=0.8, loop=False, weapon="sheathed", weapon_end="drawn", events={"swap_weapon": 0.20}),
    "sheathe": dict(fn=sheathe, duration=0.8, loop=False, weapon="drawn", weapon_end="sheathed", events={"swap_weapon": 0.60}),
    "combat_idle": dict(fn=combat_idle, duration=4.0, loop=True, weapon="drawn"),
    "attack_overhead": dict(fn=attack_overhead, duration=1.0, loop=False, weapon="drawn", events={"impact": 0.62}),
    "attack_diagonal": dict(fn=attack_diagonal, duration=1.05, loop=False, weapon="drawn", events={"impact": 0.67}),
    "attack_horizontal": dict(fn=attack_horizontal, duration=1.0, loop=False, weapon="drawn", events={"impact": 0.60}),
    "attack_thrust": dict(fn=attack_thrust, duration=0.9, loop=False, weapon="drawn", events={"impact": 0.52}),
    "block": dict(fn=block, duration=0.8, loop=False, weapon="drawn"),
    "hit": dict(fn=hit, duration=0.6, loop=False, weapon="drawn"),
    "death": dict(fn=death, duration=1.25, loop=False, weapon="drawn"),
    "crouch_idle": dict(fn=crouch_idle, duration=5.0, loop=True, weapon="sheathed"),
    "sneak": dict(fn=sneak, duration=SNEAK_G["T"], loop=True, weapon="sheathed", speed=SNEAK_V),
    "idle__hilt": dict(fn=idle_hilt, duration=10.0, loop=True, weapon="sheathed"),
    "idle__easy": dict(fn=idle_easy, duration=9.0, loop=True, weapon="sheathed"),
    "walk__hilt": dict(fn=walk_hilt, duration=WALK_G["T"], loop=True, weapon="sheathed", speed=WALK_V),
}
