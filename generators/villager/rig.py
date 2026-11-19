"""Stage 3: the skeleton and the skin.

The joints and the skin weights come from an auto-rig of the LOD0 mesh (Meshy, 24 bones, through Higgsfield). That rig arrives as a 0.01-scaled
armature with heuristic bone tails and no hands, so it is not used as it is: a clean armature is built at the same joint positions (metres,
bones point at their child, blend-up's names so the game's foot planting finds `hips / thigh / shin / foot`), the weights are carried over by
position, and what a labourer needs is added:

    fingers.L/R, fingers2.L/R, thumb.L/R   the hand closes around a handle (the four fingers move together: it is a fist, not a pianist)
    tool_r, tool_l                          grip frames: +Y = along the handle toward the working end, +Z = the way the tool strikes
    line                                    the fishing line (rest: wound back along the rod; the fish clip lets it hang)
    load_shoulder, load_front               where a carried load rides (children of the chest, axes = the armature's)

`hands.json` records the measured hand frames (wrist, direction, palm normal, spread axis, grip point) for the clip stage.
Conventions: metres, the figure faces -Y, LEFT = +X (blend-up characters).
"""
import json
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector, kdtree

from . import props as P, qa

V = Vector
MAP = {"Hips": "hips", "Spine02": "spine", "Spine01": "spine1", "Spine": "chest", "neck": "neck", "Head": "head", "head_end": "head", "headfront": "head"}
for _s, _S in (("L", "Left"), ("R", "Right")):
    MAP.update({f"{_S}Shoulder": f"shoulder.{_s}", f"{_S}Arm": f"upper_arm.{_s}", f"{_S}ForeArm": f"forearm.{_s}", f"{_S}Hand": f"hand.{_s}",
                f"{_S}UpLeg": f"thigh.{_s}", f"{_S}Leg": f"shin.{_s}", f"{_S}Foot": f"foot.{_s}", f"{_S}ToeBase": f"toe.{_s}"})
CHAINS = [("root", None), ("hips", "root"), ("spine", "hips"), ("spine1", "spine"), ("chest", "spine1"), ("neck", "chest"), ("head", "neck")]
for _s in "LR":
    CHAINS += [(f"shoulder.{_s}", "chest"), (f"upper_arm.{_s}", f"shoulder.{_s}"), (f"forearm.{_s}", f"upper_arm.{_s}"), (f"hand.{_s}", f"forearm.{_s}"),
               (f"thigh.{_s}", "hips"), (f"shin.{_s}", f"thigh.{_s}"), (f"foot.{_s}", f"shin.{_s}"), (f"toe.{_s}", f"foot.{_s}")]
NEXT = {"hips": "spine", "spine": "spine1", "spine1": "chest", "chest": "neck", "neck": "head"}
for _s in "LR":
    NEXT.update({f"shoulder.{_s}": f"upper_arm.{_s}", f"upper_arm.{_s}": f"forearm.{_s}", f"forearm.{_s}": f"hand.{_s}",
                 f"thigh.{_s}": f"shin.{_s}", f"shin.{_s}": f"foot.{_s}", f"foot.{_s}": f"toe.{_s}"})
HANDLE_R = 0.014         # m: the handle radius the grip frame is measured for


def _deselect():
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)


def import_rig(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    mesh = max((o for o in new if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)), key=lambda o: len(o.data.vertices))
    return arm, mesh, new


def rest_joints(arm):
    mw = arm.matrix_world
    return {b.name: (mw @ b.head_local).copy() for b in arm.data.bones}


def build_armature(J, coll, name="VillagerRig"):
    """J: joint positions by OUR bone names (head of each bone). Returns the armature object (no hand / prop bones yet)."""
    data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, data)
    coll.objects.link(arm)
    _deselect()
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = {}
    for n, parent in CHAINS:
        b = data.edit_bones.new(n)
        if n == "root":
            b.head, b.tail = (0, 0, 0), (0, 0, 0.14)
        else:
            b.head = J[n]
            if n in NEXT:
                b.tail = J[NEXT[n]]
            elif n == "head":
                b.tail = V((J[n].x, J[n].y, J["head_end_z"]))
            elif n.startswith("hand"):
                d = (J[n] - J["forearm" + n[4:]]).normalized()
                b.tail = J[n] + d * 0.085
            elif n.startswith("toe"):
                b.tail = J[n] + V((0, -0.075, 0))
        if (V(b.tail) - V(b.head)).length < 1e-4:
            b.tail = V(b.head) + V((0, 0, 0.05))
        b.parent = eb.get(parent)
        b.use_connect = False
        b.use_deform = True
        eb[n] = b
    for n, b in eb.items():                                  # bone Z toward the front (-Y) where that is not degenerate: a readable, consistent roll
        y = (V(b.tail) - V(b.head)).normalized()
        b.align_roll(V((0, -1, 0)) if abs(y.y) < 0.9 else V((0, 0, 1)))
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return arm


