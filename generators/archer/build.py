"""Assemble the archer's rest model: parts -> skinned objects (body, bow, nocked arrow, banner) bound to the armature.

`live=True` is for a LIVE Blender session (the Blender MCP): everything is built in its own scene ('Archer') and only that scene is ever cleared, so whatever the
user has open stays untouched. Headless builds (factory startup) clear everything, like the samurai's."""
import bpy

from . import body, bow, gear, rig, shaders, skin

GROUPS = (("banner_", "Sashimono"), ("bow_", "Yumi"), ("lowbow_", "Yumi_Low"), ("arrow_", "Arrow_Nocked"))
SCENE = "Archer"


def _own_scene():
    sc = bpy.data.scenes.get(SCENE) or bpy.data.scenes.new(SCENE)
    if bpy.context.window is not None:
        bpy.context.window.scene = sc
    for o in list(sc.collection.all_objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(sc.collection.children_recursive):
        bpy.data.collections.remove(c)
    own = ("Archer_", "Yumi", "Arrow_", "Sashimono", "lowbow_", "body_", "cloth_", "armor_", "cord_", "gear_", "glove_", "banner_", "bow_", "arrow_", "straw_", "_tmp")
    for blocks, pre in ((bpy.data.meshes, own), (bpy.data.armatures, ("ArcherRig",)), (bpy.data.materials, ("arc_",)), (bpy.data.actions, ("arc:",))):
        for d in list(blocks):                      # only this generator's own orphans: nothing else in the session is touched
            if d.users == 0 and d.name.startswith(pre):
                blocks.remove(d)
    bpy.context.view_layer.update()
    return sc


def build_model(mat_fn=None, coll_name="archer_LOD0", live=False):
    """Returns dict(arm, body, Yumi, Yumi_Low, Arrow_Nocked, Sashimono, parts)."""
    mat_fn = mat_fn or shaders.procedural
    if live:
        sc = _own_scene()
    else:
        from samurai import build as SBuild
        SBuild.clear_scene()
        sc = bpy.context.scene
    coll = bpy.data.collections.new(coll_name)
    sc.collection.children.link(coll)
    table = rig.bone_table()
    arm = rig.build_armature(coll, table)
    parts = body.all_soft(table) + gear.all_gear() + gear.banner_parts() + bow.bow_parts() + bow.bow_parts(low=True) + bow.arrow_parts()
    objs = []
    for p in parts:
        ob = p.to_object(coll)
        ob.data.materials.append(mat_fn(p.mat))
        skin.apply_weights(ob, arm)
        objs.append(ob)
    wmap, body_objs = {}, []
    for ob in objs:
        for prefix, target in GROUPS:
            if ob.name.startswith(prefix):
                wmap.setdefault(target, []).append(ob)
                break
        else:
            body_objs.append(ob)
    out = {"arm": arm, "parts": len(objs)}
    out["body"] = skin.bind(skin.join(body_objs, "Archer_LOD0"), arm)
    for target, lst in wmap.items():
        out[target] = skin.bind(skin.join(lst, target), arm)
    return out
