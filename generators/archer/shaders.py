"""Procedural PBR materials of the light archer (Cycles-bakeable, one Principled each; built with the samurai's node builder). Colours are scene-linear.
Pattern UV 'pat': cloth and tubes in metres, hara-ate in plate / row units, the war hat (u, radius), the bow (u, metres from the grip), feathers (0..1 along, 0..1 out)."""
import math

import bpy

from samurai import shaders as SSh
from samurai.shaders import NB

from . import consts as K

TAU = 6.2832


def cloth(name, c0, c1, valley, lint, team=0.0, pitch=0.0042, fold=1.0, dirt_from=0.75, rough=0.82, stripe=None, shade=0.36, wander=5.0):
    """Plain-weave cloth: two-tone dye, slubs, wandering folds whose valleys go dark, dust toward the ground. stripe = (period m, colour, strength) adds warp stripes."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    wu = b.math("SINE", b.math("MULTIPLY", u, TAU / pitch))
    wv = b.math("SINE", b.math("MULTIPLY", v, TAU / pitch))
    weave = b.math("ADD", b.math("MULTIPLY", wu, wv), b.math("MULTIPLY", b.math("ADD", wu, wv), 0.35))
    slub = b.noise(objv, 220.0, 3.0)
    fade = b.noise(objv, 9.0, 4.0)
    base = b.mix(b.smoothstep(0.3, 0.7, fade), c0, c1)
    if stripe:
        st = b.smoothstep(0.55, 0.90, b.math("SINE", b.math("MULTIPLY", u, TAU / stripe[0])))
        base = b.mix(b.math("MULTIPLY", st, stripe[2]), base, stripe[1])
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.50, 0.9, b.noise(objv, 16.0, 3.0)), b.smoothstep(dirt_from, 0.05, oz)), base, (0.10, 0.072, 0.045, 1))
    col = b.mix(b.math("MULTIPLY", b.math("ADD", slub, weave), 0.07), col, lint)
    wob = b.noise(objv, 5.0, 2.0)
    f1 = b.math("SINE", b.math("ADD", b.math("MULTIPLY", u, TAU / 0.066), b.math("MULTIPLY", wob, wander)))
    f2 = b.math("SINE", b.math("ADD", b.math("MULTIPLY", u, TAU / 0.021), b.math("MULTIPLY", b.noise(objv, 19.0, 3.0), 9.0)))
    crease = b.math("MULTIPLY", b.math("ADD", b.math("MULTIPLY", f1, 0.70), b.math("MULTIPLY", f2, 0.12)), 0.75 * fold)
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.10, 0.90, b.math("SUBTRACT", 0.0, crease)), shade), col, valley)
    weave_n = b.bump(b.math("ADD", b.math("MULTIPLY", weave, 0.5), b.math("MULTIPLY", slub, 0.3)), 0.9, 0.0016)
    n = b.bump(crease, 2.0, 0.010, normal=weave_n)
    return b.finish(col, b.math("ADD", rough, b.math("MULTIPLY", slub, 0.12)), 0.0, n, team=team)


def cord(name, color, team=0.0):
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    twist = b.math("SINE", b.math("ADD", b.math("MULTIPLY", v, 520.0), b.math("MULTIPLY", u, 190.0)))
    fib = b.noise(objv, 400.0, 3.0)
    col = b.mix(b.math("MULTIPLY", b.math("ADD", twist, 1.0), 0.18), color, tuple(min(c * 1.5, 1.0) for c in color[:3]) + (1,))
    col = b.mix(b.math("MULTIPLY", fib, 0.22), col, tuple(c * 0.25 for c in color[:3]) + (1,))
    n = b.bump(b.math("ADD", b.math("MULTIPLY", twist, 0.5), b.math("MULTIPLY", fib, 0.2)), 0.9, 0.0012)
    return b.finish(col, 0.78, 0.0, n, team=team)


def leather(name="arc_leather", c0=(0.085, 0.045, 0.022, 1), c1=(0.150, 0.082, 0.040, 1), rough=0.58):
    """Vegetable-tanned strap leather: grain, darker pores, pale scuffed edges."""
    b = NB(name)
    objv, oz = b.obj()
    n1 = b.noise(objv, 55.0, 4.0)
    grain = b.voronoi(objv, 900.0)
    wear = b.edge_wear(0.0020, 1.1)
    col = b.mix(b.smoothstep(0.3, 0.7, n1), c0, c1)
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.25, 0.0, grain), 0.35), col, tuple(c * 0.4 for c in c0[:3]) + (1,))
    col = b.mix(b.math("MULTIPLY", wear, 0.7), col, tuple(min(c * 2.4, 1.0) for c in c1[:3]) + (1,))
    n = b.bump(b.math("ADD", b.math("MULTIPLY", grain, -0.5), b.math("MULTIPLY", n1, 0.3)), 0.7, 0.0012)
    return b.finish(col, b.math("ADD", rough, b.math("MULTIPLY", n1, 0.18)), 0.0, n)


def haraate(name="arc_haraate"):
    """Hara-ate rows: black-brown lacquered rawhide with sparse paired lacing (sugake odoshi) crossing each row and a knot row along the top edge.
    Only the lacing feeds the team mask."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    ui = b.math("ROUND", u)
    d = b.math("ABSOLUTE", b.math("SUBTRACT", u, ui))
    on = b.math("LESS_THAN", b.math("MODULO", b.math("ADD", ui, 0.5), 2.0), 1.0)                      # every other plate boundary carries a pair of cords
    pair = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.010, 0.022, b.math("ABSOLUTE", b.math("SUBTRACT", d, 0.050)))), on)
    fv = b.math("FRACT", v)
    cross = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.045, 0.085, b.math("ABSOLUTE", b.math("SUBTRACT", fv, 0.13)))),
                   b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.062, 0.085, d)), on))     # the cross stitch at the head of each pair
    lace = b.math("MAXIMUM", pair, cross)
    n1 = b.noise(objv, 120.0, 5.0)
    streak = b.stretched(uvv, 12.0, 0.15, 14.0, 3.0)                                                  # brush strokes along the row
    plate = b.mix(b.smoothstep(0.30, 0.70, n1), (0.020, 0.014, 0.010, 1), (0.046, 0.029, 0.018, 1))
    plate = b.mix(b.math("MULTIPLY", b.smoothstep(0.62, 0.92, streak), 0.28), plate, (0.090, 0.055, 0.030, 1))
    wear = b.edge_wear(0.0018, 0.9)
    plate = b.mix(b.math("MULTIPLY", wear, b.math("SUBTRACT", 1.0, lace)), plate, (0.19, 0.115, 0.060, 1))      # worn through to the hide
    low = b.math("SUBTRACT", 1.0, b.smoothstep(0.80, 0.97, fv))                                       # the lower lip of each row lies in the next row's shadow line
    braid = b.math("SINE", b.math("ADD", b.math("MULTIPLY", v, 70.0), b.math("MULTIPLY", u, 46.0)))
    lace_col = b.mix(b.math("MULTIPLY", b.math("ADD", braid, 1.0), 0.2), (0.185, 0.175, 0.165, 1), (0.27, 0.255, 0.24, 1))
    col = b.mix(lace, plate, lace_col)
    col = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, low), 0.5), col, (0.008, 0.006, 0.005, 1))
    height = b.math("ADD", b.math("MULTIPLY", lace, 0.55), b.math("ADD", b.math("MULTIPLY", b.math("MULTIPLY", braid, lace), 0.12), b.math("MULTIPLY", n1, 0.06)))
    n = b.bump(height, 1.3, 0.0016)
    rough = b.math("ADD", b.mixf(lace, 0.32, 0.80), b.math("MULTIPLY", streak, 0.12))
    return b.finish(col, rough, 0.0, n, team=lace)


