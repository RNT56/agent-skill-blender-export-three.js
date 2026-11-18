"""Character recipe: a skinned, animated hero (armature + LOD meshes + weapon meshes) -> ONE GLB with every clip.

Spec (recipe "character"), under spec["recipe_cfg"]:
  collection : the Blender collection holding the armature, the <x>_LOD<n> body meshes and any weapon meshes
The recipe creates nothing: it restores the rest pose (clips stay as Actions), writes clips.json (frames, loop flag, which weapon
the clip assumes, stride speed in m/s for locomotion) and hands the objects to the gate (validate -> export -> inspect).
Clips are authored IN PLACE: the game moves the unit and scales playback to `speed` so feet do not slide.
"""
import json
import os

import bpy

META = {"name": "character", "version": "1", "needs": ["collection"]}


def build(spec, out_dir):
    coll = bpy.data.collections.get(spec["recipe_cfg"]["collection"])
    if coll is None:
        raise RuntimeError(f"collection {spec['recipe_cfg']['collection']!r} not found in the source blend")
    arm = next((o for o in coll.all_objects if o.type == "ARMATURE"), None)
    if arm is not None:
        if arm.animation_data:
            arm.animation_data.action = None
        for pb in arm.pose.bones:
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
        bpy.context.view_layer.update()
    names = [arm.name] if arm else []
    names += [o.name for o in coll.all_objects if o.type == "MESH"]
    clips = {}
    for name in spec.get("character", {}).get("clips", {}):
        act = bpy.data.actions.get(name)
        if act is None:
            continue
        a, b = act.frame_range
        fps = act.get("gp_fps", 30)
        clips[name] = {"frames": int(b - a), "fps": fps, "duration": round((b - a) / fps, 4), "loop": bool(act.get("gp_loop", 0)),
                       "weapon": act.get("gp_weapon", "sheathed"), "weapon_end": act.get("gp_weapon_end", act.get("gp_weapon", "sheathed")),
                       "speed_mps": round(float(act.get("gp_speed", 0.0)), 3), "events": json.loads(act.get("gp_events", "{}"))}
    mask = spec.get("character", {}).get("team_mask")
    if mask:                                    # team-colour mask baked with the atlas (same UVs): shipped next to the GLB
        import shutil
        src = mask if os.path.isabs(mask) else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), mask)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out_dir, f"{spec['name']}.team.png"))
    emb = spec.get("character", {}).get("emblems")
    if emb:                                      # faction crests for the banner: a signed-distance sheet + its json (cell layout, banner region): required, a missing sheet must fail the build
        import shutil
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for key, suffix in (("png", "emblems.png"), ("json", "emblems.json")):
            src = emb[key] if os.path.isabs(emb[key]) else os.path.join(root, emb[key])
            if not os.path.exists(src):
                raise FileNotFoundError(f"character.emblems.{key} declared but missing: {src} (run the generator with --bake)")
            shutil.copyfile(src, os.path.join(out_dir, f"{spec['name']}.{suffix}"))
    clo = spec.get("character", {}).get("cloth")
    if clo:                                      # the runtime cloth descriptor (chains, rest directions): the clips are baked dry and the engine adds the wind; required when declared
        import shutil
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src = clo["json"] if os.path.isabs(clo["json"]) else os.path.join(root, clo["json"])
        if not os.path.exists(src):
            raise FileNotFoundError(f"character.cloth.json declared but missing: {src} (run the generator with --bake)")
        shutil.copyfile(src, os.path.join(out_dir, f"{spec['name']}.cloth.json"))
    with open(os.path.join(out_dir, "clips.json"), "w") as fh:
        json.dump(clips, fh, indent=2)
    return [{
        "name": spec["name"], "type": spec["type"], "root_object": spec.get("root_object"), "include_objects": names,
        "budgets": spec.get("budgets", {}), "lod_budgets": spec.get("lod_budgets", {}), "rules": spec.get("rules", {}),
        "export": spec.get("export", {}), "glb_expect": spec.get("glb_expect"), "character": spec.get("character", {}), "lod": "pack",
    }]
