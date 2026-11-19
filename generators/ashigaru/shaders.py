"""Procedural PBR materials of the ashigaru and of every piece of his kit (Cycles-bakeable, one Principled each; the samurai's node builder and the archer's cloth,
cord, leather and hat). Materials are named ash_<key>. Colours are scene-linear.
Pattern UV 'pat': cloth and tubes in metres, strips in plate / row units, the war hats (angle, profile radius), a spear shaft (around, metres from the butt)."""
import bpy

from samurai import shaders as SSh
from samurai.shaders import NB
from archer import shaders as AS

TAU = 6.2832


def spear_shaft(name, c0, c1, red_from=None, bands=()):
    """A lacquered oak shaft: grain along its length, a hand-polished stretch where it is held; optionally a vermilion upper length and brass bands (the pike)."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    grain = b.stretched(uvv, 26.0, 0.9, 30.0, 3.0)
    col = b.mix(b.smoothstep(0.30, 0.70, grain), c0, c1)
    held = b.math("MULTIPLY", b.smoothstep(0.30, 0.50, v), b.math("SUBTRACT", 1.0, b.smoothstep(1.35, 1.60, v)))
    col = b.mix(b.math("MULTIPLY", held, 0.22), col, tuple(min(c * 1.7, 1.0) for c in c1[:3]) + (1,))
    metal = 0.0
    if red_from is not None:
        red = b.smoothstep(red_from, red_from + 0.004, v)
        col = b.mix(red, col, b.mix(b.smoothstep(0.3, 0.7, grain), (0.260, 0.028, 0.016, 1), (0.360, 0.052, 0.026, 1)))
        m = None
        for at in bands:
            k = b.math("SUBTRACT", 1.0, b.smoothstep(0.010, 0.012, b.math("ABSOLUTE", b.math("SUBTRACT", v, at))))
            m = k if m is None else b.math("MAXIMUM", m, k)
        if m is not None:
            col = b.mix(m, col, (0.66, 0.43, 0.11, 1))
            metal = m
    n = b.bump(b.math("MULTIPLY", grain, 0.35), 0.5, 0.0006)
    rough = b.math("SUBTRACT", b.math("ADD", 0.40, b.math("MULTIPLY", grain, 0.14)), b.math("MULTIPLY", held, 0.10))
    return b.finish(col, rough, metal, n)


def okegawa(name):
    """Okegawa do: horizontal iron lames under black lacquer, riveted (a row of rivet heads along the top of every lame), the lacquer worn brown at the edges; on the
    chest the house's mark in gold (a ring and its centre). pat UV = (plate, row): the fraction of v runs from the top edge of a lame to its bottom edge."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    tc = b.node("ShaderNodeSeparateXYZ")
    b.l.new(objv, tc.inputs["Vector"])
    fv = b.math("FRACT", v)
    du = b.math("MULTIPLY", b.math("ABSOLUTE", b.math("SUBTRACT", u, b.math("ROUND", u))), 0.037)
    dv = b.math("MULTIPLY", b.math("SUBTRACT", fv, 0.24), 0.050)
    dr = b.math("POWER", b.math("ADD", b.math("POWER", du, 2.0), b.math("POWER", dv, 2.0)), 0.5)
    rivet = b.math("SUBTRACT", 1.0, b.smoothstep(0.0030, 0.0046, dr))
    lip = b.math("SUBTRACT", 1.0, b.smoothstep(0.0, 0.09, fv))
    under = b.smoothstep(0.84, 1.0, fv)
    n1 = b.noise(objv, 120.0, 5.0)
    brush = b.stretched(uvv, 3.0, 40.0, 30.0, 3.0)
    col = b.mix(b.smoothstep(0.35, 0.65, n1), (0.011, 0.011, 0.013, 1), (0.024, 0.023, 0.026, 1))
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.60, 0.92, brush), 0.20), col, (0.050, 0.044, 0.042, 1))
    col = b.mix(b.math("MULTIPLY", under, 0.55), col, (0.004, 0.004, 0.005, 1))
    wear = b.math("MAXIMUM", b.edge_wear(0.0025, 1.2), b.math("MULTIPLY", lip, b.smoothstep(0.45, 0.80, b.noise(objv, 60.0, 3.0))))
    col = b.mix(b.math("MULTIPLY", wear, 0.55), col, (0.110, 0.070, 0.045, 1))
    dust = b.math("MULTIPLY", b.smoothstep(0.52, 0.86, b.noise(objv, 13.0, 3.0)), b.smoothstep(1.30, 1.10, oz))
    col = b.mix(b.math("MULTIPLY", dust, 0.22), col, (0.090, 0.070, 0.050, 1))
    front = b.smoothstep(-0.03, -0.07, tc.outputs["Y"])
    dm = b.math("POWER", b.math("ADD", b.math("POWER", tc.outputs["X"], 2.0), b.math("POWER", b.math("SUBTRACT", oz, 1.318), 2.0)), 0.5)
    mark = b.math("MAXIMUM", b.math("SUBTRACT", 1.0, b.smoothstep(0.0048, 0.0064, b.math("ABSOLUTE", b.math("SUBTRACT", dm, 0.0400)))),
                  b.math("SUBTRACT", 1.0, b.smoothstep(0.0125, 0.0141, dm)))
    mark = b.math("MULTIPLY", mark, front)
    gold = b.mix(b.smoothstep(0.4, 0.7, b.noise(objv, 70.0, 4.0)), (0.70, 0.46, 0.12, 1), (0.50, 0.31, 0.07, 1))
    col = b.mix(rivet, col, (0.150, 0.140, 0.130, 1))
    col = b.mix(mark, col, gold)
    metal = b.math("MAXIMUM", b.math("MULTIPLY", rivet, 0.9), mark)
    height = b.math("ADD", b.math("MULTIPLY", rivet, 1.0), b.math("SUBTRACT", b.math("MULTIPLY", lip, 0.35), b.math("MULTIPLY", under, 0.5)))
    height = b.math("ADD", height, b.math("ADD", b.math("MULTIPLY", brush, 0.06), b.math("MULTIPLY", mark, 0.25)))
    n = b.bump(height, 0.9, 0.0016)
    rough = b.math("ADD", b.mixf(metal, 0.24, 0.34), b.math("MULTIPLY", b.noise(objv, 40.0, 3.0), 0.16))
    return b.finish(col, rough, metal, n)