def add_bone(arm, name, parent, head, y_axis, z_hint, length):
    _deselect()
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    b = arm.data.edit_bones.new(name)
    b.head = V(head)
    b.tail = V(head) + V(y_axis).normalized() * length
    b.parent = arm.data.edit_bones[parent]
    b.use_connect = False
    b.use_deform = True
    b.align_roll(V(z_hint))
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.pose.bones[name].rotation_mode = "QUATERNION"
    return arm.data.bones[name]


# ---------------------------------------------------------------------------------------------------- weights
def _np_verts(me, M=None):
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    if M is not None:
        A = np.array(M)
        co = co @ A[:3, :3].T + A[:3, 3]
    return co


def read_weights(ob, names):
    """dense (verts x len(names)) weights of `ob`, its groups mapped through MAP onto `names`."""
    idx = {n: i for i, n in enumerate(names)}
    gmap = {g.index: idx[MAP[g.name]] for g in ob.vertex_groups if g.name in MAP}
    W = np.zeros((len(ob.data.vertices), len(names)))
    for v in ob.data.vertices:
        for g in v.groups:
            j = gmap.get(g.group)
            if j is not None:
                W[v.index, j] += g.weight
    return W


def transfer(src_mesh, low, names):
    src = _np_verts(src_mesh.data, src_mesh.matrix_world)
    dst = _np_verts(low.data, low.matrix_world)
    Ws = read_weights(src_mesh, names)
    kd = kdtree.KDTree(len(src))
    for i, p in enumerate(src):
        kd.insert(p, i)
    kd.balance()
    W = np.zeros((len(dst), len(names)))
    worst = 0.0
    for i, p in enumerate(dst):
        _, j, d = kd.find(p)
        W[i] = Ws[j]
        worst = max(worst, d)
    return W, worst


