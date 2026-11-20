"""Assemble the rest model: parts -> skinned objects (body + weapon meshes + banner) bound to the armature."""
import bpy
from mathutils import Vector

from . import armour, banner, body, katana as K, materials, rig, skin, tachi as T

V = Vector

GROUPS = (("tachi_hand", "Tachi_Drawn"), ("tachi_hip", "Tachi_Sheathed"), ("tachi_saya", "Tachi_Saya"), ("tachi_cords", "Tachi_Saya"), ("banner_", "Sashimono"), ("katana_hand", "Katana_Drawn"), ("katana_hip", "Katana_Sheathed"), ("katana_saya", "Katana_Saya"), ("katana_sageo", "Katana_Saya"))


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    bpy.context.view_layer.update()


def _mat(mat_fn, key):
    """a material table that has no 'face' (the placeholder set) paints the face as skin"""
    try:
        return mat_fn(key)
    except KeyError:
        return mat_fn("skin" if key == "face" else key)


def build_model(stage="all", mat_fn=None, coll_name="samurai_LOD0", split_tails=False):
    """Returns dict(arm, body, Armour_Oyoroi, Helmet, Katana_*, Sashimono, parts). The body is whole without armour and helmet (they are their own skinned
    nodes, so an engine can dress him). stage 'body' skips them (fast look-dev)."""
    mat_fn = mat_fn or materials.placeholder
    clear_scene()
    sc = bpy.context.scene
    coll = bpy.data.collections.new(coll_name)
    sc.collection.children.link(coll)
    table = rig.bone_table()
    arm = rig.build_armature(coll, table)

    # the head is the archer's (a face, ears, hair tied back over the crown): the helmet and the mask used to hide a plain egg, and he can stand bare-headed now
    from archer import body as AB
    HEAD = ("body_head", "body_eyes", "body_iris", "body_lids", "body_brow", "body_lash")
    from archer import skin as AK
    head = AB.head_parts() + AB.hair_parts()
    soft_head = {id(p) for p in head}                      # skinned by the archer's rules (its neck turns inside the collar)
    parts = [p for p in body.all_soft(table) if p.name not in HEAD] + head
    gear = {"Armour_Oyoroi": armour.body_armour(), "Armour_Kawa": armour.kawa_armour(), "Helmet": armour.helmet(), "Helmet_Kawa": armour.kawa_helmet()} if stage in ("armour", "all") else {}
    node_of = {id(p): name for name, ps in gear.items() for p in ps}
    for ps in gear.values():
        parts += ps
    go, gt = rig.grip_origin()
    M_hand = K.placement(go, gt, V((0, 0, -1)))
    weapons = K.hip_katana() + K.saya_parts() + K.hand_katana(M_hand) + T.hip_tachi() + T.saya_parts() + T.hand_tachi(M_hand) + banner.banner_parts()

    objs, piece = [], {}
    for p in parts + weapons:
        ob = p.to_object(coll)
        if id(p) in node_of:
            piece[ob.name] = node_of[id(p)]
        ob.data.materials.append(_mat(mat_fn, p.mat))
        (AK if id(p) in soft_head else skin).apply_weights(ob, arm)
        objs.append(ob)

    wmap = {}
    body_objs = []
    for ob in objs:
        if split_tails and ob.name.startswith("cloth_sash_tail"):      # measurement builds keep the tails apart from the body
            wmap.setdefault("Sash_Tails", []).append(ob)
            continue
        if ob.name in piece:
            wmap.setdefault(piece[ob.name], []).append(ob)
            continue
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
