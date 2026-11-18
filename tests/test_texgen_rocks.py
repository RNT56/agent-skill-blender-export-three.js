"""Rock / earth texture set (cliff_strata, granite, scree, red_clay, mossy_rock, basalt; specs/rocks.json).
Pure numpy, NO Blender needed:   python3 tests/test_texgen_rocks.py   (or: blender -b --factory-startup -P tests/test_texgen_rocks.py).
Checks at 256 px: registration, shapes, ranges, tileability (every map), ORM convention (R=AO, G=roughness 0.6-0.95,
B = normalised HEIGHT, not constant 0), relief strength of the normal map, determinism, and that older materials keep B = 0."""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "gamepipe"))
import gp_texgen as T

ROCKS = ["cliff_strata", "granite", "scree", "red_clay", "mossy_rock", "basalt"]
N = 256
fails = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# spec lists exactly the six and biomes.json is untouched by them
spec = json.load(open(os.path.join(ROOT, "specs", "rocks.json")))
biomes = json.load(open(os.path.join(ROOT, "specs", "biomes.json")))
check("rocks.json lists exactly the six rock materials", spec["materials"] == ROCKS, str(spec["materials"]))
check("rocks.json: size 1024, own seed", spec.get("size") == 1024 and spec.get("seed") != biomes.get("seed"))
check("biomes.json does not list the rock materials", not (set(ROCKS) & set(biomes["materials"])))

for name in ROCKS:
    check(f"{name}: registered in MATERIALS", name in T.MATERIALS)
    a, nm, o = T.build_one(name, N, spec["seed"])
    check(f"{name}: shapes", a.shape == nm.shape == o.shape == (N, N, 3), f"{a.shape} {nm.shape} {o.shape}")
    check(f"{name}: finite, 0..1", all(np.isfinite(x).all() and x.min() >= 0 and x.max() <= 1 for x in (a, nm, o)))
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    check(f"{name}: albedo luminance within 0.08..0.75 (min {lum.min():.3f}, max {lum.max():.3f})", lum.min() >= 0.075 and lum.max() <= 0.76)
    check(f"{name}: albedo has variation (std {lum.std():.3f})", lum.std() >= 0.03)
    ao, rough, height = o[..., 0], o[..., 1], o[..., 2]
    check(f"{name}: ORM.R = AO, strong in cracks/ledges (min {ao.min():.2f}, mean {ao.mean():.2f})", ao.min() <= 0.4 and ao.mean() >= 0.5)
    check(f"{name}: ORM.G roughness within 0.6..0.95 ({rough.min():.2f}..{rough.max():.2f})", rough.min() >= 0.599 and rough.max() <= 0.951)
    check(f"{name}: ORM.B is HEIGHT, not constant 0 (range {height.min():.2f}..{height.max():.2f}, std {height.std():.2f})",
          height.max() - height.min() > 0.95 and height.std() > 0.05)
    n3 = nm * 2.0 - 1.0
    ln = np.sqrt((n3 ** 2).sum(-1))
    check(f"{name}: normals unit length", abs(float(ln.mean()) - 1.0) < 0.02 and float(ln.min()) > 0.9)
    check(f"{name}: normal mean z {nm[..., 2].mean():.2f} >= 0.75 (check_set limit)", nm[..., 2].mean() >= 0.75)
    check(f"{name}: normals carry real relief (std xy {n3[..., :2].std():.3f})", n3[..., :2].std() >= 0.04)
    for label, arr in (("albedo", a), ("normal", nm), ("orm", o)):
        r = T.seam_ratio(arr)
        check(f"{name}: {label} seamless (seam ratio {r:.2f})", r <= 1.2, f"{r:.2f}")
    res = T.check_set(name, a, nm, o)
    check(f"{name}: check_set raises no errors", not [f for f in res["findings"] if f[0] == "error"], str(res["findings"]))
    a2, n2, o2 = T.build_one(name, N, spec["seed"])
    check(f"{name}: deterministic", np.array_equal(a, a2) and np.array_equal(o, o2))

# the six must differ from each other (mean colour or contrast) so the game can tell them apart
stats = {}
for name in ROCKS:
    a, _, _ = T.build_one(name, N, spec["seed"])
    stats[name] = a.reshape(-1, 3).mean(0)
for i, x in enumerate(ROCKS):
    for y in ROCKS[i + 1:]:
        d = float(np.abs(stats[x] - stats[y]).sum())
        check(f"{x} vs {y}: distinct mean colour (d={d:.2f})", d >= 0.08, f"{d:.3f}")

# older materials keep B = 0 (metalness) and the default code path
_, _, o_old = T.build_one("meadow", 64, 7)
check("existing materials still write ORM.B = 0", float(o_old[..., 2].max()) == 0.0)

print("\nALL PASSED" if not fails else "\nFAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