def components(sub, edges):
    """connected components among the vertex ids in `sub` (a boolean mask) -> list of index arrays, largest first."""
    keep = sub[edges[:, 0]] & sub[edges[:, 1]]
    ed = edges[keep]
    lab = np.arange(len(sub))
    while True:
        m = np.minimum(lab[ed[:, 0]], lab[ed[:, 1]])
        new = lab.copy()
        np.minimum.at(new, ed[:, 0], m)
        np.minimum.at(new, ed[:, 1], m)
        new = new[new]
        if (new == lab).all():
            break
        lab = new
    ids = np.nonzero(sub)[0]
    out = {}
    for i in ids:
        out.setdefault(int(lab[i]), []).append(int(i))
    return sorted((np.array(v) for v in out.values()), key=lambda a: -len(a))


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def measure_hand(co, edges, w_hand, wrist, elbow, sx, log=print):
    """Find the thumb, the knuckle line and the hand's frame on the mesh itself. sx = +1 left, -1 right."""
    hand = w_hand > 0.5
    W = np.array(wrist)
    fore = np.array(wrist) - np.array(elbow)
    fore /= np.linalg.norm(fore)
    rel = co - W
    d = np.linalg.norm(rel, axis=1)
    far = hand & (d > np.quantile(d[hand], 0.97))
    a = rel[far].mean(0)
    a /= np.linalg.norm(a)
    s = rel @ a
    L = float(s[hand].max())
    # the thumb: the first slice (walking from the wrist to the tips) that leaves a separate piece which stops well short of the fingertips
    thumb, s_t = None, None
    for cut in np.linspace(0.12 * L, 0.62 * L, 40):
        comps = [c for c in components(hand & (s > cut), edges) if len(c) >= 5]
        if len(comps) >= 2:
            short = [c for c in comps if s[c].max() < 0.86 * L]
            long = [c for c in comps if s[c].max() >= 0.86 * L]
            if short and long:
                thumb = max(short, key=len)
                s_t = float(cut)
                break
    if thumb is None:
        raise RuntimeError("no thumb found: the hand of the low-poly mesh is fused")
    is_thumb = np.zeros(len(co), dtype=bool)
    is_thumb[thumb] = True
    rest = hand & ~is_thumb
    # the finger crotches: the first slice where the rest falls into three or more pieces that reach the tips
    s_k = None
    for cut in np.linspace(s_t, 0.85 * L, 60):
        comps = [c for c in components(rest & (s > cut), edges) if len(c) >= 4 and s[c].max() > 0.8 * L]
        if len(comps) >= 3:
            s_k = float(cut)
            fingers = comps
            break
    if s_k is None:
        s_k, fingers = 0.56 * L, [np.nonzero(rest & (s > 0.56 * L))[0]]
        log("  WARN: fingers not separated; knuckle line guessed")
    s_mcp = s_k - 0.020                                      # the joint lies about 2 cm behind the webbing
    s_mid = s_mcp + 0.44 * (L - s_mcp)
    # spread axis: from the little finger to the index (the index is the finger next to the thumb)
    cents = np.array([co[c].mean(0) for c in fingers])
    tc = co[thumb].mean(0)
    if len(cents) >= 2:
        order = np.argsort(np.linalg.norm(cents - tc, axis=1))
        c_ax = cents[order[0]] - cents[order[-1]]
    else:
        c_ax = tc - co[rest].mean(0)
    c_ax = c_ax - a * (c_ax @ a)
    c_ax /= np.linalg.norm(c_ax)
    n = np.cross(a, c_ax)
    if n[0] * (-sx) < 0:                                      # the palm faces the body in the A-pose
        n = -n
    n /= np.linalg.norm(n)
    # joints
    def band(mask, lo, hi):
        m = mask & (s > lo) & (s < hi)
        return co[m].mean(0) if m.any() else None
    k0 = band(rest, s_mcp - 0.008, s_mcp + 0.008)
    k1 = band(rest, s_mid - 0.008, s_mid + 0.008)
    k2 = band(rest, L - 0.02, L + 1)
    tb_s = s[thumb]
    t0 = co[thumb][tb_s < np.quantile(tb_s, 0.25)].mean(0)
    t1 = co[thumb][tb_s > np.quantile(tb_s, 0.9)].mean(0)
    t_base = t0 - (t1 - t0) * 0.55                            # the thumb's saddle joint sits inside the heel of the hand
    # the grip: across the palm just behind the knuckles, a handle's radius off the palm surface
    s_g = s_mcp * 0.80
    palm = hand & (np.abs(s - s_g) < 0.014)
    surf = float(((co[palm] - W) @ n).max()) if palm.any() else 0.015
    across = float(np.median((co[palm] - W) @ c_ax)) if palm.any() else 0.0
    grip = W + a * s_g + n * (surf + HANDLE_R * 0.75) + c_ax * across
    H = {"wrist": W.tolist(), "a": a.tolist(), "n": n.tolist(), "c": c_ax.tolist(), "L": L, "s_thumb": s_t, "s_crotch": s_k, "s_mcp": s_mcp, "s_mid": s_mid,
         "knuckle": k0.tolist(), "mid": k1.tolist(), "tip": k2.tolist(), "thumb_base": t_base.tolist(), "thumb_mid": t0.tolist(), "thumb_tip": t1.tolist(),
         "grip": grip.tolist(), "palm_surface": surf, "fingers_found": len(fingers), "thumb_verts": int(len(thumb)), "forearm": fore.tolist()}
    return H, s, is_thumb, rest


def split_hand(W, names, co, s, is_thumb, rest, H, side):
    """share the hand's weight out to fingers / fingers2 / thumb with soft joints."""
    ih, i1, i2, it = (names.index(f"{k}.{side}") for k in ("hand", "fingers", "fingers2", "thumb"))
    w = W[:, ih].copy()
    t1 = smooth(H["s_mcp"] - 0.011, H["s_mcp"] + 0.011, s) * rest
    t2 = smooth(H["s_mid"] - 0.009, H["s_mid"] + 0.009, s) * rest
    # the thumb: full weight on its own piece, fading over the ball of the thumb toward the palm
    tb = np.array(H["thumb_mid"])
    dist = np.linalg.norm(co - tb, axis=1)
    tw = np.where(is_thumb, 1.0, 0.0)
    near = (~is_thumb) & (w > 0.3) & (dist < 0.030) & (s < H["s_mcp"])
    tw = np.where(near, 0.75 * (1 - smooth(0.006, 0.030, dist)), tw)
    W[:, it] = w * tw
    w_rest = w * (1 - tw)
    W[:, i1] = w_rest * t1 * (1 - t2)
    W[:, i2] = w_rest * t1 * t2
    W[:, ih] = w_rest * (1 - t1)
    return W


