"""Bake the procedural materials of all samurai meshes into ONE shared PBR atlas (albedo, tangent normal, ORM), drop never-seen
faces first, then rebuild every mesh with a single baked material. Cycles, CPU, headless only (never in a live session)."""
import math
import os

import bmesh
import bpy
import numpy as np

from . import shaders


def strip_hidden(ob):
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    lay = bm.faces.layers.int.get("hid")
    n = 0
    if lay is not None:
        dead = [f for f in bm.faces if f[lay]]
        n = len(dead)
        bmesh.ops.delete(bm, geom=dead, context="FACES")
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    return n


def _select(ob):
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def atlas_uv(objs, margin=0.0016):
    """Smart-project + pack ALL objects into one 0..1 atlas (via a temporary joined copy) and copy the UVs back."""
    copies = []
    for k, ob in enumerate(objs):
        c = ob.copy()
        c.data = ob.data.copy()
        c.modifiers.clear()
        c.parent = None
        bpy.context.scene.collection.objects.link(c)
        a = c.data.attributes.new("src", "INT", "FACE")
        a.data.foreach_set("value", [k] * len(c.data.polygons))
        copies.append(c)
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    for c in copies:
        c.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    bpy.ops.object.join()
    tmp = bpy.context.view_layer.objects.active
    uvl = tmp.data.uv_layers.new(name="atlas")
    tmp.data.uv_layers.active = uvl
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(62), island_margin=margin, scale_to_bounds=False)
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(margin=margin, rotate=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    uvl = tmp.data.uv_layers["atlas"]                       # re-fetch: edit mode invalidates the old wrapper
    uv = np.empty(len(tmp.data.loops) * 2, dtype=np.float32)
    uvl.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    npoly = len(tmp.data.polygons)
    src = np.empty(npoly, dtype=np.int32)
    tmp.data.attributes["src"].data.foreach_get("value", src)
    ls = np.empty(npoly, dtype=np.int32)
    tot = np.empty(npoly, dtype=np.int32)
    tmp.data.polygons.foreach_get("loop_start", ls)
    tmp.data.polygons.foreach_get("loop_total", tot)
    for k, ob in enumerate(objs):
        idx = np.concatenate([np.arange(ls[i], ls[i] + tot[i]) for i in np.nonzero(src == k)[0]])
        assert len(idx) == len(ob.data.loops), (ob.name, len(idx), len(ob.data.loops))
        lay = ob.data.uv_layers.new(name="atlas")
        lay.data.foreach_set("uv", uv[idx].ravel())
        ob.data.uv_layers.active = lay
        lay.active_render = True
    return tmp


def _image(name, px, color, float_buf=False):
    img = bpy.data.images.new(name, px, px, alpha=False, float_buffer=float_buf)
    img.colorspace_settings.name = "sRGB" if color else "Non-Color"
    return img


def _principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def _demetalize(mat):
    """A fully metallic Principled has no diffuse colour, so the DIFFUSE bake would be black. Bake the base colour as if metal=0;
    the metal amount travels in the ORM map."""
    pr = _principled(mat)
    sock = pr.inputs["Metallic"]
    for lk in list(sock.links):
        mat.node_tree.links.remove(lk)
    sock.default_value = 0.0


def _emit_team(mat):
    """Route the material's unconnected TEAM emission node to the output so an EMIT bake writes the team-colour mask."""
    nt = mat.node_tree
    em = nt.nodes.get("TEAM")
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    if em is None:
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (0, 0, 0, 1)
    nt.links.new(em.outputs[0], out.inputs["Surface"])


def _emit_metal(mat):
    nt = mat.node_tree
    pr = _principled(mat)
    emi = nt.nodes.new("ShaderNodeEmission")
    sock = pr.inputs["Metallic"]
    if sock.is_linked:
        nt.links.new(sock.links[0].from_socket, emi.inputs["Color"])
    else:
        rgb = nt.nodes.new("ShaderNodeRGB")
        v = sock.default_value
        rgb.outputs[0].default_value = (v, v, v, 1)
        nt.links.new(rgb.outputs[0], emi.inputs["Color"])
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    nt.links.new(emi.outputs[0], out.inputs["Surface"])


def _bake_pass(tmp, kind, px, name, color, samples):
    sc = bpy.context.scene
    img = _image(name, px, color, float_buf=(kind == "NORMAL"))
    originals = [s.material for s in tmp.material_slots]
    copies = []
    for i, slot in enumerate(tmp.material_slots):
        c = originals[i].copy()
        copies.append(c)
        slot.material = c
        node = c.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = img
        c.node_tree.nodes.active = node
        for n in c.node_tree.nodes:
            n.select = (n == node)
        if kind == "METAL":
            _emit_metal(c)
        elif kind == "TEAM":
            _emit_team(c)
        elif kind == "ALBEDO":
            _demetalize(c)
    sc.cycles.samples = samples
    _select(tmp)
    if kind == "ALBEDO":
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=10, margin_type="EXTEND", use_clear=True)
    elif kind == "NORMAL":
        sc.render.bake.normal_space = "TANGENT"
        bpy.ops.object.bake(type="NORMAL", margin=10, margin_type="EXTEND", use_clear=True)
    elif kind == "ROUGH":
        bpy.ops.object.bake(type="ROUGHNESS", margin=10, margin_type="EXTEND", use_clear=True)
    elif kind in ("METAL", "TEAM"):
        bpy.ops.object.bake(type="EMIT", margin=10, margin_type="EXTEND", use_clear=True)
    elif kind == "AO":
        bpy.ops.object.bake(type="AO", margin=10, margin_type="EXTEND", use_clear=True)
    for i, slot in enumerate(tmp.material_slots):
        slot.material = originals[i]
    for c in copies:
        bpy.data.materials.remove(c)
    return img


