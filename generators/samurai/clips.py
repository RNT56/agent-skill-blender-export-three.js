"""Clip definitions: each clip is (params(t) function, duration seconds, loop?, meta). Locomotion is analytic (planted-foot cycles);
combat clips are keyed poses of the SWORD and stance, blended with Catmull-Rom and solved to FK by anim.Solver.
Stride speeds are recorded in `meta` (m/s at the authored playback rate) so the game can match playback to movement speed."""
import math

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
    T = 3.0
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


def locomotion(t, T, sweep, duty, lift, bob, lean, swing, sink, spacing=0.095, kick=0.0, arm_bend=0.0, sword_hand=False):
    """Planted-foot cycle. Forward = -Y. A foot is in stance for `duty` of the cycle (sweeping back relative to the hips)."""
    ph = (t % T) / T
    feet = {}
    for side, off in (("L", 0.0), ("R", 0.5)):
        u = (ph + off) % 1.0
        sx = 1.0 if side == "L" else -1.0
        if u < duty:
            s = u / duty
            y = lerp(-sweep, sweep, s)
            z = AZ + 0.045 * smooth((s - 0.72) / 0.28)
            pitch = lerp(-12.0, 0.0, smooth(s / 0.25)) + 30.0 * smooth((s - 0.75) / 0.25)
        else:
            s = (u - duty) / (1.0 - duty)
            e = smooth(s)
            y = lerp(sweep + kick, -sweep, e)
            z = AZ + 0.045 * (1 - smooth(s / 0.5)) + lift * math.sin(math.pi * min(s * 1.08, 1.0)) ** 0.9
            pitch = lerp(30.0, -12.0, smooth(s))
        feet[side] = dict(pos=V(sx * spacing, y, z), yaw=sx * 4.0, pitch=pitch, toe=-0.5 * pitch if pitch > 0 else 0.0)
    ph2 = TAU * ph
    stance = TAU * (ph - 0.5 * duty * 0.9)
    hz = -sink + bob * math.cos(2 * ph2 - 2 * TAU * 0.5 * duty * 0.9)
    P = dict(
        hips_pos=V(0.020 * math.cos(ph2 - TAU * 0.5 * duty * 0.9 * 0.0), 0.0, hz),
        hips_rot=(lean * 0.4, 0.0, 7.0 * math.sin(ph2 + 0.2)),
        spine=(lean * 0.8, -9.0 * math.sin(ph2 + 0.2), 2.5 * math.sin(ph2)),
        neck=(-lean * 0.6, 4.0 * math.sin(ph2 + 0.2), 0.0),
        footL=feet["L"], footR=feet["R"],
        handL=LHAND_SAYA, curl_L=0.5, curl_R=0.30,
    )
    # right arm swings opposite to the right leg; hand targets are chest/hips-relative
    sw = swing * math.sin(ph2 + 0.2)
    P["handR"] = dict(pos=(-0.285 - 0.02 * arm_bend, -0.02 - sw, 0.93 + 0.15 * arm_bend), pole=(-0.5, 0.6, -0.5))
    if sword_hand:                      # katana carried in the right hand beside the hip, point forward and up; the left arm pumps
        P["sword"] = dict(O=V(-0.30, -0.20 - 0.03 * math.sin(ph2 + 0.2), 1.02 + hz), A=V(-0.22, -0.60, 0.32), E=V(0, 0, -1), one_hand=1.0)
        P["handL"] = dict(pos=(0.285 + 0.02 * arm_bend, -0.02 + sw, 0.93 + 0.15 * arm_bend), pole=(0.5, 0.6, -0.5))
        P["curl_R"] = 0.9
        P["curl_L"] = 0.25
    return fix(P)


def walk(t):
    return locomotion(t, 0.92, 0.30, 0.60, 0.085, 0.020, 3.0, 0.20, 0.030)


def run(t):
    return locomotion(t, 0.62, 0.33, 0.34, 0.17, 0.045, 8.0, 0.30, 0.06, spacing=0.085, kick=0.24, arm_bend=1.0)


