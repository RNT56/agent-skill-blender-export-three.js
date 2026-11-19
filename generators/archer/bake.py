"""Atlas baking for the archer: the samurai's baker (samurai/bake.py) with one change: texel density is not uniform. The face, eyes and hair get 2.1x the linear
density of the rest and the war hat 1.35x (they are what a close camera looks at), by scaling those UV islands between 'average islands scale' and the pack."""
import math

import bpy
import numpy as np

from samurai import bake as SBk

BOOST = {"arc_face": 2.6, "arc_eye": 2.1, "arc_iris": 2.1, "arc_hair": 1.6, "arc_jingasa": 1.35, "arc_fletch": 1.4, "arc_teamcloth": 1.2}


def atlas_uv(objs, margin=0.0016):
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
    bpy.ops.object.mode_set(mode="OBJECT")
    me = tmp.data
    uvl = me.uv_layers["atlas"]                             # re-fetch: edit mode invalidates the old wrapper
    nloop, npoly = len(me.loops), len(me.polygons)
    uv = np.empty(nloop * 2, dtype=np.float32)
    uvl.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    mi = np.empty(npoly, dtype=np.int32)
    ls = np.empty(npoly, dtype=np.int32)
    tot = np.empty(npoly, dtype=np.int32)
    me.polygons.foreach_get("material_index", mi)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", tot)
    scale = np.array([BOOST.get(s.material.name if s.material else "", 1.0) for s in tmp.material_slots] or [1.0], dtype=np.float32)
    loop_scale = np.repeat(scale[mi], tot)                    # polygons own consecutive loop runs, in order
    order = np.argsort(ls, kind="stable")
    assert np.array_equal(order, np.arange(npoly))
    uv *= loop_scale[:, None]                                 # islands of one material scale together (an island never mixes materials: parts are separate shells)
    uvl.data.foreach_set("uv", uv.ravel())
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(margin=margin, rotate=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    uvl = tmp.data.uv_layers["atlas"]
    uvl.data.foreach_get("uv", uv.reshape(-1))
    uv = uv.reshape(-1, 2)
    src = np.empty(npoly, dtype=np.int32)
    tmp.data.attributes["src"].data.foreach_get("value", src)
    for k, ob in enumerate(objs):
        idx = np.concatenate([np.arange(ls[i], ls[i] + tot[i]) for i in np.nonzero(src == k)[0]])
        assert len(idx) == len(ob.data.loops), (ob.name, len(idx), len(ob.data.loops))
        lay = ob.data.uv_layers.new(name="atlas")
        lay.data.foreach_set("uv", uv[idx].ravel())
        ob.data.uv_layers.active = lay
        lay.active_render = True
    return tmp


def bake_atlas(objs, out_dir, name, px=2048, quality=1.0, log=print):
    SBk.atlas_uv = atlas_uv                                   # the samurai baker calls its module-level atlas_uv: give it the weighted one for this run
    return SBk.bake_atlas(objs, out_dir, name, px=px, quality=quality, log=log, ao_samples=int(192 * quality), ao_blur=True)       # bare skin under a hat brim shows AO grain that armour hides


assign_baked = SBk.assign_baked
