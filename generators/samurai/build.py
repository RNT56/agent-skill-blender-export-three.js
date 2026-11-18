"""Assemble the rest model: parts -> skinned objects (body + three weapon meshes) bound to the armature."""
import bpy
from mathutils import Vector

from . import armour, body, katana as K, materials, rig, skin

V = Vector

GROUPS = (("katana_hand", "Katana_Drawn"), ("katana_hip", "Katana_Sheathed"), ("katana_saya", "Katana_Saya"), ("katana_sageo", "Katana_Saya"))


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    bpy.context.view_layer.update()


def build_model(stage="all", mat_fn=None, coll_name="samurai_LOD0"):
    """Returns dict(arm, body, drawn, sheathed, saya, parts). stage 'body' skips armour (fast look-dev)."""
    mat_fn = mat_fn or materials.placeholder
    clear_scene()
    sc = bpy.context.scene
    coll = bpy.data.collections.new(coll_name)
    sc.collection.children.link(coll)
    table = rig.bone_table()
    arm = rig.build_armature(coll, table)

    parts = body.all_soft(table)
    if stage in ("armour", "all"):
        parts += armour.all_armour(table)
    go, gt = rig.grip_origin()
    M_hand = K.placement(go, gt, V((0, 0, -1)))
    weapons = K.hip_katana() + K.saya_parts() + K.hand_katana(M_hand)

    objs = []
    for p in parts + weapons:
        ob = p.to_object(coll)
        ob.data.materials.append(mat_fn(p.mat))
        skin.apply_weights(ob, arm)
        objs.append(ob)

    wmap = {}
    body_objs = []
    for ob in objs:
        for prefix, target in GROUPS:
            if ob.name.startswith(prefix):
                wmap.setdefault(target, []).append(ob)
                break
        else:
            body_objs.append(ob)
    out = {"arm": arm, "parts": len(objs)}
    out["body"] = skin.bind(skin.join(body_objs, "Samurai_LOD0"), arm)
    for target, lst in wmap.items():
        out[target] = skin.bind(skin.join(lst, target), arm)
    return out


# ------------------------------------------------------------------------------------------------------------- demo poses
def demo_pose(arm, name):
    from .pose import Pose, Rig
    rg = Rig(arm)
    p = Pose(rg)
    if name == "bow":
        p.rot("spine", (8, 0, 0)); p.rot("spine1", (14, 0, 0)); p.rot("chest", (10, 0, 0)); p.rot("neck", (8, 0, 0))
    elif name == "twist":
        p.rot("hips", (0, 0, 28)); p.rot("spine1", (0, 0, -40)); p.rot("chest", (0, 0, -12)); p.rot("head", (0, 0, 20))
    elif name == "arms_up":
        for sd, sx in (("L", 1), ("R", -1)):
            p.limb(f"upper_arm.{sd}", f"forearm.{sd}", f"hand.{sd}", V((0.20 * sx, -0.32, 1.78)), V((0.4 * sx, 0.6, 0.0)), -1)
    elif name == "reach":
        for sd, sx in (("L", 1), ("R", -1)):
            p.limb(f"upper_arm.{sd}", f"forearm.{sd}", f"hand.{sd}", V((0.12 * sx, -0.52, 1.36)), V((0.5 * sx, 0.3, -0.3)), -1)
    elif name == "lunge":
        p.move("hips", V(0, -0.16, -0.30))
        p.rot("spine", (-8, 0, 0)); p.rot("spine1", (-6, 0, 0))
        p.limb("thigh.L", "shin.L", "foot.L", V(0.15, -0.62, 0.09), V(0, -1, 0.1), 1)
        p.limb("thigh.R", "shin.R", "foot.R", V(-0.14, 0.30, 0.09), V(0, -1, 0.2), 1)
        p.aim("foot.L", V(0, -0.93, -0.35), V(0, -0.35, 0.93)); p.aim("foot.R", V(0, -0.93, -0.35), V(0, -0.35, 0.93))
    elif name == "squat":
        p.move("hips", V(0, 0.06, -0.42))
        p.rot("spine", (18, 0, 0)); p.rot("spine1", (10, 0, 0))
        p.limb("thigh.L", "shin.L", "foot.L", V(0.15, -0.05, 0.09), V(0, -1, 0), 1)
        p.limb("thigh.R", "shin.R", "foot.R", V(-0.15, -0.05, 0.09), V(0, -1, 0), 1)
        p.aim("foot.L", V(0, -0.93, -0.35), V(0, -0.35, 0.93)); p.aim("foot.R", V(0, -0.93, -0.35), V(0, -0.35, 0.93))
    return p
