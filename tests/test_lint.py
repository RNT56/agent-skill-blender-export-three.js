"""Plain-Python test (no Blender):  python3 tests/test_lint.py
Each known Blender trap must be flagged; clean idiomatic code must not be."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gamepipe"))
import gp_lint

fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def codes(src):
    return {f["code"] for f in gp_lint.lint_source(src)}


check("`is` on nodes flagged", "BPY_IS_IDENTITY" in codes("for n in nodes:\n    n.select = n is node\n"))
check("`is None` not flagged", "BPY_IS_IDENTITY" not in codes("if obj is None:\n    pass\n"))
check("== on nodes not flagged", "BPY_IS_IDENTITY" not in codes("for n in nodes:\n    n.select = (n == node)\n"))
check("blend_method flagged", "BPY_BLEND_METHOD" in codes("m.blend_method = 'CLIP'\n"))
check("result str flagged", "MCP_RESULT_NOT_DICT" in codes("result = 'ok'\n"))
check("result dict ok", "MCP_RESULT_NOT_DICT" not in codes("result = {'ok': 1}\n"))
check("bake without active node flagged", "BAKE_NO_ACTIVE_NODE" in codes("import bpy\nbpy.ops.object.bake(type='DIFFUSE')\n"))
check("bake with active node ok", "BAKE_NO_ACTIVE_NODE" not in codes("import bpy\nnt.nodes.active = n\nbpy.ops.object.bake(type='DIFFUSE')\n"))
check("stale transforms flagged", "BPY_NO_UPDATE" in codes("o = bpy.data.objects.new('a', None)\no.location = (1,0,0)\nx = o.matrix_world\n"))
check("update silences it", "BPY_NO_UPDATE" not in codes("o.location = (1,0,0)\nbpy.context.view_layer.update()\nx = o.matrix_world\n"))
check("ops in loop flagged", "BPY_OPS_IN_LOOP" in codes("for i in range(9):\n    bpy.ops.mesh.primitive_cube_add()\n"))
check("density factor flagged", "GN_DENSITY_FACTOR" in codes("n = nodes.new('GeometryNodeDistributePointsOnFaces')\nn.inputs['Density Factor']\n"))
check("edit mode leak flagged", "BPY_EDIT_MODE_LEAK" in codes("bpy.ops.object.mode_set(mode='EDIT')\n"))
check("syntax error reported", "SYNTAX" in codes("def (:\n"))

# the pipeline's own code must be clean of error-level findings
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = []
for d in ("gamepipe", os.path.join("gamepipe", "recipes"), "generators"):
    for fn in sorted(os.listdir(os.path.join(root, d))):
        if fn.endswith(".py") and fn != "gp_lint.py":
            for f in gp_lint.lint_file(os.path.join(root, d, fn)):
                if f["level"] == "error":
                    bad.append(f"{fn}:{f['line']} {f['code']}")
check("pipeline sources lint clean (no errors)", not bad)
if bad:
    print("   ", bad)

print("\nALL PASSED" if not fails else "\nFAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
