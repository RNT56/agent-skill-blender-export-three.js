"""QA renders for the samurai (EEVEE, neutral studio). LOOK at the output; logs cannot tell you the head is lopsided."""
import math

import bpy
from mathutils import Vector

VIEWS = {
    "front": ((0, -6.0, 0.95), (0, 0, 0.95), 85),
    "side": ((6.0, 0, 0.95), (0, 0, 0.95), 85),
    "side_c": ((5.0, 0, 0.95), (0, 0, 0.95), 70),
    "front_c": ((0, -5.0, 0.95), (0, 0, 0.95), 70),
    "three_c": ((3.2, -3.6, 1.1), (0, 0, 0.95), 62),
    "hand_l": ((0.78, -0.55, 0.98), (0.42, -0.03, 0.86), 80),
    "hand_back": ((0.78, 0.45, 0.98), (0.42, -0.03, 0.86), 80),
    "grip": ((0.55, -1.05, 1.28), (0.0, -0.30, 1.08), 55),
    "grip_top": ((0.1, -0.55, 1.95), (0.0, -0.30, 1.08), 55),
    "back": ((0, 6.0, 0.95), (0, 0, 0.95), 85),
    "robe": ((1.0, -1.5, 0.80), (0.0, 0, 0.70), 60),
    "face": ((0.30, -0.62, 1.67), (0.0, -0.10, 1.655), 62),
    "face_f": ((0.0, -0.65, 1.68), (0.0, -0.10, 1.65), 55),
    "shikoro_f": ((0.55, -0.95, 1.62), (0.0, 0.0, 1.60), 52),
    "hips_f": ((0.55, -1.45, 0.95), (0.06, -0.1, 0.85), 50),
    "flag_b": ((0.0, 3.2, 2.0), (0.1, 0.0, 2.0), 50),
    "back_hi": ((0.0, 4.6, 1.5), (0, 0, 1.5), 62),
    "back_q": ((2.6, 3.4, 1.7), (0, 0, 1.5), 55),
    "three": ((3.4, -4.6, 1.25), (0, 0, 0.9), 70),
    "head": ((0.6, -1.5, 1.66), (0, 0, 1.62), 60),
    "torso": ((0.9, -2.4, 1.2), (0, 0, 1.15), 60),
    "hands": ((1.0, -1.9, 0.95), (0.38, 0, 0.95), 60),
    "legs": ((1.0, -2.8, 0.5), (0, 0, 0.5), 60),
}


def setup_scene(res=(900, 1200), samples=24):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = res
    try:
        sc.eevee.taa_render_samples = samples
    except Exception:
        pass
    sc.view_settings.view_transform = "AgX"
    w = bpy.data.worlds.new("qa_world")
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.62, 0.64, 0.68, 1)
    bg.inputs["Strength"].default_value = 1.1
    sc.world = w
    objs = []
    for name, loc, rot, energy, col, size in (
        ("key", (3.5, -4.0, 4.5), None, 600.0, (1.0, 0.93, 0.82), 3.0),
        ("fill", (-4.0, -3.0, 2.2), None, 220.0, (0.75, 0.85, 1.0), 4.0),
        ("rim", (0.5, 4.5, 3.5), None, 380.0, (1.0, 0.95, 0.9), 3.0),
    ):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.color, ld.size = energy, col, size
        lo = bpy.data.objects.new(name, ld)
        sc.collection.objects.link(lo)
        lo.location = loc
        d = Vector((0, 0, 1.0)) - Vector(loc)
        lo.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        objs.append(lo)
    # ground disc for contact shadows
    me = bpy.data.meshes.new("qa_ground")
    bpy.ops.mesh.primitive_circle_add(vertices=48, radius=2.5, fill_type="NGON", location=(0, 0, -0.002))
    g = bpy.context.active_object
    g.name = "qa_ground"
    gm = bpy.data.materials.new("qa_ground_mat")
    gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.22, 0.22, 0.23, 1)
    gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    g.data.materials.append(gm)
    cd = bpy.data.cameras.new("qa_cam")
    cam = bpy.data.objects.new("qa_cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    return cam


def shoot(path_base, views, res=(900, 1200), samples=24):
    cam = setup_scene(res, samples)
    sc = bpy.context.scene
    out = []
    for tag in views:
        loc, tgt, lens = VIEWS[tag]
        cam.data.lens = lens
        cam.location = loc
        cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = f"{path_base}_{tag}.png"
        bpy.ops.render.render(write_still=True)
        out.append(sc.render.filepath)
    return out


def montage(files, out, cols=None):
    """Tile PNGs side by side (numpy only, no PIL inside Blender)."""
    import numpy as np
    imgs = []
    for f in files:
        im = bpy.data.images.load(f)
        w, h = im.size
        a = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(a)
        imgs.append(a.reshape(h, w, 4))
        bpy.data.images.remove(im)
    cols = cols or len(imgs)
    rows = (len(imgs) + cols - 1) // cols
    h, w = imgs[0].shape[:2]
    sheet = np.ones((h * rows, w * cols, 4), dtype=np.float32)
    for i, a in enumerate(imgs):
        r, c = divmod(i, cols)
        sheet[(rows - 1 - r) * h:(rows - r) * h, c * w:(c + 1) * w] = a
    o = bpy.data.images.new("montage", w * cols, h * rows, alpha=False)
    o.pixels.foreach_set(sheet.ravel())
    o.filepath_raw = out
    o.file_format = "PNG"
    o.save()
    return out
