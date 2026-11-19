"""Stage 2: the game mesh (LOD0) from the high-poly source: weighted collapse decimation, new UVs, and a baked atlas.

The source is ~2M triangles with its own 4K textures on an image-to-3D UV layout (hundreds of tiny charts): neither survives decimation.
So: decimate the SHAPE (hands, face and feet are protected by a vertex group), unwrap the result afresh, and transfer everything else by
baking high -> low (selected to active): albedo (as emission, so metal / lighting cannot touch it), tangent normal (the source's own normal
map included: the 2M triangles AND its texture detail land in one map), roughness, ambient occlusion, and a POSITION map that later stages
use to find regions (the jacket for the trade tint) without painting anything by hand.

Atlas layout: the body occupies v in [BODY_V0, 1]; the strip below is reserved for the props (tools, loads, hat), filled in the finalize stage.
"""
import json
import math
import os

import bmesh
import bpy
import numpy as np

from . import qa

BODY_V0 = 0.25           # the body's UVs are packed into v >= this; props get the strip below
CAGE = 0.010             # m: how far the bake rays start above the low surface
RAY = 0.028              # m: how far they may travel (thin gaps between fingers: keep it small)
PROTECT = {"hand": 0.12, "head": 0.03, "face": 0.07, "foot": 0.0}     # how much of the decimation weight the detail regions lose (0 = like cloth)
PROTECT_FACTOR = float(os.environ.get("VILLAGER_PROTECT", "1.0"))


def _coords(me):
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def protect_weights(co, height, hand_x=None):
    """per-vertex decimation weight (1 = decimate freely, small = keep): hands, face, feet keep more triangles than cloth."""
    x, y, z = np.abs(co[:, 0]), co[:, 1], co[:, 2]
    w = np.ones(len(co))
    # hands: the A-pose arms end beyond |x| ~ 0.36 below the hip line
    hx = hand_x if hand_x is not None else float(x.max()) - 0.159          # the A-pose arms end in the hands: the outermost 16 cm
    hand = np.clip((x - hx) / 0.05, 0, 1) * np.clip((0.98 * height / 1.68 - z) / 0.06, 0, 1)
    w = np.minimum(w, 1.0 - PROTECT["hand"] * hand)
    # head: face (front, -y) more than the back of the hair
    head = np.clip((z - (height - 0.27)) / 0.04, 0, 1)
    face = head * np.clip((-y + 0.02) / 0.06, 0, 1)
    w = np.minimum(w, 1.0 - PROTECT["head"] * head - PROTECT["face"] * face)
    # feet and sandals
    foot = np.clip((0.10 - z) / 0.04, 0, 1)
    w = np.minimum(w, 1.0 - PROTECT["foot"] * foot)
    return np.clip(w, 0.08, 1.0)


