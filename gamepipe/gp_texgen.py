"""gp_texgen: procedural TILEABLE PBR texture sets (albedo / tangent normal / ORM) + automatic tileability checks.

Runs inside Blender's Python (numpy + bpy image saving), headless:
    blender -b --factory-startup -P gamepipe/gp_texgen.py -- specs/biomes.json [--out DIR]
    bin/gp textures specs/biomes.json

Tileability is by construction: spectral (FFT) noise and torus-wrapped Worley cells are periodic. The checker proves it.
Output per material: <name>_albedo.jpg (sRGB), <name>_normal.png (tangent, OpenGL +Y), <name>_orm.png (R=AO G=roughness B=metal),
plus out/textures/manifest.json (checks) and contact_sheet.jpg.

EXCEPTION: the rock / earth set (cliff_strata, granite, scree, red_clay, mossy_rock, basalt; specs/rocks.json) is non-metal, so its
ORM B channel carries the HEIGHT map (0..1, 1 = highest) instead of metalness, for height-based blending in the game. A material opts in
by returning orm_b="height" (see build_one). Everything else keeps B = 0.

All "albedo" colours below are display (sRGB) values chosen by eye, not measured; they are tuned to look vivid, not scanned.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


# ----------------------------------------------------------------------------- periodic primitives
def fbm(n, beta, rng, stretch=(1.0, 1.0), lo=None):
    """Periodic spectral noise in 0..1. beta ~ spectral slope (0.5 fine/grainy ... 3 smooth/cloudy). stretch elongates features:
    stretch=(1, 0.12) gives vertical streaks. lo: optional highpass cutoff (cycles)."""
    w = rng.standard_normal((n, n))
    fx = np.fft.fftfreq(n)[None, :] * n
    fy = np.fft.fftfreq(n)[:, None] * n
    f = np.sqrt((fx * stretch[0]) ** 2 + (fy * stretch[1]) ** 2)
    f[0, 0] = 1.0
    spec = np.fft.fft2(w) / np.maximum(f, 1.0) ** (beta / 2.0)
    if lo:
        spec *= np.clip(f / lo, 0, 1)
    spec[0, 0] = 0
    a = np.real(np.fft.ifft2(spec))
    p1, p99 = np.percentile(a, 1), np.percentile(a, 99)
    return np.clip((a - p1) / max(p99 - p1, 1e-9), 0, 1).astype(np.float32)


def blur(a, sigma):
    """Periodic gaussian blur via FFT."""
    n = a.shape[0]
    fx = np.fft.fftfreq(n)[None, :]
    fy = np.fft.fftfreq(n)[:, None]
    g = np.exp(-2 * (np.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * g)).astype(np.float32)


def worley(n, cells, rng, warp=None, jitter=0.9):
    """Periodic Worley noise. Returns (d1, d2, cell_id[0..1]) in cell units. warp: optional (wx, wy) pixel-space domain warp (0..1 noise)."""
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    u = xs / n * cells
    v = ys / n * cells
    if warp is not None:
        u = (u + (warp[0] - 0.5) * warp[2]) % cells
        v = (v + (warp[1] - 0.5) * warp[2]) % cells
    cx, cy = np.floor(u).astype(int), np.floor(v).astype(int)
    px = rng.random((cells, cells)).astype(np.float32)
    py = rng.random((cells, cells)).astype(np.float32)
    ids = rng.random((cells, cells)).astype(np.float32)
    d1 = np.full((n, n), 9.0, np.float32)
    d2 = np.full((n, n), 9.0, np.float32)
    cid = np.zeros((n, n), np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            gx, gy = (cx + dx) % cells, (cy + dy) % cells
            fx_ = cx + dx + 0.5 + (px[gy, gx] - 0.5) * jitter
            fy_ = cy + dy + 0.5 + (py[gy, gx] - 0.5) * jitter
            # torus-wrapped distance (cells are periodic because gx,gy wrap; fx_ is in unwrapped space relative to this pixel's cell)
            d = np.sqrt((u - fx_) ** 2 + (v - fy_) ** 2)
            closer = d < d1
            d2 = np.where(closer, d1, np.minimum(d2, d))
            cid = np.where(closer, ids[gy, gx], cid)
            d1 = np.where(closer, d, d1)
    return d1, d2, cid


def smooth(a, e0, e1):
    t = np.clip((a - e0) / max(e1 - e0, 1e-9), 0, 1)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    t = t[..., None] if np.ndim(t) == 2 else t
    return a + (b - a) * t


def col(*c):
    return np.array(c, np.float32)


# ----------------------------------------------------------------------------- maps from height
def normal_from_height(h, strength, slope=None):
    """slope: optional extra analytic surface slope (n,n,2) = (dz/dx, dz/dy_up) in output units, added to the height-derived one.
    Lets planar facets (rock faces, fragment tops) tilt visibly without absurd height ranges."""
    dhdx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    dhdy_up = (np.roll(h, 1, 0) - np.roll(h, -1, 0)) * 0.5      # image row 0 is up
    nx, ny, nz = -dhdx * strength, -dhdy_up * strength, np.ones_like(h)
    if slope is not None:
        nx, ny = nx - slope[..., 0], ny - slope[..., 1]
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5


def ao_from_height(h, radius, k):
    return np.clip(1.0 - np.clip(blur(h, radius) - h, 0, None) * k, 0.25, 1.0)


# ----------------------------------------------------------------------------- materials
# Each returns dict(albedo[n,n,3], height[n,n], rough[n,n], ao_k=(radius,k), nstrength)
def mat_meadow(n, rng):
    blades = fbm(n, 0.9, rng, stretch=(1.0, 0.10))
    fine = fbm(n, 0.35, rng)
    patch = fbm(n, 2.6, rng)
    t = np.clip(0.55 * blades + 0.45 * fine, 0, 1)
    a = lerp(col(0.05, 0.19, 0.03), col(0.17, 0.47, 0.06), smooth(t, 0.15, 0.6))
    a = lerp(a, col(0.46, 0.72, 0.13), smooth(t, 0.62, 0.95) * 0.9)
    a = lerp(a, col(0.55, 0.60, 0.10), smooth(patch, 0.62, 0.9) * 0.55)       # sun-dried patches
    d1, d2, cid = worley(n, 70, rng)                                           # clover/daisies
    flower = (cid > 0.965) & (d1 < 0.16)
    a = np.where(flower[..., None], lerp(col(0.95, 0.94, 0.75), col(0.98, 0.85, 0.25), (cid * 997 % 1.0)), a)
    clover = (cid > 0.8) & (d1 < 0.30) & ~flower
    a = np.where(clover[..., None], a * 0.8 + col(0.0, 0.10, 0.0), a)
    return dict(albedo=a, height=0.6 * blades + 0.4 * fine, rough=0.80 - 0.15 * t, ao=(6, 5.0), ns=2.2)


def mat_dry_grass(n, rng):
    blades = fbm(n, 0.9, rng, stretch=(1.0, 0.10))
    fine = fbm(n, 0.35, rng)
    patch = fbm(n, 2.4, rng)
    t = np.clip(0.55 * blades + 0.45 * fine, 0, 1)
    a = lerp(col(0.20, 0.13, 0.04), col(0.58, 0.40, 0.12), smooth(t, 0.1, 0.6))
    a = lerp(a, col(0.86, 0.70, 0.34), smooth(t, 0.6, 0.95) * 0.85)
    a = lerp(a, col(0.30, 0.38, 0.08), smooth(patch, 0.7, 0.95) * 0.5)        # surviving green
    return dict(albedo=a, height=0.6 * blades + 0.4 * fine, rough=0.88 - 0.1 * t, ao=(6, 5.0), ns=2.0)


def mat_forest_floor(n, rng):
    soil = fbm(n, 2.0, rng)
    warp = (fbm(n, 2.5, rng), fbm(n, 2.5, rng), 1.6)
    d1, d2, cid = worley(n, 26, rng, warp=warp)
    leaf = d1 < (0.30 + 0.25 * fbm(n, 1.5, rng))                                # cell blob = leaf
    palette = np.array([[0.72, 0.28, 0.05], [0.82, 0.50, 0.08], [0.55, 0.14, 0.05], [0.62, 0.40, 0.09], [0.30, 0.17, 0.05]], np.float32)
    pc = palette[(cid * 4.999).astype(int)] * (0.75 + 0.5 * fbm(n, 0.6, rng)[..., None])
    base = lerp(col(0.05, 0.03, 0.02), col(0.14, 0.09, 0.05), soil)
    moss = smooth(fbm(n, 3.0, rng), 0.62, 0.85)
    base = lerp(base, col(0.10, 0.28, 0.06), moss * 0.8)
    a = np.where(leaf[..., None], pc, base)
    veins = np.abs(d2 - d1) < 0.04
    a = np.where((veins & leaf)[..., None], a * 0.6, a)
    twig = fbm(n, 1.2, rng, stretch=(1.0, 0.04))
    a = np.where((np.abs(twig - 0.5) < 0.012)[..., None], col(0.09, 0.06, 0.04), a)
    h = np.where(leaf, 0.55 + 0.4 * (1 - np.clip(d1 / 0.5, 0, 1)), 0.25 * soil)
    return dict(albedo=a, height=h, rough=np.where(leaf, 0.65, 0.95), ao=(5, 6.0), ns=3.0)


def mat_rocky_gravel(n, rng):
    warp = (fbm(n, 2.2, rng), fbm(n, 2.2, rng), 0.5)
    d1, d2, cid = worley(n, 40, rng, warp=warp, jitter=0.95)
    edge = d2 - d1
    palette = np.array([[0.42, 0.40, 0.37], [0.55, 0.50, 0.42], [0.33, 0.35, 0.38], [0.62, 0.58, 0.50], [0.47, 0.37, 0.30], [0.25, 0.25, 0.26]], np.float32)
    pc = palette[(cid * 5.999).astype(int)] * (0.8 + 0.4 * fbm(n, 0.7, rng)[..., None])
    sand = lerp(col(0.36, 0.31, 0.24), col(0.52, 0.45, 0.35), fbm(n, 1.2, rng))
    stone = smooth(edge, 0.02, 0.22)
    a = lerp(sand, pc, stone[..., None] if np.ndim(stone) == 2 else stone)
    h = stone * (0.6 + 0.4 * (1 - np.clip(d1 / 0.7, 0, 1))) + 0.05 * fbm(n, 0.5, rng)
    return dict(albedo=a, height=h, rough=0.9 - 0.25 * stone, ao=(4, 6.0), ns=4.0)


def mat_dirt_road(n, rng):
    soil = fbm(n, 2.2, rng)
    fine = fbm(n, 0.5, rng)
    a = lerp(col(0.27, 0.17, 0.10), col(0.46, 0.32, 0.20), np.clip(0.6 * soil + 0.4 * fine, 0, 1))
    a = lerp(a, col(0.58, 0.47, 0.34), smooth(fbm(n, 2.8, rng), 0.7, 0.95) * 0.6)    # dry dusty patches
    d1, d2, cid = worley(n, 60, rng)
    peb = (cid > 0.82) & (d1 < 0.28)
    a = np.where(peb[..., None], lerp(col(0.40, 0.37, 0.33), col(0.58, 0.52, 0.44), cid * 3 % 1.0), a)
    h = 0.5 * fine + 0.3 * soil + np.where(peb, 0.5 * (1 - d1 / 0.28), 0)
    return dict(albedo=a, height=h, rough=0.93, ao=(4, 5.0), ns=2.5)


def mat_sakura(n, rng):
    soil = fbm(n, 2.0, rng)
    a = lerp(col(0.07, 0.05, 0.04), col(0.17, 0.13, 0.09), soil)
    moss = smooth(fbm(n, 3.0, rng), 0.55, 0.85)
    a = lerp(a, col(0.12, 0.34, 0.07), moss * 0.85)
    h = 0.2 * soil
    petal = np.zeros((n, n), bool)
    pc = np.zeros((n, n, 3), np.float32)
    for k, cells in enumerate((60, 95, 140)):                                     # three petal scales
        warp = (fbm(n, 1.8, rng), fbm(n, 1.8, rng), 0.35)
        d1, d2, cid = worley(n, cells, rng, warp=warp)
        m = (cid > 0.35) & (d1 < 0.34 - 0.04 * k)
        tone = lerp(col(1.0, 0.76, 0.85), col(0.93, 0.50, 0.66), (cid * 31 % 1.0))
        tone = tone * (0.85 + 0.25 * (1 - d1[..., None] / 0.4))
        pc = np.where(m[..., None], tone, pc)
        h = np.where(m, 0.4 + 0.12 * k, h)
        petal |= m
    a = np.where(petal[..., None], pc, a)
    return dict(albedo=a, height=h, rough=np.where(petal, 0.55, 0.92), ao=(4, 5.0), ns=2.0)


def mat_zen_gravel(n, rng):
    grain = fbm(n, 0.3, rng)
    wob = fbm(n, 2.5, rng)
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    rake = np.sin(2 * np.pi * (xs / n * 28 + 0.8 * (wob - 0.5)))               # raked furrows (vertical lines)
    base = lerp(col(0.58, 0.56, 0.52), col(0.80, 0.78, 0.72), grain)
    a = base * (0.90 + 0.10 * rake[..., None])
    d1, d2, cid = worley(n, 110, rng)
    peb = (cid > 0.7) & (d1 < 0.3)
    a = np.where(peb[..., None], a * (0.7 + 0.5 * (cid * 13 % 1.0))[..., None], a)
    return dict(albedo=a, height=0.5 + 0.30 * rake + 0.2 * grain, rough=0.95, ao=(3, 5.0), ns=3.0)


def mat_stone_wall(n, rng):
    """Ishigaki: dry-laid granite in rough courses (running bond, irregular block widths, warped edges)."""
    wu, wv = fbm(n, 2.4, rng), fbm(n, 2.4, rng)
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    rows = 5
    v = ((ys / n + (wv - 0.5) * 0.035) % 1.0) * rows
    u = ((xs / n + (wu - 0.5) * 0.04) % 1.0)
    row = np.floor(v).astype(int) % rows
    vf = v - np.floor(v)
    d_row = np.minimum(vf, 1 - vf) / rows * 1.0                                   # distance to course joint (0..0.1)
    cid = np.zeros((n, n), np.float32)
    d_col = np.full((n, n), 9.0, np.float32)
    for r in range(rows):
        k = int(rng.integers(3, 5))
        cuts = np.sort(rng.random(k))
        cuts = np.concatenate([cuts, [cuts[0] + 1.0]])                            # periodic
        ids = rng.random(k).astype(np.float32)
        m = row == r
        uu = u[m]
        best = np.full(uu.shape, 9.0, np.float32)
        bid = np.zeros(uu.shape, np.float32)
        for i in range(k):
            lo, hi = cuts[i], cuts[i + 1]
            inside = ((uu - lo) % 1.0) < (hi - lo)
            dist = np.minimum((uu - lo) % 1.0, (hi - uu) % 1.0)
            bid = np.where(inside, ids[i], bid)
            best = np.where(inside, np.minimum(dist, 9.0), best)
        cid[m] = bid
        d_col[m] = best
    edge = np.minimum(d_row * 1.6, d_col * 0.9)                                   # shared "distance to nearest joint"
    block = smooth(edge, 0.002, 0.013)
    bevel = smooth(edge, 0.0, 0.10)
    surf = fbm(n, 1.6, rng)
    fine = fbm(n, 0.5, rng)
    tone = 0.34 + 0.26 * ((cid * 17.3) % 1.0)
    a = (tone[..., None] * (0.80 + 0.32 * surf[..., None]) * (0.92 + 0.16 * fine[..., None])) * col(1.0, 0.98, 0.94)
    a = a + ((cid * 7.7) % 1.0)[..., None] * col(-0.02, 0.0, 0.03)
    lichen = smooth(fbm(n, 2.8, rng), 0.66, 0.88)
    a = lerp(a, col(0.40, 0.46, 0.22), lichen * 0.5)
    a = lerp(col(0.05, 0.045, 0.04), a, block)                                    # dark joints
    h = block * (0.5 + 0.5 * bevel) + 0.12 * surf + 0.06 * fine
    return dict(albedo=a, height=h, rough=0.92, ao=(7, 7.0), ns=6.0)


def mat_plaster(n, rng):
    """Shikkui white plaster: warm off-white, trowel marks, water stains, hairline cracks."""
    stain = fbm(n, 2.6, rng)
    trowel = fbm(n, 1.4, rng, stretch=(0.35, 1.0))
    fine = fbm(n, 0.5, rng)
    a = lerp(col(0.80, 0.78, 0.72), col(0.92, 0.90, 0.84), trowel)
    a = a * (0.94 + 0.10 * fine[..., None])
    a = lerp(a, col(0.58, 0.54, 0.46), smooth(stain, 0.62, 0.95) * 0.6)
    crack = fbm(n, 1.9, rng)
    cr = np.abs(crack - 0.5) < 0.006
    a = np.where(cr[..., None], a * 0.55, a)
    h = 0.35 * trowel + 0.2 * fine - cr * 0.4
    return dict(albedo=a, height=h, rough=0.88, ao=(5, 3.0), ns=1.4)


def mat_wood_dark(n, rng):
    """Aged/charred cedar, vertical planks."""
    planks = 6
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    px = xs / n * planks
    pid = np.floor(px).astype(int) % planks
    pf = px - np.floor(px)
    gap = smooth(np.minimum(pf, 1 - pf), 0.0, 0.035)
    grain = fbm(n, 1.1, rng, stretch=(1.0, 0.04))
    ring = np.sin(2 * np.pi * (grain * 9.0 + pf * 0.7))
    rnd = rng.random(planks).astype(np.float32)
    tone = 0.55 + 0.45 * rnd[pid]
    knot = smooth(fbm(n, 2.0, rng), 0.82, 0.95)
    a = lerp(col(0.06, 0.04, 0.03), col(0.40, 0.27, 0.16), np.clip(0.45 * grain + 0.35 * (0.5 + 0.5 * ring) + 0.20 * tone, 0, 1) ** 1.3)
    a = a * (0.80 + 0.4 * tone[..., None]) * (1 - 0.45 * knot[..., None])
    a = a * (0.35 + 0.65 * gap[..., None])
    h = gap * (0.6 + 0.2 * grain + 0.1 * ring)
    return dict(albedo=a, height=h, rough=0.72, ao=(4, 6.0), ns=3.0)


def mat_roof_tile(n, rng):
    """Kawara: charcoal glazed tiles; wide concave pans between narrow half-round covers (maru), lapped rows."""
    cols, rows = 8, 8
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    u = xs / n * cols
    v = ys / n * rows
    uf, vf = u - np.floor(u), v - np.floor(v)
    cell = (np.floor(u).astype(int) % cols) * 31 + (np.floor(v).astype(int) % rows) * 17
    hrand = ((np.sin(cell * 12.9898) * 43758.5453) % 1.0).astype(np.float32)
    cover = smooth(1 - np.abs(uf - 0.5) * 2, 0.72, 0.95)                         # narrow convex cover along the joint
    pan = 0.5 - 0.5 * np.cos(2 * np.pi * uf)
    lap = vf ** 1.8
    h = 0.5 * cover + 0.22 * (1 - pan) * (1 - cover) + 0.38 * lap
    rim = np.clip(cover * (1 - cover) * 4, 0, 1)
    base = lerp(col(0.09, 0.10, 0.12), col(0.22, 0.24, 0.28), 0.55 * hrand + 0.45 * fbm(n, 0.7, rng))
    a = lerp(base, col(0.42, 0.46, 0.52), smooth(h, 0.62, 0.98) * 0.55)          # silver glaze on the high spots
    a = a + (cover * 0.06 + rim * 0.10)[..., None]
    streak = fbm(n, 1.8, rng, stretch=(1.0, 0.2))
    a = lerp(a, col(0.12, 0.21, 0.08), smooth(streak, 0.70, 0.92) * (1 - cover) * 0.6)
    a = a * (0.50 + 0.50 * smooth(vf, 0.0, 0.20)[..., None])                     # shadow under the overlapping row
    return dict(albedo=a, height=h, rough=0.40 + 0.25 * (1 - smooth(h, 0.5, 0.95)), ao=(6, 8.0), ns=6.0)


def mat_thatch(n, rng):
    """Kayabuki straw thatch: horizontal courses of bundled straw, strands running down-slope (image Y), moss on old thatch."""
    courses = 7
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    v = ys / n * courses
    vf = v - np.floor(v)
    cid = np.floor(v).astype(int) % courses
    tone = rng.random(courses).astype(np.float32)[cid]
    strands = fbm(n, 0.8, rng, stretch=(1.0, 0.035))
    fine = fbm(n, 0.4, rng, stretch=(1.0, 0.12))
    patch = fbm(n, 2.4, rng)
    base = lerp(col(0.24, 0.16, 0.07), col(0.74, 0.57, 0.27), np.clip(0.55 * strands + 0.45 * fine, 0, 1))
    a = base * (0.76 + 0.38 * tone[..., None])
    a = lerp(a, col(0.32, 0.38, 0.12), smooth(patch, 0.66, 0.9) * 0.5)
    a = a * (0.50 + 0.50 * smooth(vf, 0.0, 0.22)[..., None])                 # shadow under each overlapping course
    h = 0.5 * strands + 0.25 * fine + 0.7 * vf ** 1.3
    return dict(albedo=a, height=h, rough=0.96, ao=(6, 7.0), ns=4.0)


def mat_wood_light(n, rng):
    """Weathered pale cedar, vertical boards (teahouse veranda / railings)."""
    planks = 5
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    px = xs / n * planks
    pid = np.floor(px).astype(int) % planks
    pf = px - np.floor(px)
    gap = smooth(np.minimum(pf, 1 - pf), 0.0, 0.03)
    grain = fbm(n, 1.1, rng, stretch=(1.0, 0.04))
    ring = np.sin(2 * np.pi * (grain * 8.0 + pf * 0.6))
    tone = (0.5 + 0.5 * rng.random(planks).astype(np.float32))[pid]
    weather = fbm(n, 2.4, rng)
    a = lerp(col(0.26, 0.19, 0.13), col(0.66, 0.53, 0.38), np.clip(0.45 * grain + 0.3 * (0.5 + 0.5 * ring) + 0.25 * tone, 0, 1))
    a = lerp(a, col(0.55, 0.52, 0.47), smooth(weather, 0.6, 0.9) * 0.45)       # silvering
    a = a * (0.35 + 0.65 * gap[..., None])
    return dict(albedo=a, height=gap * (0.6 + 0.2 * grain + 0.1 * ring), rough=0.8, ao=(4, 6.0), ns=3.0)


# ----------------------------------------------------------------------------- rock / earth set (specs/rocks.json)
# CONVENTION (differs from every material above): these six are NON-metals, so ORM.B holds the HEIGHT map (0..1, 1 = highest, min-max
# normalised) for height-based blending in the game, NOT metalness. ORM.R = AO (strong in cracks/ledges), ORM.G = roughness (0.6-0.95).
# Normals are generated from a slightly more detailed height than the exported one (key "nheight") so relief reads under grazing light.
# Authoring notes: all widths are fractions of the tile (resolution independent: the 256px test and the 1024px build look alike).
# fbm(stretch=(sx, sy)): the SMALL axis gets the fine detail, so (1, 0.1) = features long in X (horizontal streaks) and
# (0.1, 1) = features long in Y (vertical streaks / rain runnels).
# Albedo is limited to luminance 0.08..0.75 with a smooth knee (_limit_lum), hue preserved.
def _grid(n):
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    return xs / n, ys / n


def _sfbm(n, beta, rng, stretch=(1.0, 1.0), lo=None):
    """fbm as signed noise (-1..1)."""
    return fbm(n, beta, rng, stretch, lo) * 2.0 - 1.0


def _norm01(a, lo=0.5, hi=99.5):
    p0, p1 = np.percentile(a, lo), np.percentile(a, hi)
    return np.clip((a - p0) / max(p1 - p0, 1e-9), 0, 1).astype(np.float32)


def _wf(n, rng, rough=0.22):
    """Domain-warp field in 0..1: a SMOOTH large-scale part (fbm beta 4.2 is differentiable; beta <= 3 is far too rough to use as a
    displacement) plus a small rough part for jagged, natural-looking edges."""
    return (1.0 - rough) * fbm(n, 4.2, rng) + rough * fbm(n, 2.4, rng)


def _wsample(a, u, v):
    """Periodic bilinear sample of a 2-D image at tile coordinates (u, v) (1.0 = one tile): domain warping that keeps the tile seamless."""
    n = a.shape[0]
    x, y = u * n, v * n
    x0, y0 = np.floor(x), np.floor(y)
    fx, fy = (x - x0).astype(np.float32), (y - y0).astype(np.float32)
    x0, y0 = x0.astype(int) % n, y0.astype(int) % n
    x1, y1 = (x0 + 1) % n, (y0 + 1) % n
    return (a[y0, x0] * (1 - fx) + a[y0, x1] * fx) * (1 - fy) + (a[y1, x0] * (1 - fx) + a[y1, x1] * fx) * fy


def ss1(a, e0=-0.5, e1=0.5):
    """smoothstep for 1-D profiles (scalar edges)."""
    t = np.clip((a - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def _ss(a, e0, e1):
    """smoothstep that also accepts array edges (smooth() takes scalars only)."""
    t = np.clip((a - e0) / np.maximum(e1 - e0, 1e-9), 0, 1)
    return t * t * (3 - 2 * t)


def _pdist(a, b):
    """Periodic distance on the unit circle."""
    return np.abs(((a - b + 0.5) % 1.0) - 0.5)


def _vor(n, cx, cy, rng, warp=None, jitter=0.9):
    """Periodic Voronoi with proper border distance. cx, cy = cells across / down (they may differ -> elongated cells).
    warp = (wx, wy, amp): 0..1 noise fields, displacement amp in cell units. Returns dict:
    d1 (distance to nearest feature), edge (distance to the nearest cell border, cell units), id (0..1 random per cell),
    lx, ly (pixel - feature point, cell units: local coordinates for per-cell facets)."""
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    u = xs / n * cx
    v = ys / n * cy
    if warp is not None:
        u = (u + (warp[0] - 0.5) * warp[2]) % cx
        v = (v + (warp[1] - 0.5) * warp[2]) % cy
    ix, iy = np.floor(u).astype(int), np.floor(v).astype(int)
    px = rng.random((cy, cx)).astype(np.float32)
    py = rng.random((cy, cx)).astype(np.float32)
    ids = rng.random((cy, cx)).astype(np.float32)
    d1 = np.full((n, n), 99.0, np.float32)
    d2 = np.full((n, n), 99.0, np.float32)
    f1x = np.zeros((n, n), np.float32)
    f1y = np.zeros((n, n), np.float32)
    f2x = np.zeros((n, n), np.float32)
    f2y = np.zeros((n, n), np.float32)
    cid = np.zeros((n, n), np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            gx, gy = (ix + dx) % cx, (iy + dy) % cy
            fx_ = ix + dx + 0.5 + (px[gy, gx] - 0.5) * jitter
            fy_ = iy + dy + 0.5 + (py[gy, gx] - 0.5) * jitter
            d = np.sqrt((u - fx_) ** 2 + (v - fy_) ** 2)
            c1 = d < d1
            c2 = ~c1 & (d < d2)
            d2 = np.where(c1, d1, np.where(c2, d, d2))
            f2x = np.where(c1, f1x, np.where(c2, fx_, f2x))
            f2y = np.where(c1, f1y, np.where(c2, fy_, f2y))
            cid = np.where(c1, ids[gy, gx], cid)
            f1x = np.where(c1, fx_, f1x)
            f1y = np.where(c1, fy_, f1y)
            d1 = np.where(c1, d, d1)
    sep = np.sqrt((f2x - f1x) ** 2 + (f2y - f1y) ** 2)
    edge = (d2 * d2 - d1 * d1) / np.maximum(2.0 * sep, 1e-6)
    return dict(d1=d1, edge=edge, id=cid, lx=u - f1x, ly=v - f1y)


def _limit_lum(a, lo=0.08, hi=0.75, knee=0.02):
    """Keep per-pixel luminance inside lo..hi with a smooth knee, preserving hue."""
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    t = np.maximum(lum, 1e-4)
    t = lo + knee * np.log1p(np.exp((t - lo) / knee))              # smooth max(lum, lo)
    t = hi - knee * np.log1p(np.exp((hi - t) / knee))              # smooth min(lum, hi)
    return np.clip(a * (t / np.maximum(lum, 1e-4))[..., None], 0, 1)


def _vcavity(h, r, k):
    """Cavity AO: how far a pixel sits below its blurred neighbourhood (r = blur sigma as a fraction of the tile)."""
    n = h.shape[0]
    return np.clip(blur(h, max(r * n, 0.6)) - h, 0, None) * k


def _tone(a, t, amt):
    """Multiply colour by (1 + amt*(t-0.5)*2) for t in 0..1."""
    return a * (1.0 + amt * (t[..., None] * 2.0 - 1.0))


def mat_cliff_strata(n, rng):
    """Sedimentary cliff face (the main cliff material). Horizontal beds of different thickness and colour (ochre / warm brown / grey /
    rust) that undulate and pinch out along X; hard beds protrude and shade the softer bed below their lower edge; master vertical
    joints (offset bed to bed) plus per-bed joints break every bed into blocks; rain stains run down; thin moss and lichen sit in the
    joints and on ledges. ORM: R = AO (cracks, ledge undersides), G = roughness 0.7-0.95, B = HEIGHT (0..1), NOT metalness."""
    X, Y = _grid(n)
    px = n / 1024.0
    xi = np.arange(n)[None, :]
    # ---- bed geometry: boundaries b_i(x) = base_i + shared tilt + own wobble, sorted per column so beds can pinch out (lens shapes)
    nb = 21
    w = np.minimum(np.exp(rng.normal(0.0, 0.70, nb - 1)), 2.3)
    w = w / w.sum() * 0.92
    base = 0.04 + np.concatenate([[0.0], np.cumsum(w)])                              # nb boundaries inside 0.04..0.96 (wrap bed = rest)
    shared = _sfbm(n, 3.4, rng)[0]                                                    # one smooth 1D profile along x (any row is periodic)
    shared = shared / max(np.abs(shared).max(), 1e-6)
    B = np.empty((nb, n), np.float32)
    for i in range(nb):
        own = _sfbm(n, 2.8, rng)[int(rng.integers(0, n))]
        own = own / max(np.abs(own).max(), 1e-6)
        B[i] = base[i] + 0.014 * shared + (0.004 + 0.010 * rng.random()) * own
    B = np.sort(B, axis=0)
    rag = _sfbm(n, 2.6, rng) * 0.0018 + _sfbm(n, 1.6, rng) * 0.0003                  # slightly chipped bed edges
    s = (Y + rag) % 1.0
    cnt = np.zeros((n, n), np.int32)
    for i in range(nb):
        cnt += (s >= B[i][None, :])
    prev_i = (cnt - 1) % nb
    next_i = cnt % nb
    top = np.where(cnt >= 1, B[prev_i, xi], B[nb - 1][None, :] - 1.0)
    bot = np.where(cnt < nb, B[next_i, xi], B[0][None, :] + 1.0)
    bed = prev_i
    above = (bed - 1) % nb
    below = (bed + 1) % nb
    thick = np.maximum(bot - top, 1e-4)
    t = np.clip((s - top) / thick, 0, 1)                                              # 0 at bed top .. 1 at bed bottom
    d_top = np.maximum(s - top, 0)
    d_bot = np.maximum(bot - s, 0)
    # ---- bed properties: muted palette (ochre, warm brown, grey, rust, pale sandstone, dark mudstone)
    pal = np.array([[0.60, 0.48, 0.30], [0.64, 0.54, 0.39], [0.44, 0.34, 0.25], [0.35, 0.28, 0.22], [0.47, 0.45, 0.42],
                    [0.41, 0.39, 0.37], [0.52, 0.32, 0.20], [0.56, 0.41, 0.27]], np.float32)
    pw = np.array([0.21, 0.15, 0.16, 0.03, 0.12, 0.05, 0.08, 0.20])
    cidx = np.zeros(nb, int)
    for i in range(nb):
        while True:
            c = int(rng.choice(len(pal), p=pw / pw.sum()))
            if i == 0 or c != cidx[i - 1]:
                break
        cidx[i] = c
    pal = pal * 0.88 + (pal @ np.array([0.2126, 0.7152, 0.0722], np.float32))[:, None] * 0.12    # pull toward grey a little
    tint = rng.uniform(0.93, 1.07, nb).astype(np.float32)
    cidx2 = np.array([int(rng.choice(len(pal), p=pw / pw.sum())) for _ in range(nb)])           # second colour: beds drift along x
    hard = np.clip(0.2 + 0.8 * rng.random(nb) ** 0.9, 0, 1).astype(np.float32)
    hard[[1, 5, 9, 13, 17]] = 1.0                                                      # a few massive cliff-forming beds
    prot = (0.08 + 0.52 * hard).astype(np.float32)
    grade = (rng.random(nb) < 0.5).astype(np.float32)                                 # gradational (vs sharp) upper contact
    seamk = rng.uniform(0.3, 1.0, nb).astype(np.float32)
    nz1 = fbm(n, 2.6, rng, stretch=(1.0, 0.5))
    P = prot[bed] + 0.07 * (nz1 - 0.5) * 2
    step_above = prot[above] - prot[bed] + 0.40 * (fbm(n, 2.4, rng, stretch=(1.0, 0.5)) - 0.5)   # >0: bed above overhangs this one
    # ---- vertical joints: master set (offset bed to bed) + per-bed subdivisions, all in tile units, wobbled by xw
    K = 12
    master = np.sort(rng.random(6))
    J = np.full((nb, K), 9.0, np.float32)
    Jopen = rng.random((nb, K)).astype(np.float32) ** 1.5
    nj = np.zeros(nb, int)
    for i in range(nb):
        pos = [m_ + rng.normal(0, 0.009) for m_ in master if rng.random() < 0.75]
        gmax = float(np.clip((B[min(i + 1, nb - 1), 0] - B[i, 0]) * rng.uniform(3.0, 6.0), 0.12, 0.32))
        pos = sorted(p_ % 1.0 for p_ in pos)
        if not pos:
            pos = [float(rng.random())]
        for _ in range(10):
            gaps = [((pos[(k + 1) % len(pos)] - pos[k]) % 1.0) or 1.0 for k in range(len(pos))]
            k = int(np.argmax(gaps))
            if gaps[k] <= gmax or len(pos) >= K:
                break
            pos.append((pos[k] + gaps[k] * rng.uniform(0.35, 0.65)) % 1.0)
            pos = sorted(pos)
        J[i, :len(pos)] = pos
        nj[i] = len(pos)
    Jfirst = J[:, 0]
    Jlast = np.array([J[i, nj[i] - 1] for i in range(nb)], np.float32)
    wob = _sfbm(n, 2.6, rng) * 0.006 + _sfbm(n, 1.4, rng) * 0.0012
    xw = (X + wob) % 1.0
    left = np.full((n, n), -9.0, np.float32)
    right = np.full((n, n), 9.0, np.float32)
    lk = np.zeros((n, n), np.int32)
    for k in range(K):
        jk = J[bed, k]
        ok = jk <= xw
        upd = ok & (jk > left)
        left = np.where(upd, jk, left)
        lk = np.where(upd, k, lk)
        right = np.where((~ok) & (jk < right), jk, right)
    wrap_l = left < -8
    left = np.where(wrap_l, Jlast[bed] - 1.0, left)
    lk = np.where(wrap_l, nj[bed] - 1, lk)
    right = np.where(right > 8, Jfirst[bed] + 1.0, right)
    dl, dr = xw - left, right - xw
    dj = np.minimum(dl, dr)                                                            # distance to nearest joint (tile units)
    bw = np.maximum(right - left, 1e-3)
    ul = dl / bw                                                                       # 0..1 across the block
    rb = rng.random((nb, K, 4)).astype(np.float32)
    rbk = rb[bed, lk]                                                                  # per-block randoms
    opn = np.where(dl < dr, Jopen[bed, lk], Jopen[bed, (lk + 1) % np.maximum(nj[bed], 1)])   # openness of the nearest joint
    cw = fbm(n, 1.8, rng)
    wc = (0.0005 + 0.0016 * opn) * (0.6 + 0.9 * cw)                                    # joint half width: tight hairlines..open gaps
    crack = 1.0 - _ss(dj, wc * 0.4, wc * 1.5)
    near = 1.0 - _ss(dj, wc * 0.5, 0.0035 + 0.006 * opn)                               # joint neighbourhood (moss/lichen/stain)
    # ---- shading from ledges
    ss = np.clip(step_above, 0, 1)
    ledge_shadow = ss * np.exp(-d_top / (0.008 + 0.028 * ss))
    shelf = np.clip(-step_above, 0, 1) * np.exp(-d_top / 0.005)                        # lit flat top of a bed that sticks out
    undercut = np.clip(prot[bed] - prot[below], 0, 1) * np.exp(-d_bot / 0.010)         # dark underside of a protruding bed
    seam = np.exp(-d_top / 0.0016) * seamk[bed]                                        # bedding-plane hairline
    # ---- height
    face = fbm(n, 2.3, rng)
    face2 = fbm(n, 1.3, rng)
    fine = fbm(n, 0.55, rng)
    lam = fbm(n, 1.3, rng, stretch=(1.0, 0.05))
    h = P + 0.12 * P * 4 * t * (1 - t) + 0.08 * (rbk[..., 1] - 0.5) * 2
    h = h + (ul - 0.5) * (rbk[..., 2] - 0.5) * 0.10 + 0.07 * face + 0.03 * face2
    h = h + 0.014 * (lam - 0.5) * 2 * (1.0 - P) + 0.05 * _ss(dj, 0, 0.010) - 0.32 * crack - 0.05 * seam
    h = h - 0.10 * ledge_shadow
    h = blur(h, 0.9 * px)
    # ---- albedo
    drift = smooth(fbm(n, 2.8, rng, stretch=(1.0, 0.35)), 0.30, 0.70)                  # each bed slides between two colours along X
    a = lerp(pal[cidx][bed], pal[cidx2][bed], drift * 0.85) * tint[bed][..., None]
    gm = grade[bed] * np.exp(-d_top / 0.012) * 0.55                                    # gradational contact with the bed above
    a = lerp(a, lerp(pal[cidx][above], pal[cidx2][above], drift * 0.85) * tint[above][..., None], gm)
    a = _tone(a, fbm(n, 2.4, rng), 0.09)                                               # large weathering patina crossing the beds
    a = _tone(a, fbm(n, 2.4, rng, stretch=(1.0, 0.3)), 0.16)                          # broad drift along each bed
    a = _tone(a, rbk[..., 0], 0.09)                                                    # per-block tone
    a = _tone(a, lam, 0.10)                                                            # fine laminations
    a = _tone(a, fine, 0.08)
    a = _tone(a, face, 0.10)
    a = a * (1.0 + 0.14 * (1 - t) ** 3 - 0.08 * t ** 2)[..., None]                    # lighter weathered top of each bed
    # pits: little weathering holes
    pv = _vor(n, 30, 30, rng, warp=(fbm(n, 1.6, rng), fbm(n, 1.6, rng), 1.6))
    pit = (pv["id"] > 0.90) & (pv["d1"] < 0.12 + 0.30 * smooth(fbm(n, 0.9, rng), 0.35, 0.8))
    a = np.where(pit[..., None], a * 0.70, a)
    # micro-fracture network: small chipped fragments (cells a bit wider than tall), own tone, hairline dark edges
    mv = _vor(n, 24, 36, rng, warp=(fbm(n, 2.0, rng), fbm(n, 2.0, rng), 0.9), jitter=1.0)
    mline = 1.0 - _ss(mv["edge"], 0.004, 0.030)
    a = _tone(a, mv["id"], 0.07)
    a = a * (1.0 - 0.28 * mline)[..., None]
    # stains: broad vertical runnels, plus warm iron staining
    vs = fbm(n, 2.2, rng, stretch=(0.14, 1.0))
    vs2 = fbm(n, 2.3, rng, stretch=(0.12, 1.0))
    patch = fbm(n, 2.6, rng)
    a = lerp(a, a * col(0.52, 0.50, 0.49), smooth(vs, 0.55, 0.85) * smooth(patch, 0.30, 0.65) * 0.45)
    a = lerp(a, col(0.50, 0.27, 0.12), smooth(vs2, 0.66, 0.9) * smooth(patch, 0.5, 0.8) * 0.40)
    # moss + lichen: thin, in joints and on ledges, ragged
    grow = np.clip(near * 0.95 + shelf * 0.8 + 0.2 * smooth(fbm(n, 2.6, rng), 0.62, 0.9), 0, 1)
    ragged = fbm(n, 1.2, rng)
    moss = smooth(grow * (0.35 + 0.9 * ragged), 0.45, 0.80)
    mc = lerp(col(0.14, 0.22, 0.07), col(0.27, 0.35, 0.11), fbm(n, 1.4, rng))
    a = lerp(a, mc * (0.8 + 0.4 * fine[..., None]), moss * 0.9)
    lv = _vor(n, 15, 15, rng, warp=(fbm(n, 2.0, rng), fbm(n, 2.0, rng), 1.2))
    lich = (lv["id"] > 0.88) & (lv["d1"] < 0.16 + 0.20 * fbm(n, 1.0, rng))
    lcol = lerp(col(0.60, 0.60, 0.40), col(0.72, 0.48, 0.17), ((lv["id"] * 91.0) % 1.0 > 0.7).astype(np.float32))
    a = np.where(lich[..., None], lerp(a, lcol * (0.85 + 0.3 * fine[..., None]), 0.65), a)
    # darkening: ledge shadow, undersides, bedding hairlines, cracks
    shade = (1.0 - 0.70 * ledge_shadow - 0.32 * undercut - 0.30 * seam)
    a = a * shade[..., None]
    a = lerp(a, col(0.05, 0.04, 0.035), crack * 0.85)
    a = a * (1.0 + 0.20 * shelf)[..., None]
    a = _limit_lum(a)
    ao = (1.0 - 0.70 * ledge_shadow - 0.35 * undercut - 0.6 * crack - 0.3 * seam - 1.6 * _vcavity(h, 0.005, 1.0)
          - 0.9 * _vcavity(h, 0.02, 1.0))
    rough = 0.82 + 0.08 * (1 - hard[bed]) - 0.04 * smooth(lam, 0.4, 0.8) + 0.06 * (fine - 0.5) - 0.05 * moss
    facet = (mv["lx"] * (mv["id"] - 0.5) + mv["ly"] * (((mv["id"] * 53.0) % 1.0) - 0.5))   # per-fragment tilt from the micro fractures
    lump = fbm(n, 2.4, rng)
    nh = h + 0.10 * (lump - 0.5) + 0.10 * facet - 0.06 * mline + 0.012 * (fine - 0.5) + 0.012 * (fbm(n, 0.9, rng) - 0.5)
    nh = nh + 0.02 * moss * fine - 0.05 * pit
    return dict(albedo=a, height=_norm01(h), nheight=_norm01(nh), ao_map=ao, rough=np.clip(rough, 0.7, 0.95), ns=22.0, orm_b="height")


def mat_granite(n, rng):
    """High-peak granite: coarse three-phase grain (pale feldspar incl. larger tablets, grey quartz, dark mafic specks) in a cool grey-blue
    matrix, large irregular fracture blocks with fading cracks, rust stains haloing the cracks and running down, sparse crustose lichen.
    ORM: R = AO (cracks), G = roughness 0.62-0.92, B = HEIGHT (0..1), NOT metalness."""
    X, Y = _grid(n)
    px = n / 1024.0
    # ---- crystals: fine grain voronoi (mineral phase by cell id), larger feldspar tablets on top
    gw = (fbm(n, 1.0, rng), fbm(n, 1.0, rng), 0.55)
    g = _vor(n, 170, 170, rng, warp=gw, jitter=1.0)
    gid = g["id"]
    feld, quartz = gid < 0.54, (gid >= 0.54) & (gid < 0.88)
    mafic = gid >= 0.88
    gtone = (gid * 97.0) % 1.0
    pink = ((gid * 31.0) % 1.0) > 0.78
    c_f = np.where(pink[..., None], col(0.64, 0.56, 0.54), col(0.60, 0.62, 0.64)) * (0.88 + 0.20 * gtone[..., None])
    c_q = col(0.45, 0.48, 0.53) * (0.85 + 0.25 * gtone[..., None])
    c_m = col(0.13, 0.14, 0.16) * (0.8 + 0.5 * gtone[..., None])
    grain = np.where(feld[..., None], c_f, np.where(quartz[..., None], c_q, c_m))
    ph = _vor(n, 44, 38, rng, warp=(fbm(n, 1.6, rng), fbm(n, 1.6, rng), 0.5), jitter=1.0)
    tab = (ph["id"] > 0.80) & (ph["d1"] < 0.34 + 0.10 * ph["id"])
    tabc = np.where((((ph["id"] * 13.0) % 1.0) > 0.7)[..., None], col(0.68, 0.60, 0.56), col(0.68, 0.69, 0.70))
    grain = np.where(tab[..., None], tabc * (0.92 + 0.10 * gtone[..., None]), grain)
    matrix = col(0.40, 0.43, 0.47)
    a = lerp(matrix, grain, 0.88)
    a = a * (1.0 - 0.20 * (1.0 - _ss(g["edge"], 0.0, 0.08)))[..., None]               # crisp grain boundaries
    # ---- large-scale tone: cool/neutral drift + bright/dark weathering
    a = a * lerp(col(0.90, 0.95, 1.03), col(1.0, 0.99, 0.97), fbm(n, 2.6, rng))
    a = _tone(a, fbm(n, 2.8, rng), 0.16)
    a = _tone(a, fbm(n, 1.4, rng), 0.05)
    # ---- fracture network: big warped blocks + curvy ridged cracks in two directions, all fading in and out
    bv = _vor(n, 4, 5, rng, warp=(_wf(n, rng, 0.05), _wf(n, rng, 0.05), 1.1), jitter=1.0)
    wA = 0.008 + 0.030 * fbm(n, 3.0, rng)
    visA = _ss(fbm(n, 2.6, rng), 0.30, 0.56)
    crackA = (1.0 - _ss(bv["edge"], wA * 0.5, wA * 1.6)) * visA
    crackB = np.zeros((n, n), np.float32)
    for sx, sy in ((1.0, 0.45), (0.45, 1.0)):
        f = fbm(n, 2.4, rng, stretch=(sx, sy))
        wb = 0.0015 + 0.0090 * fbm(n, 3.0, rng)
        crackB = np.maximum(crackB, (1.0 - _ss(np.abs(f - 0.5), wb * 0.4, wb)) * _ss(fbm(n, 2.4, rng), 0.30, 0.58))
    hair = (1.0 - _ss(_vor(n, 20, 20, rng, warp=(_wf(n, rng), _wf(n, rng), 1.2))["edge"], 0.004, 0.016)) * _ss(fbm(n, 2.6, rng), 0.55, 0.8)
    crack = np.clip(np.maximum(crackA, crackB), 0, 1)
    cdil = blur(crack, 7 * px)
    cdil = np.clip(cdil * 5.0, 0, 1)                                                   # soft halo around cracks
    # ---- iron stains: halo around cracks + rain runnels below them
    runnel = fbm(n, 1.8, rng, stretch=(0.10, 1.0))
    halo = np.clip(blur(crack, 4 * px) * 9.0, 0, 1)
    stain = np.clip(halo * smooth(fbm(n, 2.2, rng), 0.35, 0.7) * 0.8 + smooth(runnel, 0.62, 0.9) * np.clip(blur(crack, 18 * px) * 7.0, 0, 1) * 0.8, 0, 1)
    a = lerp(a, a * col(1.00, 0.72, 0.50) + col(0.07, 0.03, 0.0), stain * 0.65)
    # ---- block shading: each fracture block has its own tone and tilt
    bt = (bv["id"] * 7.0) % 1.0
    a = _tone(a, bt, 0.06)
    # ---- lichen: sparse patches with speckled interior and ragged outline
    lv = _vor(n, 7, 7, rng, warp=(_wf(n, rng), _wf(n, rng), 1.0), jitter=1.0)
    rad = 0.10 + 0.16 * ((lv["id"] * 17.0) % 1.0)
    rag = _wf(n, rng, 0.45)
    patch = (lv["id"] > 0.88) & (lv["d1"] < rad * (0.25 + 1.5 * rag))
    lv2 = _vor(n, 36, 36, rng, warp=(_wf(n, rng, 0.4), _wf(n, rng, 0.4), 0.8), jitter=1.0)     # many tiny scattered crusts
    patch2 = (lv2["id"] > 0.86) & (lv2["d1"] < 0.30 * (0.3 + 1.4 * fbm(n, 1.8, rng)))
    speck = fbm(n, 0.8, rng) > 0.30
    pick = (lv["id"] * 131.0) % 1.0
    lc = np.where((pick > 0.66)[..., None], col(0.66, 0.50, 0.24), np.where((pick > 0.33)[..., None], col(0.58, 0.64, 0.48), col(0.68, 0.68, 0.55)))
    lmask = (patch & speck).astype(np.float32)
    pick2 = (lv2["id"] * 71.0) % 1.0
    lc = np.where(patch2[..., None], np.where((pick2 > 0.5)[..., None], col(0.62, 0.66, 0.52), col(0.66, 0.62, 0.50)), lc)
    lmask = np.maximum(lmask, (patch2 & speck).astype(np.float32) * 0.9)
    lmask = np.maximum(lmask, blur((patch & speck).astype(np.float32), 1.2 * px) * 0.0)
    lt = 0.70 + 0.55 * fbm(n, 1.8, rng)[..., None] * (0.7 + 0.5 * fbm(n, 0.6, rng)[..., None])
    a = lerp(a, lc * lt, lmask * 0.80)
    # ---- cracks darken last
    a = lerp(a, col(0.05, 0.05, 0.06), np.clip(crack * 0.92 + hair * 0.35, 0, 1))
    a = _limit_lum(a)
    # ---- height: blocks with their own offset/tilt, rounded toward cracks, grain relief, cracks cut deep
    bh = (bv["id"] - 0.5) * 0.20
    tilt = bv["lx"] * (((bv["id"] * 37.0) % 1.0) - 0.5) * 0.30 + bv["ly"] * (((bv["id"] * 61.0) % 1.0) - 0.5) * 0.30
    round_ = 0.12 * _ss(bv["edge"], 0.0, 0.45)
    surf = fbm(n, 2.4, rng)
    h = bh + tilt + round_ + 0.22 * surf + 0.05 * fbm(n, 1.4, rng) - 0.40 * crack - 0.12 * hair
    h = h - 0.05 * mafic - 0.03 * (1.0 - _ss(g["edge"], 0.0, 0.08))                    # mafic grains / boundaries weather in
    h = h + 0.04 * lmask
    h = blur(h, 0.7 * px)
    ao = 1.0 - 0.9 * crack - 0.15 * hair - 0.25 * cdil * (1 - crack) - 1.8 * _vcavity(h, 0.006, 1.0) - 0.8 * _vcavity(h, 0.025, 1.0)
    rough = 0.74 - 0.08 * (feld | quartz) + 0.10 * (1 - _ss(g["edge"], 0.0, 0.1)) + 0.10 * smooth(surf, 0.5, 0.9) + 0.18 * lmask + 0.08 * stain
    gb = g["lx"] * (gid - 0.5) + g["ly"] * (((gid * 53.0) % 1.0) - 0.5)
    nh = h + 0.020 * gb + 0.012 * (fbm(n, 0.6, rng) - 0.5) + 0.05 * (feld | tab) - 0.05 * mafic
    return dict(albedo=a, height=_norm01(h), nheight=_norm01(nh), ao_map=ao, rough=np.clip(rough, 0.62, 0.92), ns=14.0, orm_b="height")


def mat_scree(n, rng):
    """Angular rock rubble for 30-45 degree slopes: five layers of sharp polygonal fragments from cm-size gravel to dm-size slabs,
    stacked by height so small stones sit in the gaps of big ones; each fragment has its own tilted top facet, tone and bevel;
    dark voids between, fine gravel and dust in the gaps. Desaturated grey-brown.
    ORM: R = AO (voids, undercuts), G = roughness 0.78-0.95, B = HEIGHT (0..1), NOT metalness."""
    X, Y = _grid(n)
    px = n / 1024.0
    pal = np.array([[0.40, 0.38, 0.35], [0.31, 0.30, 0.30], [0.50, 0.46, 0.40], [0.36, 0.32, 0.28], [0.31, 0.30, 0.285],
                    [0.52, 0.48, 0.42], [0.44, 0.37, 0.31], [0.24, 0.22, 0.21], [0.47, 0.42, 0.34]], np.float32)
    surf = fbm(n, 1.7, rng)
    speck = fbm(n, 0.5, rng)
    dust = fbm(n, 2.6, rng)
    H = np.full((n, n), 0.03, np.float32)
    A = np.broadcast_to(col(0.14, 0.115, 0.095), (n, n, 3)).copy() * (0.8 + 0.5 * speck[..., None])        # dark soil in the voids
    edge_top = np.full((n, n), 1.0, np.float32)
    S = np.zeros((n, n, 2), np.float32)                                                  # per-fragment facet slope for the normal map
    layers = [(150, 150, 0.95, 0.12, 0.08, 0.08), (66, 74, 0.85, 0.11, 0.20, 0.14), (28, 36, 0.72, 0.09, 0.34, 0.20),
              (14, 18, 0.62, 0.08, 0.52, 0.24), (9, 11, 0.55, 0.06, 0.70, 0.22)]
    light = np.array([-0.55, -0.55], np.float32)                                         # light from upper left (facet tone only)
    for li, (cx, cy, keep, gap, hb, hs) in enumerate(layers):
        v = _vor(n, cx, cy, rng, warp=(_wf(n, rng, 0.12), _wf(n, rng, 0.12), 0.55), jitter=1.0)
        r1 = v["id"]
        r2 = (r1 * 7919.0) % 1.0
        r3 = (r1 * 104729.0) % 1.0
        r4 = (r1 * 15485863.0) % 1.0
        g = gap * (0.5 + 1.4 * r3)                                                       # some fragments are shrunk more
        inside = (r2 < keep) & (v["edge"] > g)
        ta = hs * 0.9
        tilt = ta * ((r3 - 0.5) * 2.0 * v["lx"] + (r4 - 0.5) * 2.0 * v["ly"])           # tilted top facet
        top = hb + hs * r1 + tilt
        bevel = _ss(v["edge"], g, g + 0.10 + 0.05 * r2)                                   # steep sides
        hf = top - hs * 0.55 * (1.0 - bevel)
        win = inside & (hf > H)
        fc = pal[np.minimum((r4 * 997.0 % 1.0 * len(pal)).astype(int), len(pal) - 1)]
        warm = ((r1 * 53.0) % 1.0 - 0.5)[..., None] * col(0.025, 0.005, -0.02)
        fcol = (fc + warm) * (0.86 + 0.24 * r2[..., None]) * (1.0 + 0.34 * (surf[..., None] - 0.5)) * (1.0 + 0.22 * (speck[..., None] - 0.5))
        fcol = fcol * (0.62 + 0.38 * bevel[..., None])                                      # edge darkening / chamfer
        fs = np.stack([(r3 - 0.5) * 2.0 * 0.42, (r4 - 0.5) * 2.0 * 0.42], -1) * (0.45 + 0.9 * r2[..., None])
        S = np.where(win[..., None], fs, S)
        A = np.where(win[..., None], fcol, A)
        H = np.where(win, hf, H)
        edge_top = np.where(win, v["edge"], edge_top)
    # dust settles on high flat parts, pale lichen specks on a few stones
    A = A * (1.0 + 0.14 * smooth(dust, 0.5, 0.9) * smooth(H, 0.3, 0.9))[..., None]
    fv = _vor(n, 44, 44, rng, jitter=1.0)                                               # chipped micro facets on top of the big ones
    mic = np.stack([(fv["id"] - 0.5) * 0.20, (((fv["id"] * 53.0) % 1.0) - 0.5) * 0.20], -1)
    S = S + mic * (H > 0.06)[..., None]
    A = A * (1.0 + 0.5 * (fv["id"][..., None] - 0.5) * 0.18)
    A = _limit_lum(A)
    h = blur(H, 0.6 * px)
    ao = 1.0 - 2.2 * _vcavity(h, 0.004, 1.0) - 1.6 * _vcavity(h, 0.012, 1.0) - 1.0 * _vcavity(h, 0.04, 1.0) - 0.30 * (1.0 - _ss(edge_top, 0.0, 0.22))
    ao = ao - 0.25 * (H < 0.06)
    rough = 0.84 + 0.08 * (speck - 0.5) * 2 + 0.07 * (H < 0.08) - 0.05 * (1.0 - _ss(edge_top, 0.0, 0.5)) * 0
    nh = h + 0.03 * (surf - 0.5) + 0.02 * (speck - 0.5)
    return dict(albedo=A, height=_norm01(h), nheight=_norm01(nh), nslope=blur(S[..., 0], 0.7 * px)[..., None] * np.array([1, 0], np.float32) + blur(S[..., 1], 0.7 * px)[..., None] * np.array([0, 1], np.float32), ao_map=ao, rough=np.clip(rough, 0.78, 0.95), ns=14.0, orm_b="height")


def mat_red_clay(n, rng):
    """Eroded red clay hillside: gullies and rills running down the slope (vertical in texture space) that meander and start/stop,
    sun-cracked dry plates in patches, embedded pebbles and cobbles, bleached dry crests and dark damp channel floors.
    Warm ochre / terracotta / red-brown. ORM: R = AO (gullies, cracks, pebble rims), G = roughness 0.72-0.94, B = HEIGHT (0..1), NOT metalness."""
    X, Y = _grid(n)
    px = n / 1024.0
    # ---- gullies: explicit meandering channels (x_k(y)), each with its own width and a depth that fades in/out down the slope
    K = 10
    xk = (np.arange(K) + 0.15 + 0.7 * rng.random(K)) / K
    wob2 = _sfbm(n, 4.2, rng) * 0.010 + _sfbm(n, 2.8, rng) * 0.0025
    deep = np.zeros((n, n), np.float32)
    lev = np.zeros((n, n), np.float32)
    for k in range(K):
        mk = _sfbm(n, 4.4, rng)[:, int(rng.integers(0, n))]                              # 1-D periodic function of y
        mk = (mk / max(np.abs(mk).max(), 1e-6))[:, None] * (0.015 + 0.030 * rng.random())
        wk = (0.018 + 0.026 * ss1(_sfbm(n, 3.6, rng)[:, int(rng.integers(0, n))])[:, None]).astype(np.float32)
        dk = ss1(_sfbm(n, 3.2, rng)[:, int(rng.integers(0, n))], -0.45, 0.35)[:, None].astype(np.float32)
        d = _pdist(X + wob2, xk[k] + mk)
        deep = np.maximum(deep, dk * (1.0 - _ss(d, wk * 0.55, wk)))
        lev = np.maximum(lev, dk * np.exp(-((d - wk * 1.35) / (wk * 0.55)) ** 2))
    Xw = X + wob2 * 1.5
    Yw = Y + _sfbm(n, 4.2, rng) * 0.012
    # rills: turbulence |2g-1| of smooth vertical noise = sharp V valleys with rounded crests, three scales, each fading in/out
    g1 = _wsample(fbm(n, 4.0, rng, stretch=(0.20, 1.0)), Xw, Yw)
    g2 = _wsample(fbm(n, 3.6, rng, stretch=(0.13, 0.9)), Xw + 0.31, Yw)
    g3 = _wsample(fbm(n, 3.2, rng, stretch=(0.09, 0.8)), Xw + 0.67, Yw)
    t1, t2, t3 = np.abs(2 * g1 - 1), np.abs(2 * g2 - 1), np.abs(2 * g3 - 1)
    D1b = _ss(fbm(n, 3.0, rng, stretch=(0.3, 1.0)), 0.10, 0.40)
    D2b = _ss(fbm(n, 3.0, rng, stretch=(0.3, 1.0)), 0.25, 0.6)
    D3b = _ss(fbm(n, 3.0, rng, stretch=(0.3, 1.0)), 0.30, 0.65)
    t1m, t2m, t3m = lerp(0.62, t1, D1b) if False else 0.62 + (t1 - 0.62) * D1b, 0.62 + (t2 - 0.62) * D2b, 0.62 + (t3 - 0.62) * D3b
    rill = (1.0 - t1) * D1b
    fine_r = (1.0 - t3) * D3b
    D1 = np.clip(deep * 1.5, 0, 1)
    crest = _ss(t1m, 0.6, 1.0)
    # ---- dry cracked plates in patches
    Mc = _ss(fbm(n, 3.4, rng), 0.55, 0.72)
    cv = _vor(n, 22, 22, rng, warp=(_wf(n, rng, 0.1), _wf(n, rng, 0.1), 1.0), jitter=1.0)
    cr = (1.0 - _ss(cv["edge"], 0.012, 0.050)) * Mc
    plate = _ss(cv["edge"], 0.0, 0.30) * Mc                                           # plates dome / curl slightly
    # ---- pebbles and cobbles
    pv = _vor(n, 30, 30, rng, warp=(_wf(n, rng, 0.35), _wf(n, rng, 0.35), 0.7), jitter=0.9)
    rp = 0.18 + 0.24 * ((pv["id"] * 31.0) % 1.0)
    peb = (pv["id"] > 0.95) & (pv["d1"] < rp * (0.65 + 0.7 * fbm(n, 1.9, rng)))
    pdome = np.sqrt(np.clip(1.0 - (pv["d1"] / np.maximum(rp, 1e-3)) ** 2, 0, 1))
    cb = _vor(n, 11, 12, rng, warp=(_wf(n, rng, 0.2), _wf(n, rng, 0.2), 0.5), jitter=0.9)
    rc = 0.17 + 0.18 * ((cb["id"] * 17.0) % 1.0)
    cob = (cb["id"] > 0.93) & (cb["d1"] < rc * (0.70 + 0.6 * fbm(n, 2.0, rng)))
    cdome = np.sqrt(np.clip(1.0 - (cb["d1"] / np.maximum(rc, 1e-3)) ** 2, 0, 1))
    stone = peb | cob
    sdome = np.where(cob, cdome * 1.6, np.where(peb, pdome, 0.0))
    sid = np.where(cob, cb["id"], pv["id"])
    # ---- height
    soil = fbm(n, 2.3, rng)
    fine = fbm(n, 0.6, rng)
    clod = _vor(n, 70, 70, rng, warp=(_wf(n, rng, 0.2), _wf(n, rng, 0.2), 0.6), jitter=1.0)
    clodh = _ss(clod["edge"], 0.0, 0.30) * (0.6 + 0.8 * clod["id"])
    h = 0.28 * (1.0 - deep * 0.9) + 0.36 * t1m + 0.20 * t2m + 0.08 * t3m + 0.08 * soil + 0.03 * fbm(n, 1.4, rng)
    h = h + 0.08 * lev + 0.12 * plate - 0.22 * cr + 0.035 * clodh
    h = np.where(stone, np.maximum(h, h + 0.12 + 0.30 * sdome), h)
    h = blur(h, 0.7 * px)
    # ---- albedo
    base_a = lerp(col(0.52, 0.30, 0.19), col(0.64, 0.45, 0.26), fbm(n, 3.0, rng))        # terracotta .. ochre, large scale
    a = lerp(base_a, col(0.40, 0.18, 0.11), smooth(fbm(n, 2.4, rng), 0.55, 0.9) * 0.7)        # deep red-brown patches
    a = lerp(a, col(0.71, 0.56, 0.36), smooth(fbm(n, 2.5, rng), 0.62, 0.92) * 0.55)            # pale yellow clay mottling
    vst = fbm(n, 2.4, rng, stretch=(0.35, 1.0))                                            # soft vertical streaking from runoff
    a = _tone(a, vst, 0.12)
    band = 0.5 + 0.5 * np.sin(2 * np.pi * (Y * 7.0 + 0.9 * _sfbm(n, 3.4, rng)))            # faint soil horizons across the slope
    a = _tone(a, band, 0.05)
    a = _tone(a, soil, 0.10)
    a = _tone(a, fine, 0.12)
    a = _tone(a, clod["id"], 0.07)
    a = a * (0.84 + 0.10 * lev - 0.22 * deep + 0.26 * (t1m * 0.5 + t2m * 0.3 + t3m * 0.2) - 0.10)[..., None]                      # bleached levees, damp dark gully floors
    a = lerp(a, col(0.63, 0.52, 0.36), (smooth(fbm(n, 2.0, rng, stretch=(0.15, 1.0)), 0.65, 0.92) * deep) * 0.55)   # pale sandy wash in the gullies
    a = _tone(a, (cv["id"] * 5.0) % 1.0 * Mc + 0.5 * (1 - Mc), 0.07)                      # per-plate tone
    a = lerp(a, a * col(0.28, 0.2, 0.18) * 2.0, cr * 0.9)                                  # cracks
    spal = np.array([[0.42, 0.37, 0.32], [0.54, 0.44, 0.33], [0.58, 0.52, 0.44], [0.30, 0.26, 0.23], [0.48, 0.38, 0.30], [0.44, 0.41, 0.37]], np.float32)
    sc = spal[np.minimum(((sid * 997.0) % 1.0 * len(spal)).astype(int), len(spal) - 1)] * (0.80 + 0.35 * fbm(n, 1.2, rng)[..., None])
    sc = sc * (0.55 + 0.45 * sdome[..., None] ** 0.5)
    a = np.where(stone[..., None], sc, a)
    a = _limit_lum(a)
    ao = 1.0 - 1.6 * _vcavity(h, 0.005, 1.0) - 1.0 * _vcavity(h, 0.02, 1.0) - 0.55 * cr - 0.18 * deep
    rough = 0.88 - 0.10 * deep * D1 - 0.06 * (1.0 - t1m) + 0.04 * Mc - 0.04 * (soil - 0.5) - 0.16 * stone
    nh = h + 0.02 * (fine - 0.5) + 0.02 * (fbm(n, 1.0, rng) - 0.5)
    return dict(albedo=a, height=_norm01(h), nheight=_norm01(nh), ao_map=ao, rough=np.clip(rough, 0.72, 0.94), ns=30.0, orm_b="height")


def mat_mossy_rock(n, rng):
    """Dark wet rock blocks (cliff foot / lake shore): rounded blocks separated by deep crevices, thick saturated moss on the flatter
    tops (denser in the upper part of the tile) and packed into every crevice, ragged moss edges, clumpy cushions, wet dark rock
    showing between. ORM: R = AO (crevices, under moss rims), G = roughness (wet rock 0.62-0.72, moss 0.80-0.90),
    B = HEIGHT (0..1), NOT metalness."""
    X, Y = _grid(n)
    px = n / 1024.0
    bv = _vor(n, 6, 6, rng, warp=(_wf(n, rng, 0.08), _wf(n, rng, 0.08), 1.3), jitter=1.0)
    e = bv["edge"]
    bid = bv["id"]
    r2 = (bid * 7919.0) % 1.0
    r3 = (bid * 104729.0) % 1.0
    r4 = (bid * 15485863.0) % 1.0
    crev = 1.0 - _ss(e, 0.02, 0.16)                                                    # crevice neighbourhood
    topness = _ss(e, 0.06, 0.60)                                                       # towards the middle of a block = flat top
    # ---- rock height + facet slopes
    shoulder = _ss(e, 0.0, 0.55)
    rough_r = fbm(n, 2.6, rng)
    rock_h = 0.45 * shoulder + 0.25 * (bid - 0.5) + 0.12 * rough_r + 0.05 * fbm(n, 1.4, rng) - 0.30 * (1.0 - _ss(e, 0.0, 0.05))
    sl = np.stack([(r3 - 0.5) * 2.0 * 0.20, (r4 - 0.5) * 2.0 * 0.20], -1)
    sl_mag = np.sqrt(sl[..., 0] ** 2 + sl[..., 1] ** 2)
    flat = 1.0 - _ss(sl_mag, 0.04, 0.17)
    # ---- moss thickness field: flat tops + crevices, denser high up, per-block bias, ragged by fine noise
    vert = 0.5 + 0.5 * np.cos(2 * np.pi * (Y - 0.10 + 0.08 * _sfbm(n, 4.0, rng)))      # upper band of the tile is mossier
    bias = 0.35 + 0.65 * r2
    upper = _ss(-bv["ly"], -0.45, 0.40)                                               # upper part of each block collects moss
    M0 = np.maximum(np.maximum(topness * (0.45 + 0.60 * vert) * (0.65 + 0.50 * flat) * bias * (0.50 + 1.15 * upper) * 2.9, crev * (0.70 + 0.30 * rough_r)),
                    (1.0 - _ss(e, 0.08, 0.45)) * (0.30 + 0.55 * rough_r) * (0.65 + 0.35 * bias + 0.35 * upper))                 # moss creeping up the shoulders
    rag = fbm(n, 1.5, rng)
    T = _ss(M0 + 0.45 * (rag - 0.5) + 0.12 * (fbm(n, 0.7, rng) - 0.5), 0.40, 0.58)
    tuft = (fbm(n, 0.55, rng) > 0.66) & (M0 > 0.22)                                    # sparse moss tufts around the edge of the cover
    T = np.maximum(T, 0.8 * tuft * _ss(M0, 0.22, 0.40))
    # cushions: clumps with domes, so the moss has real thickness variation
    cv = _vor(n, 64, 64, rng, warp=(_wf(n, rng, 0.2), _wf(n, rng, 0.2), 0.6), jitter=1.0)
    dome = np.clip(1.0 - cv["d1"] / 0.75, 0, 1) ** 0.7
    cv2 = _vor(n, 150, 150, rng, jitter=1.0)
    fuzz = fbm(n, 0.7, rng)
    mtone = fbm(n, 2.2, rng)
    # ---- albedo: wet dark rock
    rock = lerp(col(0.115, 0.125, 0.125), col(0.26, 0.26, 0.25), fbm(n, 2.6, rng))
    rock = rock * (0.70 + 0.65 * r2[..., None]) * lerp(col(0.94, 1.03, 1.04), col(1.06, 1.0, 0.92), r3[..., None] * 0.7 + 0.3 * fbm(n, 3.0, rng)[..., None])
    rock = _tone(rock, fbm(n, 1.2, rng), 0.16)
    rock = _tone(rock, fbm(n, 0.45, rng), 0.12)                                         # fine grain
    vein = np.abs(fbm(n, 2.6, rng, stretch=(0.5, 1.0)) - 0.5) < 0.004
    rock = np.where(vein[..., None], rock * 1.7, rock)                                  # thin pale veins
    rock = lerp(rock, col(0.46, 0.50, 0.42), smooth(fbm(n, 2.4, rng), 0.72, 0.92) * 0.35)   # pale lichen bloom
    wetstreak = fbm(n, 2.2, rng, stretch=(0.14, 1.0))
    rock = rock * (1.0 - 0.30 * smooth(wetstreak, 0.55, 0.9))[..., None]
    rock = lerp(rock, col(0.42, 0.41, 0.37), (1.0 - _ss(e, 0.06, 0.20)) * smooth(fbm(n, 1.5, rng), 0.6, 0.9) * 0.5)   # dry worn edges
    # ---- albedo: moss (rich greens, lighter yellow-green on cushion tips, dark in the crevices)
    mdark, mmid, mhi, mtip = col(0.07, 0.20, 0.04), col(0.14, 0.35, 0.06), col(0.25, 0.50, 0.07), col(0.48, 0.62, 0.13)
    m = lerp(mdark, mmid, smooth(mtone * 0.7 + dome * 0.45, 0.25, 0.75))
    m = lerp(m, mhi, smooth(dome * 0.6 + fuzz * 0.4 + 0.45 * (mtone - 0.5) + 0.25 * upper, 0.50, 0.90))
    m = lerp(m, mtip, smooth(dome, 0.82, 1.0) * smooth(fuzz, 0.4, 0.8) * 0.65)
    m = lerp(m, col(0.12, 0.31, 0.14), smooth(fbm(n, 2.8, rng), 0.62, 0.90) * 0.55)             # teal-olive patches
    m = lerp(m, col(0.34, 0.42, 0.08), smooth(fbm(n, 2.6, rng), 0.66, 0.92) * 0.55)             # yellow-olive patches
    m = m * (0.82 + 0.30 * cv2["id"][..., None]) * (1.0 - 0.45 * crev[..., None] * T[..., None])
    a = lerp(rock, m, T)
    a = _limit_lum(a)
    # ---- height / AO / roughness
    mh = T * (0.10 + 0.20 * dome + 0.05 * fuzz)
    h = rock_h + mh
    h = blur(h, 0.7 * px)
    ao = 1.0 - 0.75 * crev * (0.55 + 0.45 * (1 - T * 0.3)) - 1.4 * _vcavity(h, 0.005, 1.0) - 0.8 * _vcavity(h, 0.02, 1.0)
    rough = 0.66 + 0.04 * (rough_r - 0.5) + T * (0.22 - 0.04 * dome)
    nh = h + 0.012 * (fuzz - 0.5) + 0.015 * T * (cv2["id"] - 0.5) + 0.01 * (fbm(n, 0.9, rng) - 0.5) * (1 - T)
    return dict(albedo=a, height=_norm01(h), nheight=_norm01(nh), nslope=sl * (1.0 - 0.6 * T)[..., None], ao_map=ao,
                rough=np.clip(rough, 0.62, 0.92), ns=16.0, orm_b="height")


def mat_basalt(n, rng):
    """Dark blue-black fine-grained basalt with columnar jointing seen from the side: vertical prismatic columns (each with its own
    facet slopes, tone and height step) separated by slightly curved vertical joints, extra thin columns fading in and out
    ("entablature" zones), irregular cross joints, conchoidal chips, a few gas pits, light weathering on the edges and slight rust
    along joints. ORM: R = AO (joints), G = roughness 0.6-0.88, B = HEIGHT (0..1), NOT metalness."""
    X, Y = _grid(n)
    px = n / 1024.0
    K = 9
    xs = (np.arange(K) + 0.15 + 0.70 * rng.random(K)) / K
    wobx = _sfbm(n, 3.6, rng) * 0.004 + _sfbm(n, 2.2, rng) * 0.0012
    woby = _sfbm(n, 3.6, rng) * 0.004
    Xw = X + wobx
    # ---- primary vertical joints, curved in y; column index via the nearest joint on the left
    P = np.empty((K, n, 1), np.float32)
    for k in range(K):
        mk = _sfbm(n, 4.3, rng)[:, int(rng.integers(0, n))]
        P[k, :, 0] = xs[k] + (mk / max(np.abs(mk).max(), 1e-6)) * (0.008 + 0.014 * rng.random())
    order = np.argsort(P[:, 0, 0])
    P = P[order]
    left = np.full((n, n), -9.0, np.float32)
    right = np.full((n, n), 9.0, np.float32)
    cid = np.zeros((n, n), np.int32)
    xwm = Xw % 1.0
    for k in range(K):
        pk = P[k]
        ok = pk <= xwm
        upd = ok & (pk > left)
        left = np.where(upd, pk, left)
        cid = np.where(upd, k, cid)
        right = np.where((~ok) & (pk < right), pk, right)
    wl = left < -8
    left = np.where(wl, P[K - 1] - 1.0, left)
    cid = np.where(wl, K - 1, cid)
    right = np.where(right > 8, P[0] + 1.0, right)
    dl, dr = xwm - left, right - xwm
    dj = np.minimum(dl, dr)
    u = dl / np.maximum(right - left, 1e-3)
    # ---- secondary thin joints (entablature): visible only in some y zones
    dj2 = np.full((n, n), 9.0, np.float32)
    for k in range(K):
        mk = _sfbm(n, 4.0, rng)[:, int(rng.integers(0, n))]
        xk2 = xs[k] + 0.5 / K + (mk / max(np.abs(mk).max(), 1e-6)) * 0.02 + 0.03 * (rng.random() - 0.5)
        vis = ss1(_sfbm(n, 3.4, rng)[:, int(rng.integers(0, n))], -0.25, 0.35)[:, None]
        dj2 = np.minimum(dj2, _pdist(Xw, xk2) + (1.0 - vis) * 9.0)
    # ---- cross joints per column
    M = 5
    Yj = np.sort(rng.random((K, M)), axis=1).astype(np.float32)
    Yj = Yj + (rng.random((K, M)).astype(np.float32) - 0.5) * 0.04
    dy = np.full((n, n), 9.0, np.float32)
    rc = rng.random((K, 6)).astype(np.float32)
    rcp = rc[cid]
    Yw = Y + woby + _sfbm(n, 2.4, rng) * 0.0015 + (rcp[..., 5] - 0.5) * 0.10 * (4.0 * (u - 0.5) ** 2 - 0.5)   # cross joints bow (ball-and-socket)
    for m in range(M):
        dy = np.minimum(dy, _pdist(Yw, Yj[cid, m]))
    cw = fbm(n, 2.0, rng)
    wcr = 0.0008 + 0.0050 * cw ** 2
    crack_v = 1.0 - _ss(dj, wcr * 0.4, wcr * 1.4)
    crack_v2 = (1.0 - _ss(dj2, wcr * 0.2, wcr * 0.8)) * 0.8
    crack_h = (1.0 - _ss(dy, wcr * 0.3, wcr * 1.1)) * _ss(fbm(n, 2.4, rng), 0.25, 0.55) * 0.9
    crack = np.clip(np.maximum(np.maximum(crack_v, crack_v2), crack_h), 0, 1)
    # ---- column faces: three facets (left bevel / middle / right bevel), own slopes; per-column height step
    f1 = 0.18 + 0.20 * rcp[..., 0]
    f2 = 0.62 + 0.20 * rcp[..., 1]
    sa = 0.16 + 0.20 * rcp[..., 2]
    sb = (rcp[..., 3] - 0.5) * 0.12
    sc = 0.16 + 0.20 * rcp[..., 4]
    slx = np.where(u < f1, sa, np.where(u > f2, -sc, sb))
    tent = np.minimum(np.minimum(u / f1, (1.0 - u) / (1.0 - f2)), 1.0)
    chunk = _vor(n, 16, 24, rng, warp=(_wf(n, rng, 0.1), _wf(n, rng, 0.1), 0.8), jitter=1.0)       # conchoidal chips
    cs = np.stack([(chunk["id"] - 0.5) * 0.16, (((chunk["id"] * 53.0) % 1.0) - 0.5) * 0.16], -1)
    grain = fbm(n, 0.5, rng)
    surf = fbm(n, 2.4, rng)
    # ---- height
    h = 0.35 * tent + 0.25 * (rcp[..., 3] - 0.5) + 0.10 * surf + 0.04 * fbm(n, 1.5, rng) - 0.32 * crack
    h = h + 0.05 * (1.0 - _ss(dy, 0.0, 0.02)) * (1.0 - crack_h) * 0.0
    h = blur(h, 0.8 * px)
    # ---- gas pits in clusters
    pv = _vor(n, 90, 90, rng, jitter=1.0)
    pits = (pv["id"] > 0.94) & (pv["d1"] < 0.22) & (fbm(n, 2.8, rng) > 0.55)
    # ---- albedo
    a = lerp(col(0.10, 0.11, 0.14), col(0.22, 0.24, 0.29), fbm(n, 3.0, rng))
    a = a * (0.78 + 0.46 * rcp[..., 3][..., None]) * (1.0 + 0.10 * (slx * 2.5)[..., None]) * lerp(col(0.95, 1.0, 1.06), col(1.05, 1.0, 0.94), rcp[..., 4][..., None] * 0.6)
    a = _tone(a, grain, 0.20)
    a = _tone(a, surf, 0.18)
    a = _tone(a, chunk["id"], 0.13)
    edgew = (1.0 - _ss(dj, 0.0, 0.030)) * smooth(fbm(n, 1.6, rng), 0.35, 0.8)
    a = lerp(a, col(0.34, 0.36, 0.40), edgew * 0.35)                                        # pale weathering rind on the column edges
    runnel = fbm(n, 2.0, rng, stretch=(0.10, 1.0))
    halo = np.clip(blur(crack, 5 * px) * 8.0, 0, 1)
    rust = np.clip(halo * smooth(fbm(n, 2.2, rng), 0.45, 0.8) * 0.9 + smooth(runnel, 0.66, 0.92) * np.clip(blur(crack, 16 * px) * 6.0, 0, 1) * 0.7, 0, 1)
    a = lerp(a, col(0.36, 0.20, 0.12) * (0.7 + 0.6 * grain[..., None]), rust * 0.55)       # slight rust
    a = np.where(pits[..., None], a * 0.45, a)
    lath = _vor(n, 210, 210, rng, jitter=1.0)
    a = np.where(((lath["id"] > 0.984) & (lath["d1"] < 0.40))[..., None], a * 1.6 + 0.015, a)       # sparse pale plagioclase specks
    a = lerp(a, col(0.03, 0.03, 0.04), crack * 0.9)
    a = _limit_lum(a)
    ao = 1.0 - 0.85 * crack - 0.25 * (1.0 - _ss(dj, 0.0, 0.03)) * (1.0 - crack) - 1.6 * _vcavity(h, 0.005, 1.0) - 0.8 * _vcavity(h, 0.02, 1.0)
    ao = ao - 0.3 * pits
    rough = 0.70 + 0.16 * smooth(surf, 0.5, 0.9) - 0.10 * (1.0 - _ss(chunk["edge"], 0.0, 0.25)) * 0.0 - 0.08 * smooth(chunk["id"], 0.6, 1.0) + 0.14 * rust + 0.10 * edgew
    sl = np.stack([slx, np.zeros_like(slx)], -1) * (1.0 - crack)[..., None] + cs
    nh = h + 0.012 * (grain - 0.5) + 0.02 * (surf - 0.5) - 0.04 * pits
    return dict(albedo=a, height=_norm01(h), nheight=_norm01(nh), nslope=sl, ao_map=ao,
                rough=np.clip(rough, 0.6, 0.9), ns=16.0, orm_b="height")


# <<< rock set end


MATERIALS = {
    "meadow": mat_meadow, "dry_grass": mat_dry_grass, "forest_floor": mat_forest_floor, "rocky_gravel": mat_rocky_gravel,
    "dirt_road": mat_dirt_road, "sakura_petals": mat_sakura, "zen_gravel": mat_zen_gravel,
    "thatch": mat_thatch, "wood_light": mat_wood_light, "stone_wall": mat_stone_wall, "plaster_white": mat_plaster, "wood_dark": mat_wood_dark, "roof_tile": mat_roof_tile,
    "cliff_strata": mat_cliff_strata, "granite": mat_granite, "scree": mat_scree, "red_clay": mat_red_clay, "mossy_rock": mat_mossy_rock, "basalt": mat_basalt,
}


# ----------------------------------------------------------------------------- checks
def seam_ratio(a):
    """Wrap-seam difference / LARGEST neighbouring-line difference, worst of both axes. <= ~1 = seamless.
    The reference is the max (not the mean/p95) so designed hard edges inside the texture (tile rows, plank gaps) don't read as
    seams, while an arbitrary cut through smooth content still shows up as a seam well above any natural neighbour difference."""
    a = a.astype(np.float32)
    worst = 0.0
    for ax in (0, 1):
        A = np.moveaxis(a, ax, 0)
        d = np.abs(A[1:] - A[:-1]).reshape(A.shape[0] - 1, -1).mean(axis=1)     # per-line mean neighbour difference
        seam = float(np.abs(A[0] - A[-1]).mean())
        worst = max(worst, seam / max(float(d.max()), 1e-6))
    return worst


def check_set(name, albedo, normal, orm):
    findings = []
    lum = 0.2126 * albedo[..., 0] + 0.7152 * albedo[..., 1] + 0.0722 * albedo[..., 2]
    res = {"albedo_mean": float(lum.mean()), "albedo_std": float(lum.std()),
           "seam_albedo": seam_ratio(albedo), "seam_normal": seam_ratio(normal), "seam_orm": seam_ratio(orm),
           "normal_z_mean": float(normal[..., 2].mean())}
    if lum.std() < 0.02:
        findings.append(("error", "TEX_FLAT", f"{name}: albedo has almost no variation (std {lum.std():.3f})"))
    if not (0.06 <= lum.mean() <= 0.88):
        findings.append(("error", "ALBEDO_RANGE", f"{name}: mean albedo luminance {lum.mean():.2f} outside plausible 0.06-0.88"))
    for k in ("seam_albedo", "seam_normal", "seam_orm"):
        if res[k] > 1.6:
            findings.append(("error", "NOT_TILEABLE", f"{name}: {k}={res[k]:.2f} > 1.6 (visible seam when tiled)"))
    if res["normal_z_mean"] < 0.75:
        findings.append(("error", "NORMAL_TOO_STRONG", f"{name}: normal map too strong (mean z {res['normal_z_mean']:.2f})"))
    res["findings"] = findings
    return res


# ----------------------------------------------------------------------------- IO (bpy only for JPEG writing)
def save_img(path, arr, quality=93):
    """JPEG for albedo only. Normal + ORM must be lossless (PNG): JPEG chroma subsampling mixes independent data channels."""
    import bpy
    h, w = arr.shape[:2]
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = np.clip(arr, 0, 1)[::-1]          # Blender image rows run bottom-to-top; our arrays are top-down
    img = bpy.data.images.new(os.path.basename(path), w, h, alpha=False)
    img.colorspace_settings.name = "Non-Color"           # raw values in, raw bytes out
    img.pixels.foreach_set(rgba.ravel())
    sc = bpy.context.scene
    fmt = "JPEG" if path.lower().endswith(".jpg") else "PNG"
    sc.render.image_settings.file_format = fmt
    sc.render.image_settings.quality = quality
    img.filepath_raw = path
    img.file_format = fmt
    img.save()
    bpy.data.images.remove(img)


def load_img(path):
    import bpy
    img = bpy.data.images.load(path)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)[..., :3][::-1]            # back to top-down


def build_one(name, n, seed):
    """Material dict -> (albedo, normal, orm) float arrays.
    Optional keys a material may return (all opt-in; the default path is unchanged for older materials):
      nheight  height used ONLY for the normal map (adds micro-relief that should not pollute the blend height)
      ao_map   explicit ambient-occlusion map (0..1) instead of ao_from_height(height, *ao)
      nslope   (n,n,2) analytic extra slope (dz/dx, dz/dy_up) for the normal map: tilted planar facets without extreme height ranges
      orm_b    "height": write the normalised height map into ORM.B (non-metal rock/earth set) instead of metalness 0"""
    rng = np.random.default_rng(seed + sum(map(ord, name)))
    m = MATERIALS[name](n, rng)
    albedo = np.clip(m["albedo"], 0, 1)
    h = np.clip(m["height"], 0, None)
    h = (h - h.min()) / max(h.max() - h.min(), 1e-9)
    hn = h
    if "nheight" in m:
        hn = np.clip(m["nheight"], 0, None)
        hn = (hn - hn.min()) / max(hn.max() - hn.min(), 1e-9)
    normal = normal_from_height(hn, m["ns"] * 0.25 * n / 256.0 * 0.5, m.get("nslope"))
    ao = np.clip(m["ao_map"], 0.1, 1.0) if "ao_map" in m else ao_from_height(h, *m["ao"])
    rough = np.clip(np.broadcast_to(m["rough"], (n, n)), 0.05, 1)
    third = h if m.get("orm_b") == "height" else np.zeros_like(ao)
    orm = np.stack([ao, rough, third], -1)
    return albedo.astype(np.float32), normal.astype(np.float32), orm.astype(np.float32)


def run(spec_path, out_override=None):
    with open(spec_path) as fh:
        spec = json.load(fh)
    n = spec.get("size", 1024)
    out = out_override or os.path.join(ROOT, spec.get("out_dir", "out"), spec.get("name", "textures"))
    os.makedirs(out, exist_ok=True)
    manifest, tiles, failed = {}, [], False
    for name in spec["materials"]:
        albedo, normal, orm = build_one(name, n, spec.get("seed", 7))
        files = {"albedo": f"{name}_albedo.jpg", "normal": f"{name}_normal.png", "orm": f"{name}_orm.png"}
        for key, arr in (("albedo", albedo), ("normal", normal), ("orm", orm)):
            save_img(os.path.join(out, files[key]), arr, 92)
        # verify what was actually written (format round trip), not the in-memory arrays
        a2, n2, o2 = (load_img(os.path.join(out, files[k])) for k in ("albedo", "normal", "orm"))
        res = check_set(name, a2, n2, o2)
        errs = [f for f in res["findings"] if f[0] == "error"]
        failed |= bool(errs)
        manifest[name] = {k: (v if k != "findings" else [{"level": l, "code": c, "message": m} for l, c, m in v]) for k, v in res.items()}
        manifest[name]["passed"] = not errs
        print(f"[{'PASS' if not errs else 'FAIL'}] {name:14} seam a/n/o = {res['seam_albedo']:.2f}/{res['seam_normal']:.2f}/{res['seam_orm']:.2f}  "
              f"albedo mean {res['albedo_mean']:.2f} std {res['albedo_std']:.2f}")
        for l, c, m in res["findings"]:
            print(f"   {l.upper()} {c}: {m}")
        tiles.append(np.tile(albedo[::2, ::2], (2, 2, 1))[:n // 2 * 2 // 2])
    # contact sheet: each albedo tiled 2x2 so seams would be visible
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    th = tiles[0].shape[0]
    sheet = np.zeros((rows * th, cols * th, 3), np.float32)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet[r * th:(r + 1) * th, c * th:(c + 1) * th] = t[:th, :th]
    save_img(os.path.join(out, "contact_sheet.jpg"), sheet, 90)
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump({"size": n, "materials": manifest, "passed": not failed}, fh, indent=2)
    print(f"\n== textures: {'ALL PASS' if not failed else 'FAILED'} ({len(spec['materials'])} sets) -> {out} ==")
    return not failed


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if not argv:
        print("usage: blender -b --factory-startup -P gamepipe/gp_texgen.py -- spec.json [--out DIR]")
        sys.exit(2)
    ok = run(argv[0], argv[argv.index("--out") + 1] if "--out" in argv else None)
    sys.exit(0 if ok else 1)
