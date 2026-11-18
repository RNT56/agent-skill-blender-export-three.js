"""Banner emblems (mon): a signed-distance atlas the engine tints per faction.

The baked atlas carries NO emblem (the banner cloth is plain team colour). The engine draws the faction's mon over the cloth at runtime, so any number of factions
share one asset, one material and one draw call: it samples this sheet where the bind-pose position says "banner cloth" (see `banner` in emblems.json).

Sheet: 4 x 2 cells of 128 px, 8-bit grey. R = 0.5 on the edge of a design, > 0.5 inside, < 0.5 outside; one unit of value = `2 * spread` cell half-widths of
distance (the engine thresholds it with fwidth, so the edge stays crisp at any size). Pure python (no numpy, no Blender): `python3 -m samurai.emblems out_dir name`.

The designs are procedural silhouettes in the manner of kamon (crests); none is a historic clan's registered mon.
"""
import json
import math
import os
import struct
import zlib

CELL = 128
COLS, ROWS = 4, 2
SPREAD = 0.25                                # distance (cell half-widths) mapped to the full 0..1 range / 2
INK = (0.84, 0.80, 0.70)                     # sRGB of the mon: off-white dye


# ------------------------------------------------------------------------------------------------------------- signed distances (negative inside), p in -1..1, y up
def circle(p, r):
    return math.hypot(*p) - r


def ring(p, r, w):
    return abs(math.hypot(*p) - r) - w * 0.5


def box(p, hx, hy):
    dx, dy = abs(p[0]) - hx, abs(p[1]) - hy
    return math.hypot(max(dx, 0.0), max(dy, 0.0)) + min(max(dx, dy), 0.0)


def rhombus(p, hx, hy):
    return (abs(p[0]) * hy + abs(p[1]) * hx - hx * hy) / math.hypot(hx, hy)


def triangle(p, c, r):
    """Equilateral triangle pointing up, centre c, inradius r (max of the three edge half-planes)."""
    x, y = p[0] - c[0], p[1] - c[1]
    k = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
    return max(-y - r, x * k[0] + y * k[1] - r, -x * k[0] + y * k[1] - r)


def star5(p, r, rf):
    """Five-pointed star (Inigo Quilez's exact distance), outer radius r, inner ratio rf; one point up."""
    k1 = (0.809016994375, -0.587785252292)
    k2 = (-k1[0], k1[1])
    x, y = abs(p[0]), p[1]
    d = max(k1[0] * x + k1[1] * y, 0.0)
    x, y = x - 2.0 * d * k1[0], y - 2.0 * d * k1[1]
    d = max(k2[0] * x + k2[1] * y, 0.0)
    x, y = x - 2.0 * d * k2[0], y - 2.0 * d * k2[1]
    x = abs(x)
    y -= r
    ba = (rf * -k1[1] - 0.0, rf * k1[0] - 1.0)
    h = max(0.0, min(r, (x * ba[0] + y * ba[1]) / (ba[0] * ba[0] + ba[1] * ba[1])))
    s = math.hypot(x - ba[0] * h, y - ba[1] * h)
    return s if (y * ba[0] - x * ba[1]) > 0.0 else -s


def union(*d):
    return min(d)


def subtract(a, b):
    return max(a, -b)


def _maru(p):
    return union(ring(p, 0.74, 0.10), circle(p, 0.46))


def _mikazuki(p):
    return subtract(circle(p, 0.70), circle((p[0] - 0.24, p[1] - 0.10), 0.60))


def _kikyo(p):
    return star5(p, 0.80, 0.42)


def tomoe(p, theta, R=0.34, r=0.16, span=110.0):
    """One tomoe (comma): a round head on the circle of radius R at angle theta and a tail that tapers away from it, clockwise, over `span` degrees."""
    c, s = math.cos(-theta), math.sin(-theta)
    qx, qy = c * p[0] - s * p[1], s * p[0] + c * p[1]            # the head sits at angle 0
    head = math.hypot(qx - R, qy) - r
    a = math.atan2(qy, qx)
    A = math.radians(span)
    if -A <= a <= 0.0:
        return min(head, abs(math.hypot(qx, qy) - R) - r * (1.0 + a / A))
    return head