def limit_normalise(W, n=4):
    W = W.copy()
    W[W < 1e-4] = 0
    order = np.argsort(-W, axis=1)
    mask = np.zeros_like(W, dtype=bool)
    np.put_along_axis(mask, order[:, :n], True, axis=1)
    W = np.where(mask, W, 0)
    tot = W.sum(1, keepdims=True)
    bad = int((tot[:, 0] < 1e-6).sum())
    tot[tot < 1e-6] = 1
    return W / tot, bad


def smooth_weights(W, edges, iters=2, lam=0.5, protect=None):
    """Laplacian smoothing of the weights over the mesh (the auto-rig's weights step at part borders after nearest-vertex transfer)."""
    n = len(W)
    deg = np.zeros(n)
    np.add.at(deg, edges[:, 0], 1)
    np.add.at(deg, edges[:, 1], 1)
    deg[deg == 0] = 1
    for _ in range(iters):
        acc = np.zeros_like(W)
        np.add.at(acc, edges[:, 0], W[edges[:, 1]])
        np.add.at(acc, edges[:, 1], W[edges[:, 0]])
        new = W * (1 - lam) + (acc / deg[:, None]) * lam
        if protect is not None:
            new = np.where(protect[:, None], W, new)
        W = new
    return W


def write_weights(ob, W, names, arm):
    for g in list(ob.vertex_groups):
        ob.vertex_groups.remove(g)
    for j, n in enumerate(names):
        vg = ob.vertex_groups.new(name=n)
        col = W[:, j]
        nz = np.nonzero(col > 0)[0]
        # group vertices of equal weight (quantised) so the python loop stays short
        q = np.round(col[nz] * 1000).astype(int)
        for lvl in np.unique(q):
            vg.add(nz[q == lvl].tolist(), float(lvl) / 1000.0, "REPLACE")
    for m in list(ob.modifiers):
        if m.type == "ARMATURE":
            ob.modifiers.remove(m)
    ob.parent = arm
    md = ob.modifiers.new("Armature", "ARMATURE")
    md.object = arm
    md.use_vertex_groups = True
    # exact normalisation after the quantisation
    for v in ob.data.vertices:
        tot = sum(g.weight for g in v.groups)
        if tot > 0 and abs(tot - 1) > 1e-4:
            for g in v.groups:
                g.weight /= tot


