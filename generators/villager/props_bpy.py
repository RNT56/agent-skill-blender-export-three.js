"""Blender side of the props: mesh objects from props.py geometry, bound to one bone each; a stand-alone preview of all of them."""
import os

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import props as P


def mesh_object(name, geo, coll, matrix=None, material=None):
    """geo = (verts, faces, uvs, info) in the prop's own frame; `matrix` takes it to armature space."""
    verts, faces, uvs, info = geo
    me = bpy.data.meshes.new(name)
    M = matrix or Matrix.Identity(4)
    me.from_pydata([tuple(M @ Vector(v)) for v in verts], [], [tuple(f) for f in faces])
    uvl = me.uv_layers.new(name="UVMap")
    k = 0
    for fi, f in enumerate(faces):
        for ci in range(len(f)):
            uvl.data[k].uv = uvs[fi][ci]
            k += 1
    # consistent outward normals (every part is a closed or near-closed shell), then triangles
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    if material is not None:
        me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def bind_rigid(ob, arm, bone):
    vg = ob.vertex_groups.new(name=bone)
    vg.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")
    md = ob.modifiers.new("Armature", "ARMATURE")
    md.object = arm
    ob.parent = arm


def strip_images(px, name="props"):
    """stand-alone atlas images with only the prop strip painted (for the preview)."""
    alb = np.zeros((px, px, 4), dtype=np.float32)
    alb[..., 3] = 1
    nrm = np.zeros((px, px, 4), dtype=np.float32)
    nrm[..., :3] = (0.5, 0.5, 1.0)
    nrm[..., 3] = 1
    orm = np.ones((px, px, 4), dtype=np.float32)
    P.paint_strip(alb, nrm, orm, px)
    img = bpy.data.images.new(name + "_albedo", px, px, alpha=False)
    img.pixels.foreach_set(alb.ravel())
    return img


def preview(out_prefix):
    """every prop side by side, textured from the strip: a geometry / swatch check that needs no character."""
    from . import qa
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    img = strip_images(2048)
    mat = bpy.data.materials.new("props_preview")
    mat.use_nodes = True
    t = mat.node_tree.nodes.new("ShaderNodeTexImage")
    t.image = img
    mat.node_tree.links.new(t.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    objs, x, report = [], 0.0, {}
    for name, fn in list(P.TOOLS.items()) + [("tsurizao_line", P.tsurizao_line)]:
        geo = fn()
        ob = mesh_object("Tool_" + name, geo, sc.collection, Matrix.Translation((x, 0, 0.25)), mat)
        objs.append(ob)
        report["Tool_" + name] = geo[3]["tris"]
        x += 0.42
    x = 0.0
    for name, fn in P.LOADS.items():
        geo = fn()
        ob = mesh_object("Load_" + name, geo, sc.collection, Matrix.Translation((x, 0, -1.2)) @ Matrix.Rotation(1.5707963, 4, "Z"), mat)
        objs.append(ob)
        report["Load_" + name] = geo[3]["tris"]
        x += 0.8
    geo = P.kasa()
    objs.append(mesh_object("Hat_kasa", geo, sc.collection, Matrix.Translation((x + 0.1, 0, -1.0)), mat))
    report["Hat_kasa"] = geo[3]["tris"]
    bpy.context.view_layer.update()
    paths = qa.shots(objs, out_prefix, views=("front", "q", "low"), size=1400)
    qa.sheet(paths, out_prefix + "_sheet.jpg")
    print("PROPS " + str(report) + " total " + str(sum(report.values())))
    return report


# where each load sits relative to its bone (load frame = armature axes): the bale is fat, so it rides further out on the shoulder
LOAD_OFFSET = {"sack": (-0.070, 0.02, 0.0), "log": (-0.012, 0.10, 0.0), "planks": (-0.012, 0.12, 0.0), "bamboo": (-0.012, 0.15, 0.0), "basket": (0.0, 0.0, 0.0)}


def build_props(arm, coll, hands, material, hat_drop=0.045):
    """every prop as its own skinned node, bound rigidly to its bone, in the armature's rest space. Returns {node name: object}."""
    from . import rig as R
    out = {}
    Tr = R.tool_matrix(arm, "tool_r")
    Tl = R.tool_matrix(arm, "tool_l")
    for name, fn in P.TOOLS.items():
        left = name == "nomi"
        ob = mesh_object("Tool_" + name, fn(), coll, Tl if left else Tr, material)
        bind_rigid(ob, arm, "tool_l" if left else "tool_r")
        out[ob.name] = ob
    # the fishing line is part of the rod's node (one draw call) but rides its own bone
    rod = out["Tool_tsurizao"]
    line = mesh_object("_line", P.tsurizao_line(), coll, arm.data.bones["line"].matrix_local, material)
    vg = line.vertex_groups.new(name="line")
    vg.add(list(range(len(line.data.vertices))), 1.0, "REPLACE")
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    rod.select_set(True)
    line.select_set(True)
    bpy.context.view_layer.objects.active = rod
    bpy.ops.object.join()
    for name, fn in P.LOADS.items():
        bone = "load_front" if name == "basket" else "load_shoulder"
        M = Matrix.Translation(Vector(arm.data.bones[bone].head_local) + Vector(LOAD_OFFSET[name]))
        ob = mesh_object("Load_" + name, fn(), coll, M, material)
        bind_rigid(ob, arm, bone)
        out[ob.name] = ob
    ob = mesh_object("Hat_kasa", P.kasa(), coll, Matrix.Translation(Vector(hands["crown"]) + Vector((0, 0, -hat_drop))), material)
    bind_rigid(ob, arm, "head")
    out[ob.name] = ob
    bpy.context.view_layer.update()
    return out
