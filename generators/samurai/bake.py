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


def _emit_white(mat):
    """Everything emits 1: an EMIT bake of a subset of the objects is that subset's coverage mask in the atlas."""
    nt = mat.node_tree
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1, 1, 1, 1)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    nt.links.new(em.outputs[0], out.inputs["Surface"])


def _join_copies(objs, name="_bake_sub"):
    """A joined copy of some of the objects, keeping their (already assigned) atlas UVs."""
    copies = []
    for ob in objs:
        c = ob.copy()
        c.data = ob.data.copy()
        c.modifiers.clear()
        c.parent = None
        c.hide_render = False                      # the sources are hidden while the occlusion is baked: the copy must not be
        bpy.context.scene.collection.objects.link(c)
        copies.append(c)
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    for c in copies:
        c.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    if len(copies) > 1:
        bpy.ops.object.join()
    tmp = bpy.context.view_layer.objects.active
    tmp.name = name
    tmp.data.uv_layers.active = tmp.data.uv_layers["atlas"]
    tmp.data.uv_layers["atlas"].active_render = True
    return tmp


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


def _bake_pass(tmp, kind, px, name, color, samples, margin=10):
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
        elif kind == "MASK":
            _emit_white(c)
        elif kind == "ALBEDO":
            _demetalize(c)
    sc.cycles.samples = samples
    _select(tmp)
    if kind == "ALBEDO":
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=margin, margin_type="EXTEND", use_clear=True)
    elif kind == "NORMAL":
        sc.render.bake.normal_space = "TANGENT"
        bpy.ops.object.bake(type="NORMAL", margin=margin, margin_type="EXTEND", use_clear=True)
    elif kind == "ROUGH":
        bpy.ops.object.bake(type="ROUGHNESS", margin=margin, margin_type="EXTEND", use_clear=True)
    elif kind in ("METAL", "TEAM", "MASK"):
        bpy.ops.object.bake(type="EMIT", margin=margin, margin_type="EXTEND", use_clear=True)
    elif kind == "AO":
        bpy.ops.object.bake(type="AO", margin=margin, margin_type="EXTEND", use_clear=True)
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


def _dilate(a, cov, n=12):
    """Grow the covered texels of `a` into the uncovered ones around them, n texels deep (what a bake margin does, for an image composed from several bakes)."""
    a, cov = a.copy(), cov.copy()
    for _ in range(n):
        acc = np.zeros_like(a)
        cnt = np.zeros_like(a)
        for ax in (0, 1):
            for sft in (1, -1):
                acc += np.roll(a * cov, sft, axis=ax)
                cnt += np.roll(cov.astype(np.float32), sft, axis=ax)
        new = (~cov) & (cnt > 0)
        a[new] = acc[new] / cnt[new]
        cov |= new
    a[~cov] = 1.0
    return a


def _ao_by_group(objs, groups, px, samples, log):
    """Occlusion for a model whose pieces an engine shows in different combinations (a body, two armours, two hats ...). groups: [(own, others)]: the texels of the
    objects `own` are occluded by `own` and `others` and by nothing else. So a bare head does not keep the shade of a hat it may not be wearing, and two hats that
    occupy the same place do not black each other out. Every pass bakes only its own texels (margin 0); the result is composed and its gutters filled."""
    occ = np.ones((px, px), dtype=np.float32)
    cov = np.zeros((px, px), dtype=bool)
    seen = set()
    for k, (own, others) in enumerate(groups):
        assert not (set(own) & set(others)), "a piece cannot occlude itself from outside"
        assert not (set(own) & seen), "a piece is in two groups"
        seen |= set(own)
        sub = _join_copies(own, f"_ao_{k}")
        for o in others:
            o.hide_render = False
        a = _bake_pass(sub, "AO", px, f"_ao_{k}", False, samples, margin=0)
        m = _bake_pass(sub, "MASK", px, f"_aom_{k}", False, 1, margin=0)
        for o in others:
            o.hide_render = True
        w = _px(m)[..., 0] > 0.5
        occ[w] = np.clip(_px(a)[..., 0], 0, 1)[w]
        cov |= w
        bpy.data.images.remove(a)
        bpy.data.images.remove(m)
        bpy.data.objects.remove(sub, do_unlink=True)
        log(f"  occlusion {k + 1}/{len(groups)}: {', '.join(o.name for o in own)[:70]} ({float(w.mean()) * 100:.1f}% of the atlas)")
    assert seen == set(objs), "ao_groups must cover every object exactly once"
    return _dilate(occ, cov)


def bake_atlas(objs, out_dir, name, px=2048, quality=1.0, log=print, ao_samples=None, ao_blur=False, ao_groups=None, ao_alone=False):
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
    # 40 adaptive samples leave grain in the occlusion: invisible on lacquer, a stipple on bare skin in a hat's shade (there the image light times the
    # occlusion is all the light there is). ao_samples: that many FIXED samples; ao_blur: a 5 x 5 binomial filter over the result (the 10 px margin keeps islands apart)
    adaptive = sc.cycles.use_adaptive_sampling
    if ao_samples:
        sc.cycles.use_adaptive_sampling = False
    # ao_alone: the source objects are hidden while the joined copy is baked. They lie exactly ON the copy, and a ray leaving a surface that has a second surface in
    # the same place hits it about half the time: every open surface came out half occluded and grainy however many samples were spent (found on the archer's face).
    # ao_groups (see _ao_by_group): occlusion per piece of kit instead of one pass over everything.
    vis = [(o, o.hide_render) for o in objs]
    if ao_alone or ao_groups:
        for o in objs:
            o.hide_render = True
    occ_groups = None
    if ao_groups:
        tmp.hide_render = True
        occ_groups = _ao_by_group(objs, ao_groups, px, ao_samples or int(40 * quality), log)
        tmp.hide_render = False
        ao = None
    else:
        ao = _bake_pass(tmp, "AO", px, "_ao", False, ao_samples or int(40 * quality))
    sc.cycles.use_adaptive_sampling = adaptive
    for o, h in vis:
        o.hide_render = h
    team = _bake_pass(tmp, "TEAM", px, "_team", False, 4)
    log("  rough / metal / ao baked")
    orm = np.zeros((px, px, 4), dtype=np.float32)
    occ = occ_groups if occ_groups is not None else np.clip(_px(ao)[..., 0], 0, 1)
    if ao_blur:
        k = (1.0, 4.0, 6.0, 4.0, 1.0)
        occ = sum(np.roll(occ, i - 2, axis=0) * k[i] for i in range(5)) / 16.0
        occ = sum(np.roll(occ, i - 2, axis=1) * k[i] for i in range(5)) / 16.0
    orm[..., 0] = occ
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
        if img is not None:
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