# ---------------------------------------------------------------------------------------------------- the stage
def run(work, rig_glb, log=print):
    from samurai import pose as PO
    bpy.ops.wm.open_mainfile(filepath=os.path.join(work, "villager_low.blend"))
    sc = bpy.context.scene
    sc.render.fps = 30
    low = bpy.data.objects["Villager_LOD0"]
    src_arm, src_mesh, new = import_rig(rig_glb)
    if src_arm.animation_data:
        src_arm.animation_data.action = None
    for pb in src_arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.rotation_euler = (0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()
    Jm = rest_joints(src_arm)
    J = {MAP[k]: v for k, v in Jm.items() if k in MAP and k not in ("head_end", "headfront")}
    J["head_end_z"] = float(Jm["head_end"].z) if "head_end" in Jm else J["head"].z + 0.2
    arm = build_armature(J, sc.collection)
    names = [n for n, _ in CHAINS]

    # ---- skin: carry the auto-rig's weights over by position
    W, worst = transfer(src_mesh, low, names)
    log(f"  weights carried over: worst nearest-vertex distance {worst * 1000:.2f} mm")
    if worst > 0.004:
        raise RuntimeError("the rigged mesh is not the LOD0 mesh (nearest-vertex distance %.1f mm)" % (worst * 1000))
    co = _np_verts(low.data)
    ed = np.empty(len(low.data.edges) * 2, dtype=np.int64)
    low.data.edges.foreach_get("vertices", ed)
    ed = ed.reshape(-1, 2)
    W = smooth_weights(W, ed, iters=2, lam=0.5)

    # ---- hands: measure, add bones, split the weights
    hands = {}
    extra = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        ih = names.index(f"hand.{side}")
        H, s, is_thumb, rest = measure_hand(co, ed, W[:, ih], J[f"hand.{side}"], J[f"forearm.{side}"], sx, log)
        hands[side] = H
        a, n, c = V(H["a"]), V(H["n"]), V(H["c"])
        add_bone(arm, f"fingers.{side}", f"hand.{side}", H["knuckle"], V(H["mid"]) - V(H["knuckle"]), n, (V(H["mid"]) - V(H["knuckle"])).length)
        add_bone(arm, f"fingers2.{side}", f"fingers.{side}", H["mid"], V(H["tip"]) - V(H["mid"]), n, (V(H["tip"]) - V(H["mid"])).length)
        add_bone(arm, f"thumb.{side}", f"hand.{side}", H["thumb_base"], V(H["thumb_tip"]) - V(H["thumb_base"]), n, (V(H["thumb_tip"]) - V(H["thumb_base"])).length)
        for k in ("fingers", "fingers2", "thumb"):
            names.append(f"{k}.{side}")
        W = np.hstack([W, np.zeros((len(W), 3))])
        W = split_hand(W, names, co, s, is_thumb, rest, H, side)
        # grip frame: +Y along the handle toward the thumb side (the working end), +Z = the hand's own direction (the way a hammer strikes)
        tn = "tool_r" if side == "R" else "tool_l"
        add_bone(arm, tn, f"hand.{side}", H["grip"], c, a, 0.12)
        extra.append(tn)
        log(f"  hand.{side}: length {H['L'] * 1000:.0f} mm, thumb splits at {H['s_thumb'] * 1000:.0f}, crotches at {H['s_crotch'] * 1000:.0f} ({H['fingers_found']} fingers), thumb verts {H['thumb_verts']}")
    # ---- the fishing line: from the rod's tip, wound back along the rod at rest
    tb = arm.data.bones["tool_r"]
    Mt = tool_matrix(arm, "tool_r")
    tip = Mt @ V(P.ROD_TIP)
    back = (Mt @ V((0.045, 0.0, 2.00))) - tip
    add_bone(arm, "line", "tool_r", tip, back, Mt.to_3x3() @ V((1, 0, 0)), 0.30)
    extra.append("line")
    # ---- loads: on the right shoulder / in front of the belly, axes = the armature's
    sh = J["upper_arm.R"]
    near = (np.abs(co[:, 0] - (sh.x * 0.78)) < 0.03) & (np.abs(co[:, 1] - sh.y) < 0.07) & (co[:, 2] > sh.z - 0.05)
    top = float(co[near][:, 2].max()) if near.any() else sh.z + 0.06
    belly = (np.abs(co[:, 2] - (J["hips"].z + 0.076)) < 0.03) & (np.abs(co[:, 0]) < 0.08)
    front = float(co[belly][:, 1].min()) if belly.any() else -0.12
    add_bone(arm, "load_shoulder", "chest", (sh.x * 0.78, sh.y, top), (0, 1, 0), (0, 0, 1), 0.2)
    add_bone(arm, "load_front", "chest", (0.0, front - 0.215, J["hips"].z - 0.044), (0, 1, 0), (0, 0, 1), 0.2)
    extra += ["load_shoulder", "load_front"]
    for n in extra:
        names.append(n)
    W = np.hstack([W, np.zeros((len(W), len(extra)))])
    W, bad = limit_normalise(W, 4)
    if bad:
        raise RuntimeError(f"{bad} vertices have no weight")
    write_weights(low, W, names, arm)
    hands["shoulder_top"] = top
    hands["belly_front"] = front
    # the head: where the skull's crown is (the hat sits there), without the topknot
    hd = co[:, 2] > J["head"].z + 0.05
    ax = co[hd][:, :2].mean(0)
    r = np.hypot(co[:, 0] - ax[0], co[:, 1] - ax[1])
    ring = hd & (r > 0.055)
    hands["crown"] = [float(ax[0]), float(ax[1]), float(co[ring][:, 2].max())]
    hands["head_top"] = float(co[:, 2].max())
    for b in arm.data.bones:
        m = b.matrix_local.to_3x3()
        if b.name.startswith("load_"):
            assert max(abs(m[i][j] - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3)) < 1e-4, "load bone is not axis-aligned: " + str(m)
    with open(os.path.join(work, "hands.json"), "w") as fh:
        json.dump(hands, fh, indent=1)
    # ---- drop the import, keep only our rig
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    stats = {"bones": len(arm.data.bones), "max_influences": int((W > 0).sum(1).max()), "verts": len(W)}
    log("  rig " + json.dumps(stats))
    qa_poses(arm, low, work, hands)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, "villager_rig.blend"), compress=True)
    return arm


