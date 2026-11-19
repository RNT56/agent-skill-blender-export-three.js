"""The archer's bow, nocked arrow and quiver on a reconstructed man (stage `assemble`, units with weapon="bow").

The owner asked for the v1 archer's own bow and arrow on the new body (2026-11-19: "use the current archer's bow and arrow with the new model"), so nothing
here is image-to-3D: `archer.bow` builds the same parts with the same procedural materials, they are baked into one cell of this unit's atlas, and then the
whole bow moves RIGIDLY from the v1 hand's grip to this man's (the grip centre his auto-rig's hand measured, the same axes: fingers, palm, thumb). The bow's
bones (weapon_l, two per limb, the nock point, the arrow) move with it, so the limb weights, the string and `archer.anim.BowModel` hold unchanged.

The quiver IS a piece (fixtures/archer_src/tripo/ebira.glb through soldier.props): it hangs behind the right hip, where the string hand finds it.
"""
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector

from villager import rig as VR

V = Vector
BOW_BONES = (("weapon_l", "hand.L"), ("bow_u1", "weapon_l"), ("bow_u2", "bow_u1"), ("bow_l1", "weapon_l"), ("bow_l2", "bow_l1"), ("bow_nock", "weapon_l"), ("arrow", "root"))
QUIVER = dict(phi=152.0, lean=(-0.10, 0.15, 1.0), mid=0.25, inner=0.100, dz=-0.07, gap=0.012, nocks=0.650)


def hand_frame(hands, side):
    """(fingers a, out of the palm n, toward the thumb th): orthonormal. The thumb's side follows from the other two (left: -(a x n), right: +(a x n))."""
    H = hands[side]
    a = V(H["a"]).normalized()
    n = V(H["n"])
    n = (n - a * n.dot(a)).normalized()
    th = a.cross(n).normalized() * (-1.0 if side == "L" else 1.0)
    return a, n, th


def _basis(u, w, s):
    M = Matrix.Identity(3)
    M.col[0], M.col[1], M.col[2] = u, w, s
    return M


def build(arm, hands, tex_dir, px, log=print):
    """-> (Yumi, Arrow_Nocked, facts). Bakes <tex_dir>/bow_{albedo.jpg,normal.png,orm.png} (px square) and leaves both meshes with ONE uv layer in 0..1."""
    from archer import bake as ABK, bow as AB, rig as AR, shaders as ASH, skin as ASK
    coll = bpy.context.scene.collection
    ref = AR.build_armature(coll)
    ref.name = ref.data.name = "_RefBowRig"
    objs = []
    for p in AB.bow_parts() + AB.arrow_parts():
        ob = p.to_object(coll)
        ob.data.materials.append(ASH.procedural(p.mat))
        ASK.apply_weights(ob, ref)
        objs.append(ob)
    ABK.bake_atlas(objs, tex_dir, "bow", px=px, quality=1.0, log=log)
    for ob in objs:
        for lay in [l for l in ob.data.uv_layers if l.name != "atlas"]:
            ob.data.uv_layers.remove(lay)
        ob.data.uv_layers[0].name = "UVMap"
        ob.data.materials.clear()
    for im in [i for i in bpy.data.images if i.name.startswith("bow_")]:
        bpy.data.images.remove(im)
    bows, arrows = [o for o in objs if o.name.startswith("bow_")], [o for o in objs if o.name.startswith("arrow_")]
    yumi = ASK.join(bows, "Yumi")
    arrow = ASK.join(arrows, "Arrow_Nocked")
    # ---- from the v1 hand's grip to this man's
    b = AR.bow_rest()
    R1 = _basis(b["U"], b["W"], b["S"])
    a, n, th = hand_frame(hands, "L")
    ang = math.radians(18.0)                                   # (archer.rig.bow_rest: the string plane passes the palm side of the forearm)
    U = (a * math.cos(ang) - n * math.sin(ang)).normalized()
    S = (n * math.cos(ang) + a * math.sin(ang)).normalized()
    G = V(hands["L"]["grip"])
    R2 = _basis(U, th, S)
    Rm = R2 @ R1.inverted()
    M = Matrix.Translation(G) @ Rm.to_4x4() @ Matrix.Translation(-b["G"])
    for ob in (yumi, arrow):
        ob.data.transform(M)
        ob.data.update()
    for name, parent in BOW_BONES:
        rb = ref.data.bones[name]
        h, t = M @ rb.head_local, M @ rb.tail_local
        VR.add_bone(arm, name, parent, h, t - h, Rm @ rb.z_axis, (t - h).length)
    d = ref.data
    bpy.data.objects.remove(ref, do_unlink=True)
    bpy.data.armatures.remove(d)
    for ob in (yumi, arrow):
        for m in list(ob.modifiers):
            ob.modifiers.remove(m)
        ob.parent = arm
        md = ob.modifiers.new("Armature", "ARMATURE")
        md.object = arm
        md.use_vertex_groups = True
    ar, nr, thr = hand_frame(hands, "R")
    wr = arm.data.bones["hand.R"].head_local
    facts = {
        "G": list(G), "U": list(U), "W": list(th), "S": list(S), "nock0": list(M @ AR.nock0()), "arrow_rest": list(M @ AR.arrow_rest()),
        "string_dir": list(ar), "string_palm": list(nr), "pinch0": list(wr + ar * 0.088 + nr * 0.026 + thr * 0.016),
        "tris": {"Yumi": sum(len(p.vertices) - 2 for p in yumi.data.polygons), "Arrow_Nocked": sum(len(p.vertices) - 2 for p in arrow.data.polygons)},
    }
    log(f"  bow: grip {[round(v, 3) for v in G]}, toward the target {[round(v, 2) for v in U]}, up the bow {[round(v, 2) for v in th]}")
    return yumi, arrow, facts


def place_quiver(ob, bodies_co, sash_z, log=print):
    """The quiver behind the right hip: its inner face on the widest body there, leaning back and out. -> facts (the nocks, the axis, in the rest pose = hips space)."""
    q = QUIVER
    phi = math.radians(q["phi"])
    out = V((-math.sin(phi), -math.cos(phi), 0.0))                 # right and back
    zc = sash_z + q["dz"]
    Rs = 0.0
    d2 = np.array((out.x, out.y))
    for co in bodies_co:
        p = co[:, :2]
        m = (np.abs(co[:, 2] - zc) < 0.06) & ((p @ d2) > 0.85 * np.linalg.norm(p, axis=1))
        if m.any():
            Rs = max(Rs, float((p[m] @ d2).max()))
    axis = V(q["lean"]).normalized()
    ez = (out - axis * out.dot(axis)).normalized()                 # the piece's thin axis: away from the body
    ex = axis.cross(ez).normalized()
    R = _basis(ex, axis, ez)
    contact = V((out.x * (Rs + q["gap"]), out.y * (Rs + q["gap"]), zc))
    origin = contact - R @ V((0.0, q["mid"], -q["inner"]))
    ob.data.transform(Matrix.Translation(origin) @ R.to_4x4())
    ob.data.update()
    slot = origin + R @ V((0.0, q["nocks"], 0.0))
    log(f"  Quiver: body radius {Rs:.3f} m at z {zc:.3f}, foot {[round(v, 3) for v in origin]}, nocks {[round(v, 3) for v in slot]}")
    return {"foot": list(origin), "axis": list(axis), "slot": list(slot), "out": list(ez)}