def _px(img):
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def bake_atlas(objs, out_dir, name, px=2048, quality=1.0, log=print):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.render.bake.margin = 10
    world = bpy.data.worlds.new("_bake_world")
    sc.world = world
    world.light_settings.distance = 0.10
    os.makedirs(out_dir, exist_ok=True)
    dropped = sum(strip_hidden(o) for o in objs)
    log(f"  dropped {dropped} hidden faces")
    tmp = atlas_uv(objs)
    log(f"  atlas UV done: {len(tmp.data.polygons)} faces")
    s_ = max(4, int(12 * quality))
    alb = _bake_pass(tmp, "ALBEDO", px, "_alb", True, s_)
    log("  albedo baked")
    nrm = _bake_pass(tmp, "NORMAL", px, "_nrm", False, s_)
    log("  normal baked")
    rgh = _bake_pass(tmp, "ROUGH", px, "_rgh", False, s_)
    met = _bake_pass(tmp, "METAL", px, "_met", False, s_)
    ao = _bake_pass(tmp, "AO", px, "_ao", False, int(40 * quality))
    team = _bake_pass(tmp, "TEAM", px, "_team", False, 4)
    log("  rough / metal / ao baked")
    orm = np.zeros((px, px, 4), dtype=np.float32)
    orm[..., 0] = np.clip(_px(ao)[..., 0], 0, 1)
    orm[..., 1] = np.clip(_px(rgh)[..., 0], 0, 1)
    orm[..., 2] = np.clip(_px(met)[..., 0], 0, 1)
    orm[..., 3] = 1.0
    orm_img = bpy.data.images.new(f"{name}_orm", px, px, alpha=False)
    orm_img.colorspace_settings.name = "Non-Color"
    orm_img.pixels.foreach_set(orm.ravel())
    maps = {}
    for key, img, fname, fmt in (("albedo", alb, f"{name}_albedo.jpg", "JPEG"), ("normal", nrm, f"{name}_normal.png", "PNG"),
                                 ("orm", orm_img, f"{name}_orm.png", "PNG")):
        img.name = f"{name}_{key}"
        img.filepath_raw = os.path.join(out_dir, fname)
        img.file_format = fmt
        if fmt == "JPEG":
            sc.render.image_settings.quality = 92
        img.save()
        maps[key] = img
    # team-colour mask (R, same atlas UVs), half resolution: the engine tints only where it is > 0
    m = np.clip(_px(team)[..., 0], 0, 1)
    k = 2
    m = m.reshape(px // k, k, px // k, k).mean(axis=(1, 3))
    tm = np.ones((px // k, px // k, 4), dtype=np.float32)
    tm[..., 0] = tm[..., 1] = tm[..., 2] = m
    team_img = bpy.data.images.new(f"{name}_team", px // k, px // k, alpha=False)
    team_img.colorspace_settings.name = "Non-Color"
    team_img.pixels.foreach_set(tm.ravel())
    team_img.filepath_raw = os.path.join(out_dir, f"{name}_team.png")
    team_img.file_format = "PNG"
    team_img.save()
    log(f"  team mask coverage {float((m > 0.5).mean()) * 100:.1f}% of the atlas")
    bpy.data.images.remove(team_img)
    for img in (rgh, met, ao, team):
        bpy.data.images.remove(img)
    bpy.data.objects.remove(tmp, do_unlink=True)
    sc.world = None
    bpy.data.worlds.remove(world)
    bpy.context.view_layer.update()
    return maps


def assign_baked(objs, maps, name):
    """Replace every material with one baked PBR material and keep only the atlas UV (exported as TEXCOORD_0)."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "gamepipe"))
    from recipes import _common as C
    mat = C.pbr_material(f"{name}_mat", maps)
    for ob in objs:
        me = ob.data
        me.materials.clear()
        me.materials.append(mat)
        if "pat" in me.uv_layers:
            me.uv_layers.remove(me.uv_layers["pat"])
        me.uv_layers[0].name = "UVMap"
        if "hid" in me.attributes:
            me.attributes.remove(me.attributes["hid"])
    return mat
