"""Finish the ashigaru: the meshes an engine draws further away, and one Action per clip.

  LOD0   the body and every piece of kit as its own node (build.py)
  LOD1   Ashigaru_LOD1 (the body, decimated) + Armour_<x>_Low (the armour, decimated; the lent armour's has the banner in it) + the hat and spear nodes as they are
  far    Ashigaru_Far_<armour>_<head>: body, armour and hat in ONE mesh per combination (2 armours x jingasa / tetsu / bare): one draw per man at the game's
         default zoom, where a crowd is. The spears stay their own nodes at every distance (under 400 triangles, and which one shows is the engine's choice)."""
import json

import bpy

from archer import finalize as AF

from . import anim, clips

lod_copy = AF.lod_copy


ARMOURS = (("HaraAte", "Armour_HaraAte"), ("Okegawa", "Armour_Okegawa"))
HEADS = (("Jingasa", "Helmet_Jingasa"), ("Tetsu", "Helmet_Tetsu"), ("Bare", None))


def far_name(armour, head):
    return f"Ashigaru_Far_{armour}_{head}"


def _without_groups(src, groups, coll, thr=0.5):
    """A copy of `src` without the vertices that hang on the bones `groups` (the head band's free tails under a neck curtain)."""
    import bmesh
    ob = src.copy()
    ob.data = src.data.copy()
    coll.objects.link(ob)
    idx = {g.index for g in ob.vertex_groups if g.name in groups}
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    dl = bm.verts.layers.deform.verify()
    dead = [v for v in bm.verts if sum(w for g, w in v[dl].items() if g in idx) > thr]
    bmesh.ops.delete(bm, geom=dead, context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


TAILS = ("tail_a1", "tail_a2", "tail_b1", "tail_b2")


def make_lods(m, arm, coll, body_tris=5400, low_tris=(1300, 2600), far_tris=2400):
    """m: build.build_model(). Returns the names of the objects made."""
    untailed = _without_groups(m["body"], TAILS, coll)                  # under the iron hat's neck curtain the tails are tucked away (an engine hides them at LOD0 / 1)
    made = [lod_copy(m["body"], "Ashigaru_LOD1", body_tris, arm, coll).name]
    for (key, node), tris in zip(ARMOURS, low_tris):
        pre = (m["Sashimono"],) if key == "Okegawa" else ()
        made.append(lod_copy(m[node], f"{node}_Low", tris, arm, coll, pre=pre).name)
    for key, node in ARMOURS:
        for hkey, hnode in HEADS:
            pre = [m[node]] + ([m[hnode]] if hnode else []) + ([m["Sashimono"]] if key == "Okegawa" else [])
            made.append(lod_copy(untailed if hkey == "Tetsu" else m["body"], far_name(key, hkey), far_tris, arm, coll, pre=tuple(pre)).name)
    me = untailed.data
    bpy.data.objects.remove(untailed, do_unlink=True)
    bpy.data.meshes.remove(me)
    return made


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
        log(f"  clip {name}: {int(act.frame_range[1] - act.frame_range[0])} frames, spear pulled in {act['gp_spear_shift_mm']} mm, left hand slipped {act['gp_hand_slip_mm']} mm, cloth {act.get('gp_cloth', '-')}")
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    return out
