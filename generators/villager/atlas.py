"""Stage 4: the texture atlas of the rigged LOD0.

Charts follow the BODY, not the triangle normals: every face belongs to the part its skin weights name (head, torso, each arm, hand, leg, foot) and
to one half of that part (front / back, palm / back of the hand, sole / upper), so the atlas is a few dozen big islands with seams where a seam
would be on a real garment pattern. Pieces too small to be worth an island are merged into their neighbour. Then: unwrap (minimum stretch),
equalise the texel density (the head and the hands get more), pack into the body's band of the atlas, and bake high -> low (lowpoly.bake_all).
"""
import json
import math
import os

import bmesh
import bpy
import numpy as np

from . import lowpoly, qa

PARTS = {
    "head": ("head", "neck"), "torso": ("chest", "spine1", "spine", "hips", "shoulder.L", "shoulder.R"),
    "arm.L": ("upper_arm.L", "forearm.L"), "arm.R": ("upper_arm.R", "forearm.R"),
    "hand.L": ("hand.L", "fingers.L", "fingers2.L", "thumb.L"), "hand.R": ("hand.R", "fingers.R", "fingers2.R", "thumb.R"),
    "leg.L": ("thigh.L", "shin.L"), "leg.R": ("thigh.R", "shin.R"), "foot.L": ("foot.L", "toe.L"), "foot.R": ("foot.R", "toe.R"),
}
DENSITY = {"head": 1.45, "hand.L": 1.25, "hand.R": 1.25, "foot.L": 0.8, "foot.R": 0.8}      # relative texel density per part (1 = the body)
MIN_CHART = 60          # faces: smaller pieces join a neighbour


def label_faces(ob, hands):
    me = ob.data
    names = [g.name for g in ob.vertex_groups]
    pid = {}
    plist = list(PARTS)
    for i, p in enumerate(plist):
        for b in PARTS[p]:
            pid[b] = i
    W = np.zeros((len(me.vertices), len(plist)))
    for v in me.vertices:
        for g in v.groups:
            j = pid.get(names[g.group])
            if j is not None:
                W[v.index, j] += g.weight
    co = np.array([v.co[:] for v in me.vertices])
    part_c = [co[W.argmax(1) == i].mean(0) if (W.argmax(1) == i).any() else np.zeros(3) for i in range(len(plist))]
    labels = np.zeros(len(me.polygons), dtype=np.int64)
    for p in me.polygons:
        vi = list(p.vertices)
        i = int(W[vi].sum(0).argmax())
        name = plist[i]
        c = np.array(p.center)
        if name.startswith("hand"):
            n = np.array(hands[name[-1]]["n"])
            side = float((c - part_c[i]) @ n) > 0
        elif name.startswith("foot"):
            side = p.normal.z < -0.35
        else:
            side = c[1] > part_c[i][1]
        labels[p.index] = i * 2 + int(side)
    return labels, plist


