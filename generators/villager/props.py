"""The villager's props: eight tools, five loads and the straw hat. Small procedural meshes (lofted rings), one bone each, textured from
swatches painted into the strip of the atlas the body leaves free (v < lowpoly.BODY_V0). Pure geometry here: no rig knowledge.

Frames
  tool   origin = the centre of the gripping hand, +Z = along the handle toward the working end, +X = the way the tool strikes / cuts, +Y = Z x X
  load   origin = where it rests (bottom centre), +Y = the carrier's back (long loads lie along Y), +Z = up, +X = the carrier's left
  hat    origin = the crown of the skull (top of the head, without the topknot), axes = the armature's

`build(name)` returns (verts, faces, uvs-per-face-corner, {"tris": n}); `SWATCH` names the texture cells; `paint_strip` fills them.
"""
import math

import numpy as np
from mathutils import Vector

V = Vector

# ---------------------------------------------------------------------------------------------------- swatches (cells of the prop strip)
COLS, ROWS = 8, 2
STRIP_V = 0.25                       # = lowpoly.BODY_V0
SWATCH = {n: i for i, n in enumerate(
    ["wood", "wood_dark", "iron", "steel", "straw", "rope", "bark", "log_end",
     "plank", "bamboo", "weave", "contents", "kasa", "line", "cloth", "kasa_under"])}
MARGIN = 0.05                        # of a cell, kept clear at every edge (the bake margin and the mips bleed into it)


def sw_uv(sw, s, t):
    i = SWATCH[sw]
    col, row = i % COLS, i // COLS
    u = (col + MARGIN + min(max(s, 0.0), 1.0) * (1 - 2 * MARGIN)) / COLS
    v = (row + MARGIN + min(max(t, 0.0), 1.0) * (1 - 2 * MARGIN)) / ROWS * STRIP_V
    return (u, v)


class Geo:
    def __init__(self):
        self.v, self.f, self.uv = [], [], []

    def _add(self, pts):
        i = len(self.v)
        self.v.extend(V(p) for p in pts)
        return list(range(i, i + len(pts)))

    def face(self, idx, uvs):
        self.f.append(tuple(idx))
        self.uv.append(tuple(uvs))

    def loft(self, rings, sw, cap0=True, cap1=True, s_rep=1.0, t0=0.0, t1=1.0, cap_sw=None):
        """closed rings (same vertex count) joined by quads; s runs around, t along. Caps are fans mapped to a disc of `cap_sw`."""
        n, m = len(rings[0]), len(rings)
        ids = [self._add(r) for r in rings]
        for i in range(m - 1):
            ta, tb = t0 + (t1 - t0) * i / (m - 1), t0 + (t1 - t0) * (i + 1) / (m - 1)
            for j in range(n):
                k = (j + 1) % n
                sa, sb = s_rep * j / n, s_rep * (j + 1) / n
                sa, sb = sa % 1.0 if sb % 1.0 > sa % 1.0 or sb % 1.0 == 0 else sa % 1.0, (sb % 1.0) or 1.0
                self.face((ids[i][j], ids[i][k], ids[i + 1][k], ids[i + 1][j]), (sw_uv(sw, sa, ta), sw_uv(sw, sb, ta), sw_uv(sw, sb, tb), sw_uv(sw, sa, tb)))
        cs = cap_sw or sw
        for on, ring in ((cap0, ids[0]), (cap1, ids[-1])):
            if on:
                self.face(ring, [sw_uv(cs, 0.5 + 0.45 * math.cos(2 * math.pi * j / n), 0.5 + 0.45 * math.sin(2 * math.pi * j / n)) for j in range(n)])
        return ids

    def ring(self, c, ax, r, n, rx=None, start=0.0, side=None):
        """n points around centre c in the plane normal to `ax`; rx (optional) = radius along `side` (default a stable perpendicular), r along the other."""
        ax = V(ax).normalized()
        a = V(side) if side is not None else (V((0, 1, 0)) if abs(ax.y) < 0.9 else V((1, 0, 0)))
        a = (a - ax * a.dot(ax)).normalized()
        b = ax.cross(a)
        rx = r if rx is None else rx
        return [V(c) + a * (rx * math.cos(start + 2 * math.pi * j / n)) + b * (r * math.sin(start + 2 * math.pi * j / n)) for j in range(n)]

    def cyl(self, p0, p1, r0, r1, n, sw, rx0=None, rx1=None, side=None, caps=(True, True), cap_sw=None, mid=0, t0=0.0, t1=1.0, s_rep=1.0):
        p0, p1 = V(p0), V(p1)
        ax = p1 - p0
        rings = []
        for i in range(mid + 2):
            u = i / (mid + 1)
            rings.append(self.ring(p0.lerp(p1, u), ax, r0 + (r1 - r0) * u, n, None if rx0 is None else rx0 + ((rx1 if rx1 is not None else rx0) - rx0) * u, side=side))
        return self.loft(rings, sw, caps[0], caps[1], cap_sw=cap_sw, t0=t0, t1=t1, s_rep=s_rep)

    def bar(self, pts, hw, ht, sw, wide=(0, 1, 0), caps=(True, True), cap_sw=None):
        """a rectangular bar through `pts`: half-width hw[i] along `wide`, half-thickness ht[i] across (in the plane of the path)."""
        rings = []
        w = V(wide).normalized()
        for i, p in enumerate(pts):
            p = V(p)
            d = (V(pts[min(i + 1, len(pts) - 1)]) - V(pts[max(i - 1, 0)])).normalized()
            t = d.cross(w).normalized()
            a, b = (hw[i] if hasattr(hw, "__len__") else hw), (ht[i] if hasattr(ht, "__len__") else ht)
            rings.append([p + w * a + t * b, p - w * a + t * b, p - w * a - t * b, p + w * a - t * b])
        return self.loft(rings, sw, caps[0], caps[1], cap_sw=cap_sw)

    def result(self):
        return self.v, self.f, self.uv, {"tris": sum(len(f) - 2 for f in self.f)}


