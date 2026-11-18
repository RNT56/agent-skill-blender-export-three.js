"""Golden regression for the samurai keep:  blender -b fixtures/samurai_keep.blend -P tests/test_keep_golden.py
Needs the tileable textures first:  bin/gp textures specs/biomes.json   (bin/gp test does this).
Checks the BUILT outputs against golden ranges so a generator/pipeline change cannot quietly degrade the asset."""
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

fails = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


GOLDEN = {"LOD0": (50000, 70000), "LOD1": (12000, 20000), "LOD2": (3000, 6000)}
tmp = tempfile.mkdtemp()
try:
    res = gp_cli.run(os.path.join(ROOT, "specs", "samurai_keep_01.json"), preview=False, out_override=tmp)
    check("keep passes validation + export", res["passed"])
    out = os.path.join(tmp, "samurai_keep_01")
    man = json.load(open(os.path.join(out, "manifest.json")))
    by = {l["name"]: l for l in man["lods"]}
    for lod, (lo, hi) in GOLDEN.items():
        l = by.get(lod)
        check(f"{lod} present in manifest", l is not None)
        if l:
            check(f"{lod} triangles in golden range {lo}-{hi}", lo <= l["tris"] <= hi, str(l["tris"]))
    glb = os.path.join(out, "samurai_keep_01.glb")
    info = gp_glb.inspect(glb)
    names = {m["name"] for m in info["materials"]}
    check("5 materials (stone, plaster, wood, tile, gold)", len(names) == 5, str(names))
    textured = [m for m in info["materials"] if "gold" not in m["name"]]
    check("the 4 building materials have albedo + normal + occlusion/roughness",
          len(textured) == 4 and all(m["baseColorTexture"] and m["normalTexture"] and m["occlusionTexture"] for m in textured))
    check("all textures are KTX2 only (no duplicate fallbacks)", {i["mime"] for i in info["images"]} == {"image/ktx2"}, str(info["images"]))
    check("one shared GLB holds all LODs under 12 MB", os.path.getsize(glb) < 12 * 1048576, str(os.path.getsize(glb)))
    j = gp_glb.read_json(glb)
    mesh_names = {n.get("name", "") for n in j["nodes"]}
    for lod in ("LOD0", "LOD1", "LOD2"):
        check(f"nodes for {lod} exist (engine selects by name)", any(f"_{lod}_" in n for n in mesh_names))
    dims = by["LOD0"]["dimensions_m"]
    check("real-world scale: ~18 m wide, 20-30 m tall", 16 < dims[0] < 22 and 20 < dims[2] < 30, str(dims))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nALL PASSED" if not fails else "\nFAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
