"""The soldier's bake: villager.lowpoly.bake_all with the two things armour needs and hemp does not: METALNESS (the blue channel of the source's ORM) and the
source's own roughness range (lacquer and iron must be able to shine). Same files, same names, same return value, so villager.atlas runs on it unchanged:

    from villager import lowpoly; from soldier import bake; lowpoly.bake_all = bake.bake_all
"""
import os

import bpy
import numpy as np

from villager.lowpoly import _emit, _px, _src_nodes, _target

# Armour has more relief than a hemp jacket (tassets, a ration tube, rope ties), and a collapse-decimated LOD0 leaves the source by more than a villager's does:
# with the villager's 10 mm cage / 28 mm ray the tips of such parts baked black. Wider here; a ray that starts inside a neighbouring finger still lands on skin.
CAGE = float(os.environ.get("SOLDIER_CAGE", 0.016))      # m: how far the bake rays start above the low surface
RAY = float(os.environ.get("SOLDIER_RAY", 0.048))        # m: how far they may travel

METAL_FLOOR = 0.35       # source metalness below this is noise (cloth, skin): none
METAL_GAIN = 0.9         # and what is left is never a full mirror (worn iron, lacquer over it)


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

    # metalness (the blue channel of the source's ORM): iron plates, rivets, spear heads
    img_met = _target(low_mat, "_met", px, False)
    if n_orm is not None:
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(n_orm.outputs["Color"], sep.inputs["Color"])
        undo = _emit(nt, sep.outputs["Blue"])
        bpy.ops.object.bake(type="EMIT", **bk)
        undo()
        nt.nodes.remove(sep)
    log("  metal baked")

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
    met = np.clip(_px(img_met)[..., 0], 0, 1) if n_orm is not None else np.zeros_like(ao)
    # a soldier wears lacquer and iron as well as cloth: the source's roughness is kept (only its noise is calmed and its range held where a game light reads well),
    # and its metalness is kept where it is sure of itself (image-to-3D metalness is speckled on cloth and skin: below METAL_FLOOR it is none)
    if n_orm is not None:
        mean = float(rgh[covered].mean())
        rgh = np.clip(mean + (rgh - mean) * 0.85, 0.28, 0.98)
        met = np.clip((met - METAL_FLOOR) / (1.0 - METAL_FLOOR), 0.0, 1.0) * METAL_GAIN
    else:
        rgh = np.full_like(ao, 0.85)
    orm = np.zeros((px, px, 4), dtype=np.float32)
    orm[..., 0] = np.clip(ao * 0.85 + 0.15, 0, 1)
    orm[..., 1] = rgh
    orm[..., 2] = met
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
    for img in (img_rgh, img_met, img_pos, img_ao):
        bpy.data.images.remove(img)
    low.data.materials.clear()
    bpy.data.materials.remove(low_mat)
    sc.world = None
    bpy.data.worlds.remove(world)
    stats = {"covered_texels": round(float(covered.mean()), 3), "ao_mean": round(float(ao[covered].mean()), 3), "rough_mean": round(float(rgh[covered].mean()), 3),
             "metal_mean": round(float(met[covered].mean()), 3), "metal_texels": round(float((met[covered] > 0.5).mean()), 3)}
    return maps, stats
