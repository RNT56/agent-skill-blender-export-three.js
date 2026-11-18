"""Finish the asset: LOD meshes (collapse-decimated copies that keep the skin weights), one Action per clip, fixture save."""
import json

import bpy

from . import anim, clips, skin


def decimate_copy(src, name, target_tris, arm, coll, extras=()):
    """Collapse-decimated, skin-preserving copy of `src` with the `extras` shells (scabbard, sheathed hilt) baked in: fewer draw calls per unit at range."""
    me = src.data.copy()
    tmp = bpy.data.objects.new("_tmp_dec", me)
    bpy.context.scene.collection.objects.link(tmp)
    if extras:
        parts = [tmp]
        for e in extras:
            c = e.copy()
            c.data = e.data.copy()
            c.modifiers.clear()
            c.parent = None
            bpy.context.scene.collection.objects.link(c)
            parts.append(c)
        for o in bpy.context.view_layer.objects:
            if o is not None:
                o.select_set(False)
        for o in parts:
            o.select_set(True)
        bpy.context.view_layer.objects.active = tmp
        bpy.ops.object.join()
        me = tmp.data
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    md = tmp.modifiers.new("dec", "DECIMATE")
    md.decimate_type = "COLLAPSE"
    md.ratio = min(1.0, target_tris / max(tris, 1))
    md.use_collapse_triangulate = True
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    out = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    out.name = name
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(me)
    bpy.context.view_layer.update()
    out.validate(verbose=False)
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(out)
    wire = [e for e in bm.edges if not e.link_faces]
    if wire:
        bmesh.ops.delete(bm, geom=wire, context="EDGES")
    loose = [v for v in bm.verts if not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(out)
    bm.free()
    for p in out.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new(name, out)
    coll.objects.link(ob)                    # group NAMES travel with the mesh data in Blender 5: do not create them again
    skin.bind(ob, arm)
    limit_influences(ob, 4)
    return ob


def limit_influences(ob, n=4):
    """Keep the n strongest weights per vertex and renormalise (decimation blends groups of the collapsed vertices)."""
    groups = {vg.index: vg for vg in ob.vertex_groups}
    for v in ob.data.vertices:
        ws = sorted(((g.weight, g.group) for g in v.groups if g.weight > 1e-4), reverse=True)
        if len(ws) <= n and abs(sum(w for w, _ in ws) - 1.0) < 1e-3:
            continue
        keep = ws[:n]
        tot = sum(w for w, _ in keep) or 1.0
        for gi in [g.group for g in v.groups]:
            groups[gi].remove([v.index])
        for w, gi in keep:
            groups[gi].add([v.index], w / tot, "REPLACE")


def weight_report(ob):
    """(vertices, unweighted, max influences) for a skinned mesh."""
    me = ob.data
    names = {vg.index: vg.name for vg in ob.vertex_groups}
    bad, mx = 0, 0
    for v in me.vertices:
        ws = [g.weight for g in v.groups if g.weight > 1e-4 and g.group in names]
        mx = max(mx, len(ws))
        if not ws or abs(sum(ws) - 1.0) > 0.02:
            bad += 1
    return len(me.vertices), bad, mx


def bake_clips(arm, names=None, log=print):
    sv = anim.Solver(arm)
    out = {}
    for name, c in clips.CLIPS.items():
        if names and name not in names:
            continue
        act = anim.bake(arm, sv, name, c["fn"], c["duration"], loop=c["loop"], speed=float(c.get("speed", 0.0)))
        act["gp_loop"] = int(c["loop"])
        act["gp_weapon"] = c["weapon"]
        act["gp_weapon_end"] = c.get("weapon_end", c["weapon"])
        act["gp_events"] = json.dumps(c.get("events", {}))
        act["gp_fps"] = anim.FPS
        act["gp_speed"] = float(c.get("speed", 0.0))
        out[name] = (act.frame_range[0], act.frame_range[1])
        log(f"  clip {name}: {int(act.frame_range[1] - act.frame_range[0])} frames, cloth {act.get('gp_cloth', '-')}")
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    return out