def jingasa(name="arc_jingasa", lacquer=None, gilt=True, mon=False):
    """War hat: black urushi over paper and hide, a brass rim, two fine gold rings with a painted band between them (the band is in the team mask),
    vermilion lacquer on the underside. pat UV = (angle 0..1, radius m).
    lacquer = two colours instead of the black; gilt=False paints the rim and the rings in ochre instead of metal (a levy's rawhide hat);
    mon=True adds a gilt house mark (a ring and its centre) on the front slope."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    geo = b.node("ShaderNodeNewGeometry")
    sep = b.node("ShaderNodeSeparateXYZ")
    b.l.new(geo.outputs["True Normal"], sep.inputs["Vector"])
    under = b.smoothstep(-0.05, -0.30, sep.outputs["Z"])
    rim = b.math("MULTIPLY", b.smoothstep(0.1820, 0.1840, v), 1.0)
    band = b.math("MULTIPLY", b.smoothstep(0.1130, 0.1150, v), b.math("SUBTRACT", 1.0, b.smoothstep(0.1440, 0.1460, v)))
    line = b.math("MAXIMUM", b.math("SUBTRACT", 1.0, b.smoothstep(0.0012, 0.0022, b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.1105)))),
                  b.math("SUBTRACT", 1.0, b.smoothstep(0.0012, 0.0022, b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.1485)))))
    top = b.math("SUBTRACT", 1.0, under)
    band = b.math("MULTIPLY", band, top)
    line = b.math("MULTIPLY", line, top)
    n1 = b.noise(objv, 150.0, 5.0)
    brush = b.stretched(uvv, 2.0, 160.0, 30.0, 3.0)                                                   # the lacquer brush went round the hat
    lq = lacquer or ((0.014, 0.013, 0.015, 1), (0.030, 0.027, 0.029, 1))
    black = b.mix(b.smoothstep(0.35, 0.65, n1), lq[0], lq[1])
    black = b.mix(b.math("MULTIPLY", b.smoothstep(0.60, 0.92, brush), 0.25), black, (0.060, 0.050, 0.046, 1))
    red = b.mix(b.smoothstep(0.35, 0.65, n1), (0.230, 0.026, 0.014, 1), (0.330, 0.050, 0.024, 1))
    gold = b.mix(b.smoothstep(0.4, 0.7, b.noise(objv, 70.0, 4.0)), (0.72, 0.47, 0.12, 1), (0.52, 0.32, 0.07, 1))
    paint = b.mix(b.math("MULTIPLY", b.smoothstep(0.55, 0.9, brush), 0.25), (0.30, 0.285, 0.27, 1), (0.22, 0.21, 0.20, 1))
    dust = b.math("MULTIPLY", b.math("MULTIPLY", b.smoothstep(0.50, 0.85, b.noise(objv, 11.0, 3.0)), top), 0.30)
    col = b.mix(under, black, red)
    col = b.mix(band, col, paint)
    metal = b.math("MAXIMUM", rim, line)
    if mon:                                                                                           # the front of the hat is u = 0.75 (toward -y)
        du = b.math("MULTIPLY", b.math("MULTIPLY", b.math("SUBTRACT", u, 0.75), TAU), v)
        dm = b.math("POWER", b.math("ADD", b.math("POWER", du, 2.0), b.math("POWER", b.math("SUBTRACT", v, 0.0800), 2.0)), 0.5)
        mark = b.math("MAXIMUM", b.math("SUBTRACT", 1.0, b.smoothstep(0.0030, 0.0046, b.math("ABSOLUTE", b.math("SUBTRACT", dm, 0.0200)))),
                      b.math("SUBTRACT", 1.0, b.smoothstep(0.0070, 0.0086, dm)))
        metal = b.math("MAXIMUM", metal, b.math("MULTIPLY", mark, top))
    if not gilt:
        gold = b.mix(b.smoothstep(0.4, 0.7, b.noise(objv, 70.0, 4.0)), (0.30, 0.19, 0.07, 1), (0.22, 0.13, 0.05, 1))
    col = b.mix(metal, col, gold)
    if not gilt:
        metal = b.math("MULTIPLY", metal, 0.0)
    col = b.mix(b.math("MULTIPLY", dust, b.math("SUBTRACT", 1.0, metal)), col, (0.085, 0.066, 0.046, 1))
    wear = b.edge_wear(0.0025, 1.2)
    col = b.mix(b.math("MULTIPLY", b.math("MULTIPLY", wear, b.math("SUBTRACT", 1.0, metal)), 0.6), col, (0.12, 0.10, 0.085, 1))
    height = b.math("ADD", b.math("MULTIPLY", metal, 0.8), b.math("ADD", b.math("MULTIPLY", brush, 0.10), b.math("MULTIPLY", band, 0.15)))
    n = b.bump(height, 0.9, 0.0012)
    rough = b.math("ADD", b.mixf(metal, 0.20, 0.30), b.math("ADD", b.math("MULTIPLY", band, 0.22), b.math("MULTIPLY", b.noise(objv, 40.0, 3.0), 0.20)))
    return b.finish(col, rough, metal, n, team=band)


def yumi(name="arc_yumi"):
    """The bow: black-lacquered bamboo laminate, rattan bindings at intervals, a vermilion section above and below the grip, pale horn tips. v = metres from the grip."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    av = b.math("ABSOLUTE", v)
    cell = b.math("FRACT", b.math("DIVIDE", b.math("ADD", av, 0.02), 0.112))
    rattan = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.085, 0.105, b.math("ABSOLUTE", b.math("SUBTRACT", cell, 0.5)))), b.smoothstep(0.10, 0.12, av))
    red = b.math("MULTIPLY", b.smoothstep(0.078, 0.084, av), b.math("SUBTRACT", 1.0, b.smoothstep(0.158, 0.164, av)))
    tipu = b.smoothstep(1.425, 1.440, v)
    tipl = b.smoothstep(-0.700, -0.714, v)
    tip = b.math("MAXIMUM", tipu, tipl)
    n1 = b.noise(objv, 140.0, 5.0)
    grain = b.stretched(uvv, 300.0, 3.0, 20.0, 3.0)
    black = b.mix(b.smoothstep(0.35, 0.65, n1), (0.012, 0.011, 0.012, 1), (0.030, 0.026, 0.024, 1))
    black = b.mix(b.math("MULTIPLY", b.smoothstep(0.62, 0.92, grain), 0.22), black, (0.070, 0.050, 0.036, 1))
    wind = b.math("SINE", b.math("MULTIPLY", v, TAU / 0.0030))
    cane = b.mix(b.math("MULTIPLY", b.math("ADD", wind, 1.0), 0.5), (0.26, 0.17, 0.065, 1), (0.48, 0.34, 0.15, 1))
    col = b.mix(b.math("MULTIPLY", red, b.math("SUBTRACT", 1.0, rattan)), black, (0.27, 0.030, 0.016, 1))
    col = b.mix(rattan, col, cane)
    col = b.mix(tip, col, (0.50, 0.44, 0.33, 1))
    wear = b.edge_wear(0.0016, 0.9)
    col = b.mix(b.math("MULTIPLY", b.math("MULTIPLY", wear, b.math("SUBTRACT", 1.0, rattan)), 0.5), col, (0.16, 0.11, 0.07, 1))
    height = b.math("ADD", b.math("MULTIPLY", rattan, 0.7), b.math("ADD", b.math("MULTIPLY", b.math("MULTIPLY", wind, rattan), 0.25), b.math("MULTIPLY", grain, 0.06)))
    n = b.bump(height, 1.0, 0.0010)
    rough = b.math("ADD", b.mixf(rattan, 0.22, 0.62), b.math("MULTIPLY", n1, 0.16))
    return b.finish(col, rough, 0.0, n)


