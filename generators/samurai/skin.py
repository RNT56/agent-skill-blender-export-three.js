"""Skin weights: rigid parts bind 100% to their bone; soft parts blend by distance to bone segments (gaussian falloff,
region-limited candidate bones, top 4 influences, normalised). Then join the parts into skinned meshes."""
import math

import bpy
from mathutils import Vector

REGION = {
    "torso": (["hips", "spine", "spine1", "chest", "neck"], 0.085),
    "banner": (["chest", "banner_1", "banner_2"], 0.16),
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


def _smooth(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def tail_weights(key, co, bones):
    """Obi tail: the chain bones by distance along the tail, but the root ring stays on the hips (blend over the first 5 cm) so a twisting torso never tears the tail off the knot."""
    from . import cloth as C
    segs = {n: bones[n] for n in (f"sash_{key}1", f"sash_{key}2")}
    ws = soft_weights(co, segs, 0.05)
    t = _smooth(C.SASH_Z - 0.05, C.SASH_Z, co.z)                      # 1 at the root, 0 five centimetres below
    out = {n: w * (1.0 - t) for n, w in ws.items()}
    if t > 1e-4:
        out["hips"] = t
    return {n: w for n, w in out.items() if w > 1e-4}


def flag_weights(co, bones):
    """Flag cloth: along the cloth by distance to the three flag bones (the chain line at mid height, so only x matters); the top edge hangs from the cross bar, so the
    chain's influence fades in over the first half of the cloth's height and the rest follows the pole (banner_2)."""
    from .consts import CLOTH_H, TOP
    segs = {n: bones[n] for n in ("flag_1", "flag_2", "flag_3")}
    mid = segs["flag_1"][0]
    probe = Vector((co.x, mid.y, mid.z))
    ws = soft_weights(probe, segs, 0.045)
    g = _smooth(0.0, 0.45, (TOP - 0.004 - co.z) / CLOTH_H)
    out = {n: w * g for n, w in ws.items()}
    out["banner_2"] = 1.0 - g
    return {n: w for n, w in out.items() if w > 1e-4}


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
    elif soft and soft.startswith("tail:"):
        for v in me.vertices:
            for n, w in tail_weights(soft.split(":")[1], v.co, bones).items():
                vg(n).add([v.index], w, "REPLACE")
    elif soft == "flag":
        for v in me.vertices:
            for n, w in flag_weights(v.co, bones).items():
                vg(n).add([v.index], w, "REPLACE")
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
