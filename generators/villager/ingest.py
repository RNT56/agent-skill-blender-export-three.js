"""Stage 1: take the image-to-3D mesh (Tripo H3.1 GLB) and make it a clean, measured HIGH-POLY source.

    blender -b --factory-startup -P generators/villager_unit.py -- --stage ingest --src fixtures/villager_src/tripo/villager_tripo_h31.glb --work <scratch dir>

What it does: import, apply transforms, face -Y (Blender; = glTF +Z), stand on z = 0 centred on x / y, scale to HEIGHT, weld, drop tiny floating shells,
report the facts a rigger needs (dimensions, shells, texture sizes, landmark cross-sections) and save <work>/villager_high.blend + QA shots.
"""
import json
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import qa

HEIGHT = 1.68          # metres to the crown of the head (the topknot adds a little): a head shorter than the armoured samurai


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = 30
    sc.unit_settings.system = "METRIC"
    return sc


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh in " + path)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    # bake the node transforms into the mesh, drop the import's empties
    mw = ob.matrix_world.copy()
    ob.parent = None
    ob.matrix_world = Matrix.Identity(4)
    ob.data.transform(mw)
    for o in new:
        if o != ob and o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    ob.name = ob.data.name = "Villager_High"
    return ob


def shells(me):
    """connected components as lists of vertex indices (union-find over edges; fast enough for 1M verts with numpy)."""
    import numpy as np
    n = len(me.vertices)
    ed = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ed)
    ed = ed.reshape(-1, 2)
    parent = np.arange(n)
    # iterative label propagation: min label over edges until stable
    while True:
        a = parent[ed[:, 0]]
        b = parent[ed[:, 1]]
        m = np.minimum(a, b)
        new = parent.copy()
        np.minimum.at(new, ed[:, 0], m)
        np.minimum.at(new, ed[:, 1], m)
        new = new[new]
        if (new == parent).all():
            break
        parent = new
    labels, counts = np.unique(parent, return_counts=True)
    return parent, labels, counts


def normalise(ob, height=HEIGHT, facing=None):
    """stand on z=0, centre x/y on the torso, scale so the crown is at `height`. Returns the facts."""
    import numpy as np
    me = ob.data
    n = len(me.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lo, hi = co.min(0), co.max(0)
    size = hi - lo
    # the glTF importer already converts to Z-up; the figure's height must be along z
    up = int(np.argmax(size))
    facts = {"import_size": [round(float(x), 4) for x in size], "up_axis": "xyz"[up]}
    if up != 2:
        raise RuntimeError(f"the figure is not upright along z after import (size {size})")
    s = height / size[2]
    co = (co - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])) * s
    me.vertices.foreach_set("co", co.ravel())
    me.update()
    facts["scale_applied"] = round(float(s), 5)
    return facts, co


def face_minus_y(ob, co):
    """Make the figure face -Y. The face is the side where the feet stick out (toes forward): compare the foot slice's y centroid with the ankle column."""
    import numpy as np
    z = co[:, 2]
    feet = co[z < 0.06]
    shin = co[(z > 0.12) & (z < 0.30)]
    toes = float(feet[:, 1].mean() - shin[:, 1].mean())          # > 0: toes point +Y
    xs = float(co[:, 0].max() - co[:, 0].min())
    ys = float(co[:, 1].max() - co[:, 1].min())
    turned = False
    if xs < ys:                                                  # arms out along Y: the figure faces +-X, turn it a quarter first
        ob.data.transform(Matrix.Rotation(1.5707963267948966, 4, "Z"))
        ob.data.update()
        return face_minus_y(ob, _coords(ob))
    if toes > 0:
        ob.data.transform(Matrix.Rotation(3.141592653589793, 4, "Z"))
        ob.data.update()
        turned = True
    return {"toe_offset_y": round(toes, 4), "turned_180": turned, "span_x": round(xs, 3), "span_y": round(ys, 3)}