def _mitsu_domoe(p):
    return union(*[tomoe(p, math.radians(a), R=0.46, r=0.22, span=115.0) for a in (90.0, 210.0, 330.0)])


def _yotsume_bishi(p):
    return union(*[rhombus((p[0] - cx, p[1] - cy), 0.31, 0.31) for cx, cy in ((0.34, 0.0), (-0.34, 0.0), (0.0, 0.34), (0.0, -0.34))])


def _sanbon_suji(p):
    return union(*[box((p[0], p[1] - cy), 0.58, 0.10) for cy in (-0.30, 0.0, 0.30)])


def _maru_ni_juji(p):
    return union(ring(p, 0.74, 0.10), box(p, 0.54, 0.08), box(p, 0.08, 0.54))


def _yotsu_hana(p):
    return union(*[circle((p[0] - cx, p[1] - cy), 0.34) for cx, cy in ((0.34, 0.0), (-0.34, 0.0), (0.0, 0.34), (0.0, -0.34))])


DESIGNS = [("maru", _maru), ("mikazuki", _mikazuki), ("kikyo", _kikyo), ("mitsu-domoe", _mitsu_domoe),
           ("yotsume-bishi", _yotsume_bishi), ("sanbon-suji", _sanbon_suji), ("maru-ni-juji", _maru_ni_juji), ("yotsu-hana", _yotsu_hana)]


# ------------------------------------------------------------------------------------------------------------- sheet
def render():
    """Rows of bytes (ROWS * CELL rows of COLS * CELL grey values)."""
    rows = []
    for r in range(ROWS * CELL):
        cr, py = divmod(r, CELL)
        y = (CELL * 0.5 - (py + 0.5)) / (CELL * 0.5)              # up
        row = bytearray()
        for c in range(COLS):
            fn = DESIGNS[cr * COLS + c][1]
            for px in range(CELL):
                x = ((px + 0.5) - CELL * 0.5) / (CELL * 0.5)
                v = 0.5 - fn((x, y)) / (2.0 * SPREAD)
                row.append(max(0, min(255, int(round(v * 255.0)))))
        rows.append(bytes(row))
    return rows


def png_bytes(rows, width, height):
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def region():
    """Where the banner cloth is, in BIND-POSE mesh coordinates (Blender axes: x right, y back, z up; glTF axes: x, z, -y). The engine matches vertices against this."""
    from .consts import CLOTH_H, CLOTH_W, TOP, X0, YC
    zt = TOP - 0.004
    y0, y1 = YC + 0.0015 - 0.003, YC + 0.0045 + 0.003
    return {"blender": {"x0": round(X0, 4), "w": CLOTH_W, "z_top": round(zt, 4), "h": CLOTH_H, "y_min": round(y0, 4), "y_max": round(y1, 4)},
            "gltf": {"x0": round(X0, 4), "w": CLOTH_W, "y_top": round(zt, 4), "h": CLOTH_H, "z_min": round(-y1, 4), "z_max": round(-y0, 4)}}


def write(out_dir, base):
    """Write <base>_emblems.png and <base>_emblems.json into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    png = os.path.join(out_dir, f"{base}_emblems.png")
    with open(png, "wb") as fh:
        fh.write(png_bytes(render(), COLS * CELL, ROWS * CELL))
    meta = {"version": 1, "px": CELL, "cols": COLS, "rows": ROWS, "spread": SPREAD, "ink_srgb": list(INK), "names": [n for n, _ in DESIGNS],
            "banner": region(), "uv": "cell (c, r) origin = (c / cols, r / rows), v down, load with flipY = false; the emblem's u runs +x on the cloth's +y face (seen from behind the unit it is mirrored: flip u there)"}
    with open(os.path.join(out_dir, f"{base}_emblems.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    return png


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(write(sys.argv[1] if len(sys.argv) > 1 else ".", sys.argv[2] if len(sys.argv) > 2 else "samurai"))