# ---------------------------------------------------------------------------------------------------- tools
# The right hand is the UPPER hand of a two-handed tool: the grip origin sits well under the head and the handle runs on below it for the left hand.
HEAD_Z = {"ono": 0.385, "tsuruhashi": 0.475, "kuwa": 0.680, "tsuchi": 0.212}      # where the working end is, along the handle from the right hand


def _handle(g, z0, z1, r=0.015, n=6, sw="wood", rx=None, r1=None):
    g.cyl((0, 0, z0), (0, 0, z1), r, r if r1 is None else r1, n, sw, rx0=rx, rx1=rx, side=(1, 0, 0))


def ono():
    """the felling axe: a long ash handle with a narrow wedge bit"""
    g = Geo()
    _handle(g, -0.32, 0.445, r=0.013, rx=0.017, n=6)
    z = HEAD_Z["ono"]
    sec = [(-0.040, 0.034, 0.017), (-0.012, 0.034, 0.018), (0.035, 0.038, 0.013), (0.095, 0.052, 0.006), (0.135, 0.062, 0.0012)]
    rings = [[V((x, t, z + h)), V((x, -t, z + h)), V((x, -t, z - h * 1.15)), V((x, t, z - h * 1.15))] for x, h, t in sec]
    g.loft(rings[:3], "iron", True, False)
    g.loft(rings[2:], "steel", False, True)
    return g.result()


def tsuruhashi():
    """the pickaxe: a stout handle, a curved head with two points"""
    g = Geo()
    _handle(g, -0.34, 0.505, r=0.015, rx=0.018, n=6)
    z = HEAD_Z["tsuruhashi"]
    pts, hw, ht = [], [], []
    for i in range(9):
        u = (i - 4) / 4.0                                  # -1 .. 1
        pts.append((u * 0.27, 0.0, z - 0.085 * u * u))
        k = 1.0 - abs(u)
        hw.append(0.004 + 0.016 * k ** 0.7)
        ht.append(0.004 + 0.018 * k ** 0.7)
    g.bar(pts, hw, ht, "iron")
    return g.result()