def decimate(high, name, tris, coll, weights=True, hand_x=None):
    me = high.data.copy()
    tmp = bpy.data.objects.new("_tmp_dec", me)
    coll.objects.link(tmp)
    n = sum(len(p.vertices) - 2 for p in me.polygons)
    md = tmp.modifiers.new("dec", "DECIMATE")
    md.decimate_type = "COLLAPSE"
    md.ratio = min(1.0, tris / n)
    md.use_collapse_triangulate = True
    if weights:
        co = _coords(me)
        w = protect_weights(co, float(co[:, 2].max()), hand_x)
        vg = tmp.vertex_groups.new(name="dec")
        # bulk assign through a float attribute is not available for vertex groups: bucket the weights (16 levels) to keep the python loop short
        q = np.round(w * 16) / 16
        for lvl in np.unique(q):
            vg.add(np.nonzero(q == lvl)[0].tolist(), float(lvl), "REPLACE")
        md.vertex_group = "dec"
        md.vertex_group_factor = PROTECT_FACTOR
        md.invert_vertex_group = False
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    out = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    out.name = name
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(me)
    bpy.context.view_layer.update()
    out.validate(verbose=False)
    bm = bmesh.new()
    bm.from_mesh(out)
    wire = [e for e in bm.edges if not e.link_faces]
    if wire:
        bmesh.ops.delete(bm, geom=wire, context="EDGES")
    loose = [v for v in bm.verts if not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(out)
    bm.free()
    for p in out.polygons:
        p.use_smooth = True
    while out.uv_layers:
        out.uv_layers.remove(out.uv_layers[0])
    out.materials.clear()
    ob = bpy.data.objects.new(name, out)
    coll.objects.link(ob)
    for vg in list(ob.vertex_groups):
        ob.vertex_groups.remove(vg)
    return ob


def region_tris(ob):
    co = _coords(ob.data)
    hands = feet = head = 0
    h = float(co[:, 2].max())
    for p in ob.data.polygons:
        c = p.center
        t = len(p.vertices) - 2
        if abs(c.x) > 0.37 and c.z < 0.95:
            hands += t
        elif c.z < 0.08:
            feet += t
        elif c.z > h - 0.25:
            head += t
    return {"hands": hands, "feet": feet, "head": head, "total": sum(len(p.vertices) - 2 for p in ob.data.polygons)}


def unwrap(ob, v0=BODY_V0, margin=0.0035):
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(72.0), island_margin=margin, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    # the strip below v0 is not ours: pack into a v0-tall rectangle by packing at aspect, then squeeze v
    try:
        bpy.ops.uv.pack_islands(rotate=True, margin=margin, shape_method="CONCAVE")
    except TypeError:
        bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    uv = ob.data.uv_layers.active
    uv.name = "UVMap"
    n = len(ob.data.loops)
    a = np.empty(n * 2, dtype=np.float64)
    uv.data.foreach_get("uv", a)
    a = a.reshape(-1, 2)
    return a


def pack_into_band(ob, v0=BODY_V0, margin=0.0035):
    """Re-pack the islands for a (1 x (1 - v0)) rectangle: scale u by 1/(1-v0) before packing (so islands are laid out for a wide target), then map back."""
    uv = ob.data.uv_layers["UVMap"]
    n = len(ob.data.loops)
    a = np.empty(n * 2, dtype=np.float64)
    uv.data.foreach_get("uv", a)
    a = a.reshape(-1, 2)
    k = 1.0 - v0
    # stretch v so that a later uniform squeeze by k restores the aspect: pack happens in a unit square whose v is "taller" by 1/k
    a[:, 1] /= k
    uv.data.foreach_set("uv", a.ravel())
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    try:
        bpy.ops.uv.pack_islands(rotate=True, margin=margin, shape_method="CONCAVE", scale=True)
    except TypeError:
        bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    uv = ob.data.uv_layers["UVMap"]
    uv.data.foreach_get("uv", a.ravel())
    a = np.empty(n * 2, dtype=np.float64)
    uv.data.foreach_get("uv", a)
    a = a.reshape(-1, 2)
    a[:, 1] = v0 + a[:, 1] * k
    uv.data.foreach_set("uv", a.ravel())
    ob.data.update()
    return {"u": [float(a[:, 0].min()), float(a[:, 0].max())], "v": [float(a[:, 1].min()), float(a[:, 1].max())]}


def uv_stats(ob, px):
    """texel density (px per metre, median over faces) and the share of the atlas the faces cover."""
    me = ob.data
    uv = me.uv_layers["UVMap"].data
    dens, cover = [], 0.0
    for p in me.polygons:
        li = list(p.loop_indices)
        a, b, c = (uv[i].uv for i in li[:3])
        ua = abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) * 0.5
        cover += ua
        if p.area > 1e-9 and ua > 0:
            dens.append(math.sqrt(ua / p.area) * px)
    dens.sort()
    return {"texel_px_per_m_median": round(dens[len(dens) // 2], 1), "texel_px_per_m_p10": round(dens[len(dens) // 10], 1), "atlas_cover": round(cover, 3)}


# ---------------------------------------------------------------------------------------------------- bake

def _src_nodes(mat):
    """the source material's base colour / normal / ORM image nodes (as the glTF importer builds them)."""
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")

    def up(sock):
        n = sock.links[0].from_node if sock.links else None
        seen = 0
        while n is not None and n.type != "TEX_IMAGE" and seen < 6:
            nxt = next((i.links[0].from_node for i in n.inputs if i.links), None)
            n = nxt
            seen += 1
        return n
    return nt, bsdf, up(bsdf.inputs["Base Color"]), up(bsdf.inputs["Normal"]), up(bsdf.inputs["Roughness"])


def _emit(nt, socket):
    """route `socket` (a colour / value output) straight to the material output as emission; returns an undo closure."""
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output)
    old = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].links else None
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(socket, em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])

    def undo():
        if old is not None:
            nt.links.new(old, out.inputs["Surface"])
        nt.nodes.remove(em)
    return undo


def _target(low_mat, name, px, srgb, is_float=False):
    img = bpy.data.images.new(name, px, px, alpha=False, float_buffer=is_float)
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    nt = low_mat.node_tree
    node = nt.nodes.get("_bake") or nt.nodes.new("ShaderNodeTexImage")
    node.name = "_bake"
    node.image = img
    for n in nt.nodes:
        n.select = False
    node.select = True
    nt.nodes.active = node
    return img