def builders():
    P = "ash_"
    indigo = dict(c0=(0.028, 0.046, 0.086, 1), c1=(0.048, 0.074, 0.126, 1), valley=(0.009, 0.015, 0.030, 1), lint=(0.105, 0.135, 0.195, 1))
    B = {
        "face": lambda: AS.face(P + "face"), "skin": lambda: SSh.skin(P + "skin"), "eye": lambda: AS.eye(P + "eye"), "iris": lambda: AS.iris(P + "iris"),
        "hair": lambda: SSh.hair(P + "hair"), "straw": lambda: SSh.straw(P + "straw"), "brass": lambda: SSh.gold(P + "brass"),
        "kosode": lambda: AS.cloth(P + "kosode", indigo["c0"], indigo["c1"], indigo["valley"], indigo["lint"], pitch=0.0046, shade=0.14, wander=2.2, fold=0.45),
        "juban": lambda: AS.cloth(P + "juban", (0.46, 0.43, 0.37, 1), (0.60, 0.57, 0.50, 1), (0.20, 0.18, 0.15, 1), (0.66, 0.63, 0.56, 1), fold=0.35, pitch=0.0036),
        "kyahan": lambda: AS.cloth(P + "kyahan", (0.016, 0.026, 0.050, 1), (0.030, 0.046, 0.082, 1), (0.006, 0.009, 0.018, 1), (0.075, 0.095, 0.135, 1), fold=0.6, dirt_from=0.55),
        "tabi": lambda: AS.cloth(P + "tabi", (0.020, 0.030, 0.056, 1), (0.036, 0.052, 0.090, 1), (0.007, 0.010, 0.020, 1), (0.085, 0.105, 0.150, 1), fold=0.3, dirt_from=0.20),
        "obi": lambda: AS.cloth(P + "obi", (0.270, 0.262, 0.250, 1), (0.360, 0.350, 0.335, 1), (0.130, 0.125, 0.118, 1), (0.40, 0.39, 0.37, 1), team=0.9, fold=0.5, pitch=0.0030),
        "teamcloth": lambda: AS.cloth(P + "teamcloth", (0.270, 0.262, 0.250, 1), (0.360, 0.350, 0.335, 1), (0.130, 0.125, 0.118, 1), (0.40, 0.39, 0.37, 1), team=1.0, fold=0.45, pitch=0.0034),
        "pennant": lambda: AS.cloth(P + "pennant", (0.290, 0.282, 0.270, 1), (0.380, 0.370, 0.355, 1), (0.150, 0.145, 0.138, 1), (0.42, 0.41, 0.39, 1), team=1.0, fold=0.25, pitch=0.0030),
        "teamcord": lambda: AS.cord(P + "teamcord", (0.250, 0.240, 0.228, 1), team=1.0),
        "cord": lambda: AS.cord(P + "cord", (0.300, 0.250, 0.165, 1)),
        "lacing": lambda: AS.cord(P + "lacing", (0.022, 0.034, 0.078, 1)),
        "leather": lambda: AS.leather(P + "leather"),
        "gourd": lambda: AS.leather(P + "gourd", c0=(0.230, 0.140, 0.050, 1), c1=(0.360, 0.240, 0.090, 1), rough=0.40),
        "ration": lambda: AS.cloth(P + "ration", (0.330, 0.300, 0.240, 1), (0.450, 0.420, 0.350, 1), (0.150, 0.130, 0.095, 1), (0.52, 0.49, 0.42, 1), pitch=0.0052, fold=0.5, shade=0.20),
        "steel": lambda: AS.steel(P + "steel"), "iron": lambda: SSh.iron(P + "iron"), "lacquer": lambda: SSh.lacquer(P + "lacquer"),
        "saya": lambda: SSh.lacquer(P + "saya"), "tsuka": lambda: AS.cord(P + "tsuka", (0.030, 0.040, 0.070, 1)),
        "lamellar": lambda: SSh.lamellar(P + "lamellar"),
        "shaft": lambda: spear_shaft(P + "shaft", (0.060, 0.030, 0.016, 1), (0.120, 0.064, 0.030, 1)),
        "pike": lambda: spear_shaft(P + "pike", (0.012, 0.011, 0.012, 1), (0.030, 0.027, 0.026, 1), red_from=2.62, bands=(2.62, 3.02)),
        "bamboo": lambda: AS.bamboo(P + "bamboo"), "banner": lambda: AS.banner(P + "banner"),
        "yugote": lambda: AS.cloth(P + "yugote", (0.020, 0.032, 0.062, 1), (0.036, 0.054, 0.096, 1), (0.007, 0.011, 0.022, 1), (0.085, 0.108, 0.155, 1), fold=0.3, pitch=0.0034),
    }
    B["hakama"] = lambda: AS.cloth(P + "hakama", (0.200, 0.168, 0.122, 1), (0.290, 0.248, 0.185, 1), (0.070, 0.056, 0.038, 1), (0.36, 0.32, 0.25, 1), fold=0.9, shade=0.22)
    B["haraate"] = lambda: AS.haraate(P + "haraate")
    B["jingasa"] = lambda: AS.jingasa(P + "jingasa", lacquer=((0.034, 0.021, 0.013, 1), (0.062, 0.040, 0.024, 1)), gilt=False)        # rawhide under brown lacquer
    B["jingasa2"] = lambda: AS.jingasa(P + "jingasa2", mon=True)                                                                         # iron, the house's mark in gold
    B["kote"] = lambda: AS.cloth(P + "kote", (0.016, 0.024, 0.046, 1), (0.030, 0.042, 0.074, 1), (0.005, 0.008, 0.016, 1), (0.070, 0.088, 0.130, 1), fold=0.5, pitch=0.0030)
    B["necloth"] = lambda: AS.cloth(P + "necloth", (0.020, 0.030, 0.058, 1), (0.038, 0.054, 0.094, 1), (0.007, 0.011, 0.022, 1), (0.085, 0.105, 0.150, 1), fold=0.8, pitch=0.0040)
    B["okegawa"] = lambda: okegawa(P + "okegawa")
    return B


_B = {}


def procedural(key):
    """mat_fn for build.build_model: key -> material (created once per session)"""
    m = bpy.data.materials.get(f"ash_{key}")
    if m:
        return m
    if not _B:
        _B.update(builders())
    return _B[key]()
