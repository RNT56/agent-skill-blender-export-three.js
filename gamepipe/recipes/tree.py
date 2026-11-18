"""Tree recipe: turn a heavy hero tree into game-ready LODs.

Spec (recipe "tree"), under spec["recipe_cfg"]:
  bark_obj / leaf_obj : source objects. Leaves must be ONE mesh made of separate islands, one island per leaf,
                        whose FIRST vertex is the leaf base (generator convention).
  tex_px, leaf_palette ("green"|"autumn"), lods: [{name, bark_tris, leaf_keep, leaf_scale, max_tris}]
  impostor (optional): {name, px, max_tris}  -> two crossed alpha cards rendered from the finished tree
Steps: leaves -> alpha-cut cards on a generated atlas | bark -> decimate, unwrap, bake albedo/normal/ORM |
       LOD1..n -> decimate bark further, keep fraction of leaves, scale up | impostor -> render 2 views onto 2 quads.
All output objects are NEW; the source objects are left untouched. Returns derived specs (one per LOD).
"""
import os
import random

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import _common as C

META = {"name": "tree", "version": "2", "needs": ["bark_obj", "leaf_obj"]}

PALETTES = {
    "green":  [(0.17, 0.37, 0.06), (0.25, 0.44, 0.07), (0.32, 0.47, 0.08), (0.40, 0.44, 0.09)],
    "autumn": [(0.62, 0.22, 0.04), (0.78, 0.46, 0.07), (0.52, 0.12, 0.04), (0.66, 0.54, 0.10)],
    "sakura": [(0.96, 0.66, 0.76), (1.00, 0.78, 0.85), (0.90, 0.52, 0.68), (1.00, 0.86, 0.90)],
    "gold":   [(0.98, 0.80, 0.18), (1.00, 0.88, 0.30), (0.90, 0.66, 0.10), (0.95, 0.74, 0.22)],
}


