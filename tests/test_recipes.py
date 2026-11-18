"""Headless:  blender -b --factory-startup -P tests/test_recipes.py
Second recipe (prop/rock) on a synthetic asset + recipe-contract enforcement. Proves the pipeline is not tree-specific."""
import json
import os
import shutil
import sys
import tempfile

import bpy
import bmesh
from mathutils import noise, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "gamepipe"))
import gp_cli
import gp_glb

fails = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def make_rock():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=5, radius=0.5)
    for v in bm.verts:
        d = noise.noise(v.co * 3.0) * 0.12 + noise.noise(v.co * 9.0) * 0.03
        v.co += v.co.normalized() * d
    me = bpy.data.meshes.new("Rock")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Rock", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = (0, 0, 0.5)
    for p in me.polygons:
        p.use_smooth = True
    m = bpy.data.materials.new("RockMat")
    m.use_nodes = True
    nt = m.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 6
    cr = nt.nodes.new("ShaderNodeValToRGB")
    cr.color_ramp.elements[0].color = (0.05, 0.05, 0.05, 1)
    cr.color_ramp.elements[1].color = (0.55, 0.5, 0.45, 1)
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    nt.links.new(n.outputs["Fac"], cr.inputs["Fac"])
    nt.links.new(cr.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    me.materials.append(m)
    return ob


tmp = tempfile.mkdtemp()
try:
    make_rock()
    spec = {
        "name": "rock_test_01", "type": "rock", "recipe": "prop",
        "budgets": {"max_materials": 1, "max_texture_px": 1024, "max_file_mb": 6},
        "rules": {"origin_tolerance": 0.2},
        "recipe_cfg": {"obj": "Rock", "tex_px": 512,
                       "lods": [{"name": "LOD0", "tris": 5000, "max_tris": 6000}, {"name": "LOD1", "tris": 800, "max_tris": 1200}]},
        "glb_expect": {"occlusion": ["rock_test_01"]},
        "export": {"out_dir": "out", "compress": True},
    }
    sp = os.path.join(tmp, "rock.json")
    json.dump(spec, open(sp, "w"))
    res = gp_cli.run(sp, preview=False, out_override=tmp)
    check("rock recipe: all LODs pass", res["passed"])
    out = os.path.join(tmp, "rock_test_01")
    for lod in ("LOD0", "LOD1"):
        g = os.path.join(out, f"rock_test_01_{lod}.glb")
        check(f"rock {lod} glb exists", os.path.exists(g))
        if os.path.exists(g):
            info = gp_glb.inspect(g)
            m0 = info["materials"][0]
            check(f"rock {lod} has albedo + occlusion textures, and omits the flat normal map",
                  m0["baseColorTexture"] and m0["occlusionTexture"] and not m0["normalTexture"])
            check(f"rock {lod} meshopt compressed", "EXT_meshopt_compression" in info["extensionsUsed"], str(info["extensionsUsed"]))
    man = json.load(open(os.path.join(out, "manifest.json")))
    check("manifest lists 2 LODs, both passed", len(man["lods"]) == 2 and all(l["passed"] for l in man["lods"]))
    check("source rock untouched", bpy.data.objects["Rock"].data.materials[0].name == "RockMat")

    # contract enforcement: a recipe that returns garbage must be rejected, not exported
    import recipes
    import types
    bad = types.ModuleType("recipes.bad")
    bad.META = {"name": "bad", "version": "0", "needs": []}
    bad.build = lambda spec, out_dir: [{"name": "x"}]
    sys.modules["recipes.bad"] = bad
    spec2 = {"name": "bad_asset", "type": "prop", "recipe": "bad", "recipe_cfg": {}, "export": {}}
    sp2 = os.path.join(tmp, "bad.json")
    json.dump(spec2, open(sp2, "w"))
    import importlib
    real_reload = importlib.reload
    importlib.reload = lambda m: m                      # keep our in-memory module
    try:
        res2 = gp_cli.run(sp2, preview=False, out_override=tmp)
    finally:
        importlib.reload = real_reload
    check("bad recipe output rejected by contract", res2["passed"] is False and res2.get("contract"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# --- grass recipe: blade pack for GPU instancing
bpy.ops.wm.read_factory_settings(use_empty=True)
tmp_g = tempfile.mkdtemp()
try:
    gspec = json.load(open(os.path.join(os.path.dirname(HERE), "specs", "grass_blades.json")))
    sg = os.path.join(tmp_g, "g.json"); json.dump(gspec, open(sg, "w"))
    rg = gp_cli.run(sg, preview=False, out_override=tmp_g)
    check("grass recipe passes", rg["passed"])
    ginfo = gp_glb.inspect(os.path.join(tmp_g, "grass_blades", "grass_blades.glb"))
    check("grass pack: 6 meshes (3 variants x 2 LODs), 30 triangles", ginfo["meshes"] == 6 and ginfo["triangles"] == 30, str(ginfo["meshes"]) + "/" + str(ginfo["triangles"]))
    gj = gp_glb.read_json(os.path.join(tmp_g, "grass_blades", "grass_blades.glb"))
    gnodes = sorted(n.get("name", "") for n in gj["nodes"])
    check("blade nodes named <asset>_<Variant>_LOD<n> (the engine parses these)", all("_LOD" in n for n in gnodes) and len(gnodes) == 6, str(gnodes))
finally:
    shutil.rmtree(tmp_g, ignore_errors=True)

print("\nALL PASSED" if not fails else "\nFAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