def _coords(ob):
    import numpy as np
    co = np.empty(len(ob.data.vertices) * 3, dtype=np.float64)
    ob.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def clean(ob, min_shell_frac=0.002, weld=1e-5):
    """weld coincident vertices, delete loose geometry and shells smaller than `min_shell_frac` of the vertices that are NOT touching the body (floaters)."""
    import numpy as np
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    n0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=weld)
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()
    parent, labels, counts = shells(me)
    order = np.argsort(-counts)
    info = [{"verts": int(counts[i])} for i in order[:12]]
    n = len(me.vertices)
    small = labels[counts < max(8, n * min_shell_frac)]
    removed = 0
    if len(small):
        kill = np.isin(parent, small)
        removed = int(kill.sum())
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.verts[i] for i in np.nonzero(kill)[0]], context="VERTS")
        bm.to_mesh(me)
        bm.free()
        me.update()
    return {"verts_in": n0, "verts_welded": n, "shells": int(len(labels)), "largest_shells": info, "small_shell_verts_removed": removed, "verts_out": len(me.vertices),
            "tris_out": sum(len(p.vertices) - 2 for p in me.polygons)}


def sections(co, zs):
    """per height: the x-extent clusters of the cross-section (to find where arms / legs separate) -> landmarks for the rig."""
    import numpy as np
    out = {}
    for z in zs:
        sl = co[np.abs(co[:, 2] - z) < 0.006]
        if len(sl) < 8:
            out[round(z, 3)] = []
            continue
        xs = np.sort(sl[:, 0])
        gaps = np.nonzero(np.diff(xs) > 0.012)[0]
        segs, a = [], 0
        for g in list(gaps) + [len(xs) - 1]:
            seg = sl[(sl[:, 0] >= xs[a]) & (sl[:, 0] <= xs[g])]
            segs.append([round(float(xs[a]), 3), round(float(xs[g]), 3), round(float(seg[:, 1].min()), 3), round(float(seg[:, 1].max()), 3)])
            a = g + 1
        out[round(z, 3)] = segs
    return out


def run(src, work, height=HEIGHT, log=print):
    os.makedirs(work, exist_ok=True)
    reset_scene()
    ob = import_glb(src)
    facts = {"source": os.path.basename(src), "tris_in": sum(len(p.vertices) - 2 for p in ob.data.polygons)}
    f, co = normalise(ob, height)
    facts.update(f)
    facts["facing"] = face_minus_y(ob, co)
    facts["clean"] = clean(ob)
    co = _coords(ob)
    # re-seat after cleaning (a removed floater may have been the lowest / highest point)
    f2, co = normalise(ob, height)
    facts["rescale_after_clean"] = f2["scale_applied"]
    lo, hi = co.min(0), co.max(0)
    facts["dimensions_m"] = [round(float(x), 4) for x in (hi - lo)]
    facts["bounds"] = {"min": [round(float(x), 4) for x in lo], "max": [round(float(x), 4) for x in hi]}
    facts["images"] = [{"name": im.name, "size": list(im.size), "colorspace": im.colorspace_settings.name} for im in bpy.data.images if im.size[0]]
    facts["materials"] = [m.name for m in ob.data.materials]
    facts["uv_layers"] = [u.name for u in ob.data.uv_layers]
    import numpy as np
    facts["sections"] = sections(co, [round(z, 3) for z in np.arange(0.02, height + 0.08, 0.04)])
    for p in ob.data.polygons:
        p.use_smooth = True
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, "villager_high.blend"), compress=True)
    with open(os.path.join(work, "ingest.json"), "w") as fh:
        json.dump(facts, fh, indent=1)
    paths = qa.shots([ob], os.path.join(work, "qa", "high"), views=("front", "side", "back", "q"), size=1000)
    paths += qa.shots([ob], os.path.join(work, "qa", "high_head"), views=("front", "q"), size=1000, focus=(0, 0, height - 0.12), span=0.5)
    paths += qa.shots([ob], os.path.join(work, "qa", "high_hand"), views=("front", "side"), size=1000, focus=(float(hi[0]) - 0.1, 0, 0.78), span=0.42)
    qa.sheet(paths[:4], os.path.join(work, "qa", "high_sheet.jpg"))
    qa.sheet(paths[4:], os.path.join(work, "qa", "high_detail.jpg"))
    log("INGEST " + json.dumps({k: v for k, v in facts.items() if k != "sections"}))
    return facts
