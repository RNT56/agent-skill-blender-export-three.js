"""Finish the archer: LOD meshes that keep the skin weights, one Action per clip.
LOD1 = decimated body + banner, then the full bow joined in; LOD2 = decimated body + banner, then the low bow: a thin bow does not survive collapse decimation,
so the bow is always joined AFTER it. One draw call per unit from LOD1 on (the nocked arrow stays its own node: it is shown only during a shot)."""
import json

import bpy

from samurai import finalize as SF

from . import anim, clips


def lod_copy(src, name, target_tris, arm, coll, pre=(), post=()):
    def tris(o):
        return sum(len(p.vertices) - 2 for p in o.data.polygons)

    ob = SF.decimate_copy(src, name, max(200, target_tris - sum(tris(o) for o in post)), arm, coll, extras=pre)
    if post:
        parts = [ob]
        for e in post:
            c = e.copy()
            c.data = e.data.copy()
            c.modifiers.clear()
            c.parent = None
            coll.objects.link(c)
            parts.append(c)
        bpy.context.view_layer.update()
        for o in bpy.context.view_layer.objects:
            if o is not None:
                o.select_set(False)
        for o in parts:
            o.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.join()
        ob = bpy.context.view_layer.objects.active
        ob.name = ob.data.name = name
        bpy.context.view_layer.update()
        SF.limit_influences(ob, 4)
    return ob


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
        log(f"  clip {name}: {int(act.frame_range[1] - act.frame_range[0])} frames, bow pulled in {act['gp_bow_shift_mm']} mm, string gap {act['gp_string_gap_mm']} mm, cloth {act.get('gp_cloth', '-')}")
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    return out