# --------------------------------------------------------------------------- leaf atlas
def _smooth_noise(n, rng):
    a = rng.random((n // 16 + 2, n // 16 + 2))
    a = np.kron(a, np.ones((16, 16)))[:n, :n]
    for _ in range(3):
        a = (a + np.roll(a, 4, 0) + np.roll(a, 4, 1) + np.roll(a, -4, 0) + np.roll(a, -4, 1)) / 5
    return a


def make_leaf_atlas(path, palette, cell=512, seed=3):
    """2x2 atlas: four colour variants of an ovate leaf with veins; RGB bled past the edge to avoid dark halos."""
    rng = np.random.default_rng(seed)
    n = cell * 2
    rgba = np.zeros((n, n, 4), dtype=np.float32)
    ys, xs = np.mgrid[0:cell, 0:cell].astype(np.float32)
    t = (ys + 0.5) / cell
    x = (xs + 0.5) / cell - 0.5
    wprof = (np.sin(np.pi * np.clip(t, 0, 1) ** 0.75) ** 0.85) * (1 - 0.15 * t)
    half = 0.5 * wprof
    alpha = np.clip((half - np.abs(x)) * cell + 0.5, 0, 1)
    xn = x / np.maximum(half, 1e-3)
    phase = t * 9.0 - np.abs(xn) * 2.4
    side = (1.0 - np.clip(np.abs((phase % 1.0) - 0.5) / 0.05, 0, 1)) * np.clip(1.0 - np.abs(xn) * 0.6, 0, 1) * 0.55
    mid = np.clip(1.0 - np.abs(x) / (0.012 + 0.012 * (1 - t)), 0, 1)
    veins = np.clip(side + mid * 0.9, 0, 1)
    edge = np.clip(np.abs(xn), 0, 1) ** 3
    for i, col in enumerate(palette[:4]):
        base = np.array(col, dtype=np.float32)
        tip = np.clip(base * np.array([1.35, 1.15, 0.8]) + 0.02, 0, 1)
        nz = _smooth_noise(cell, rng)
        k = np.clip(t ** 2 * 0.6 + (nz - 0.5) * 0.5, 0, 1)[..., None]
        rgb = base * (1 - k) + tip * k
        rgb = np.clip(rgb * (1.0 + 0.35 * veins[..., None]) * (1.0 - 0.25 * edge[..., None]), 0, 1)
        cx, cy = (i % 2) * cell, (i // 2) * cell
        rgba[cy:cy + cell, cx:cx + cell, :3] = rgb
        rgba[cy:cy + cell, cx:cx + cell, 3] = alpha
    img = bpy.data.images.new(os.path.basename(path), n, n, alpha=True)
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    return img


# --------------------------------------------------------------------------- leaves -> cards
def leaf_islands(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    seen = [False] * len(bm.verts)
    islands = []
    for v in bm.verts:
        if seen[v.index]:
            continue
        seen[v.index] = True
        stack, comp = [v], []
        while stack:
            x = stack.pop()
            comp.append(x.index)
            for e in x.link_edges:
                y = e.other_vert(x)
                if not seen[y.index]:
                    seen[y.index] = True
                    stack.append(y)
        islands.append(sorted(comp))
    return bm, islands


def build_cards(src_obj, name, keep, scale, seed, bend=0.65):
    rng = random.Random(seed)
    bm_src, islands = leaf_islands(src_obj.data)
    bases = [bm_src.verts[i[0]].co for i in islands]
    ctr = sum(bases, Vector()) / max(len(bases), 1)
    zs = [b.z for b in bases]
    ctr.z = min(zs) + 0.45 * (max(zs) - min(zs))
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    normals = {}
    corner_uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
    for comp in islands:
        if keep < 1.0 and rng.random() > keep:
            continue
        pts = [bm_src.verts[i].co for i in comp]
        if len(pts) < 3:
            continue
        base = pts[0]
        far = max(pts, key=lambda p: (p - base).length)
        L = (far - base).length
        if L < 1e-5:
            continue
        u = (far - base) / L
        nrm = sum((bm_src.verts[i].normal for i in comp), Vector())
        w = u.cross(nrm)
        if w.length < 1e-6:
            continue
        w.normalize()
        half = max(abs((p - base).dot(w)) for p in pts) * 1.12 * scale
        L *= scale
        c = [base - w * half, base + w * half, base + u * L + w * half, base + u * L - w * half]
        order = [0, 1, 2, 3]
        if (c[1] - c[0]).cross(c[2] - c[0]).dot(nrm) < 0:
            order = [3, 2, 1, 0]
        var = rng.randrange(4)
        cx, cy = (var % 2) * 0.5, (var // 2) * 0.5
        verts = [bm.verts.new(c[k]) for k in order]
        face = bm.faces.new(verts)
        for lp, k in zip(face.loops, order):
            uu, vv = corner_uv[k]
            lp[uvl].uv = (cx + 0.5 * (0.02 + 0.96 * uu), cy + 0.5 * (0.02 + 0.96 * vv))
        fn = face.normal.copy()
        for v, k in zip(verts, order):
            radial = c[k] - ctr
            radial = radial.normalized() if radial.length > 1e-6 else fn
            fn_use = -fn if radial.dot(fn) < 0 else fn
            normals[v.index] = (fn_use * (1 - bend) + radial * bend).normalized()
    bm_src.free()
    bm.verts.ensure_lookup_table()
    me = bpy.data.meshes.new(name)
    nlist = [normals[v.index] for v in bm.verts]
    bm.to_mesh(me)
    bm.free()
    try:
        me.normals_split_custom_set_from_vertices(nlist)
    except Exception as exc:
        print("custom normals unavailable:", exc)
    return me


def alpha_cut_material(name, image, roughness=0.55):
    """Cutout material. glTF alphaMode is read from the NODE GRAPH (Blender 5.x): alpha -> Round -> Alpha == MASK."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    clip = nt.nodes.new("ShaderNodeMath")
    clip.operation = "ROUND"
    nt.links.new(tex.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], clip.inputs[0])
    nt.links.new(clip.outputs["Value"], b.inputs["Alpha"])
    b.inputs["Roughness"].default_value = roughness
    m.use_backface_culling = False
    try:
        m.surface_render_method = "DITHERED"
    except Exception:
        pass
    return m


# --------------------------------------------------------------------------- impostor
def _world_bounds(objs):
    lo = Vector((1e9,) * 3)
    hi = Vector((-1e9,) * 3)
    for o in objs:
        for c in o.bound_box:
            p = o.matrix_world @ Vector(c)
            lo = Vector((min(lo.x, p.x), min(lo.y, p.y), min(lo.z, p.z)))
            hi = Vector((max(hi.x, p.x), max(hi.y, p.y), max(hi.z, p.z)))
    return lo, hi


def render_impostor_views(objs, tex_dir, base, px):
    """Render front (+Y) and side (-X) orthographic views with transparent background; returns (png paths, ortho size, centre)."""
    import math
    bpy.context.view_layer.update()          # new parented objects need a refreshed matrix_world
    sc = bpy.context.scene
    keep = set(objs)
    saved = {o: o.hide_render for o in sc.objects}
    for o in sc.objects:
        o.hide_render = o not in keep
    lo, hi = _world_bounds(objs)
    ctr = (lo + hi) / 2
    size = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z) * 1.06
    prev = (sc.render.engine, sc.camera, sc.world, sc.render.film_transparent, sc.render.resolution_x,
            sc.render.resolution_y, sc.render.resolution_percentage, sc.render.filepath)
    cd = bpy.data.cameras.new("_imp_cam"); cd.type = "ORTHO"; cd.ortho_scale = size
    cam = bpy.data.objects.new("_imp_cam", cd); sc.collection.objects.link(cam)
    sd = bpy.data.lights.new("_imp_sun", "SUN"); sd.energy = 3.0; sd.angle = math.radians(20)
    sun = bpy.data.objects.new("_imp_sun", sd); sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), 0, math.radians(35))
    w = bpy.data.worlds.new("_imp_world"); w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.8, 0.85, 0.95, 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.1
    sc.world = w
    sc.camera = cam
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.film_transparent = True
    sc.render.resolution_x = sc.render.resolution_y = px
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    paths = []
    try:
        for tag, loc, rot in (("front", (ctr.x, ctr.y - 40, ctr.z), (math.radians(90), 0, 0)),
                              ("side", (ctr.x + 40, ctr.y, ctr.z), (math.radians(90), 0, math.radians(90)))):
            cam.location, cam.rotation_euler = loc, rot
            p = os.path.join(tex_dir, f"{base}_impostor_{tag}.png")
            sc.render.filepath = p
            bpy.ops.render.render(write_still=True)
            paths.append(p)
    finally:
        sc.render.engine, sc.camera, sc.world, sc.render.film_transparent = prev[0], prev[1], prev[2], prev[3]
        sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage, sc.render.filepath = prev[4:]
        for o, h in saved.items():
            o.hide_render = h
        for ob in (cam, sun):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.cameras.remove(cd); bpy.data.lights.remove(sd); bpy.data.worlds.remove(w)
    return paths, size, ctr


def build_impostor(name, objs, root, coll, tex_dir, px, parent_matrix_basis, parent_inverse):
    paths, size, ctr_w = render_impostor_views(objs, tex_dir, name, px)
    imgs = []
    for p in paths:
        im = bpy.data.images.load(p)
        a = np.empty(px * px * 4, dtype=np.float32)
        im.pixels.foreach_get(a)
        imgs.append(a.reshape(px, px, 4))
        bpy.data.images.remove(im)
    atlas = np.concatenate(imgs, axis=1)           # 2px wide x px tall
    # bleed RGB into transparent texels to avoid dark fringes under alpha-test / mips
    rgb, al = atlas[..., :3], atlas[..., 3:]
    for _ in range(4):
        m = (al[..., 0] > 0.01)[..., None]
        blur = (np.roll(rgb, 1, 0) + np.roll(rgb, -1, 0) + np.roll(rgb, 1, 1) + np.roll(rgb, -1, 1)) / 4
        rgb = np.where(m, rgb, blur)
    atlas[..., :3] = rgb
    img = bpy.data.images.new(f"{name}_impostor", px * 2, px, alpha=True)
    img.pixels.foreach_set(atlas.ravel())
    img.filepath_raw = os.path.join(tex_dir, f"{name}_impostor.png")
    img.file_format = "PNG"
    img.save()
    # centre in asset-local space (root removed)
    ctr = ctr_w - (root.matrix_world.translation if root is not None else Vector())
    h = size / 2
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    quads = (
        # front card: in XZ plane, faces -Y
        ([(-h, 0, -h), (h, 0, -h), (h, 0, h), (-h, 0, h)], 0.0),
        # side card: in YZ plane, faces +X
        ([(0, h, -h), (0, -h, -h), (0, -h, h), (0, h, h)], 0.5),
    )
    for corners, u0 in quads:
        vs = [bm.verts.new(ctr + Vector(c)) for c in corners]
        f = bm.faces.new(vs)
        for lp, uv in zip(f.loops, [(0, 0), (1, 0), (1, 1), (0, 1)]):
            lp[uvl].uv = (u0 + 0.5 * uv[0], uv[1])
    me = bpy.data.meshes.new(f"{name}_Impostor")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(alpha_cut_material(f"{name}_impostor_mat", img, roughness=1.0))
    ob = bpy.data.objects.new(f"{name}_Impostor", me)
    coll.objects.link(ob)
    if root is not None:
        ob.parent = root
        ob.matrix_parent_inverse = parent_inverse.copy()
    ob.matrix_basis = parent_matrix_basis.copy()
    return ob


# --------------------------------------------------------------------------- recipe entry
def build(spec, out_dir):
    cfg = spec["recipe_cfg"]
    name = spec["name"]
    tex_dir = os.path.join(out_dir, "textures")
    os.makedirs(tex_dir, exist_ok=True)
    bark_src = bpy.data.objects[cfg["bark_obj"]]
    leaf_src = bpy.data.objects[cfg["leaf_obj"]]
    root = bpy.data.objects.get(spec.get("root_object", ""))
    px = cfg.get("tex_px", 2048)

    coll = bpy.data.collections.get(f"{name}_game") or bpy.data.collections.new(f"{name}_game")
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)

    atlas = make_leaf_atlas(os.path.join(tex_dir, f"{name}_leaves.png"), PALETTES[cfg.get("leaf_palette", "green")])
    leaf_mat = alpha_cut_material(f"{name}_leaf_mat", atlas)

    lods = cfg["lods"]
    bark_me0 = C.decimate_mesh(bark_src.data, lods[0]["bark_tris"], f"{name}_LOD0_Bark")
    derived, lod0_objs, bark_mat = [], [], None
    for li, lod in enumerate(lods):
        tag = lod["name"]
        bark_me = bark_me0 if li == 0 else C.decimate_mesh(bark_me0, lod["bark_tris"], f"{name}_{tag}_Bark")
        bark_ob = bpy.data.objects.new(f"{name}_{tag}_Bark", bark_me)
        leaf_me = build_cards(leaf_src, f"{name}_{tag}_Leaves", lod.get("leaf_keep", 1.0), lod.get("leaf_scale", 1.0), seed=100 + li)
        leaf_ob = bpy.data.objects.new(f"{name}_{tag}_Leaves", leaf_me)
        for ob in (bark_ob, leaf_ob):
            coll.objects.link(ob)
            if root is not None:
                ob.parent = root
                ob.matrix_parent_inverse = bark_src.matrix_parent_inverse.copy()
            ob.matrix_basis = bark_src.matrix_basis.copy()
        leaf_me.materials.append(leaf_mat)
        if li == 0:
            C.unwrap(bark_ob)
            maps = C.bake_pbr(bark_ob, bark_src.data.materials[0], px, tex_dir, f"{name}_bark")
            bark_mat = C.pbr_material(f"{name}_bark_mat", maps)
            lod0_objs = [bark_ob, leaf_ob]
        bark_me.materials.clear()
        bark_me.materials.append(bark_mat)
        derived.append({
            "name": f"{name}_{tag}", "type": spec["type"], "root_object": spec.get("root_object"),
            "include_objects": [bark_ob.name, leaf_ob.name],
            "budgets": {**spec.get("budgets", {}), "max_tris": lod["max_tris"]},
            "rules": spec.get("rules", {}), "export": spec.get("export", {}), "lod": tag,
        })
    imp = cfg.get("impostor")
    if imp:
        ob = build_impostor(name, lod0_objs, root, coll, tex_dir, imp.get("px", 1024),
                            bark_src.matrix_basis, bark_src.matrix_parent_inverse)
        derived.append({
            "name": f"{name}_{imp['name']}", "type": spec["type"], "root_object": spec.get("root_object"),
            "include_objects": [ob.name],
            "budgets": {**spec.get("budgets", {}), "max_tris": imp.get("max_tris", 20), "max_materials": 1},
            "rules": {**spec.get("rules", {}), "origin_tolerance": 1.0},
            "export": spec.get("export", {}), "lod": imp["name"],
        })
    return derived
