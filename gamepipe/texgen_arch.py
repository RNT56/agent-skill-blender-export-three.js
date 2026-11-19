"""Architecture materials for the Samurai Vale kits (walls, towers, settlement buildings): tileable PBR sets authored for roofs and walls seen from an RTS
camera, where the silhouette of a course of thatch or a row of shingles has to read at forty metres and still hold up at ten.

  thatch_kaya      kayabuki: courses of reed with ragged butt ends, strands running DOWN the slope (image Y), bleached tips, damp and moss
  wood_shingle     kokerabuki / itabuki: staggered rows of split shingles of uneven width, wedge-thick at the butt, silvered cedar
  timber_dark      aged or charred cedar boards of uneven width, grain ALONG the board (image Y), knots, cathedral figure
  timber_pale      hinoki / weathered pale boards, the same build, honey to silver
  stone_nozura     nozura-zumi: undressed field stone fitted dry, pillowed faces, chinking stones and earth in the joints, lichen
  plaster_shikkui  lime plaster: trowel sweep, rain streaks, hairline crazing
  earth_wall       tsuchikabe: ochre daub with chopped straw, fine shrinkage cracks, damp patches
  paper_washi      shoji paper: warm fibre flecked white (the lattice is geometry)

Registered into gp_texgen.MATERIALS by register(); build with   bin/gp textures specs/arch_textures.json --out out/textures_arch   and copy the
images into out/textures (the spec is kept apart so the biome manifest and contact sheet are not overwritten).
Convention as in gp_texgen: each material returns dict(albedo, height, rough, ao=(radius, k), ns); image row 0 is UP.
"""
import numpy as np