def run_drawn(t):
    return locomotion(t, 0.62, 0.33, 0.34, 0.17, 0.045, 8.0, 0.30, 0.06, spacing=0.085, kick=0.24, arm_bend=1.0, sword_hand=True)


# ------------------------------------------------------------------------------------------------------------- combat
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
    T = 2.4
    ph = TAU * t / T
    sw = S((0.004 * math.sin(ph), -0.17 + 0.006 * math.sin(ph * 2), 1.08 + 0.008 * math.sin(ph * 2 + 1.0)), (0.0, -0.96, 0.28 + 0.02 * math.sin(ph * 2)), E_DOWN)
    P = stance(sw, hips=(0.006 * math.sin(ph), -0.04, -0.075 + 0.006 * math.sin(ph * 2)), spine=(4 + 0.8 * math.sin(ph * 2), 0, 6))
    return fix(P)


def _attack(keys_list, T):
    ks = [(k[0] * T, stance(*k[1:3], **k[3])) if len(k) == 4 else (k[0] * T, stance(*k[1:3])) for k in keys_list]
    return lambda t: fix(keyed(ks, t))


def _make(keylist, T):
    ks = [(a * T, b) for a, b in keylist]
    return lambda t: fix(keyed(ks, t))


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
    T = 1.6
    base = stance(CHUDAN)
    keys = [
        (0.00, base),
        (0.20, stance(S((0.0, -0.02, 1.06), (0.0, -0.80, 0.55), E_DOWN), hips=(0, 0.12, -0.08), hrot=(-6, 0, 10), spine=(-16, 10, -4), neck=(-14, 0, 0), fl=(0.13, 0.22), fr=(-0.11, -0.10), curl=0.6)),
        (0.55, stance(S((0.05, 0.08, 0.96), (0.4, -0.40, 0.80), E_DOWN), hips=(0, 0.22, -0.45), hrot=(-22, 0, 8), spine=(-20, 8, 0), neck=(-16, 0, 0), fl=(0.14, 0.20), fr=(-0.12, -0.02), curl=0.3)),
        (1.00, stance(S((0.10, 0.20, 0.30), (0.5, -0.30, 0.25), E_DOWN), hips=(0, 0.30, -0.78), hrot=(-70, 0, 6), spine=(-14, 4, 0), neck=(-10, 0, 0), fl=(0.16, 0.30), fr=(-0.12, 0.06), curl=0.15)),
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


CLIPS = {
    "idle": dict(fn=idle, duration=3.0, loop=True, weapon="sheathed"),
    "walk": dict(fn=walk, duration=0.92, loop=True, weapon="sheathed", speed=2 * 0.30 / (0.60 * 0.92)),
    "run": dict(fn=run, duration=0.62, loop=True, weapon="sheathed", speed=2 * 0.33 / (0.34 * 0.62)),
    "run_drawn": dict(fn=run_drawn, duration=0.62, loop=True, weapon="drawn", speed=2 * 0.33 / (0.34 * 0.62)),
    "draw": dict(fn=draw, duration=0.8, loop=False, weapon="sheathed", weapon_end="drawn", events={"swap_weapon": 0.20}),
    "sheathe": dict(fn=sheathe, duration=0.8, loop=False, weapon="drawn", weapon_end="sheathed", events={"swap_weapon": 0.60}),
    "combat_idle": dict(fn=combat_idle, duration=2.4, loop=True, weapon="drawn"),
    "attack_overhead": dict(fn=attack_overhead, duration=1.0, loop=False, weapon="drawn", events={"impact": 0.62}),
    "attack_diagonal": dict(fn=attack_diagonal, duration=1.05, loop=False, weapon="drawn", events={"impact": 0.67}),
    "attack_horizontal": dict(fn=attack_horizontal, duration=1.0, loop=False, weapon="drawn", events={"impact": 0.60}),
    "attack_thrust": dict(fn=attack_thrust, duration=0.9, loop=False, weapon="drawn", events={"impact": 0.52}),
    "block": dict(fn=block, duration=0.8, loop=False, weapon="drawn"),
    "hit": dict(fn=hit, duration=0.6, loop=False, weapon="drawn"),
    "death": dict(fn=death, duration=1.6, loop=False, weapon="drawn"),
}