def merge_small(me, labels, min_faces=MIN_CHART, rounds=6):
    """connected pieces of one label smaller than `min_faces` take the label most of their neighbours have."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    nf = len(bm.faces)
    adj = [[lf.index for e in f.edges for lf in e.link_faces if lf.index != f.index] for f in bm.faces]
    bm.free()
    for _ in range(3):                                       # straighten the borders: a face takes the label two of its three neighbours share
        new = labels.copy()
        for f in range(nf):
            ls = [labels[g] for g in adj[f]]
            for l in set(ls):
                if l != labels[f] and ls.count(l) >= 2:
                    new[f] = l
        labels = new
    for _ in range(rounds):
        comp = -np.ones(nf, dtype=np.int64)
        comps = []
        for s in range(nf):
            if comp[s] >= 0:
                continue
            stack, members = [s], []
            comp[s] = len(comps)
            while stack:
                f = stack.pop()
                members.append(f)
                for g in adj[f]:
                    if comp[g] < 0 and labels[g] == labels[f]:
                        comp[g] = len(comps)
                        stack.append(g)
            comps.append(members)
        changed = 0
        for members in comps:
            if len(members) >= min_faces:
                continue
            votes = {}
            ms = set(members)
            for f in members:
                for g in adj[f]:
                    if g not in ms:
                        votes[labels[g]] = votes.get(labels[g], 0) + 1
            if votes:
                best = max(votes, key=votes.get)
                for f in members:
                    labels[f] = best
                changed += 1
        if not changed:
            break
    return labels, len(comps)


def mark_seams(ob, labels):
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    n = 0
    for e in bm.edges:
        fs = e.link_faces
        e.seam = bool(len(fs) == 2 and labels[fs[0].index] != labels[fs[1].index])
        n += int(e.seam)
    bm.to_mesh(me)
    bm.free()
    return n


def _select(ob):
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def _get_uv(ob):
    a = np.empty(len(ob.data.loops) * 2, dtype=np.float64)
    ob.data.uv_layers["UVMap"].data.foreach_get("uv", a)
    return a.reshape(-1, 2)


def _set_uv(ob, a):
    ob.data.uv_layers["UVMap"].data.foreach_set("uv", np.ascontiguousarray(a).ravel())
    ob.data.update()


def unwrap(ob, labels, plist, v0=lowpoly.BODY_V0, margin=0.004, log=print):
    me = ob.data
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name="UVMap")
    _select(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    # angle-based (ABF): the minimum-stretch solver left several of these half-shells as the disc it starts from
    method = "ANGLE_BASED"
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    # islands the solver gave up on (not disc-like: a fold that closes on itself) come back with zero area: retry those with the angle-based
    # solver, and as a last resort project them flat along the direction their half faces
    def dead_labels():
        uvl = me.uv_layers["UVMap"].data
        tot, dead = {}, {}
        for p in me.polygons:
            li = list(p.loop_indices)
            a, b, c = (uvl[i].uv for i in li[:3])
            ua = abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y))
            lab = int(labels[p.index])
            tot[lab] = tot.get(lab, 0) + 1
            dead[lab] = dead.get(lab, 0) + (ua < 1e-12)
        return [lab for lab in tot if dead[lab] > 0.04 * tot[lab]]
    failed = dead_labels()
    if failed:
        log("  unwrap gave up on " + ", ".join(f"{plist[l // 2]}/{l % 2}" for l in failed) + ": conformal retry")
        bpy.context.scene.tool_settings.mesh_select_mode = (False, False, True)
        for p in me.polygons:
            p.select = int(labels[p.index]) in failed
        for e in me.edges:
            e.select = False
        for v in me.vertices:
            v.select = False
        for p in me.polygons:
            if p.select:
                for vi in p.vertices:
                    me.vertices[vi].select = True
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.uv.unwrap(method="CONFORMAL", margin=margin)
        bpy.ops.object.mode_set(mode="OBJECT")
        still = dead_labels()
        if still:
            log("  still flat: " + ", ".join(f"{plist[l // 2]}/{l % 2}" for l in still) + ": planar projection")
            uv = _get_uv(ob)
            for lab in still:
                name = plist[lab // 2]
                faces = [p for p in me.polygons if int(labels[p.index]) == lab]
                nrm = np.mean([p.normal[:] for p in faces], axis=0)
                nrm /= (np.linalg.norm(nrm) or 1.0)
                up = np.array((0.0, 0.0, 1.0)) if abs(nrm[2]) < 0.9 else np.array((0.0, 1.0, 0.0))
                ax = np.cross(up, nrm)
                ax /= np.linalg.norm(ax)
                ay = np.cross(nrm, ax)
                for p in faces:
                    for li, vi in zip(p.loop_indices, p.vertices):
                        c = np.array(me.vertices[vi].co)
                        uv[li] = (c @ ax, c @ ay)
            _set_uv(ob, uv)
    _select(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()
    bpy.ops.object.mode_set(mode="OBJECT")
    # per-part density: scale each chart about its own centre
    uv = _get_uv(ob)
    loops_of = {}
    for p in me.polygons:
        loops_of.setdefault(int(labels[p.index]), []).extend(p.loop_indices)
    for lab, li in loops_of.items():
        k = DENSITY.get(plist[lab // 2], 1.0)
        if k != 1.0:
            li = np.array(li)
            c = uv[li].mean(0)
            uv[li] = c + (uv[li] - c) * k
    _set_uv(ob, uv)
    k = 1.0 - v0
    # 1) let the packer turn every island the way it packs best; 2) squash u by k and pack again WITHOUT turning, so that mapping the unit
    #    square onto the (1 x k) band afterwards restores every island's aspect
    _select(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    uv = _get_uv(ob)
    uv[:, 0] *= k
    _set_uv(ob, uv)
    _select(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=False, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    uv = _get_uv(ob)
    uv[:, 1] = v0 + uv[:, 1] * k
    _set_uv(ob, uv)
    return {"method": method, "u": [round(float(uv[:, 0].min()), 4), round(float(uv[:, 0].max()), 4)], "v": [round(float(uv[:, 1].min()), 4), round(float(uv[:, 1].max()), 4)]}


def stretch_stats(ob):
    """how far the UV map is from uniform scale: per face sqrt(uv area / 3d area) relative to the median (1 = even)."""
    me = ob.data
    uv = me.uv_layers["UVMap"].data
    r = []
    for p in me.polygons:
        li = list(p.loop_indices)
        a, b, c = (uv[i].uv for i in li[:3])
        ua = abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) * 0.5
        if p.area > 1e-10 and ua > 1e-12:
            r.append(math.sqrt(ua / p.area))
    r = np.array(r)
    m = np.median(r)
    return {"density_p05": round(float(np.quantile(r, 0.05) / m), 2), "density_p95": round(float(np.quantile(r, 0.95) / m), 2), "faces_flipped_or_zero": int(len(me.polygons) - len(r))}


def run(work, px=2048, samples=48, log=print):
    from recipes import _common as C
    bpy.ops.wm.open_mainfile(filepath=os.path.join(work, "villager_rig.blend"))
    sc = bpy.context.scene
    low = bpy.data.objects["Villager_LOD0"]
    arm = bpy.data.objects["VillagerRig"]
    with open(os.path.join(work, "hands.json")) as fh:
        hands = json.load(fh)
    with bpy.data.libraries.load(os.path.join(work, "villager_high.blend")) as (src, dst):
        dst.objects = [n for n in src.objects if n == "Villager_High"]
    high = dst.objects[0]
    sc.collection.objects.link(high)
    bpy.context.view_layer.update()
    for m in low.modifiers:
        m.show_viewport = m.show_render = False
    labels, plist = label_faces(low, hands)
    labels, ncomp = merge_small(low.data, labels)
    seams = mark_seams(low, labels)
    info = unwrap(low, labels, plist, log=log)
    st = {**info, **lowpoly.uv_stats(low, px), **stretch_stats(low), "charts": ncomp, "seam_edges": seams}
    log("  uv " + json.dumps(st))
    old = [m for m in low.data.materials]
    tex = os.path.join(work, "tex")
    maps, bstats = lowpoly.bake_all(high, low, tex, px=px, ao_samples=samples, log=log)
    log("  bake " + json.dumps(bstats))
    mat = C.pbr_material("villager_mat", maps)
    low.data.materials.clear()
    low.data.materials.append(mat)
    for m in low.modifiers:
        m.show_viewport = m.show_render = True
    bpy.data.objects.remove(high, do_unlink=True)
    bpy.context.view_layer.update()
    paths = qa.shots([low], os.path.join(work, "qa", "atlas"), views=("front", "q", "back"), size=1000)
    paths += qa.shots([low], os.path.join(work, "qa", "atlas_head"), views=("front", "q"), size=1000, focus=(0, 0, 1.56), span=0.5)
    paths += qa.shots([low], os.path.join(work, "qa", "atlas_hand"), views=("front",), size=1000, focus=(0.40, 0, 0.78), span=0.42)
    qa.sheet(paths, os.path.join(work, "qa", "atlas_sheet.jpg"), cols=3)
    try:
        qa.sheet(lowpoly.lit_shots(low, os.path.join(work, "qa", "atlas_lit")), os.path.join(work, "qa", "atlas_lit_sheet.jpg"))
    except Exception as exc:
        log("  lit shots skipped: " + repr(exc))
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, "villager_skin.blend"), compress=True)
    with open(os.path.join(work, "atlas.json"), "w") as fh:
        json.dump({"uv": st, "bake": bstats, "px": px}, fh, indent=1)
