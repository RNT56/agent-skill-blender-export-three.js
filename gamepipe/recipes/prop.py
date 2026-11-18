"""Prop / rock recipe: one hero mesh with a procedural material -> decimated LODs sharing one baked PBR set.

Spec (recipe "prop"), under spec["recipe_cfg"]:
  obj     : source mesh object (with a procedural or image material in slot 0)
  tex_px  : bake resolution (default 1024)
  lods    : [{name, tris, max_tris}]   LOD0 is decimated from the source, later LODs from LOD0 (UVs carried)
"""
import os

import bpy

from . import _common as C

META = {"name": "prop", "version": "1", "needs": ["obj"]}


def build(spec, out_dir):
    cfg = spec["recipe_cfg"]
    name = spec["name"]
    tex_dir = os.path.join(out_dir, "textures")
    os.makedirs(tex_dir, exist_ok=True)
    src = bpy.data.objects[cfg["obj"]]
    root = bpy.data.objects.get(spec.get("root_object", ""))
    px = cfg.get("tex_px", 1024)

    coll = bpy.data.collections.get(f"{name}_game") or bpy.data.collections.new(f"{name}_game")
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)

    lods = cfg["lods"]
    me0 = C.decimate_mesh(src.data, lods[0]["tris"], f"{name}_LOD0")
    derived, mat = [], None
    for li, lod in enumerate(lods):
        tag = lod["name"]
        me = me0 if li == 0 else C.decimate_mesh(me0, lod["tris"], f"{name}_{tag}")
        ob = bpy.data.objects.new(f"{name}_{tag}", me)
        coll.objects.link(ob)
        if root is not None:
            ob.parent = root
            ob.matrix_parent_inverse = src.matrix_parent_inverse.copy()
        ob.matrix_basis = src.matrix_basis.copy()
        if li == 0:
            C.unwrap(ob)
            maps = C.bake_pbr(ob, src.data.materials[0], px, tex_dir, f"{name}")
            mat = C.pbr_material(f"{name}_mat", maps)
        me.materials.clear()
        me.materials.append(mat)
        derived.append({
            "name": f"{name}_{tag}", "type": spec["type"], "root_object": spec.get("root_object"),
            "include_objects": [ob.name],
            "budgets": {**spec.get("budgets", {}), "max_tris": lod["max_tris"]},
            "rules": spec.get("rules", {}), "export": spec.get("export", {}), "lod": tag,
        })
    return derived