def shaft(name="arc_shaft"):
    """Arrow shaft: fire-straightened bamboo with dark nodes, a vermilion nock, black thread wraps at both ends of the fletching. v = metres from the nock."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    node = b.math("SUBTRACT", 1.0, b.smoothstep(0.004, 0.010, b.math("ABSOLUTE", b.math("SUBTRACT", b.math("FRACT", b.math("DIVIDE", b.math("ADD", v, 0.07), 0.205)), 0.5))))
    nock = b.math("SUBTRACT", 1.0, b.smoothstep(0.026, 0.030, v))
    wrap = b.math("MAXIMUM", b.math("SUBTRACT", 1.0, b.smoothstep(0.006, 0.008, b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.172)))),
                  b.math("SUBTRACT", 1.0, b.smoothstep(0.003, 0.005, b.math("ABSOLUTE", b.math("SUBTRACT", v, 0.033)))))
    fib = b.stretched(uvv, 400.0, 2.0, 30.0, 3.0)
    col = b.mix(b.smoothstep(0.3, 0.7, fib), (0.40, 0.27, 0.105, 1), (0.56, 0.41, 0.19, 1))
    col = b.mix(b.math("MULTIPLY", node, 0.7), col, (0.16, 0.095, 0.035, 1))
    col = b.mix(nock, col, (0.30, 0.032, 0.018, 1))
    col = b.mix(wrap, col, (0.016, 0.014, 0.014, 1))
    n = b.bump(b.math("ADD", b.math("MULTIPLY", node, 0.6), b.math("MULTIPLY", wrap, 0.5)), 0.8, 0.0008)
    return b.finish(col, b.math("ADD", 0.36, b.math("MULTIPLY", fib, 0.2)), 0.0, n)


def fletch(name="arc_fletch"):
    """Hawk feathers: pale vanes with three dark bars, slanted barbs, a dark quill. u along the feather, v from the quill outward."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    bars = b.smoothstep(0.25, 0.75, b.math("SINE", b.math("ADD", b.math("MULTIPLY", u, TAU * 3.2), b.math("ADD", b.math("MULTIPLY", v, 1.6), 0.6))))
    barb = b.math("SINE", b.math("MULTIPLY", b.math("SUBTRACT", b.math("MULTIPLY", u, 46.0), b.math("MULTIPLY", v, 15.0)), TAU))
    mott = b.noise(objv, 300.0, 3.0)
    col = b.mix(bars, (0.60, 0.55, 0.46, 1), (0.085, 0.055, 0.032, 1))
    col = b.mix(b.math("MULTIPLY", mott, 0.25), col, (0.30, 0.24, 0.17, 1))
    col = b.mix(b.math("SUBTRACT", 1.0, b.smoothstep(0.05, 0.12, v)), col, (0.10, 0.07, 0.045, 1))
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.3, 1.0, barb), 0.18), col, (0.02, 0.016, 0.012, 1))
    n = b.bump(b.math("MULTIPLY", barb, 0.6), 0.7, 0.0006)
    return b.finish(col, 0.72, 0.0, n, spec=0.3)