def register(T):
    fbm, blur, smooth, lerp, col, _vor, _wsample = T["fbm"], T["blur"], T["smooth"], T["lerp"], T["col"], T["_vor"], T["_wsample"]

    def grid(n):
        ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
        return xs / n, ys / n

    def line1(n, beta, rng, amp=1.0):
        """periodic 1-D noise along X (the same in every row), -amp..amp"""
        return ((fbm(n, beta, rng)[0] * 2 - 1) * amp).astype(np.float32)[None, :].repeat(n, 0)

    def row_cells(u, row, rows, kmin, kmax, rng):
        """every row cut into k cells of random width (periodic in u). @returns id (0..1), dist (to the nearest side edge, tile units), f (0..1 across the cell)"""
        cid = np.zeros(u.shape, np.float32)
        dist = np.full(u.shape, 9.0, np.float32)
        frac = np.zeros(u.shape, np.float32)
        for r in range(rows):
            k = int(rng.integers(kmin, kmax + 1))
            w = 0.55 + rng.random(k)
            cuts = np.cumsum(w) / w.sum()
            cuts = (np.concatenate([[0.0], cuts[:-1]]) + rng.random()) % 1.0
            cuts.sort()
            cuts = np.concatenate([cuts, [cuts[0] + 1.0]])
            ids = rng.random(k).astype(np.float32)
            m = row == r
            uu = u[m]
            bid, bd, bf = np.zeros(uu.shape, np.float32), np.full(uu.shape, 9.0, np.float32), np.zeros(uu.shape, np.float32)
            for i in range(k):
                lo, wd = cuts[i], cuts[i + 1] - cuts[i]
                rel = (uu - lo) % 1.0
                inside = rel < wd
                bid = np.where(inside, ids[i], bid)
                bd = np.where(inside, np.minimum(rel, wd - rel), bd)
                bf = np.where(inside, rel / wd, bf)
            cid[m], dist[m], frac[m] = bid, bd, bf
        return cid, dist, frac

    def h1(a, k=12.9898):
        return ((np.sin(a * k) * 43758.5453) % 1.0).astype(np.float32)

    # ------------------------------------------------------------------------------------------------ thatch
    def mat_thatch_kaya(n, rng):
        courses = 6
        u, v = grid(n)
        rag = line1(n, 0.7, rng, 0.16) + line1(n, 1.8, rng, 0.10)             # the butt line of a course is never ruled
        vv = v * courses + rag
        cid = np.floor(vv).astype(int) % courses
        vf = vv - np.floor(vv)                                                # 0 under the course above ... 1 at the butt ends
        s1 = fbm(n, 0.9, rng, stretch=(0.03, 1.0))                            # reeds: long in Y
        s2 = fbm(n, 0.25, rng, stretch=(0.02, 0.45))
        shift = (cid * 0.371) % 1.0                                           # every course is its own layer of reeds
        s1 = _wsample(s1, u + shift, v)
        s2 = _wsample(s2, u + shift * 1.7, v)
        strands = np.clip(0.55 * s1 + 0.45 * s2, 0, 1)
        tone = (0.5 + 0.5 * rng.random(courses).astype(np.float32))[cid]
        patch = fbm(n, 2.6, rng)
        damp = smooth(fbm(n, 2.2, rng), 0.55, 0.9)
        tip = smooth(vf, 0.55, 1.0)                                           # the weathered ends bleach
        base = lerp(col(0.17, 0.13, 0.085), col(0.60, 0.50, 0.33), strands ** 1.1)
        base = lerp(base, col(0.74, 0.67, 0.50), tip * (0.35 + 0.4 * strands))
        a = base * (0.80 + 0.30 * tone[..., None]) * (0.86 + 0.28 * patch[..., None])
        a = lerp(a, a * col(0.62, 0.60, 0.58), damp * 0.6)                    # grey damp
        moss = smooth(fbm(n, 2.8, rng), 0.62, 0.86) * (1 - 0.5 * tip)
        a = lerp(a, col(0.27, 0.31, 0.13), moss * 0.38)
        under = smooth(vf, 0.0, 0.16)                                         # the shadow under the course above
        a = a * (0.5 + 0.5 * under[..., None])
        ends = smooth(vf, 0.93, 1.0)                                          # cut ends: a darker, speckled lip
        a = a * (1 - 0.28 * ends[..., None] * (0.5 + 0.5 * fbm(n, 0.2, rng))[..., None])
        h = 0.18 + 0.62 * vf ** 0.9 + 0.20 * strands * (0.4 + 0.6 * vf) - 0.25 * ends * (1 - strands)
        return dict(albedo=a, height=h, rough=0.97, ao=(7, 7.5), ns=5.0)

    # ------------------------------------------------------------------------------------------------ shingles
    def mat_wood_shingle(n, rng):
        rows = 8
        u, v = grid(n)
        vr = v * rows
        r0 = np.floor(vr).astype(int) % rows
        vf = vr - np.floor(vr)
        rngs = np.random.default_rng(int(rng.integers(1 << 30)))
        # cells of this row and of the row above (whose butts hang down into this one by a random amount)
        state = rngs.bit_generator.state
        id0, d0, f0 = row_cells(u, r0, rows, 9, 13, rngs)
        rngs.bit_generator.state = state
        idp, dp, fp = row_cells(u, (r0 - 1) % rows, rows, 9, 13, rngs)
        offp = 0.02 + 0.16 * h1(idp * 91.7)
        above = vf < offp                                                     # still the shingle of the row above
        sid = np.where(above, idp, id0)
        sd = np.where(above, dp, d0)
        sf = np.where(above, fp, f0)
        pos = np.where(above, 1.0, (vf - offp) / np.maximum(1 - offp, 1e-3))  # 0 top of the shingle ... 1 its butt
        gapw = 0.0035
        gap = smooth(sd, 0.0, gapw)
        grain = fbm(n, 0.9, rng, stretch=(0.035, 1.0))
        fine = fbm(n, 0.3, rng, stretch=(0.02, 0.5))
        g = _wsample(grain, u + sid * 0.37, v + sid * 0.61)                   # every shingle its own piece of wood
        tone = h1(sid * 37.1)
        hue = h1(sid * 5.3)
        silver = smooth(fbm(n, 2.4, rng), 0.35, 0.8)
        a = lerp(col(0.20, 0.14, 0.10), col(0.47, 0.36, 0.25), np.clip(0.6 * g + 0.4 * fine, 0, 1))
        a = lerp(a, col(0.50, 0.49, 0.45), np.clip(0.25 + 0.6 * silver + 0.3 * (hue - 0.5), 0, 0.9))      # cedar silvers in the weather
        a = a * (0.72 + 0.42 * tone[..., None])
        new = (h1(sid * 113.0) > 0.94)[..., None]                             # a repair here and there: a newer, warmer shingle
        a = np.where(new, lerp(a, col(0.62, 0.47, 0.30), 0.55), a)
        lichen = smooth(fbm(n, 2.9, rng), 0.68, 0.9)
        a = lerp(a, col(0.33, 0.38, 0.20), lichen * 0.4)
        topsh = np.where(above, 1.0, smooth(vf - offp, 0.0, 0.10))            # shadow cast by the butt above
        a = a * (0.40 + 0.60 * topsh[..., None]) * (0.45 + 0.55 * gap[..., None])
        butt = np.where(above, np.clip((vf - offp + 0.035) / 0.035, 0, 1), 0.0)           # the cut edge catches a little light
        a = a + (butt * 0.05)[..., None]
        cup = (np.abs(sf - 0.5) * 2) ** 2                                     # shingles cup as they dry
        tilt = (h1(sid * 71.3) - 0.5)
        h = (0.25 + 0.55 * pos + 0.10 * cup + 0.12 * tilt * (sf - 0.5) + 0.06 * g) * gap
        return dict(albedo=a, height=h, rough=0.86, ao=(5, 7.0), ns=5.5)

    # ------------------------------------------------------------------------------------------------ boards
    def boards(n, rng, kmin, kmax, dark):
        u, v = grid(n)
        rngs = np.random.default_rng(int(rng.integers(1 << 30)))
        bid, bd, bf = row_cells(u, np.zeros(u.shape, int), 1, kmin, kmax, rngs)
        gap = smooth(bd, 0.0, 0.0045)
        cham = smooth(bd, 0.0, 0.016)
        streak = fbm(n, 1.0, rng, stretch=(0.03, 1.0))
        fine = fbm(n, 0.3, rng, stretch=(0.018, 0.4))
        g = _wsample(streak, u + bid * 0.41, v + bid * 0.23)
        wob = _wsample(fbm(n, 3.2, rng), u * 0.0 + bid, v + bid * 0.7)        # the heart of the figure wanders along the board
        cath = np.abs(bf - 0.5 - (wob - 0.5) * 0.5)
        rings = 0.5 + 0.5 * np.sin(2 * np.pi * (cath * (7 + 6 * h1(bid * 3.1)) + g * 1.6))
        # knots: a few per tile, dark with a pale halo that bends the figure
        kn = _vor(n, 5, 4, rng, jitter=0.95)
        has = h1(kn["id"] * 57.0) > 0.62
        kr = np.sqrt((kn["lx"] * 2.6) ** 2 + (kn["ly"] * 1.2) ** 2)
        knot = np.where(has, 1 - smooth(kr, 0.05, 0.11), 0.0)
        halo = np.where(has, 1 - smooth(kr, 0.10, 0.30), 0.0)
        tone = h1(bid * 23.7)
        fig = np.clip(0.42 * g + 0.26 * fine + 0.32 * rings + 0.12 * halo, 0, 1)
        weather = fbm(n, 2.5, rng)
        if dark:
            a = lerp(col(0.085, 0.060, 0.042), col(0.43, 0.30, 0.19), fig ** 1.15)
            a = lerp(a, col(0.21, 0.20, 0.185), smooth(weather, 0.55, 0.9) * 0.45)                      # greyed where the rain reaches
            a = a * (0.74 + 0.46 * tone[..., None])
            rough = 0.78
        else:
            a = lerp(col(0.30, 0.215, 0.135), col(0.72, 0.585, 0.40), fig)
            a = lerp(a, col(0.56, 0.54, 0.49), smooth(weather, 0.5, 0.9) * 0.5)
            a = a * (0.84 + 0.28 * tone[..., None])
            rough = 0.82
        a = a * (1 - 0.72 * knot[..., None])
        a = a * (0.28 + 0.72 * gap[..., None]) * (0.86 + 0.14 * cham[..., None])
        stain = smooth(fbm(n, 1.6, rng, stretch=(0.12, 1.0)), 0.7, 0.95)      # runs of rain down the boards
        a = a * (1 - 0.22 * stain[..., None])
        h = gap * (0.55 + 0.12 * cham + 0.16 * g + 0.10 * rings - 0.25 * knot + 0.08 * (tone - 0.5))
        return dict(albedo=a, height=h, rough=rough, ao=(4, 6.0), ns=3.4)

    def mat_timber_dark(n, rng):
        return boards(n, rng, 7, 9, True)

    def mat_timber_pale(n, rng):
        return boards(n, rng, 6, 8, False)

    # ------------------------------------------------------------------------------------------------ field stone
    def mat_stone_nozura(n, rng):
        wx, wy = fbm(n, 3.6, rng), fbm(n, 3.6, rng)
        big = _vor(n, 6, 8, rng, warp=(wx, wy, 0.55), jitter=0.95)
        small = _vor(n, 17, 21, rng, warp=(wy, wx, 0.4), jitter=0.95)
        e = big["edge"]
        joint = smooth(e, 0.012, 0.055)
        pillow = smooth(e, 0.0, 0.34) ** 0.55
        # chinking: little stones packed into the wider joints
        chink_zone = 1 - smooth(e, 0.03, 0.075)
        cj = smooth(small["edge"], 0.02, 0.09)
        surf = fbm(n, 1.5, rng)
        pit = fbm(n, 0.45, rng)
        sid = big["id"]
        tone = 0.30 + 0.30 * h1(sid * 17.3)
        hue = h1(sid * 7.7)
        stone = tone[..., None] * (0.78 + 0.34 * surf[..., None]) * (0.92 + 0.14 * pit[..., None]) * col(1.0, 0.985, 0.95)
        stone = stone + ((hue - 0.5) * 0.10)[..., None] * col(1.0, 0.35, -0.7)                           # warm and cool stones
        facet = (big["lx"] * (h1(sid * 3.3) - 0.5) + big["ly"] * (h1(sid * 9.1) - 0.5)) * 0.5              # each face leans its own way
        stone = stone * (1 + facet[..., None] * 0.5)
        chink = (0.22 + 0.2 * h1(small["id"] * 31.0))[..., None] * col(1.0, 0.97, 0.92) * (0.5 + 0.5 * cj[..., None])
        earth = col(0.085, 0.070, 0.052)
        a = lerp(lerp(earth, chink, cj * 0.85), stone, joint)
        a = np.where((chink_zone > 0.5)[..., None] & (joint < 0.5)[..., None], lerp(earth, chink, cj * 0.9), a)
        lichen = smooth(fbm(n, 2.7, rng), 0.60, 0.86) * joint
        a = lerp(a, col(0.36, 0.40, 0.22), lichen * 0.42)
        mossj = (1 - joint) * smooth(fbm(n, 2.2, rng), 0.45, 0.8)
        a = lerp(a, col(0.15, 0.22, 0.07), mossj * 0.6)
        white = smooth(fbm(n, 1.2, rng), 0.78, 0.95) * joint                  # pale crusts of lichen
        a = lerp(a, col(0.62, 0.62, 0.56), white * 0.3)
        h = joint * (0.35 + 0.55 * pillow + 0.12 * surf + 0.05 * pit + 0.4 * facet) + (1 - joint) * 0.16 * cj * chink_zone
        return dict(albedo=a, height=h, rough=0.93, ao=(8, 8.0), ns=6.5)

    # ------------------------------------------------------------------------------------------------ plaster, earth, paper
    def mat_plaster_shikkui(n, rng):
        sweep = fbm(n, 1.7, rng, stretch=(0.3, 1.0))
        cloud = fbm(n, 2.8, rng)
        fine = fbm(n, 0.4, rng)
        runs = smooth(fbm(n, 1.5, rng, stretch=(0.10, 1.0)), 0.62, 0.95)      # rain runs
        a = lerp(col(0.79, 0.77, 0.71), col(0.93, 0.915, 0.86), 0.6 * sweep + 0.4 * cloud)
        a = a * (0.95 + 0.08 * fine[..., None])
        a = lerp(a, col(0.60, 0.585, 0.53), runs * 0.42)
        stain = smooth(cloud, 0.68, 0.96)
        a = lerp(a, col(0.66, 0.62, 0.52), stain * 0.4)
        cr = _vor(n, 5, 6, rng, warp=(fbm(n, 3.0, rng), fbm(n, 3.0, rng), 0.7))
        hair = (1 - smooth(cr["edge"], 0.0, 0.006)) * smooth(fbm(n, 2.4, rng), 0.45, 0.7)                # crazing, only in patches
        a = a * (1 - 0.38 * hair[..., None])
        h = 0.34 * sweep + 0.14 * fine + 0.2 * cloud - 0.35 * hair
        return dict(albedo=a, height=h, rough=0.9, ao=(5, 3.0), ns=1.5)

    def mat_earth_wall(n, rng):
        cloud = fbm(n, 2.6, rng)
        grit = fbm(n, 0.35, rng)
        sweep = fbm(n, 1.6, rng, stretch=(1.0, 0.35))
        a = lerp(col(0.36, 0.27, 0.17), col(0.60, 0.48, 0.31), 0.5 * cloud + 0.3 * sweep + 0.2 * grit)
        # chopped straw in the daub: short pale flecks lying every way
        s1 = smooth(fbm(n, 0.2, rng, stretch=(1.0, 0.07)), 0.80, 0.9)
        s2 = smooth(fbm(n, 0.2, rng, stretch=(0.07, 1.0)), 0.82, 0.92)
        s3 = smooth(_wsample(fbm(n, 0.2, rng, stretch=(1.0, 0.07)), *((lambda uu, vv: (uu + vv * 0.6, vv - uu * 0.6))(*grid(n)))), 0.83, 0.92)
        straw = np.clip(s1 + s2 + s3, 0, 1)
        a = lerp(a, col(0.74, 0.65, 0.42), straw * 0.6)
        peb = _vor(n, 26, 26, rng, jitter=1.0)
        pm = (h1(peb["id"] * 91.0) > 0.86) * (1 - smooth(peb["d1"], 0.12, 0.26))
        a = lerp(a, col(0.42, 0.40, 0.37), pm * 0.7)
        cr = _vor(n, 7, 7, rng, warp=(fbm(n, 3.0, rng), fbm(n, 3.0, rng), 0.8))
        crack = (1 - smooth(cr["edge"], 0.0, 0.010)) * smooth(fbm(n, 2.2, rng), 0.35, 0.6)
        a = a * (1 - 0.5 * crack[..., None])
        damp = smooth(fbm(n, 2.4, rng), 0.62, 0.9)
        a = lerp(a, a * col(0.66, 0.66, 0.64), damp * 0.7)
        h = 0.3 * cloud + 0.22 * grit + 0.2 * sweep + 0.16 * straw + 0.2 * pm - 0.5 * crack
        return dict(albedo=a, height=h, rough=0.95, ao=(5, 4.0), ns=2.6)

    def mat_paper_washi(n, rng):
        cloud = fbm(n, 2.4, rng)
        fib = np.clip(smooth(fbm(n, 0.2, rng, stretch=(1.0, 0.05)), 0.78, 0.9) + smooth(fbm(n, 0.2, rng, stretch=(0.05, 1.0)), 0.8, 0.92), 0, 1)
        a = lerp(col(0.74, 0.69, 0.57), col(0.90, 0.86, 0.75), cloud)
        a = lerp(a, col(0.97, 0.94, 0.86), fib * 0.5)
        stain = smooth(fbm(n, 2.9, rng), 0.66, 0.92)
        a = lerp(a, col(0.62, 0.55, 0.40), stain * 0.45)
        return dict(albedo=a, height=0.4 * cloud + 0.5 * fib, rough=0.85, ao=(4, 1.5), ns=0.8)

    T["MATERIALS"].update({"thatch_kaya": mat_thatch_kaya, "wood_shingle": mat_wood_shingle, "timber_dark": mat_timber_dark, "timber_pale": mat_timber_pale,
                           "stone_nozura": mat_stone_nozura, "plaster_shikkui": mat_plaster_shikkui, "earth_wall": mat_earth_wall, "paper_washi": mat_paper_washi})
