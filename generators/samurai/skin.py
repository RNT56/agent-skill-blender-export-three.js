"""Skin weights: rigid parts bind 100% to their bone; soft parts blend by distance to bone segments (gaussian falloff,
region-limited candidate bones, top 4 influences, normalised). Then join the parts into skinned meshes."""
import math

import bpy
from mathutils import Vector

REGION = {
    "torso": (["hips", "spine", "spine1", "chest", "neck"], 0.085),
}
for _s in ("L", "R"):
    # the sleeve ends at the wrist and the rigid kote cuffs ride the forearm: no hand influence, so the cuff never separates from them
    REGION[f"arm.{_s}"] = (["chest", f"shoulder.{_s}", f"upper_arm.{_s}", f"forearm.{_s}"], 0.065)
    REGION[f"leg.{_s}"] = (["hips", f"thigh.{_s}", f"shin.{_s}", f"foot.{_s}"], 0.095)
    for _f in ("index", "middle", "ring", "pinky"):
        REGION[f"fing:{_f}.{_s}"] = ([f"hand.{_s}", f"{_f}_01.{_s}", f"{_f}_02.{_s}"], 0.016)
    REGION[f"fing:thumb.{_s}"] = ([f"hand.{_s}", f"thumb_01.{_s}", f"thumb_02.{_s}"], 0.018)


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (p - (a + ab * t)).length


def soft_weights(co, segs, sigma):
    ws = []
    for name, (a, b) in segs.items():
        d = seg_dist(co, a, b)
        w = math.exp(-(d / sigma) ** 2)
        if w > 1e-3:
            ws.append((w, name))
    if not ws:
        name = min(segs, key=lambda n: seg_dist(co, *segs[n]))
        return {name: 1.0}
    ws.sort(reverse=True)
    ws = ws[:4]
    tot = sum(w for w, _ in ws)
    return {n: w / tot for w, n in ws}


def apply_weights(ob, arm_obj):
    """Create vertex groups on `ob` from its gp_bone / gp_soft tags."""
    me = ob.data
    bone = ob.get("gp_bone") or ""
    soft = ob.get("gp_soft") or ""
    bones = {b.name: (b.head_local.copy(), b.tail_local.copy()) for b in arm_obj.data.bones}
    groups = {}

    def vg(name):
        if name not in groups:
            groups[name] = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
        return groups[name]

    if bone:
        g = vg(bone)
        g.add(list(range(len(me.vertices))), 1.0, "REPLACE")
    elif soft:
        cand, sigma = REGION[soft]
        segs = {n: bones[n] for n in cand}
        for v in me.vertices:
            for n, w in soft_weights(v.co, segs, sigma).items():
                vg(n).add([v.index], w, "REPLACE")
    else:
        raise RuntimeError(f"part {ob.name} has neither a bone nor a soft region")


def join(objs, name):
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    ob.data.name = name
    return ob


def bind(ob, arm_obj):
    ob.parent = arm_obj
    md = ob.modifiers.new("Armature", "ARMATURE")
    md.object = arm_obj
    md.use_vertex_groups = True
    return ob
