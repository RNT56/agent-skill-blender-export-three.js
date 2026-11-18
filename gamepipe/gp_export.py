"""gamepipe export primitives (run inside Blender).

Conventions: GLB, +Y up, metres, modifiers applied, only the asset's objects, root offset removed.
Compression uses Blender's OWN glTF exporter (no external tools, nothing downloaded):
  meshopt geometry compression (EXT_meshopt_compression) + KTX2/BasisU textures (KHR_texture_basisu).
  Needs MeshoptDecoder + KTX2Loader in the engine (three.js: see viewer/). Falls back to plain GLB if unsupported.
"""
import os

import bpy

from gp_validate import resolve_objects


def _select_only(objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def _supported(kwargs):
    """Drop export kwargs this Blender's exporter doesn't know (keeps the pipeline portable across versions)."""
    props = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    dropped = [k for k in kwargs if k not in props]
    return {k: v for k, v in kwargs.items() if k in props}, dropped


def export_glb(spec, out_dir):
    """Export the spec's objects to <out_dir>/<name>.glb. Returns {path, size_mb, compressed, dropped_options}."""
    objs, _ = resolve_objects(spec)
    is_char = spec.get("type") == "character"
    objs = [o for o in objs if o.type in ({"MESH", "CURVE", "ARMATURE"} if is_char else {"MESH", "CURVE"})]
    if not objs:
        raise RuntimeError("nothing to export")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{spec['name']}.glb")
    exp = spec.get("export", {})
    compress = exp.get("compress", True)

    root = bpy.data.objects.get((spec.get("root_object") or ""))
    root_loc = None
    if root is not None:
        root_loc = root.location.copy()
        root.location = (0, 0, 0)       # glTF exports world transforms; neutralise the root so the asset sits at the origin
        bpy.context.view_layer.update()
    kwargs = dict(
        filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
        export_texcoords=True, export_normals=True, export_tangents=exp.get("tangents", False),
        export_materials="EXPORT", export_image_format="AUTO",
        export_cameras=False, export_lights=False, export_animations=is_char,
        export_draco_mesh_compression_enable=False,
    )
    if is_char:                      # skinned mesh + one glTF animation per Action (FK keys are already baked in the Actions)
        kwargs.update(export_skins=True, export_animation_mode="ACTIONS", export_force_sampling=True, export_frame_range=False,
                      export_optimize_animation_size=True, export_anim_single_armature=True, export_reset_pose_bones=True,
                      export_influence_nb=4, export_nla_strips=False, export_def_bones=False)
    if compress:
        kwargs.update(
            export_meshopt_compression_enable=True,
            export_image_add_compressed_images=True,
            export_compressed_images_type="KTX2",
            export_compressed_images_fallback=exp.get("png_fallback", False),
            export_use_ktx_compression=True,        # zstd on the UASTC (normal/ORM) KTX2 textures
        )
    kwargs, dropped = _supported(kwargs)
    try:
        _select_only(objs)
        bpy.ops.export_scene.gltf(**kwargs)
    finally:
        if root is not None:
            root.location = root_loc
            bpy.context.view_layer.update()
    saved = 0
    if compress and "export_compressed_images_type" in kwargs and not exp.get("png_fallback", False):
        import gp_glb
        saved = gp_glb.strip_fallback_images(path)      # Blender embeds every texture twice (KTX2 + original); keep KTX2 only
    return {"path": path, "size_mb": round(os.path.getsize(path) / 1048576, 3),
            "compressed": bool(compress and "export_meshopt_compression_enable" in kwargs),
            "fallback_images_stripped_kb": saved // 1024, "dropped_options": dropped}
