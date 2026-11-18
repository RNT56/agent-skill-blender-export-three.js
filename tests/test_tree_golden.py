"""Golden regression:  blender -b fixtures/tree_source.blend -P tests/test_tree_golden.py
Rebuilds the hero tree from the fixture and checks the real outputs against golden ranges. If a recipe change quietly
degrades the tree (blank texture, lost occlusion, blended leaves, budget drift), this fails."""
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


GOLDEN = {  # LOD -> (min tris, max tris)
    "LOD0": (30000, 40000), "LOD1": (10000, 14000), "LOD2": (1500, 4000), "LOD3": (4, 20),
}

tmp = tempfile.mkdtemp()
try:
    res = gp_cli.run(os.path.join(ROOT, "specs", "tree_autumn_01.json"), preview=False, out_override=tmp)
    check("all four LODs pass validation + export", res["passed"])
    out = os.path.join(tmp, "tree_autumn_01")
    man = json.load(open(os.path.join(out, "manifest.json")))
    by = {l["name"]: l for l in man["lods"]}
    for lod, (lo, hi) in GOLDEN.items():
        l = by.get(lod)
        check(f"{lod} present", l is not None)
        if l:
            check(f"{lod} triangles in golden range {lo}-{hi}", lo <= l["tris"] <= hi, str(l["tris"]))
            check(f"{lod} file exists and is compressed", l["file"] and l["compressed"])
            check(f"{lod} under 10 MB", (l["size_mb"] or 99) < 10, str(l["size_mb"]))
    lod0 = gp_glb.inspect(os.path.join(out, "tree_autumn_01_LOD0.glb"))
    mats = {m["name"]: m for m in lod0["materials"]}
    leaf = next(m for n, m in mats.items() if "leaf" in n)
    bark = next(m for n, m in mats.items() if "bark" in n)
    check("leaves are alphaMode MASK (cutout)", leaf["alphaMode"] == "MASK")
    check("bark has albedo + normal + occlusion/roughness", bark["baseColorTexture"] and bark["normalTexture"] and bark["occlusionTexture"])
    check("meshopt + basisu extensions present", {"EXT_meshopt_compression", "KHR_texture_basisu"} <= set(lod0["extensionsUsed"]),
          str(lod0["extensionsUsed"]))
    mimes = {i["mime"] for i in lod0["images"]}
    check("LOD0 textures are KTX2 only (no duplicate PNG/JPEG fallbacks)", mimes == {"image/ktx2"}, str(mimes))
    check("LOD0 requires KHR_texture_basisu", "KHR_texture_basisu" in gp_glb.read_json(os.path.join(out, "tree_autumn_01_LOD0.glb")).get("extensionsRequired", []))
    tex = os.listdir(os.path.join(out, "textures"))
    for need in ("tree_autumn_01_bark_albedo.jpg", "tree_autumn_01_bark_normal.png", "tree_autumn_01_bark_orm.png",
                 "tree_autumn_01_leaves.png", "tree_autumn_01_impostor.png"):
        check(f"texture {need}", need in tex)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nALL PASSED" if not fails else "\nFAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
