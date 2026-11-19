"""Skin weights of the archer: the samurai's method (rigid parts 100% on one bone, soft parts by gaussian distance to bone segments, top 4) with the archer's regions:
flexing bow limbs, the string (tips on the limbs, centre on the nock bone), hachimaki tails that stay on the knot, the flag that hangs from its bar."""
from mathutils import Vector

from samurai import skin as SS

from . import consts as K, rig as R

REGION = {
    "torso": (["hips", "spine", "spine1", "chest", "neck"], 0.085),
    "neck": (["chest", "neck", "head"], 0.045),
    "pelvis": (["hips", "spine", "thigh.L", "thigh.R"], 0.085),
    "banner": (["chest", "banner_1", "banner_2"], 0.16),
    "bow": (["weapon_l", "bow_u1", "bow_u2", "bow_l1", "bow_l2"], 0.070),
}
for _s in ("L", "R"):
    REGION[f"arm.{_s}"] = (["chest", f"shoulder.{_s}", f"upper_arm.{_s}", f"forearm.{_s}"], 0.065)
    REGION[f"leg.{_s}"] = (["hips", f"thigh.{_s}", f"shin.{_s}", f"foot.{_s}"], 0.095)
    for _f in ("index", "middle", "ring", "pinky"):
        REGION[f"fing:{_f}.{_s}"] = ([f"hand.{_s}", f"{_f}_01.{_s}", f"{_f}_02.{_s}"], 0.016)
    REGION[f"fing:thumb.{_s}"] = ([f"hand.{_s}", f"thumb_01.{_s}", f"thumb_02.{_s}"], 0.018)


def tail_weights(key, co, bones):
    segs = {n: bones[n] for n in (f"tail_{key}1", f"tail_{key}2")}
    ws = SS.soft_weights(co, segs, 0.045)
    t = SS._smooth(R.TAIL_Z - 0.04, R.TAIL_Z, co.z)                      # the root stays on the knot
    out = {n: w * (1.0 - t) for n, w in ws.items()}
    if t > 1e-4:
        out["head"] = t
    return {n: w for n, w in out.items() if w > 1e-4}


def flag_weights(co, bones):
    segs = {n: bones[n] for n in ("flag_1", "flag_2", "flag_3")}
    mid = segs["flag_1"][0]
    ws = SS.soft_weights(Vector((co.x, mid.y, mid.z)), segs, 0.040)
    gg = SS._smooth(0.0, 0.45, (K.TOP - 0.004 - co.z) / K.CLOTH_H)
    out = {n: w * gg for n, w in ws.items()}
    out["banner_2"] = 1.0 - gg
    return {n: w for n, w in out.items() if w > 1e-4}


def string_weights(co):
    b = R.bow_rest()
    w = (co - b["G"]).dot(b["W"])
    if abs(w - R.NOCK_H) < 0.05:
        return {"bow_nock": 1.0}
    return {"bow_u2": 1.0} if w > 0 else {"bow_l2": 1.0}


def apply_weights(ob, arm_obj):
    me = ob.data
    bone = ob.get("gp_bone") or ""
    soft = ob.get("gp_soft") or ""
    bones = {b.name: (b.head_local.copy(), b.tail_local.copy()) for b in arm_obj.data.bones}
    groups = {}

    def vg(name):
        if name not in groups:
            groups[name] = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
        return groups[name]

    def put(v, ws):
        for n, w in ws.items():
            vg(n).add([v.index], w, "REPLACE")

    if bone:
        if bone not in bones:
            raise RuntimeError(f"part {ob.name}: no bone {bone}")
        vg(bone).add(list(range(len(me.vertices))), 1.0, "REPLACE")
    elif soft.startswith("tail:"):
        for v in me.vertices:
            put(v, tail_weights(soft.split(":")[1], v.co, bones))
    elif soft == "flag":
        for v in me.vertices:
            put(v, flag_weights(v.co, bones))
    elif soft == "string":
        for v in me.vertices:
            put(v, string_weights(v.co))
    elif soft:
        cand, sigma = REGION[soft]
        segs = {n: bones[n] for n in cand}
        for v in me.vertices:
            put(v, SS.soft_weights(v.co, segs, sigma))
    else:
        raise RuntimeError(f"part {ob.name} has neither a bone nor a soft region")


join, bind = SS.join, SS.bind