def weave(name, c0, c1, pitch=0.011, rim_from=None):
    """Basket weave (quiver, string reel): over-under splints from the pattern UV in metres, lacquered."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    su = b.math("SINE", b.math("MULTIPLY", u, TAU / pitch))
    sv = b.math("SINE", b.math("MULTIPLY", v, TAU / pitch))
    over = b.smoothstep(-0.25, 0.25, b.math("MULTIPLY", su, sv))
    gap = b.math("SUBTRACT", 1.0, b.smoothstep(0.0, 0.22, b.math("MINIMUM", b.math("ABSOLUTE", su), b.math("ABSOLUTE", sv))))
    n1 = b.noise(objv, 60.0, 4.0)
    col = b.mix(over, c0, c1)
    col = b.mix(b.math("MULTIPLY", n1, 0.3), col, tuple(c * 0.5 for c in c0[:3]) + (1,))
    col = b.mix(gap, col, (0.010, 0.007, 0.005, 1))
    height = b.math("SUBTRACT", b.math("MULTIPLY", over, 0.5), b.math("MULTIPLY", gap, 0.8))
    rough = b.math("ADD", 0.36, b.math("MULTIPLY", n1, 0.25))
    if rim_from is not None:                                                                          # a lacquered leather band round the mouth
        rm = b.smoothstep(rim_from, rim_from + 0.004, v)
        col = b.mix(rm, col, (0.035, 0.020, 0.012, 1))
        height = b.math("MULTIPLY", height, b.math("SUBTRACT", 1.0, rm))
    n = b.bump(height, 1.2, 0.0014)
    return b.finish(col, rough, 0.0, n)


def bamboo(name="arc_bamboo"):
    """Banner pole: smoked bamboo with nodes."""
    b = NB(name)
    objv, oz = b.obj()
    node = b.math("SUBTRACT", 1.0, b.smoothstep(0.012, 0.030, b.math("ABSOLUTE", b.math("SUBTRACT", b.math("FRACT", b.math("DIVIDE", oz, 0.235)), 0.5))))
    n1 = b.noise(objv, 50.0, 4.0)
    col = b.mix(b.smoothstep(0.3, 0.7, n1), (0.060, 0.038, 0.018, 1), (0.125, 0.082, 0.038, 1))
    col = b.mix(b.math("MULTIPLY", node, 0.8), col, (0.022, 0.014, 0.008, 1))
    n = b.bump(b.math("MULTIPLY", node, 0.8), 0.9, 0.0012)
    return b.finish(col, b.math("ADD", 0.32, b.math("MULTIPLY", n1, 0.25)), 0.0, n)


def banner(name="arc_banner"):
    """Back banner: plain cloth, all of it in the team mask, a stitched border, no emblem (the engine draws the faction's crest from the emblem sheet)."""
    b = NB(name)
    objv, oz = b.obj()
    tc = b.node("ShaderNodeSeparateXYZ")
    b.l.new(objv, tc.inputs["Vector"])
    x = tc.outputs["X"]
    border = b.math("SUBTRACT", 1.0, b.smoothstep(0.0, 0.0040, b.math("MINIMUM", b.math("ABSOLUTE", b.math("SUBTRACT", x, K.X0)),
                    b.math("MINIMUM", b.math("ABSOLUTE", b.math("SUBTRACT", x, K.X0 + K.CLOTH_W)), b.math("ABSOLUTE", b.math("SUBTRACT", oz, K.BOTTOM))))))
    p = 0.0050
    wu = b.math("SINE", b.math("MULTIPLY", x, TAU / p))
    wv = b.math("SINE", b.math("MULTIPLY", oz, TAU / p))
    wv2 = b.math("ADD", b.math("MULTIPLY", wu, wv), b.math("MULTIPLY", b.math("ADD", wu, wv), 0.35))
    slub = b.noise(objv, 240.0, 3.0)
    cl = b.mix(b.math("MULTIPLY", b.math("ADD", slub, wv2), 0.10), (0.30, 0.30, 0.30, 1), (0.36, 0.36, 0.36, 1))
    col = b.mix(b.math("MULTIPLY", border, 0.5), cl, (0.20, 0.20, 0.20, 1))
    n = b.bump(b.math("ADD", b.math("MULTIPLY", wv2, 0.5), b.math("ADD", b.math("MULTIPLY", slub, 0.3), b.math("MULTIPLY", border, 0.5))), 0.9, 0.0014)
    return b.finish(col, b.math("ADD", 0.84, b.math("MULTIPLY", slub, 0.1)), 0.0, n, team=1.0)


def _ell(b, ax, oz, cx, cz, sx, sz):
    """elliptical distance of (|x|, z) to (cx, cz) in units of (sx, sz)"""
    return b.math("POWER", b.math("ADD", b.math("POWER", b.math("DIVIDE", b.math("SUBTRACT", ax, cx), sx), 2.0),
                                  b.math("POWER", b.math("DIVIDE", b.math("SUBTRACT", oz, cz), sz), 2.0)), 0.5)


def face(name="arc_face"):
    """The bare face: weathered warm skin, shadowed sockets, sun on the cheek bones and nose, lips, the blue shadow of a shaved jaw, darker nostrils and ears."""
    b = NB(name)
    objv, oz = b.obj()
    tc = b.node("ShaderNodeSeparateXYZ")
    b.l.new(objv, tc.inputs["Vector"])
    ax = b.math("ABSOLUTE", tc.outputs["X"])
    front = b.smoothstep(-0.02, -0.07, tc.outputs["Y"])
    n1 = b.noise(objv, 40.0, 4.0)
    col = b.mix(b.smoothstep(0.25, 0.75, n1), (0.360, 0.198, 0.124, 1), (0.415, 0.232, 0.148, 1))
    sock = b.math("SUBTRACT", 1.0, b.smoothstep(0.35, 1.25, _ell(b, ax, oz, 0.031, 1.652, 0.020, 0.012)))
    flush = b.math("SUBTRACT", 1.0, b.smoothstep(0.30, 1.10, _ell(b, ax, oz, 0.050, 1.617, 0.026, 0.022)))
    nose = b.math("SUBTRACT", 1.0, b.smoothstep(0.30, 1.10, _ell(b, ax, oz, 0.0, 1.618, 0.014, 0.016)))
    lips = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.55, 1.0, _ell(b, ax, oz, 0.0, 1.5822, 0.0245, 0.0085))), front)
    seam = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.4, 1.0, _ell(b, ax, oz, 0.0, 1.5822, 0.0235, 0.0016))), front)
    nostril = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.5, 1.0, _ell(b, ax, oz, 0.0078, 1.6062, 0.0036, 0.0018))), front)
    beard = b.math("MULTIPLY", b.math("MULTIPLY", b.smoothstep(1.612, 1.590, oz), b.smoothstep(1.524, 1.540, oz)), b.math("SUBTRACT", 1.0, lips))
    beard = b.math("MULTIPLY", b.math("MULTIPLY", beard, b.smoothstep(0.02, -0.03, tc.outputs["Y"])), b.math("ADD", 0.80, b.math("MULTIPLY", b.noise(objv, 260.0, 2.0), 0.20)))
    col = b.mix(b.math("MULTIPLY", sock, 0.60), col, (0.185, 0.092, 0.064, 1))
    col = b.mix(b.math("MULTIPLY", b.math("MAXIMUM", flush, nose), 0.38), col, (0.52, 0.235, 0.150, 1))
    col = b.mix(b.math("MULTIPLY", beard, 0.24), col, (0.165, 0.118, 0.100, 1))
    col = b.mix(b.math("MULTIPLY", lips, 0.72), col, (0.300, 0.105, 0.085, 1))
    col = b.mix(b.math("MULTIPLY", seam, 0.85), col, (0.090, 0.030, 0.026, 1))
    col = b.mix(b.math("MULTIPLY", nostril, 0.6), col, (0.075, 0.030, 0.022, 1))
    # no pore bump: at the atlas's texel size it is noise, and in a hat's shade (image light only) noisy normals sparkle
    rough = b.math("SUBTRACT", b.math("ADD", 0.52, b.math("MULTIPLY", n1, 0.05)), b.math("MULTIPLY", lips, 0.14))
    return b.finish(col, rough, 0.0)


