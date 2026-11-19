"""villager.atlas for a soldier: finer charts, and a second look at each.

An angle-based unwrap keeps angles, not areas: a chart that holds both a ballooning pair of knee-breeches and the narrow gaiter under it gives the gaiter a
twentieth of the texels (it baked as a smear). So:
  1. the body is cut into more charts: every limb SEGMENT is its own part (thigh / shin, upper arm / forearm, chest / pelvis), front and back as before;
  2. after the unwrap every chart is measured: where a fifth of its area is still far below the median texel density it is cut once more (left / right of its
     own middle) and unwrapped again;
  3. what is starved even then is projected (few, small islands). NOT the whole chart by Smart UV Project: on a decimated organic mesh that makes thousands of
     islands (GOTCHAS: 17% of the atlas used, and every island border bleeds in the mip maps);
  4. everything is scaled even, the detail regions get their extra density back, and the square is packed by the islands' true outlines.

    from villager import atlas; from soldier import atlasfix; atlasfix.install(atlas)
"""
import math

import bpy
import numpy as np

LOW = 0.45          # a face is starved when its texel density is below this fraction of the median
SHARE = 0.18        # a chart is redone when this share of its 3D area is starved

PARTS = {
    "head": ("head", "neck"),
    "chest": ("chest", "spine1", "shoulder.L", "shoulder.R"), "pelvis": ("spine", "hips"),
    "upper_arm.L": ("upper_arm.L",), "forearm.L": ("forearm.L",), "upper_arm.R": ("upper_arm.R",), "forearm.R": ("forearm.R",),
    "hand.L": ("hand.L", "fingers.L", "fingers2.L", "thumb.L"), "hand.R": ("hand.R", "fingers.R", "fingers2.R", "thumb.R"),
    "thigh.L": ("thigh.L",), "shin.L": ("shin.L",), "thigh.R": ("thigh.R",), "shin.R": ("shin.R",),
    "foot.L": ("foot.L", "toe.L"), "foot.R": ("foot.R", "toe.R"),
}


def _density(me, uv):
    n = len(me.polygons)
    a3 = np.empty(n)
    me.polygons.foreach_get("area", a3)
    au = np.zeros(n)
    for p in me.polygons:
        li = list(p.loop_indices)
        a = uv[li[0]]
        s = 0.0
        for i in range(1, len(li) - 1):
            b, c = uv[li[i]], uv[li[i + 1]]
            s += abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) * 0.5
        au[p.index] = s
    d = np.sqrt(au / np.maximum(a3, 1e-12))
    return d, a3


def _starved(me, uv, groups):
    """groups: per-face chart id. Returns the ids whose area is starved beyond SHARE, the starved face mask and the starved share of the whole."""
    d, a3 = _density(me, uv)
    med = float(np.median(d[d > 0])) if (d > 0).any() else 1.0
    st = d < LOW * med
    out = []
    for g in np.unique(groups):
        m = groups == g
        if float(a3[m & st].sum() / max(a3[m].sum(), 1e-12)) > SHARE:
            out.append(int(g))
    return out, st, float(a3[st].sum() / a3.sum())


def _select_faces(atlas, ob, mask):
    me = ob.data
    atlas._select(ob)
    bpy.context.scene.tool_settings.mesh_select_mode = (False, False, True)
    for e in me.edges:
        e.select = False
    for v in me.vertices:
        v.select = False
    for p in me.polygons:
        p.select = bool(mask[p.index])
        if p.select:
            for vi in p.vertices:
                me.vertices[vi].select = True


def install(atlas):
    atlas.PARTS = PARTS
    orig = atlas.unwrap

    def unwrap(ob, labels, plist, v0=0.0, margin=0.004, log=print):
        info = orig(ob, labels, plist, v0=v0, margin=margin, log=log)
        me = ob.data
        groups = np.asarray(labels).copy()
        uv = atlas._get_uv(ob)
        bad, st, before = _starved(me, uv, groups)
        name = lambda g: plist[(g % 1000) // 2] + "/" + str(g % 2) + ("" if g < 1000 else "lr"[(g // 1000) - 1])
        steps = []
        if bad:
            # 2. cut those charts once more: left / right of their own middle
            cen = np.array([p.center[:] for p in me.polygons])
            for g in bad:
                m = groups == g
                c = cen[m].mean(0)
                span = cen[m].max(0) - cen[m].min(0)
                ax = 0 if span[0] >= span[1] * 0.6 else 1                      # across the limb (x), unless the chart is much deeper than wide
                groups[m & (cen[:, ax] >= c[ax])] = g + 1000
                groups[m & (cen[:, ax] < c[ax])] = g + 2000
            groups, _ = atlas.merge_small(me, groups, min_faces=40)
            atlas.mark_seams(ob, groups)
            redo = np.isin(groups // 1000 * 0 + groups, [g + k for g in bad for k in (1000, 2000)])
            _select_faces(atlas, ob, redo)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=margin)
            bpy.ops.object.mode_set(mode="OBJECT")
            steps.append("cut again: " + ", ".join(name(g) for g in bad))
            uv = atlas._get_uv(ob)
            bad2, st2, _ = _starved(me, uv, groups)
            if bad2:
                # 3. the faces still starved in those charts: projected
                m = np.isin(groups, bad2) & st2
                _select_faces(atlas, ob, m)
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_mode(type="FACE")
                bpy.ops.uv.smart_project(angle_limit=math.radians(85.0), island_margin=margin, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
                bpy.ops.object.mode_set(mode="OBJECT")
                steps.append(f"projected: {int(m.sum())} faces of " + ", ".join(name(g) for g in bad2))
        # 4. even scale, detail density, pack by outline
        atlas._select(ob)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.select_all(action="SELECT")
        bpy.ops.uv.average_islands_scale()
        bpy.ops.object.mode_set(mode="OBJECT")
        uv = atlas._get_uv(ob)
        loops_of = {}
        for p in me.polygons:
            loops_of.setdefault(int(groups[p.index]), []).extend(p.loop_indices)
        for g, li in loops_of.items():
            k = atlas.DENSITY.get(plist[(g % 1000) // 2], 1.0)
            if k != 1.0:
                li = np.array(li)
                c = uv[li].mean(0)
                uv[li] = c + (uv[li] - c) * k
        atlas._set_uv(ob, uv)
        atlas._select(ob)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.select_all(action="SELECT")
        try:
            bpy.ops.uv.pack_islands(rotate=True, margin=margin, shape_method="CONCAVE")
        except TypeError:
            bpy.ops.uv.pack_islands(rotate=True, margin=margin)
        bpy.ops.object.mode_set(mode="OBJECT")
        uv = atlas._get_uv(ob)
        _, _, after = _starved(me, uv, groups)
        for s in steps:
            log("  charts " + s)
        info.update({"steps": steps, "starved_area_before": round(before, 3), "starved_area_after": round(after, 3),
                     "u": [round(float(uv[:, 0].min()), 4), round(float(uv[:, 0].max()), 4)], "v": [round(float(uv[:, 1].min()), 4), round(float(uv[:, 1].max()), 4)]})
        return info

    atlas.unwrap = unwrap
