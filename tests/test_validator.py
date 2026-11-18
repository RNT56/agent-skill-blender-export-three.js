"""Headless self-test:  blender -b --factory-startup -P tests/test_validator.py
Builds a good asset and several deliberately broken ones; asserts the validator reports exactly the expected codes.
"""
import os, sys, tempfile, json, shutil
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "gamepipe"))
import gp_validate, gp_export

fails = []

def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)

def cube(name, loc=(0, 0, 0.5), size=1.0):
    bpy.ops.mesh.primitive_cube_add(size=size, location=loc)
    o = bpy.context.active_object; o.name = name
    return o

def flat_mat(name="Flat"):
    m = bpy.data.materials.new(name); m.use_nodes = True
    return m

def codes(spec):
    rep = gp_validate.validate(spec)
    return rep, {f["code"] for f in rep["findings"]}

def spec(names, **kw):
    s = {"name": "t", "type": "prop", "include_objects": names}
    s.update(kw); return s

# 1. good asset passes and exports
reset()
o = cube("good_cube"); o.data.materials.append(flat_mat())
rep, c = codes(spec(["good_cube"]))
check("good asset passes", rep["passed"], gp_validate.format_report(rep))
tmp = tempfile.mkdtemp()
try:
    exp = gp_export.export_glb(spec(["good_cube"]), tmp)
    check("glb written", os.path.exists(exp["path"]) and exp["size_mb"] > 0)
    with open(exp["path"], "rb") as fh:
        check("glb magic", fh.read(4) == b"glTF")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 2. triangle budget
reset(); o = cube("big"); o.data.materials.append(flat_mat())
rep, c = codes(spec(["big"], budgets={"max_tris": 5}))
check("tri budget fails", "BUDGET_TRIS" in c and not rep["passed"])

# 3. missing UV
reset(); o = cube("nouv"); o.data.materials.append(flat_mat())
for uv in list(o.data.uv_layers): o.data.uv_layers.remove(uv)
rep, c = codes(spec(["nouv"]))
check("missing UV fails", "UV_MISSING" in c)

# 4. negative + non-uniform scale
reset(); o = cube("neg"); o.scale = (-1, 1, 1); o.data.materials.append(flat_mat())
rep, c = codes(spec(["neg"]))
check("negative scale fails", "XFORM_NEG_SCALE" in c)
reset(); o = cube("nu"); o.scale = (1, 2, 1); o.data.materials.append(flat_mat())
rep, c = codes(spec(["nu"]))
check("non-uniform scale warns", "XFORM_NONUNIFORM" in c and rep["passed"] is not None)

# 5. procedural material
reset(); o = cube("proc")
m = flat_mat("Proc"); nt = m.node_tree
noise = nt.nodes.new("ShaderNodeTexNoise")
bsdf = nt.nodes["Principled BSDF"]
nt.links.new(noise.outputs["Color"], bsdf.inputs["Base Color"])
o.data.materials.append(m)
rep, c = codes(spec(["proc"]))
check("procedural material fails", "MAT_PROCEDURAL" in c and not rep["passed"])

# 6. oversized image
reset(); o = cube("bigtex")
m = flat_mat("Img"); nt = m.node_tree
img = bpy.data.images.new("huge", 4096, 4096)
tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
o.data.materials.append(m)
rep, c = codes(spec(["bigtex"]))
check("oversized texture fails", "TEX_TOO_LARGE" in c)

# 7. wrong units (1 km cube) and origin off the ground
reset(); o = cube("huge", size=500.0, loc=(0, 0, 250)); o.data.materials.append(flat_mat())
rep, c = codes(spec(["huge"]))
check("absurd size fails", "DIM_SANITY" in c)
reset(); o = cube("floating", loc=(0, 0, 5)); o.data.materials.append(flat_mat())
rep, c = codes(spec(["floating"]))
check("origin off ground warns", "ORIGIN_NOT_AT_BASE" in c)

# 8. missing source
reset()
rep, c = codes(spec(["ghost"]))
check("missing object fails", "SRC_MISSING" in c and "NO_MESH" in c)

# 9. bad name chars
reset(); o = cube("bad name.001"); o.data.materials.append(flat_mat())
rep, c = codes(spec(["bad name.001"]))
check("bad name warns", "NAME_CHARS" in c)

# 9b. blank (failed-bake) texture is caught
reset(); o = cube("blank")
m = flat_mat("Blank"); nt = m.node_tree
img = bpy.data.images.new("flat", 256, 256)   # solid black = what a silently failed bake leaves behind
tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
o.data.materials.append(m)
rep, c = codes(spec(["blank"]))
check("blank texture fails", "TEX_BLANK" in c and not rep["passed"])

# 9c. alpha texture without a clip node warns (would export as BLEND)
reset(); o = cube("alpha")
m = flat_mat("Alpha"); nt = m.node_tree
img = bpy.data.images.new("a", 64, 64)
import numpy as np
img.pixels.foreach_set(np.random.default_rng(1).random(64 * 64 * 4).astype("float32"))
tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
nt.links.new(tex.outputs["Alpha"], nt.nodes["Principled BSDF"].inputs["Alpha"])
o.data.materials.append(m)
rep, c = codes(spec(["alpha"]))
check("blended alpha warns", "ALPHA_BLENDED" in c)
clip = nt.nodes.new("ShaderNodeMath"); clip.operation = "ROUND"
nt.links.new(tex.outputs["Alpha"], clip.inputs[0]); nt.links.new(clip.outputs["Value"], nt.nodes["Principled BSDF"].inputs["Alpha"])
rep, c = codes(spec(["alpha"]))
check("cutout alpha does not warn", "ALPHA_BLENDED" not in c)

# 10. cli refuses to export a failing asset
reset(); o = cube("blocked"); o.data.materials.append(flat_mat())
import gp_cli
tmp = tempfile.mkdtemp()
try:
    sp = spec(["blocked"], name="blocked", budgets={"max_tris": 5}, export={"out_dir": "out"})
    p = os.path.join(tmp, "s.json"); json.dump(sp, open(p, "w"))
    rep = gp_cli.run(p, out_override=tmp, preview=False)
    check("failing asset not exported", rep["export"] is None and not os.path.exists(os.path.join(tmp, "blocked", "blocked.glb")))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{'ALL PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