def eye(name="arc_eye"):
    """The white of a bare-faced eye: off-white, a little red toward the corners (a pure white stares out from under a hat brim)."""
    b = NB(name)
    objv, oz = b.obj()
    tc = b.node("ShaderNodeSeparateXYZ")
    b.l.new(objv, tc.inputs["Vector"])
    edge = b.smoothstep(0.004, 0.011, b.math("ABSOLUTE", b.math("SUBTRACT", b.math("ABSOLUTE", tc.outputs["X"]), 0.031)))
    col = b.mix(b.math("MULTIPLY", edge, 0.55), (0.54, 0.50, 0.45, 1), (0.42, 0.27, 0.22, 1))
    return b.finish(col, 0.24, 0.0, spec=0.7)


def iris(name="arc_iris"):
    b = NB(name)
    return b.finish((0.034, 0.017, 0.009, 1), 0.12, 0.0, spec=0.85)


def glove(name="arc_glove"):
    """Yugake: smoked deerskin, soft and matte, with darker wear on the fingers and stitched seams."""
    b = NB(name)
    objv, oz = b.obj()
    n1 = b.noise(objv, 45.0, 4.0)
    grain = b.noise(objv, 700.0, 2.0)
    wear = b.edge_wear(0.0030, 1.0)
    col = b.mix(b.smoothstep(0.3, 0.7, n1), (0.300, 0.190, 0.085, 1), (0.430, 0.290, 0.140, 1))
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.55, 0.85, b.noise(objv, 18.0, 3.0)), 0.45), col, (0.150, 0.085, 0.038, 1))
    col = b.mix(b.math("MULTIPLY", wear, 0.35), col, (0.52, 0.38, 0.22, 1))
    n = b.bump(b.math("MULTIPLY", grain, 0.5), 0.5, 0.0010)
    return b.finish(col, b.math("ADD", 0.74, b.math("MULTIPLY", n1, 0.12)), 0.0, n, spec=0.3)


