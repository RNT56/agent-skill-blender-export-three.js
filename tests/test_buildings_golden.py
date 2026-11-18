"""Golden regression for the village buildings:
    blender -b fixtures/minka.blend    -P tests/test_buildings_golden.py -- minka_01
    blender -b fixtures/teahouse.blend -P tests/test_buildings_golden.py -- teahouse_01
Needs the tileable textures first (bin/gp textures specs/biomes.json)."""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "gamepipe"))
import gp_cli
import gp_glb

GOLDEN = {   # spec -> (LOD tri ranges, width range m, height range m, materials that must exist)
    "minka_01": ({"LOD0": (9000, 18000), "LOD1": (2500, 6000), "LOD2": (400, 2000)}, (13, 17), (8, 11), ["minka_thatch", "minka_plaster", "minka_stone", "minka_wood"]),
    "teahouse_01": ({"LOD0": (15000, 28000), "LOD1": (4500, 9000), "LOD2": (400, 2500)}, (10, 14), (9, 12), ["tea_tile", "tea_plaster", "tea_wood", "tea_woodl"]),
}
name = sys.argv[sys.argv.index("--") + 1]
lods, wr, hr, mats = GOLDEN[name]
fails = []


def check(n, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + n + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(n)


tmp = tempfile.mkdtemp()
try:
    res = gp_cli.run(os.path.join(ROOT, "specs", f"{name}.json"), preview=False, out_override=tmp)
    check(f"{name}: passes validation + export", res["passed"])
    out = os.path.join(tmp, name)
    man = json.load(open(os.path.join(out, "manifest.json")))
    by = {l["name"]: l for l in man["lods"]}
    for lod, (lo, hi) in lods.items():
        check(f"{name} {lod} triangles in {lo}-{hi}", lod in by and lo <= by[lod]["tris"] <= hi, str(by.get(lod, {}).get("tris")))
    dims = by["LOD0"]["dimensions_m"]
    check(f"{name}: real-world width {wr} m and height {hr} m", wr[0] < max(dims[0], dims[1]) < wr[1] + 6 and hr[0] < dims[2] < hr[1], str(dims))
    info = gp_glb.inspect(os.path.join(out, f"{name}.glb"))
    present = {m["name"] for m in info["materials"]}
    check("expected materials present", all(m in present for m in mats), str(present))
    check("all textures KTX2-only", {i["mime"] for i in info["images"]} == {"image/ktx2"})
    check("PBR: every textured material has albedo + normal + occlusion/roughness",
          all(m["baseColorTexture"] and m["normalTexture"] and m["occlusionTexture"] for m in info["materials"] if m["name"] in mats))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nALL PASSED" if not fails else "\nFAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
