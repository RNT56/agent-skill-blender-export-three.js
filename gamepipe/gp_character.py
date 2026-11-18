"""Validator extras for skinned, animated characters (spec type "character"). Runs inside Blender.

Spec block:  "character": {"max_bones": 64, "max_influences": 4, "clips": {"idle": {"loop": true}, ...}}
Finding codes: SKIN_NO_ARMATURE SKIN_NOT_BOUND SKIN_UNWEIGHTED SKIN_MAX_INFLUENCE SKIN_BAD_GROUP RIG_BONE_BUDGET
               ANIM_MISSING ANIM_SHORT ANIM_LOOP_MISMATCH ANIM_ACTIVE
"""
import bpy


def _f(level, code, obj, msg):
    return {"level": level, "code": code, "object": obj, "message": msg}


def weight_stats(ob, bone_names):
    """(vertices, unweighted_or_unnormalised, max_influences, groups_that_are_not_bones)."""
    names = {vg.index: vg.name for vg in ob.vertex_groups}
    bad, mx = 0, 0
    for v in ob.data.vertices:
        ws = [g.weight for g in v.groups if g.weight > 1e-4 and g.group in names]
        mx = max(mx, len(ws))
        if not ws or abs(sum(ws) - 1.0) > 0.02:
            bad += 1
    stray = sorted({n for n in names.values() if n not in bone_names})
    return len(ob.data.vertices), bad, mx, stray


def check(spec, objs):
    cfg = spec.get("character", {})
    out = []
    arms = [o for o in objs if o.type == "ARMATURE"]
    meshes = [o for o in objs if o.type == "MESH"]
    if len(arms) != 1:
        out.append(_f("error", "SKIN_NO_ARMATURE", "-", f"a character needs exactly one armature in include_objects, found {len(arms)}"))
        return out
    arm = arms[0]
    bones = {b.name for b in arm.data.bones}
    if len(bones) > cfg.get("max_bones", 64):
        out.append(_f("error", "RIG_BONE_BUDGET", arm.name, f"{len(bones)} bones exceeds budget {cfg.get('max_bones', 64)}"))
    if arm.animation_data and arm.animation_data.action:
        out.append(_f("warn", "ANIM_ACTIVE", arm.name, "an action is assigned: the rest pose was validated with it applied; clear the action"))
    mx_ok = cfg.get("max_influences", 4)
    for o in meshes:
        mod = next((m for m in o.modifiers if m.type == "ARMATURE" and m.object == arm), None)
        if mod is None:
            out.append(_f("error", "SKIN_NOT_BOUND", o.name, "mesh has no Armature modifier for the character's armature"))
            continue
        n, bad, mx, stray = weight_stats(o, bones)
        if bad:
            out.append(_f("error", "SKIN_UNWEIGHTED", o.name, f"{bad}/{n} vertices are unweighted or not normalised (sum != 1)"))
        if mx > mx_ok:
            out.append(_f("error", "SKIN_MAX_INFLUENCE", o.name, f"up to {mx} influences per vertex; the engine skins {mx_ok}"))
        if stray:
            out.append(_f("warn", "SKIN_BAD_GROUP", o.name, f"vertex groups that are not bones: {stray[:4]}"))
    for name, want in cfg.get("clips", {}).items():
        act = bpy.data.actions.get(name)
        if act is None:
            out.append(_f("error", "ANIM_MISSING", name, "clip not found among the blend's actions"))
            continue
        a, b = act.frame_range
        if b - a < 2:
            out.append(_f("error", "ANIM_SHORT", name, f"clip is {b - a} frames long"))
            continue
        if want.get("loop"):
            worst = 0.0
            for fc in act.fcurves if hasattr(act, "fcurves") else _fcurves(act):
                worst = max(worst, abs(fc.evaluate(a) - fc.evaluate(b)))
            if worst > 1e-3:
                out.append(_f("error", "ANIM_LOOP_MISMATCH", name, f"loop clip's first and last frame differ by {worst:.4f}"))
    return out


def _fcurves(act):
    """Blender 5 slotted actions: gather fcurves from every channelbag."""
    res = []
    for layer in act.layers:
        for strip in layer.strips:
            for slot in act.slots:
                try:
                    res += list(strip.channelbag(slot).fcurves)
                except Exception:
                    pass
    return res