def yugote(name="arc_yugote"):
    """The bow arm's sleeve: indigo cotton quilted with white sashiko stitches in a diamond lattice."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    p = 0.0125
    d1 = b.math("ABSOLUTE", b.math("SUBTRACT", b.math("FRACT", b.math("DIVIDE", b.math("ADD", u, v), p)), 0.5))
    d2 = b.math("ABSOLUTE", b.math("SUBTRACT", b.math("FRACT", b.math("DIVIDE", b.math("SUBTRACT", u, v), p)), 0.5))
    dash1 = b.math("GREATER_THAN", b.math("SINE", b.math("MULTIPLY", b.math("SUBTRACT", u, v), TAU / 0.0052)), -0.2)
    dash2 = b.math("GREATER_THAN", b.math("SINE", b.math("MULTIPLY", b.math("ADD", u, v), TAU / 0.0052)), -0.2)
    st = b.math("MAXIMUM", b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.018, 0.040, d1)), dash1), b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.018, 0.040, d2)), dash2))
    wu = b.math("SINE", b.math("MULTIPLY", u, TAU / 0.0040))
    wv = b.math("SINE", b.math("MULTIPLY", v, TAU / 0.0040))
    weave_ = b.math("MULTIPLY", wu, wv)
    fade = b.noise(objv, 12.0, 4.0)
    col = b.mix(b.smoothstep(0.3, 0.7, fade), (0.016, 0.024, 0.062, 1), (0.034, 0.052, 0.118, 1))
    col = b.mix(b.math("MULTIPLY", b.math("ADD", weave_, 1.0), 0.06), col, (0.07, 0.09, 0.16, 1))
    col = b.mix(b.math("MULTIPLY", st, 0.62), col, (0.46, 0.45, 0.40, 1))
    n = b.bump(b.math("ADD", b.math("MULTIPLY", weave_, 0.3), b.math("MULTIPLY", st, 0.8)), 0.9, 0.0012)
    return b.finish(col, 0.84, 0.0, n)


def steel(name="arc_steel"):
    b = NB(name)
    objv, oz = b.obj()
    n1 = b.noise(objv, 300.0, 4.0)
    col = b.mix(b.smoothstep(0.3, 0.7, n1), (0.42, 0.44, 0.48, 1), (0.66, 0.67, 0.70, 1))
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.62, 0.85, b.noise(objv, 90.0, 3.0)), 0.4), col, (0.10, 0.08, 0.07, 1))
    return b.finish(col, b.math("ADD", 0.26, b.math("MULTIPLY", n1, 0.2)), 1.0, b.bump(b.math("MULTIPLY", n1, 0.3), 0.4, 0.0006))


BUILDERS = {
    "face": face,
    "skin": lambda: SSh.skin("arc_skin"), "eye": eye, "iris": iris, "hair": lambda: SSh.hair("arc_hair"),
    "straw": lambda: SSh.straw("arc_straw"), "brass": lambda: SSh.gold("arc_brass"),
    "kosode": lambda: cloth("arc_kosode", (0.300, 0.215, 0.125, 1), (0.420, 0.315, 0.195, 1), (0.085, 0.055, 0.030, 1), (0.50, 0.40, 0.27, 1), pitch=0.0046,
                            stripe=(0.0115, (0.170, 0.115, 0.068, 1), 0.10), shade=0.12, wander=2.2, fold=0.42),
    "juban": lambda: cloth("arc_juban", (0.46, 0.43, 0.37, 1), (0.60, 0.57, 0.50, 1), (0.20, 0.18, 0.15, 1), (0.66, 0.63, 0.56, 1), fold=0.35, pitch=0.0036),
    "hakama": lambda: cloth("arc_hakama", (0.017, 0.027, 0.066, 1), (0.036, 0.054, 0.118, 1), (0.005, 0.008, 0.021, 1), (0.065, 0.085, 0.150, 1), fold=1.15),
    "kyahan": lambda: cloth("arc_kyahan", (0.022, 0.036, 0.028, 1), (0.046, 0.068, 0.055, 1), (0.007, 0.011, 0.009, 1), (0.085, 0.105, 0.090, 1), fold=0.6, dirt_from=0.55),
    "tabi": lambda: cloth("arc_tabi", (0.250, 0.235, 0.200, 1), (0.360, 0.340, 0.295, 1), (0.110, 0.095, 0.075, 1), (0.42, 0.40, 0.35, 1), fold=0.3, dirt_from=0.20),
    "obi": lambda: cloth("arc_obi", (0.100, 0.026, 0.016, 1), (0.165, 0.048, 0.026, 1), (0.030, 0.008, 0.006, 1), (0.21, 0.08, 0.05, 1), fold=0.5, pitch=0.0030),
    "teamcloth": lambda: cloth("arc_teamcloth", (0.270, 0.262, 0.250, 1), (0.360, 0.350, 0.335, 1), (0.130, 0.125, 0.118, 1), (0.40, 0.39, 0.37, 1), team=1.0, fold=0.45, pitch=0.0034),
    "teamcord": lambda: cord("arc_teamcord", (0.250, 0.240, 0.228, 1), team=1.0),
    "cord": lambda: cord("arc_cord", (0.300, 0.250, 0.165, 1)),
    "string": lambda: cord("arc_string", (0.400, 0.340, 0.230, 1)),
    "leather": leather, "glove": glove, "yugote": yugote, "haraate": haraate, "jingasa": jingasa, "yumi": yumi, "shaft": shaft, "fletch": fletch,
    "steel": steel, "bamboo": bamboo, "banner": banner,
    "quiver": lambda: weave("arc_quiver", (0.060, 0.034, 0.016, 1), (0.150, 0.088, 0.036, 1), 0.0125, rim_from=0.355),
    "wicker": lambda: weave("arc_wicker", (0.200, 0.135, 0.060, 1), (0.360, 0.255, 0.115, 1), 0.0070),
}


def procedural(key):
    m = bpy.data.materials.get(f"arc_{key}")
    return m if m else BUILDERS[key]()
