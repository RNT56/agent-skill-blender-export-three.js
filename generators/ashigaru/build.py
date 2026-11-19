"""Assemble the ashigaru's rest model: parts -> skinned objects bound to ONE armature: the body (whole without any kit) and one object per piece of kit
(gear.nodes: two armours, two hats, two spears, the side arm, the banner).

`live=True` is for a LIVE Blender session (the Blender MCP): everything is built in its own scene ('Ashigaru') and only that scene is ever cleared, so whatever the
user has open stays untouched. Headless builds (factory startup) clear everything."""
import bpy

from . import body, gear, rig, shaders, skin

SCENE = "Ashigaru"


def _own_scene():
    sc = bpy.data.scenes.get(SCENE) or bpy.data.scenes.new(SCENE)
    if bpy.context.window is not None:
        bpy.context.window.scene = sc
    for o in list(sc.collection.all_objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(sc.collection.children_recursive):
        bpy.data.collections.remove(c)
    own = ("Ashigaru_", "Armour_", "Helmet_", "Side_", "Yari", "Sashimono", "body_", "cloth_", "armor_", "cord_", "gear_", "yari_", "nagae_", "banner_", "straw_", "_tmp")
    for blocks, pre in ((bpy.data.meshes, own), (bpy.data.armatures, ("AshigaruRig",)), (bpy.data.materials, ("ash_", "ash1_", "ash2_"))):
        for d in list(blocks):                      # only this generator's own orphans: nothing else in the session is touched
            if d.users == 0 and d.name.startswith(pre):
                blocks.remove(d)
    bpy.context.view_layer.update()
    return sc


def build_model(mat_fn=None, coll_name="ashigaru_LOD0", live=False):
    """Returns dict(arm, body, <node name>: object for every gear.nodes() entry, nodes: their names in order, parts)."""
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
    arm = rig.build_armature(coll)
    count = [0]

    def make(name, parts):
        objs = []
        for p in parts:
            ob = p.to_object(coll)
            ob.data.materials.append(mat_fn(p.mat))
            skin.apply_weights(ob, arm)
            objs.append(ob)
        count[0] += len(objs)
        return skin.bind(skin.join(objs, name), arm)

    out = {"arm": arm, "nodes": []}
    out["body"] = make("Ashigaru_LOD0", body.all_soft(table) + gear.base_gear())
    for name, fn in gear.nodes():
        out[name] = make(name, fn())
        out["nodes"].append(name)
    out["parts"] = count[0]
    return out