def _px(img):
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def bake_all(high, low, out_dir, px=2048, ao_samples=48, log=print):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.use_denoising = False
    world = bpy.data.worlds.new("_bake_world")
    sc.world = world
    world.light_settings.distance = 0.12
    os.makedirs(out_dir, exist_ok=True)
    low_mat = bpy.data.materials.new("_bake_low")
    low_mat.use_nodes = True
    low.data.materials.clear()
    low.data.materials.append(low_mat)
    nt, bsdf, n_col, n_nrm, n_orm = _src_nodes(high.data.materials[0])
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    high.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    bk = dict(use_selected_to_active=True, cage_extrusion=CAGE, max_ray_distance=RAY, margin=12, margin_type="EXTEND", use_clear=True)

    # albedo: the source's base colour as emission (no lighting, no metal)
    sc.cycles.samples = 4
    img_alb = _target(low_mat, "villager_albedo", px, True)
    undo = _emit(nt, n_col.outputs["Color"])
    bpy.ops.object.bake(type="EMIT", **bk)
    undo()
    log("  albedo baked")

    # roughness (the green channel of the source's ORM) as emission
    img_rgh = _target(low_mat, "_rgh", px, False)
    if n_orm is not None:
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(n_orm.outputs["Color"], sep.inputs["Color"])
        undo = _emit(nt, sep.outputs["Green"])
        bpy.ops.object.bake(type="EMIT", **bk)
        undo()
        nt.nodes.remove(sep)
    log("  roughness baked")

    # position of the surface (object space, packed into 0..1): finds regions later
    img_pos = _target(low_mat, "_pos", px, False, is_float=True)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mp = nt.nodes.new("ShaderNodeVectorMath")
    mp.operation = "MULTIPLY_ADD"
    mp.inputs[1].default_value = (0.5, 0.5, 0.5)
    mp.inputs[2].default_value = (0.5, 0.5, 0.0)
    nt.links.new(geo.outputs["Position"], mp.inputs[0])
    undo = _emit(nt, mp.outputs["Vector"])
    bpy.ops.object.bake(type="EMIT", **dict(bk, margin=0))
    undo()
    nt.nodes.remove(mp)
    nt.nodes.remove(geo)
    log("  position baked")

    # tangent-space normal: the high poly's geometry AND its own normal map
    sc.render.bake.normal_space = "TANGENT"
    img_nrm = _target(low_mat, "villager_normal", px, False)
    bpy.ops.object.bake(type="NORMAL", **bk)
    log("  normal baked")

    # ambient occlusion of the high poly (creases of the cloth, under the jacket hem, between the fingers)
    sc.cycles.samples = ao_samples
    img_ao = _target(low_mat, "_ao", px, False)
    bpy.ops.object.bake(type="AO", **bk)
    log("  ao baked")

    pos = _px(img_pos)[..., :3].copy()
    np.save(os.path.join(out_dir, "villager_pos.npy"), pos.astype(np.float16))
    ao = np.clip(_px(img_ao)[..., 0], 0, 1)
    rgh = np.clip(_px(img_rgh)[..., 0], 0, 1)
    covered = (pos[..., 2] > 1e-4) | (pos[..., 0] != 0)
    # a villager has no metal; cloth and skin want a high, slightly varied roughness (the source's roughness is noisy: compress it)
    rgh = np.clip(0.62 + (rgh - float(rgh[covered].mean())) * 0.6 + 0.16, 0.45, 0.98) if n_orm is not None else np.full_like(ao, 0.85)
    orm = np.zeros((px, px, 4), dtype=np.float32)
    orm[..., 0] = np.clip(ao * 0.85 + 0.15, 0, 1)
    orm[..., 1] = rgh
    orm[..., 2] = 0.0
    orm[..., 3] = 1.0
    img_orm = bpy.data.images.new("villager_orm", px, px, alpha=False)
    img_orm.colorspace_settings.name = "Non-Color"
    img_orm.pixels.foreach_set(orm.ravel())
    maps = {}
    for key, img, fname, fmt in (("albedo", img_alb, "villager_albedo.png", "PNG"), ("normal", img_nrm, "villager_normal.png", "PNG"), ("orm", img_orm, "villager_orm.png", "PNG")):
        img.filepath_raw = os.path.join(out_dir, fname)
        img.file_format = fmt
        img.save()
        maps[key] = img
    for img in (img_rgh, img_pos, img_ao):
        bpy.data.images.remove(img)
    low.data.materials.clear()
    bpy.data.materials.remove(low_mat)
    sc.world = None
    bpy.data.worlds.remove(world)
    stats = {"covered_texels": round(float(covered.mean()), 3), "ao_mean": round(float(ao[covered].mean()), 3), "rough_mean": round(float(rgh[covered].mean()), 3)}
    return maps, stats