def kuwa():
    """the hoe: a long handle and a wooden blade shod with iron, set at an acute angle back toward the hands"""
    g = Geo()
    _handle(g, -0.48, 0.705, r=0.014, rx=0.016, n=6)
    z = HEAD_Z["kuwa"]
    a = (0.0, 0.0, z)
    b = (0.115, 0.0, z - 0.050)
    c = (0.245, 0.0, z - 0.120)
    g.bar([a, b], [0.050, 0.058], [0.014, 0.011], "wood_dark", caps=(True, False))
    g.bar([b, c], [0.058, 0.062], [0.011, 0.0025], "iron", caps=(False, True))
    return g.result()


def tsuchi():
    """the hammer (genno): a short handle and a plain iron head"""
    g = Geo()
    _handle(g, -0.085, 0.235, r=0.0105, rx=0.013, n=6)
    g.cyl((-0.048, 0, 0.212), (0.048, 0, 0.212), 0.021, 0.021, 8, "iron", side=(0, 1, 0), mid=0)
    return g.result()


def kama():
    """the sickle: a short handle, a hooked blade"""
    g = Geo()
    _handle(g, -0.075, 0.255, r=0.0105, rx=0.0125, n=6)
    pts = [(0.0, 0, 0.240), (0.060, 0, 0.268), (0.125, 0, 0.262), (0.180, 0, 0.230), (0.215, 0, 0.178)]
    g.bar(pts, [0.0022, 0.0020, 0.0018, 0.0014, 0.0006], [0.017, 0.019, 0.018, 0.013, 0.003], "steel")
    g.cyl((0, 0, 0.225), (0, 0, 0.258), 0.0135, 0.0135, 6, "iron", side=(1, 0, 0))
    return g.result()


def nokogiri():
    """the saw: a rattan-wrapped handle and a broad blade, teeth toward +X"""
    g = Geo()
    _handle(g, -0.07, 0.20, r=0.011, rx=0.014, n=6, sw="rope")
    t = 0.0016
    prof = [(-0.016, 0.19), (0.040, 0.19), (0.092, 0.62), (0.060, 0.66), (-0.022, 0.64)]          # (x, z): spine at -x, teeth at +x
    front = [V((x, t, z)) for x, z in prof]
    back = [V((x, -t, z)) for x, z in reversed(prof)]
    i0 = g._add(front)
    i1 = g._add(back)

    def uvp(p):
        return sw_uv("steel", (p.x + 0.03) / 0.13, (p.z - 0.18) / 0.5)
    g.face(i0, [uvp(p) for p in front])
    g.face(i1, [uvp(p) for p in back])
    n = len(prof)
    for j in range(n):
        a, b = i0[j], i0[(j + 1) % n]
        c, d = i1[n - 1 - ((j + 1) % n)], i1[n - 1 - j]
        g.face((a, d, c, b), [sw_uv("iron", 0.1, 0.1), sw_uv("iron", 0.1, 0.2), sw_uv("iron", 0.9, 0.2), sw_uv("iron", 0.9, 0.1)])
    return g.result()


def nomi():
    """the chisel, held like a dagger in the LEFT hand: the edge leaves the hand at the little finger (-Z), the hammer strikes the butt (+Z)"""
    g = Geo()
    g.cyl((0, 0, -0.025), (0, 0, 0.105), 0.0125, 0.0115, 6, "wood", side=(1, 0, 0))
    g.cyl((0, 0, 0.100), (0, 0, 0.112), 0.0135, 0.0135, 6, "iron", side=(1, 0, 0))
    g.bar([(0, 0, -0.022), (0, 0, -0.105), (0, 0, -0.165)], [0.0075, 0.0085, 0.0110], [0.0065, 0.0050, 0.0012], "steel", wide=(0, 1, 0))
    return g.result()


ROD_TIP = (0.085, 0.0, 2.36)          # where the line leaves the rod (tool frame)
LINE_LEN = 1.35


def tsurizao():
    """the fishing rod: a tapering bamboo pole with a gentle droop"""
    g = Geo()
    pts = [(0, 0, -0.22), (0, 0, 0.30), (0.004, 0, 0.90), (0.018, 0, 1.50), (0.045, 0, 2.00), ROD_TIP]
    rad = [0.0125, 0.0120, 0.0100, 0.0075, 0.0050, 0.0028]
    rings = []
    for i, p in enumerate(pts):
        d = V(pts[min(i + 1, len(pts) - 1)]) - V(pts[max(i - 1, 0)])
        rings.append(g.ring(p, d, rad[i], 5, side=(1, 0, 0)))
    g.loft(rings, "bamboo", True, True)
    return g.result()


