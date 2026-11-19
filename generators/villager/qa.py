"""QA renders for the villager: fast Workbench shots (texture colour) of chosen objects from named views. Headless-safe.

    from villager import qa
    qa.shots(objs, "out/_villager/qa_high", views=("front", "side", "back", "q"), size=900)
"""
import math
import os

import bpy
from mathutils import Vector

VIEWS = {
    "front": (0.0, -1.0, 0.0), "back": (0.0, 1.0, 0.0), "side": (1.0, 0.0, 0.0), "side_r": (-1.0, 0.0, 0.0),
    "q": (0.75, -1.0, 0.25), "q_back": (-0.75, 1.0, 0.25), "top": (0.0, -0.05, 1.0), "low": (0.6, -1.0, -0.15),
}


def bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type != "MESH":
            continue
        ev = o.evaluated_get(dg)
        for c in ev.bound_box:
            w = ev.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


def _camera(scene):
    cam = bpy.data.objects.get("_qa_cam")
    if cam is None:
        cam = bpy.data.objects.new("_qa_cam", bpy.data.cameras.new("_qa_cam"))
        scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    scene.camera = cam
    return cam


def shots(objs, prefix, views=("front", "side", "back", "q"), size=900, focus=None, span=None, engine="BLENDER_WORKBENCH", flat=False, bg=(0.32, 0.33, 0.35)):
    """Render `objs` (everything else hidden from render) from each view to <prefix>_<view>.png. focus/span: centre and ortho height (default: fit)."""
    scene = bpy.context.scene
    os.makedirs(os.path.dirname(os.path.abspath(prefix)), exist_ok=True)
    keep = {o.name for o in objs}
    was = {o.name: o.hide_render for o in scene.objects}
    for o in scene.objects:
        o.hide_render = o.name not in keep
    lo, hi = bounds(objs)
    c = Vector(focus) if focus is not None else (lo + hi) * 0.5
    h = span if span is not None else max(hi.z - lo.z, hi.x - lo.x, hi.y - lo.y) * 1.08
    cam = _camera(scene)
    cam.data.ortho_scale = h
    scene.render.engine = engine
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    if engine == "BLENDER_WORKBENCH":
        sh = scene.display.shading
        sh.light = "FLAT" if flat else "STUDIO"
        sh.color_type = "TEXTURE"
        sh.show_shadows = False
        sh.show_cavity = not flat
        sh.show_object_outline = False
        sh.show_specular_highlight = False
        scene.display.render_aa = "8"
    world = scene.world or bpy.data.worlds.new("_qa_world")
    scene.world = world
    world.color = bg
    out = []
    for v in views:
        d = Vector(VIEWS[v]).normalized()
        cam.location = c + d * 12.0
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = f"{prefix}_{v}.png"
        bpy.ops.render.render(write_still=True)
        out.append(scene.render.filepath)
    for o in scene.objects:
        o.hide_render = was.get(o.name, False)
    return out


def sheet(paths, out, cols=None):
    """Tile PNGs into one contact sheet with Blender's own image API (no PIL in Blender's python)."""
    import numpy as np
    ims = []
    for p in paths:
        im = bpy.data.images.load(p)
        w, h = im.size
        a = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(a)
        ims.append(a.reshape(h, w, 4))
        bpy.data.images.remove(im)
    cols = cols or len(ims)
    rows = math.ceil(len(ims) / cols)
    h, w = ims[0].shape[:2]
    canvas = np.zeros((rows * h, cols * w, 4), dtype=np.float32)
    canvas[..., 3] = 1.0
    for i, a in enumerate(ims):
        r, c = divmod(i, cols)
        canvas[(rows - 1 - r) * h:(rows - r) * h, c * w:(c + 1) * w] = a
    res = bpy.data.images.new("_sheet", cols * w, rows * h, alpha=False)
    res.pixels.foreach_set(canvas.ravel())
    res.filepath_raw = out
    res.file_format = "JPEG" if out.lower().endswith((".jpg", ".jpeg")) else "PNG"
    res.save()
    bpy.data.images.remove(res)
    return out
