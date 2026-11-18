"""Building recipe: pre-authored multi-material LOD sets (e.g. generators/samurai_keep.py) -> ONE GLB with all LODs.

Why a single GLB: the LODs share the same tileable PBR materials, so one file carries each texture once (and the engine keeps one
copy on the GPU). Per-LOD triangle budgets are enforced by the validator via spec["lod_budgets"]; objects must be named
<anything>_LOD<n>_<Material>.

Spec (recipe "building"), under spec["recipe_cfg"]:
  collections : names of the Blender collections holding the authored LOD objects (e.g. keep_LOD0, keep_LOD1, keep_LOD2)
The recipe creates nothing; it gathers the objects and hands them to the gate (validate -> export -> inspect).
"""
import bpy

META = {"name": "building", "version": "1", "needs": ["collections"]}


def build(spec, out_dir):
    names = []
    for cname in spec["recipe_cfg"]["collections"]:
        coll = bpy.data.collections.get(cname)
        if coll is None:
            raise RuntimeError(f"collection {cname!r} not found in the source blend")
        names += [o.name for o in coll.all_objects if o.type == "MESH"]
    return [{
        "name": spec["name"], "type": spec["type"], "root_object": spec.get("root_object"), "include_objects": names,
        "budgets": spec.get("budgets", {}), "lod_budgets": spec.get("lod_budgets", {}), "rules": spec.get("rules", {}),
        "export": spec.get("export", {}), "glb_expect": spec.get("glb_expect"), "lod": "pack",
    }]
