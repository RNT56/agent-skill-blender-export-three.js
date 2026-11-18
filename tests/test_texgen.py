"""Headless:  blender -b --factory-startup -P tests/test_texgen.py
Texture generator: tileability by construction AND the checker's ability to FAIL (a checker that cannot fail proves nothing),
image-orientation round trip (Blender images are bottom-up), JPEG-vs-PNG data-channel integrity."""
import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "gamepipe"))
import gp_texgen as T

fails = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# 1. every material generator is seamless in memory (before any file format touches it)
for name in T.MATERIALS:
    a, n, o = T.build_one(name, 256, 7)
    worst = max(T.seam_ratio(a), T.seam_ratio(n), T.seam_ratio(o))
    check(f"{name}: seamless by construction (seam ratio {worst:.2f})", worst <= 1.2, f"{worst:.2f}")

# 2. the checker catches a NON-tileable texture: smooth content cut at the edge
rng = np.random.default_rng(3)
ys, xs = np.mgrid[0:256, 0:256].astype(np.float32) / 256
broken = np.stack([0.2 + 0.6 * xs, 0.3 + 0.5 * ys, 0.5 + 0.2 * np.sin(6 * xs + 3 * ys)], -1)     # ramps: left edge != right edge
check("checker FAILS a non-tileable ramp texture", T.seam_ratio(broken) > 1.6, f"{T.seam_ratio(broken):.2f}")
res = T.check_set("broken", broken, broken, broken)
check("check_set reports NOT_TILEABLE for it", any(f[1] == "NOT_TILEABLE" for f in res["findings"]))

# 3. checker catches a flat texture and an absurdly bright albedo
flat = np.full((64, 64, 3), 0.5, np.float32)
check("flat albedo flagged TEX_FLAT", any(f[1] == "TEX_FLAT" for f in T.check_set("flat", flat, flat, flat)["findings"]))
white = np.clip(np.random.default_rng(1).random((64, 64, 3)) * 0.05 + 0.95, 0, 1).astype(np.float32)
check("over-bright albedo flagged ALBEDO_RANGE", any(f[1] == "ALBEDO_RANGE" for f in T.check_set("white", white, white, white)["findings"]))

# 4. orientation round trip: row 0 must stay row 0 through save + load
tmp = tempfile.mkdtemp()
try:
    arr = np.zeros((32, 32, 3), np.float32)
    arr[0, :, 0] = 1.0           # top row red
    arr[-1, :, 2] = 1.0          # bottom row blue
    p = os.path.join(tmp, "o.png")
    T.save_img(p, arr)
    back = T.load_img(p)
    check("PNG round trip keeps top row on top", back[0, 0, 0] > 0.9 and back[-1, 0, 2] > 0.9, f"top={back[0,0]} bottom={back[-1,0]}")

    # 5. data channels survive PNG exactly (the reason ORM/normal are PNG, not JPEG)
    orm = np.stack([rng.random((64, 64)), rng.random((64, 64)), np.zeros((64, 64))], -1).astype(np.float32)
    T.save_img(os.path.join(tmp, "d.png"), orm)
    back = T.load_img(os.path.join(tmp, "d.png"))
    err = float(np.abs(back - orm).max())
    check("ORM-style data survives PNG (max err < 1/255)", err < 0.006, f"{err:.4f}")
    T.save_img(os.path.join(tmp, "d.jpg"), orm)
    errj = float(np.abs(T.load_img(os.path.join(tmp, "d.jpg")) - orm).max())
    check("... and would NOT survive JPEG (documents why)", errj > 0.02, f"{errj:.4f}")

    # 6. full run on a small spec writes the files + manifest and passes
    spec = {"name": "t", "size": 256, "seed": 7, "materials": ["meadow", "roof_tile", "stone_wall"]}
    sp = os.path.join(tmp, "s.json")
    json.dump(spec, open(sp, "w"))
    ok = T.run(sp, out_override=os.path.join(tmp, "out"))
    check("texgen.run passes on 3 materials", ok)
    for m in spec["materials"]:
        for k in ("albedo.jpg", "normal.png", "orm.png"):
            check(f"wrote {m}_{k}", os.path.exists(os.path.join(tmp, "out", f"{m}_{k}")))
    man = json.load(open(os.path.join(tmp, "out", "manifest.json")))
    check("manifest.json records passed=true", man["passed"] is True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nALL PASSED" if not fails else "\nFAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
