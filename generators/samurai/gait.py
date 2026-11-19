"""The planted-foot gait cycle shared by every character on this skeleton (samurai, archer, ashigaru). Forward = -Y.

A foot is on the ground for `duty` of the cycle. It lands `ahead` of the hips and leaves `behind` them, moving back at constant speed relative to the hips, so
    ground speed = (ahead + behind) / (duty * T)
and a clip played at that speed does not slide. What makes it read as a person rather than a pair of compasses:
  * the stance is NOT symmetric: a leg reaches less far forward (the knee must not lock at the strike) than it trails back (the heel comes up, the ankle rides high
    over the toe at push-off: `rise`). The numbers used by the units are inside what this skeleton's 0.82 m leg can reach with the hips where the cycle puts them;
  * the swinging foot follows through behind the hips and is already moving back when it lands (a Hermite swing, not an ease in and out);
  * a WALK is an inverted pendulum: the hips are highest over the standing foot. A RUN is a bounce: lowest over the standing foot, highest in the air.
Cadences: a march of about 120 steps a minute, a run of about 170 (the first version ran at 195 and the game played it at up to 225)."""
import math

from mathutils import Vector

V = Vector
TAU = math.tau
AZ = 0.092                      # planted ankle height
R0 = 0.66                       # fraction of the stance after which the heel comes up


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def duty_for(speed, T, ahead, behind):
    """the stance fraction that gives `speed` (m/s) with this reach"""
    return (ahead + behind) / (speed * T)


def cycle(t, T, ahead, behind, duty, lift, bob, sink, spacing=0.095, rise=0.06, run=False, toe=32.0, strike=-12.0, yaw=4.0, sway=0.020):
    """-> (feet {"L" | "R": dict(pos, yaw, pitch, toe)}, hips (Vector: sway, 0, height), ph2 (the cycle's phase in radians))"""
    ph = (t % T) / T
    vy = (ahead + behind) / (duty * T)                       # the planted foot's speed relative to the hips (m/s, backward)
    Ts = (1.0 - duty) * T
    feet = {}
    for side, off in (("L", 0.0), ("R", 0.5)):
        u = (ph + off) % 1.0
        sx = 1.0 if side == "L" else -1.0
        if u < duty:
            s = u / duty
            y = lerp(-ahead, behind, s)
            up = smooth((s - R0) / (1.0 - R0))
            z = AZ + rise * up
            pitch = lerp(strike, 0.0, smooth(s / 0.22)) + toe * up
        else:
            s = (u - duty) / (1.0 - duty)
            m0, m1 = 0.50 * vy * Ts, 0.45 * vy * Ts          # it follows through behind, and is on its way back when it lands
            s2, s3 = s * s, s * s * s
            y = (2 * s3 - 3 * s2 + 1) * behind + (s3 - 2 * s2 + s) * m0 + (-2 * s3 + 3 * s2) * (-ahead) + (s3 - s2) * m1
            z = AZ + rise * (1.0 - smooth(s / 0.40)) + lift * math.sin(math.pi * s) ** 0.9           # it is on the ground at s = 1 and not a frame before: a foot at ground height that is still swinging slides
            pitch = lerp(toe, strike, smooth((s - 0.12) / 0.80))
        feet[side] = dict(pos=V((sx * spacing, y, z)), yaw=sx * yaw, pitch=pitch, toe=-0.5 * pitch if pitch > 0 else 0.0)
    mid = 0.5 * duty                                          # the left foot is under the hips
    if run:
        hz = -sink - bob * math.cos(2 * TAU * (ph - mid - 0.03))
    else:
        hz = -sink + bob * math.cos(2 * TAU * (ph - mid))
    return feet, V((sway * math.cos(TAU * ph), 0.0, hz)), TAU * ph
