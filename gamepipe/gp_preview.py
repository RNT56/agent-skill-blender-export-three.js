"""Preview: re-import each exported GLB into a CLEAN scene and render it with the shared look (looks/*.json),
so what you see is what the engine gets. Runs inside Blender. Replaces the open scene: headless runs only.

GLB files compressed with meshopt/KTX2 may not re-import in a Blender without the decoders; then pass the
uncompressed twin (export.preview_uncompressed) or skip - the three.js viewer is the real engine check.
"""
import json
import math
import os

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_look(name="golden_hour"):
    with open(os.path.join(ROOT, "looks", f"{name}.json")) as fh:
        return json.load(fh)


def render_previews(glb_paths, out_dir, look="golden_hour", size=(900, 1100)):
    lk = load_look(look)
    rendered = []
    for path in glb_paths:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sc = bpy.context.scene
        bpy.ops.import_scene.gltf(filepath=path)
        objs = [o for o in sc.objects if o.type == "MESH"]
        lo = Vector((1e9,) * 3); hi = Vector((-1e9,) * 3)
        for o in objs:
            for c in o.bound_box:
                p = o.matrix_world @ Vector(c)
                lo = Vector((min(lo.x, p.x), min(lo.y, p.y), min(lo.z, p.z)))
                hi = Vector((max(hi.x, p.x), max(hi.y, p.y), max(hi.z, p.z)))
        ctr = (lo + hi) / 2
        h = max(hi.z - lo.z, 0.5)
        bpy.ops.mesh.primitive_plane_add(size=h * 8, location=(ctr.x, ctr.y, lo.z))
        g = bpy.context.active_object
        gm = bpy.data.materials.new("g"); gm.use_nodes = True
        gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*lk["ground"]["color"], 1)
        g.data.materials.append(gm)
        s = lk["sun"]
        ld = bpy.data.lights.new("sun", "SUN"); ld.energy = s["blender_strength"]
        ld.color = s["color"]; ld.angle = math.radians(3)
        sun = bpy.data.objects.new("sun", ld); sc.collection.objects.link(sun)
        sun.rotation_euler = (math.radians(90 - s["elevation_deg"]), 0, math.radians(s["azimuth_deg"] + 180))
        w = bpy.data.worlds.new("w"); w.use_nodes = True
        bg = w.node_tree.nodes["Background"]
        bg.inputs["Color"].default_value = (*lk["sky"]["ambient_sky"], 1)
        bg.inputs["Strength"].default_value = lk["sky"]["blender_strength"]
        sc.world = w
        cd = bpy.data.cameras.new("cam"); cd.lens = 45
        cam = bpy.data.objects.new("cam", cd); sc.collection.objects.link(cam)
        cam.location = ctr + Vector((h * 1.7, -h * 1.7, h * 0.08))
        cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
        sc.camera = cam
        sc.render.engine = "BLENDER_EEVEE"
        sc.render.resolution_x, sc.render.resolution_y = size
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.exposure = lk["exposure"]["blender"]
        sc.render.filepath = os.path.join(out_dir, os.path.basename(path).replace(".glb", ".preview.png"))
        bpy.ops.render.render(write_still=True)
        rendered.append(sc.render.filepath)
        print("preview:", sc.render.filepath)
    return rendered
