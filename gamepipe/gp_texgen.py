"""gp_texgen: procedural TILEABLE PBR texture sets (albedo / tangent normal / ORM) + automatic tileability checks.

Runs inside Blender's Python (numpy + bpy image saving), headless:
    blender -b --factory-startup -P gamepipe/gp_texgen.py -- specs/biomes.json [--out DIR]
    bin/gp textures specs/biomes.json

Tileability is by construction: spectral (FFT) noise and torus-wrapped Worley cells are periodic. The checker proves it.
Output per material: <name>_albedo.jpg (sRGB), <name>_normal.png (tangent, OpenGL +Y), <name>_orm.png (R=AO G=roughness B=metal),
plus out/textures/manifest.json (checks) and contact_sheet.jpg.

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
def normal_from_height(h, strength):
    dhdx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    dhdy_up = (np.roll(h, 1, 0) - np.roll(h, -1, 0)) * 0.5      # image row 0 is up
    nx, ny, nz = -dhdx * strength, -dhdy_up * strength, np.ones_like(h)
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


MATERIALS = {
    "meadow": mat_meadow, "dry_grass": mat_dry_grass, "forest_floor": mat_forest_floor, "rocky_gravel": mat_rocky_gravel,
    "dirt_road": mat_dirt_road, "sakura_petals": mat_sakura, "zen_gravel": mat_zen_gravel,
    "thatch": mat_thatch, "wood_light": mat_wood_light, "stone_wall": mat_stone_wall, "plaster_white": mat_plaster, "wood_dark": mat_wood_dark, "roof_tile": mat_roof_tile,
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
    rng = np.random.default_rng(seed + sum(map(ord, name)))
    m = MATERIALS[name](n, rng)
    albedo = np.clip(m["albedo"], 0, 1)
    h = np.clip(m["height"], 0, None)
    h = (h - h.min()) / max(h.max() - h.min(), 1e-9)
    normal = normal_from_height(h, m["ns"] * 0.25 * n / 256.0 * 0.5)
    ao = ao_from_height(h, *m["ao"])
    rough = np.clip(np.broadcast_to(m["rough"], (n, n)), 0.05, 1)
    orm = np.stack([ao, rough, np.zeros_like(ao)], -1)
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