def run(work, tris=11000, px=2048, samples=48, hand_x=None, log=print):
    import sys
    from recipes import _common as C
    bpy.ops.wm.open_mainfile(filepath=os.path.join(work, "villager_high.blend"))
    sc = bpy.context.scene
    sc.render.fps = 30
    high = bpy.data.objects["Villager_High"]
    coll = sc.collection
    low = decimate(high, "Villager_LOD0", tris, coll, weights=PROTECT_FACTOR != 0, hand_x=hand_x)
    rt = region_tris(low)
    log("  LOD0 " + json.dumps(rt))
    if os.environ.get("VILLAGER_DEC_ONLY"):
        qa.sheet(qa.shots([low], os.path.join(work, "qa", "dec"), views=("front", "q"), size=1000) + qa.shots([low], os.path.join(work, "qa", "dec_hand"), views=("front", "side"), size=1000, focus=(0.40, 0, 0.78), span=0.42)
                 + qa.shots([low], os.path.join(work, "qa", "dec_head"), views=("front", "q"), size=1000, focus=(0, 0, 1.56), span=0.5), os.path.join(work, "qa", "dec_sheet.jpg"), cols=3)
        return low
    unwrap(low)
    band = pack_into_band(low)
    st = uv_stats(low, px)
    log("  uv " + json.dumps({**band, **st}))
    tex = os.path.join(work, "tex")
    maps, bstats = bake_all(high, low, tex, px=px, ao_samples=samples, log=log)
    log("  bake " + json.dumps(bstats))
    mat = C.pbr_material("villager_mat", maps)
    low.data.materials.append(mat)
    # QA: the low poly with its baked albedo next to the source
    paths = qa.shots([low], os.path.join(work, "qa", "low"), views=("front", "side", "back", "q"), size=1000)
    paths += qa.shots([low], os.path.join(work, "qa", "low_head"), views=("front", "q"), size=1000, focus=(0, 0, 1.56), span=0.5)
    paths += qa.shots([low], os.path.join(work, "qa", "low_hand"), views=("front", "side"), size=1000, focus=(0.40, 0, 0.78), span=0.42)
    qa.sheet(paths[:4], os.path.join(work, "qa", "low_sheet.jpg"))
    qa.sheet(paths[4:], os.path.join(work, "qa", "low_detail.jpg"))
    # lit check (EEVEE, normal map + AO at work)
    try:
        lit = lit_shots(low, os.path.join(work, "qa", "low_lit"))
        qa.sheet(lit, os.path.join(work, "qa", "low_lit_sheet.jpg"))
    except Exception as exc:
        log("  lit shots skipped: " + repr(exc))
    # the upload for auto-rigging: LOD0 with the albedo only, glTF axes (+Y up, the figure faces +Z)
    bpy.data.objects.remove(high, do_unlink=True)
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(o == low)
    bpy.context.view_layer.objects.active = low
    rig_mat = bpy.data.materials.new("villager_rigsrc")
    rig_mat.use_nodes = True
    t = rig_mat.node_tree.nodes.new("ShaderNodeTexImage")
    t.image = maps["albedo"]
    rig_mat.node_tree.links.new(t.outputs["Color"], rig_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    low.data.materials.clear()
    low.data.materials.append(rig_mat)
    bpy.ops.export_scene.gltf(filepath=os.path.join(work, "villager_low.glb"), export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
                              export_image_format="JPEG", export_jpeg_quality=88, export_animations=False)
    low.data.materials.clear()
    low.data.materials.append(mat)
    bpy.data.materials.remove(rig_mat)
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, "villager_low.blend"), compress=True)
    with open(os.path.join(work, "lowpoly.json"), "w") as fh:
        json.dump({"tris": rt, "uv": {**band, **st}, "bake": bstats, "px": px}, fh, indent=1)
    return low


def lit_shots(ob, prefix, size=1000):
    """EEVEE shots under a sun + sky fill: the normal map and AO must read as cloth folds, not as noise."""
    sc = bpy.context.scene
    sun = bpy.data.objects.new("_qa_sun", bpy.data.lights.new("_qa_sun", "SUN"))
    sc.collection.objects.link(sun)
    sun.data.energy = 3.2
    sun.rotation_euler = (math.radians(52), 0, math.radians(-38))
    w = bpy.data.worlds.new("_qa_lit")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.62, 0.75, 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9
    old = sc.world
    sc.world = w
    eng = "BLENDER_EEVEE" if "BLENDER_EEVEE" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE_NEXT"
    sc.view_settings.view_transform = "Standard"
    out = qa.shots([ob], prefix, views=("front", "q", "back"), size=size, engine=eng)
    out += qa.shots([ob], prefix + "_head", views=("q",), size=size, focus=(0, 0, 1.52), span=0.6, engine=eng)
    sc.world = old
    bpy.data.objects.remove(sun, do_unlink=True)
    return out
