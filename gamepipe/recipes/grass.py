"""Grass recipe: a pack of wind-ready grass BLADE meshes for GPU instancing (the scattering and wind live in the engine).

Why not export the Blender Geometry-Nodes scatter: instancing 70k blades realizes to millions of vertices and the wind is a node
graph glTF cannot carry. What carries over is the blade mesh. The engine (runtime/grass.js) instances it per chunk with a wind shader.

Spec (recipe "grass"), under spec["recipe_cfg"]:
  variants     : [{name, height, width, bend, twist}]   (metres; bend = forward lean at the tip)
  lod_segments : [4, 2]  segments for LOD0, LOD1 (LOD0 = 7 tris, LOD1 = 3 tris for 4/2 segments)
Blade convention (Blender Z-up): base at origin, grows +Z, leans toward +Y; width along X.
UV: u across the blade (0..1), **v = height along the blade (0 base .. 1 tip)** -> the engine uses v for colour gradient + wind weight.
Objects are named  <asset>_<Variant>_LOD<n>.
"""
import math
import os

import bmesh
import bpy

from . import _common  # noqa: F401  (kept for symmetry; recipes share helpers)

META = {"name": "grass", "version": "1", "needs": ["variants", "lod_segments"]}


def make_blade(name, height, width, bend, twist, segments):
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    rows = segments
    L, R = [], []
    for i in range(rows):
        t = i / rows
        w = width * (1.0 - t) ** 0.65 * (1.0 - 0.15 * t)
        y = bend * t * t * height
        tw = math.sin(t * twist) * w
        L.append(bm.verts.new((-w * math.cos(twist * t), y - tw * 0.2, t * height)))
        R.append(bm.verts.new((w * math.cos(twist * t), y + tw * 0.2, t * height)))
    tip = bm.verts.new((0.0, bend * height, height))
    faces = []
    for i in range(rows - 1):
        faces.append(bm.faces.new((L[i], R[i], R[i + 1], L[i + 1])))
    faces.append(bm.faces.new((L[rows - 1], R[rows - 1], tip)))
    # winding so the front face points toward -Y (away from the lean), i.e. +Z-up blade seen from the side it leans away from
    for f in faces:
        for lp in f.loops:
            v = lp.vert
            lp[uvl].uv = (0.5 + v.co.x / (2.0 * width), v.co.z / height)
    bm.normal_update()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return me


def build(spec, out_dir):
    cfg = spec["recipe_cfg"]
    name = spec["name"]
    os.makedirs(out_dir, exist_ok=True)
    coll = bpy.data.collections.get(f"{name}_game") or bpy.data.collections.new(f"{name}_game")
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    mat = bpy.data.materials.new(f"{name}_mat")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
    mat.use_backface_culling = False
    names = []
    for v in cfg["variants"]:
        for li, segs in enumerate(cfg["lod_segments"]):
            oname = f"{name}_{v['name']}_LOD{li}"
            me = make_blade(oname, v.get("height", 1.0), v.get("width", 0.035), v.get("bend", 0.2), v.get("twist", 0.0), segs)
            me.materials.append(mat)
            ob = bpy.data.objects.new(oname, me)
            coll.objects.link(ob)
            names.append(oname)
    return [{
        "name": name, "type": spec["type"], "root_object": None, "include_objects": names,
        "budgets": {**spec.get("budgets", {})}, "rules": {**spec.get("rules", {}), "origin_tolerance": 0.05},
        "export": spec.get("export", {}), "lod": "pack",
    }]
