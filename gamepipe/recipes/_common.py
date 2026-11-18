"""Shared recipe building blocks: decimate, unwrap, bake (albedo / normal / AO), ORM packing, PBR material.

Gotchas encoded here (Blender 5.3):
  * compare nodes with ==, never `is` (bpy returns a fresh wrapper per access)
  * the bake target Image Texture node must be BOTH active and selected, or Cycles silently bakes nothing
  * glTF occlusion comes from the 'glTF Material Output' node group, roughness/metal from the principled inputs
"""
import math
import os

import bpy
import numpy as np


# --------------------------------------------------------------------------- mesh
def tri_count(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def decimate_mesh(src_me, target_tris, name):
    """Collapse-decimate a COPY of src_me to ~target_tris (UVs are carried through). Repairs degenerate faces."""
    tmp_me = src_me.copy()
    tmp = bpy.data.objects.new("_tmp_dec", tmp_me)
    bpy.context.scene.collection.objects.link(tmp)
    ratio = min(1.0, target_tris / max(tri_count(tmp_me), 1))
    md = tmp.modifiers.new("dec", "DECIMATE")
    md.decimate_type = "COLLAPSE"
    md.ratio = ratio
    md.use_collapse_triangulate = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    me.name = name
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(tmp_me)
    bpy.context.view_layer.update()          # removed objects leave stale (None) view-layer entries until refreshed
    before = len(me.polygons)
    if me.validate(verbose=False):
        print(f"  repaired mesh {name}: {before - len(me.polygons)} degenerate/duplicate faces removed")
    for p in me.polygons:
        p.use_smooth = True
    return me


def _select_only(obj):
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def unwrap(obj, margin=0.003):
    _select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


# --------------------------------------------------------------------------- bake
def _read_rgba(img):
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def _bake_one(obj, src_mat, kind, px, samples):
    """Bake `kind` ('DIFFUSE'|'NORMAL'|'AO') of src_mat onto obj's active UV map. Returns the (unsaved) image."""
    sc = bpy.context.scene
    mat = src_mat.copy()
    mat.name = f"_bake_{kind}"
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    img = bpy.data.images.new(f"_bake_{kind}", px, px, alpha=False)
    img.colorspace_settings.name = "sRGB" if kind == "DIFFUSE" else "Non-Color"
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    mat.node_tree.nodes.active = node
    for n in mat.node_tree.nodes:
        n.select = (n == node)
    _select_only(obj)
    sc.cycles.samples = samples
    if kind == "DIFFUSE":
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=8, use_clear=True)
    elif kind == "NORMAL":
        sc.render.bake.normal_space = "TANGENT"
        bpy.ops.object.bake(type="NORMAL", margin=8, use_clear=True)
    else:
        bpy.ops.object.bake(type="AO", margin=8, use_clear=True)
    obj.data.materials.clear()
    bpy.data.materials.remove(mat)
    return img


def bake_pbr(obj, src_mat, px, tex_dir, base_name, ao_samples=16, ao_distance=1.0, orm_downscale=2):
    """Bake albedo (JPEG), tangent normal (PNG) and an ORM map (PNG: R=AO, G=roughness, B=metal) from a procedural material.
    Returns dict of saved bpy images. Roughness is derived from albedo luminance (crevices rougher), a cheap but
    plausible stand-in for a baked roughness pass when the source material has a constant roughness.
    """
    sc = bpy.context.scene
    prev = sc.render.engine
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.render.bake.margin = 8
    made_world = None
    if sc.world is None:                       # AO bake reads world light settings; a world-less scene bakes garbage
        made_world = bpy.data.worlds.new("_bake_world")
        sc.world = made_world
    try:
        sc.world.light_settings.distance = ao_distance
    except Exception:
        pass
    out = {}
    try:
        alb = _bake_one(obj, src_mat, "DIFFUSE", px, 4)
        nrm = _bake_one(obj, src_mat, "NORMAL", px, 4)
        ao = _bake_one(obj, src_mat, "AO", px, ao_samples)
        a = _read_rgba(alb)
        lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
        lo, hi = np.percentile(lum, 2), np.percentile(lum, 98)
        lumn = np.clip((lum - lo) / max(hi - lo, 1e-4), 0, 1)
        rough = np.clip(0.95 - 0.25 * lumn, 0.5, 1.0)
        occ = np.clip(_read_rgba(ao)[..., 0], 0, 1)
        orm = np.zeros_like(a)
        orm[..., 0] = occ
        orm[..., 1] = rough
        orm[..., 2] = 0.0
        orm[..., 3] = 1.0
        n_arr = _read_rgba(nrm)[..., :3]
        flat_normal = float(n_arr.reshape(-1, 3).std(axis=0).max()) < 0.01   # material had no bump/normal detail
        specs = [("albedo", alb, f"{base_name}_albedo.jpg", "JPEG", "sRGB")]
        if not flat_normal:
            specs.append(("normal", nrm, f"{base_name}_normal.png", "PNG", "Non-Color"))
        else:
            print(f"  {base_name}: baked normal map is flat (no bump in source material): omitted from the asset")
            bpy.data.images.remove(nrm)
        for key, img, fname, fmt, cs in specs:
            img.name = f"{base_name}_{key}"
            img.filepath_raw = os.path.join(tex_dir, fname)
            img.file_format = fmt
            if fmt == "JPEG":
                sc.render.image_settings.quality = 90
            img.save()
            out[key] = img
        # AO + roughness are low-frequency: half resolution (2x2 box filter) saves ~3 MB of KTX2 at 2048 px
        k = max(1, orm_downscale)
        if k > 1 and px % k == 0:
            h = px // k
            orm = orm.reshape(h, k, h, k, 4).mean(axis=(1, 3))
        opx = orm.shape[0]
        orm_img = bpy.data.images.new(f"{base_name}_orm", opx, opx, alpha=False)
        orm_img.colorspace_settings.name = "Non-Color"
        orm_img.pixels.foreach_set(orm.astype(np.float32).ravel())
        orm_img.filepath_raw = os.path.join(tex_dir, f"{base_name}_orm.png")
        orm_img.file_format = "PNG"
        orm_img.save()
        out["orm"] = orm_img
        bpy.data.images.remove(ao)
    finally:
        sc.render.engine = prev
        if made_world is not None:
            sc.world = None
            bpy.data.worlds.remove(made_world)
    return out


# --------------------------------------------------------------------------- materials
def _gltf_output_group():
    g = bpy.data.node_groups.get("glTF Material Output")
    if g is None:
        g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    return g


def pbr_material(name, maps, double_sided=False):
    """Principled material from baked maps: albedo -> base colour, normal -> normal map, ORM -> occlusion/roughness/metal."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    a = nt.nodes.new("ShaderNodeTexImage"); a.image = maps["albedo"]
    nt.links.new(a.outputs["Color"], b.inputs["Base Color"])
    if "normal" in maps:
        nrm = nt.nodes.new("ShaderNodeTexImage"); nrm.image = maps["normal"]
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(nrm.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    if "orm" in maps:
        o = nt.nodes.new("ShaderNodeTexImage"); o.image = maps["orm"]
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(o.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], b.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], b.inputs["Metallic"])
        grp = nt.nodes.new("ShaderNodeGroup")
        grp.node_tree = _gltf_output_group()
        nt.links.new(sep.outputs["Red"], grp.inputs["Occlusion"])
    else:
        b.inputs["Roughness"].default_value = 0.88
    m.use_backface_culling = not double_sided
    return m