def tsurizao_line():
    """the line and its float, in the LINE bone's frame: origin = the rod tip, the line runs along +Y of that bone (rest: wound back along the rod)"""
    g = Geo()
    w = 0.0022
    for k in range(2):                                       # two crossed ribbons read as a thread from every side
        a = V((w, 0, 0)) if k == 0 else V((0, 0, w))
        p0, p1 = V((0, 0.0, 0)), V((0, LINE_LEN, 0))
        i = g._add([p0 - a, p0 + a, p1 + a, p1 - a])
        g.face(i, [sw_uv("line", 0.2, 0.1), sw_uv("line", 0.8, 0.1), sw_uv("line", 0.8, 0.9), sw_uv("line", 0.2, 0.9)])
        i = g._add([p1 - a, p1 + a, p0 + a, p0 - a])
        g.face(i, [sw_uv("line", 0.2, 0.9), sw_uv("line", 0.8, 0.9), sw_uv("line", 0.8, 0.1), sw_uv("line", 0.2, 0.1)])
    c = V((0, LINE_LEN - 0.10, 0))                           # the float: a small spindle
    rings = [g.ring(c + V((0, dy, 0)), (0, 1, 0), r, 5) for dy, r in ((-0.035, 0.0015), (-0.012, 0.011), (0.012, 0.009), (0.030, 0.0015))]
    g.loft(rings, "cloth", True, True)
    return g.result()


# ---------------------------------------------------------------------------------------------------- loads
def sack():
    """a tawara: the straw rice bale every store of a Sengoku village is counted in. Lies along Y on the shoulder."""
    g = Geo()
    L, R, n = 0.60, 0.165, 10
    prof = [(-L / 2, R * 0.55), (-L / 2 + 0.03, R * 0.90), (-L / 2 + 0.10, R), (0.0, R * 1.03), (L / 2 - 0.10, R), (L / 2 - 0.03, R * 0.90), (L / 2, R * 0.55)]
    rings = [g.ring((0, y, R), (0, 1, 0), r, n, side=(1, 0, 0)) for y, r in prof]
    g.loft(rings, "straw", True, True, s_rep=1.0, cap_sw="kasa_under")
    for y in (-0.19, 0.0, 0.19):
        g.cyl((0, y - 0.011, R), (0, y + 0.011, R), R * 1.045, R * 1.045, n, "rope", side=(1, 0, 0), caps=(False, False))
    return g.result()


def log():
    g = Geo()
    L, R = 1.55, 0.082
    rings = [g.ring((0.004 * math.sin(i * 1.7), -L / 2 + L * i / 4, R + 0.004 * math.cos(i * 2.3)), (0, 1, 0), R * (1.0 + 0.05 * math.sin(i * 2.1)), 8, side=(1, 0, 0)) for i in range(5)]
    g.loft(rings, "bark", True, True, cap_sw="log_end")
    return g.result()


def planks():
    g = Geo()
    L, W, T = 1.75, 0.082, 0.011
    for k, (dx, dy, dz, yaw) in enumerate(((0.0, 0.0, 0.0, 0.0), (0.012, 0.05, 2 * T + 0.002, 0.012), (-0.010, -0.04, 4 * T + 0.004, -0.010))):
        c, s = math.cos(yaw), math.sin(yaw)
        pts = [(dx - s * (-L / 2), dy + c * (-L / 2), dz + T), (dx - s * (L / 2), dy + c * (L / 2), dz + T)]
        g.bar(pts, W, T, "plank", wide=(c, s, 0), cap_sw="log_end")
    return g.result()