def tool_matrix(arm, bone):
    """tool frame -> armature space for a grip bone: tool +X = bone Z (strike), tool +Y = bone X, tool +Z = bone Y (along the handle)."""
    m = arm.data.bones[bone].matrix_local
    R = m.to_3x3()
    T = Matrix.Identity(4)
    x, y, z = R.col[2], R.col[0], R.col[1]
    for i in range(3):
        T[i][0], T[i][1], T[i][2], T[i][3] = x[i], y[i], z[i], m[i][3]
    return T


def curl(pose, rig, side, amount, hands, thumb=None):
    """close the hand: amount 0 (the rest pose's open hand) .. 1 (a fist around a handle)."""
    H = hands[side]
    a, n, c = V(H["a"]), V(H["n"]), V(H["c"])
    hinge = a.cross(n).normalized()                           # turning about it takes the fingers from `a` toward the palm normal
    from mathutils import Quaternion
    pose.rot(f"fingers.{side}", Quaternion(hinge, math.radians(78.0) * amount))
    pose.rot(f"fingers2.{side}", Quaternion(hinge, math.radians(88.0) * amount))
    t = amount if thumb is None else thumb
    ta = a if (a.cross(c)).dot(n) > 0 else -a
    pose.rot(f"thumb.{side}", Quaternion(ta, math.radians(38.0) * t) @ Quaternion(hinge, math.radians(22.0) * t))


def qa_poses(arm, low, work, hands):
    """Deformation checks: the poses a labourer will actually take (arms overhead, a deep squat, a twist, fists)."""
    from samurai import pose as PO
    rig = PO.Rig(arm)
    tests = {}
    p = PO.Pose(rig)
    for s, sx in (("L", 1.0), ("R", -1.0)):
        p.rot(f"upper_arm.{s}", (-150, 0, sx * 12))
        p.rot(f"forearm.{s}", (-45, 0, 0))
        curl(p, rig, s, 1.0, hands)
    tests["overhead_fists"] = p
    p = PO.Pose(rig)
    p.move("hips", (0, 0.05, -0.34))
    p.rot("hips", (18, 0, 0))
    for s, sx in (("L", 1.0), ("R", -1.0)):
        p.rot(f"thigh.{s}", (-95, 0, sx * 8))
        p.rot(f"shin.{s}", (118, 0, 0))
        p.rot(f"foot.{s}", (-28, 0, 0))
        p.rot(f"upper_arm.{s}", (-58, 0, sx * -22))
        p.rot(f"forearm.{s}", (-70, 0, 0))
        curl(p, rig, s, 0.5, hands)
    p.rot("spine", (14, 0, 0))
    p.rot("chest", (12, 0, 0))
    tests["squat_reach"] = p
    p = PO.Pose(rig)
    p.rot("spine", (8, 0, 22))
    p.rot("spine1", (8, 0, 22))
    p.rot("chest", (6, 0, 22))
    p.rot("neck", (0, 0, -20))
    p.rot("head", (-8, 14, -20))
    p.rot("thigh.L", (-42, 0, 0))
    p.rot("shin.L", (50, 0, 0))
    p.rot("thigh.R", (24, 0, 0))
    p.rot("upper_arm.L", (-70, 0, -30))
    p.rot("forearm.L", (-95, 0, 0))
    p.rot("upper_arm.R", (35, 0, 20))
    tests["twist_stride"] = p
    paths = []
    for name, pose in tests.items():
        PO.show_pose(arm, pose)
        bpy.context.view_layer.update()
        paths += qa.shots([low], os.path.join(work, "qa", f"rig_{name}"), views=("front", "q", "side", "q_back"), size=900)
    qa.sheet(paths, os.path.join(work, "qa", "rig_sheet.jpg"), cols=4)
    # hands close up
    PO.show_pose(arm, tests["overhead_fists"].__class__(rig))
    p = PO.Pose(rig)
    curl(p, rig, "L", 1.0, hands)
    curl(p, rig, "R", 0.5, hands)
    PO.show_pose(arm, p)
    bpy.context.view_layer.update()
    hp = qa.shots([low], os.path.join(work, "qa", "rig_fistL"), views=("front", "side", "q"), size=900, focus=(0.44, 0, 0.80), span=0.36)
    hp += qa.shots([low], os.path.join(work, "qa", "rig_halfR"), views=("front", "side_r", "q"), size=900, focus=(-0.44, 0, 0.80), span=0.36)
    qa.sheet(hp, os.path.join(work, "qa", "rig_hands.jpg"), cols=3)
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    bpy.context.view_layer.update()