def bamboo():
    g = Geo()
    L, R = 2.05, 0.021
    lay = [(-0.043, 0.0, R), (0.0, 0.03, R), (0.043, -0.02, R), (-0.021, 0.05, R * 2.75), (0.022, -0.04, R * 2.75)]
    for k, (x, dy, z) in enumerate(lay):
        g.cyl((x, -L / 2 + dy, z), (x, L / 2 + dy, z), R, R * 0.86, 5, "bamboo", side=(1, 0, 0), cap_sw="log_end")
    for y in (-0.55, 0.55):
        g.cyl((0, y - 0.012, R * 1.9), (0, y + 0.012, R * 1.9), 0.062, 0.062, 8, "rope", rx0=0.075, rx1=0.075, side=(1, 0, 0), caps=(False, False))
    return g.result()


BASKET_GRIP = (0.205, 0.0, 0.205)        # where a hand takes the rim (mirror x for the other hand)


def basket():
    """a woven carrying basket heaped with whatever is being hauled (the heap is tinted by the engine through the mask)"""
    g = Geo()
    n = 10
    wall = [(0.0, 0.135), (0.02, 0.155), (0.12, 0.190), (0.215, 0.212)]
    rings = [g.ring((0, 0, z), (0, 0, 1), r, n, side=(1, 0, 0)) for z, r in wall]
    g.loft(rings, "weave", True, False, s_rep=1.0)
    g.loft([g.ring((0, 0, 0.207), (0, 0, 1), 0.219, n, side=(1, 0, 0)), g.ring((0, 0, 0.228), (0, 0, 1), 0.219, n, side=(1, 0, 0)), g.ring((0, 0, 0.228), (0, 0, 1), 0.198, n, side=(1, 0, 0))],
           "rope", False, False)
    heap = [(0.222, 0.200), (0.262, 0.165), (0.300, 0.105), (0.322, 0.040)]
    hr = []
    for i, (z, r) in enumerate(heap):
        ring = g.ring((0.01 * math.sin(i * 2.0), 0.012 * math.cos(i * 1.3), z), (0, 0, 1), r, n, side=(1, 0, 0))
        hr.append([p + V((0, 0, 0.012 * math.sin(j * 2.4 + i * 1.9))) for j, p in enumerate(ring)])
    g.loft(hr, "contents", False, True, s_rep=1.0)
    return g.result()


# ---------------------------------------------------------------------------------------------------- hat
def kasa():
    """a sedge hat (sugegasa): a shallow cone with a rim, a liner ring that sits on the head and a chin cord"""
    g = Geo()
    n = 12
    top = [(0.150, 0.004), (0.118, 0.075), (0.045, 0.185), (-0.012, 0.262)]
    rings = [g.ring((0, 0.005, z), (0, 0, 1), r, n, side=(1, 0, 0)) for z, r in top]
    g.loft(rings, "kasa", True, False)
    under = [(-0.012, 0.262), (-0.020, 0.258), (0.030, 0.180), (0.062, 0.098)]
    rings = [g.ring((0, 0.005, z), (0, 0, 1), r, n, side=(1, 0, 0)) for z, r in under]
    g.loft(list(reversed(rings)), "kasa_under", True, False)
    for sx in (1.0, -1.0):                                   # the cord: brim liner -> past the ear -> under the chin
        pts = [(sx * 0.094, 0.000, 0.058), (sx * 0.083, -0.012, -0.075), (sx * 0.070, -0.038, -0.165), (sx * 0.030, -0.078, -0.218), (0.0, -0.088, -0.226)]
        g.bar(pts, 0.0035, 0.0018, "cloth", wide=(0, 1, 0), caps=(False, False))
    return g.result()


TOOLS = {"ono": ono, "nokogiri": nokogiri, "kama": kama, "nomi": nomi, "tsuruhashi": tsuruhashi, "tsuchi": tsuchi, "kuwa": kuwa, "tsurizao": tsurizao}
LOADS = {"sack": sack, "basket": basket, "log": log, "planks": planks, "bamboo": bamboo}
# where the second (left) hand takes a two-handed tool: distance along the handle from the right hand (tool +Z; negative = toward the butt), None = one-handed
SECOND_GRIP = {"ono": -0.22, "tsuruhashi": -0.24, "kuwa": -0.32, "nokogiri": None, "kama": None, "tsuchi": None, "nomi": None, "tsurizao": -0.17}
LONG_TOOLS = ("ono", "kuwa", "tsuruhashi", "tsurizao")


# ---------------------------------------------------------------------------------------------------- textures of the strip
def _noise(rng, h, w, cells_y, cells_x):
    g = rng.random((cells_y + 1, cells_x + 1))
    ys = np.linspace(0, cells_y, h, endpoint=False)
    xs = np.linspace(0, cells_x, w, endpoint=False)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    a = g[y0][:, x0] * (1 - fx) + g[y0][:, x0 + 1] * fx
    b = g[y0 + 1][:, x0] * (1 - fx) + g[y0 + 1][:, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def _fbm(rng, h, w, cy, cx, octaves=3):
    out, amp, tot = np.zeros((h, w)), 1.0, 0.0
    for o in range(octaves):
        out += _noise(rng, h, w, cy * 2 ** o, cx * 2 ** o) * amp
        tot += amp
        amp *= 0.5
    return out / tot


def swatch_maps(name, px, seed=7):
    """(albedo sRGB h x w x 3, height h x w in 0..1, roughness, metal, tint-mask) for one cell. Row 0 = bottom (Blender's image order); s along x, t along y."""
    rng = np.random.default_rng(seed + SWATCH[name] * 101)
    h = w = px
    t = np.linspace(0, 1, h)[:, None] * np.ones((1, w))
    s = np.ones((h, 1)) * np.linspace(0, 1, w)[None, :]
    metal, mask = 0.0, 0.0

    def col(c, var):
        return np.clip(np.array(c)[None, None, :] * (1.0 + (var[..., None] - 0.5)), 0, 1)
    if name in ("wood", "wood_dark", "plank"):
        base = {"wood": (0.60, 0.46, 0.29), "wood_dark": (0.36, 0.26, 0.17), "plank": (0.72, 0.56, 0.35)}[name]
        grain = _fbm(rng, h, w, 3, 40) * 0.6 + _fbm(rng, h, w, 1, 6) * 0.4               # streaks along t (the handle's length)
        hgt = grain
        alb = col(base, 0.5 + (grain - 0.5) * 0.55)
        rough = 0.74 + 0.1 * grain
    elif name in ("iron", "steel"):
        base = (0.17, 0.17, 0.18) if name == "iron" else (0.50, 0.51, 0.53)
        nz = _fbm(rng, h, w, 14, 14)
        hgt = nz * 0.4
        alb = col(base, 0.5 + (nz - 0.5) * (0.5 if name == "iron" else 0.22))
        rough = (0.58 if name == "iron" else 0.36) + 0.16 * nz
        metal = 0.85
    elif name in ("straw", "kasa", "kasa_under"):
        fib = _fbm(rng, h, w, 2, 64, 2)                                                   # fibres along t
        base = {"straw": (0.74, 0.62, 0.36), "kasa": (0.79, 0.69, 0.42), "kasa_under": (0.66, 0.55, 0.33)}[name]
        hgt = fib.copy()
        var = 0.5 + (fib - 0.5) * 0.5
        if name != "straw":                                                                # concentric stitching rows across the fibres
            rows = 0.5 + 0.5 * np.cos(t * 2 * math.pi * 11)
            hgt = fib * 0.6 + rows * 0.4
            var = var - (rows < 0.12) * 0.16
        alb = col(base, var)
        rough = 0.86 + 0.0 * fib
    elif name == "rope":
        tw = 0.5 + 0.5 * np.sin((s * 9 + t * 22) * 2 * math.pi)
        nz = _fbm(rng, h, w, 20, 20, 2)
        hgt = tw * 0.8 + nz * 0.2
        alb = col((0.62, 0.52, 0.33), 0.5 + (tw - 0.5) * 0.35 + (nz - 0.5) * 0.2)
        rough = 0.9 + 0 * tw
    elif name == "bark":
        ridg = np.abs(_fbm(rng, h, w, 3, 22) - 0.5) * 2
        hgt = 1 - ridg
        alb = col((0.30, 0.23, 0.16), 0.5 + (hgt - 0.5) * 0.8)
        rough = 0.92 + 0 * ridg
    elif name == "log_end":
        r = np.hypot(s - 0.5, t - 0.5) * 2
        rings = 0.5 + 0.5 * np.cos((r + _fbm(rng, h, w, 4, 4) * 0.12) * 2 * math.pi * 9)
        hgt = rings * 0.3
        alb = col((0.74, 0.60, 0.38), 0.5 + (rings - 0.5) * 0.22 - (r - 0.5) * 0.12)
        rough = 0.8 + 0 * r
    elif name == "bamboo":
        nz = _fbm(rng, h, w, 2, 30, 2)
        node = np.minimum(np.abs(((t * 5) % 1.0) - 0.5) * 2, 1.0)                           # 0 at a node, 1 between
        ring = np.clip(1 - node * 14, 0, 1)
        hgt = 0.4 + 0.5 * ring + nz * 0.1
        alb = col((0.60, 0.63, 0.32), 0.5 + (nz - 0.5) * 0.25 - ring * 0.22)
        rough = 0.5 + 0.2 * ring
    elif name == "weave":
        a = np.sin(s * 2 * math.pi * 14)
        b = np.sin(t * 2 * math.pi * 14)
        chk = ((a > 0) ^ (b > 0)).astype(float)
        bump = np.abs(a) * chk + np.abs(b) * (1 - chk)
        nz = _fbm(rng, h, w, 12, 12, 2)
        hgt = bump
        alb = col((0.60, 0.48, 0.27), 0.5 + (bump - 0.5) * 0.45 + (nz - 0.5) * 0.2)
        rough = 0.86 + 0 * a
    elif name == "contents":
        cells = _fbm(rng, h, w, 9, 9, 2)
        lump = np.abs(cells - 0.5) * 2
        hgt = 1 - lump
        alb = col((0.80, 0.80, 0.80), 0.5 + (hgt - 0.5) * 0.5)
        rough = 0.85 + 0 * lump
        mask = 1.0
    elif name == "line":
        hgt = np.full((h, w), 0.5)
        alb = col((0.10, 0.09, 0.08), np.full((h, w), 0.5))
        rough = np.full((h, w), 0.7)
    else:                                                                                  # cloth
        wv = 0.5 + 0.25 * np.sin(s * 2 * math.pi * 40) + 0.25 * np.sin(t * 2 * math.pi * 40)
        hgt = wv
        alb = col((0.84, 0.81, 0.74), 0.5 + (wv - 0.5) * 0.12)
        rough = 0.9 + 0 * wv
    return alb.astype(np.float32), hgt.astype(np.float32), np.broadcast_to(np.asarray(rough, dtype=np.float32), (h, w)), metal, mask


def _srgb_to_lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def paint_strip(albedo_lin, normal, orm, px, strength=1.6):
    """Fill the prop strip of the three atlas arrays (h x w x 4, bottom-up; the albedo array holds display (sRGB) values, as an 8-bit Blender image does).
    Returns the tint mask (h x w) for the strip."""
    cell = px // COLS
    assert cell * ROWS <= int(px * STRIP_V) + 1, "the strip is too small for the swatch grid"
    mask = np.zeros((px, px), dtype=np.float32)
    for name, i in SWATCH.items():
        colx, row = i % COLS, i // COLS
        alb, hgt, rough, metal, mk = swatch_maps(name, cell)
        y0, x0 = row * cell, colx * cell
        albedo_lin[y0:y0 + cell, x0:x0 + cell, :3] = alb
        gy, gx = np.gradient(hgt)
        nx, ny = -gx * strength * (cell / 64.0), -gy * strength * (cell / 64.0)
        nz = np.ones_like(nx)
        ln = np.sqrt(nx * nx + ny * ny + nz * nz)
        normal[y0:y0 + cell, x0:x0 + cell, 0] = nx / ln * 0.5 + 0.5
        normal[y0:y0 + cell, x0:x0 + cell, 1] = ny / ln * 0.5 + 0.5
        normal[y0:y0 + cell, x0:x0 + cell, 2] = nz / ln * 0.5 + 0.5
        orm[y0:y0 + cell, x0:x0 + cell, 0] = np.clip(0.80 + 0.20 * hgt, 0, 1)
        orm[y0:y0 + cell, x0:x0 + cell, 1] = rough
        orm[y0:y0 + cell, x0:x0 + cell, 2] = metal
        mask[y0:y0 + cell, x0:x0 + cell] = mk
    return mask
