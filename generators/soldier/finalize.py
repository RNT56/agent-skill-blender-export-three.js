"""Stage `finalize`: what an engine draws at each distance, the game's textures, the side files, the fixture and the spec.

  near   <Unit>_<Body>_LOD0   one complete body per body armour and one without any (18,000 triangles each) + the kit's own nodes
  mid    <Unit>_<Body>_LOD1   the body decimated (the lent armour's with its banner in it) + the same hat / spear nodes
  far    <Unit>_Far_<Body>_<Head>   body and hat (and banner) in ONE mesh per combination: the game's default zoom, where a crowd is. Under a hat the hair knot
                                    is cut away (an engine shrinks its bone at the nearer levels). Spears stay their own nodes at every distance.
  textures   the 4096 sources -> albedo 4096 JPEG, normal and ORM 2048 PNG: plain images, so the engine builds mip maps (a single-level KTX2 of cloth sparkles)
  side files <unit>_team.png (the house's colour), <unit>_cloth.json (wind chains), <unit>_emblems.png / .json (crests + the banner's cloth region)

    blender -b --factory-startup -P generators/soldier_unit.py -- --unit ashigaru --stage finalize --work <dir>   -> fixtures/<asset>.blend, specs/<asset>.json, out/<asset>_tex/
"""
import json
import os
import shutil

import bmesh
import bpy
import numpy as np

from samurai import emblems, finalize as SF
from villager import qa

from . import assemble as AS

LOD1_TRIS, FAR_TRIS = 6000, 2400
ALBEDO_PX, DATA_PX = 4096, 2048
HEADS = (("Bare", None), ("Jingasa", "Helmet_Jingasa"), ("Tetsu", "Helmet_Tetsu"))


def tris(o):
    return sum(len(p.vertices) - 2 for p in o.data.polygons)


def clean(ob):
    """no zero-area faces, no loose geometry (the gate refuses them)"""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
    dead = [f for f in bm.faces if f.calc_area() < 1e-10]
    if dead:
        bmesh.ops.delete(bm, geom=dead, context="FACES")
    wire = [e for e in bm.edges if not e.link_faces]
    if wire:
        bmesh.ops.delete(bm, geom=wire, context="EDGES")
    loose = [v for v in bm.verts if not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def without_bone(src, bone, coll, thr=0.5):
    """a copy of `src` without the vertices that hang on `bone` (the hair knot under a hat)"""
    ob = src.copy()
    ob.data = src.data.copy()
    coll.objects.link(ob)
    idx = {g.index for g in ob.vertex_groups if g.name == bone}
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    dl = bm.verts.layers.deform.verify()
    dead = [v for v in bm.verts if sum(w for g, w in v[dl].items() if g in idx) > thr]
    bmesh.ops.delete(bm, geom=dead, context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def game_textures(mat, tex, unit, sc, log=print):
    """the 4096 sources on disk -> the images the GLB carries"""
    out = {}
    for k, px, fmt, ext in (("albedo", ALBEDO_PX, "JPEG", "jpg"), ("normal", DATA_PX, "PNG", "png"), ("orm", DATA_PX, "PNG", "png")):
        a = AS._load_px(os.path.join(tex, f"{unit}_{k}_src.png"))
        n = a.shape[0]
        f = n // px
        if f > 1:
            c = a[..., :3].astype(np.float64)
            if k == "albedo":
                c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
            c = c.reshape(px, f, px, f, 3).mean(axis=(1, 3))
            if k == "albedo":
                c = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.maximum(c, 1e-8), 1 / 2.4) - 0.055)
            if k == "normal":
                v = c * 2 - 1
                v /= np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6)
                c = v * 0.5 + 0.5
            a = np.ones((px, px, 4), dtype=np.float32)
            a[..., :3] = np.clip(c, 0, 1)
        g = bpy.data.images.new(f"{unit}_{k}_game", px, px, alpha=False)
        g.colorspace_settings.name = "sRGB" if k == "albedo" else "Non-Color"
        g.pixels.foreach_set(np.ascontiguousarray(a, dtype=np.float32).ravel())
        path = os.path.join(tex, f"{unit}_{k}.{ext}")
        g.filepath_raw = path
        g.file_format = fmt
        if fmt == "JPEG":
            sc.render.image_settings.quality = 92
        g.save()
        g.filepath = path
        g.reload()
        g.name = f"{unit}_{k}"
        out[k] = g
        log(f"  texture {k}: {px} px {fmt}, {os.path.getsize(path) / 1e6:.1f} MB")
        del a
    for node in mat.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None:
            to = node.outputs["Color"].links[0].to_node.type if node.outputs["Color"].links else ""
            key = "albedo" if to == "BSDF_PRINCIPLED" else "normal" if to == "NORMAL_MAP" else "orm"
            old = node.image
            node.image = out[key]
            if old.users == 0:
                bpy.data.images.remove(old)
    return out


def spec_for(cfg, clips, bodies, tex_rel):
    unit, asset = cfg["unit"], cfg["asset"]
    names = list(clips)
    return {
        "name": asset, "type": "character", "recipe": "character", "source_blend": f"fixtures/{asset}.blend", "preview": False,
        "budgets": {"max_tris": 112000, "max_materials": 1, "max_texture_px": ALBEDO_PX, "max_file_mb": 32},
        "lod_budgets": {"LOD0": 18200 * len(bodies), "LOD1": (LOD1_TRIS + 300) * len(bodies)},
        "rules": {"origin_tolerance": 0.05, "allow_non_manifold": True}, "recipe_cfg": {"collection": f"{unit}_game"},
        "character": {"max_bones": 64, "max_influences": 4, "clips": {n: {"loop": bool(clips[n])} for n in names},
                      "team_mask": f"{tex_rel}/{unit}_team.png", "cloth": {"json": f"{tex_rel}/{unit}_cloth.json"},
                      "emblems": {"png": f"{tex_rel}/{unit}_emblems.png", "json": f"{tex_rel}/{unit}_emblems.json"}},
        "glb_expect": {"occlusion": [f"{unit}_mat"], "joints_max": 64, "animations": names},
        "export": {"out_dir": "out", "compress": False},
    }


def run(cfg, work, A=None, rel=lambda p: p, log=print):
    unit, asset = cfg["unit"], cfg["asset"]
    U = unit.capitalize()
    bpy.ops.wm.open_mainfile(filepath=os.path.join(work, unit, "anim.blend"))
    sc = bpy.context.scene
    sc.render.fps = 30
    sc.render.fps_base = 1.0
    with open(os.path.join(work, unit, "assembled.json")) as fh:
        facts = json.load(fh)
    arm = bpy.data.objects[f"{U}Rig"]
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()
    mat = bpy.data.materials[f"{unit}_mat"]
    tex = os.path.join(work, unit, "tex")
    game_textures(mat, tex, unit, sc, log)
    coll = bpy.data.collections.new(f"{unit}_game")
    sc.collection.children.link(coll)
    kit = {n: bpy.data.objects[n] for n in facts["kit"]}
    made = {}
    for key, node in facts["bodies"].items():
        body = bpy.data.objects[node]
        stem = node.split("_", 1)[1]                                   # Bare / HaraAte / Okegawa
        body.name = body.data.name = f"{U}_{stem}_LOD0"
        banner = (kit["Sashimono"],) if cfg["bodies"][key].get("banner") and "Sashimono" in kit else ()
        l1 = SF.decimate_copy(body, f"{U}_{stem}_LOD1", LOD1_TRIS - sum(tris(b) for b in banner), arm, coll, extras=banner)
        SF.limit_influences(l1, 4)
        made[body.name], made[l1.name] = body, l1
        bald = without_bone(body, "topknot", coll)
        for hkey, hnode in HEADS:
            if hnode and hnode not in kit:
                continue
            pre = tuple([kit[hnode]] if hnode else []) + banner
            far = SF.decimate_copy(bald if hnode else body, f"{U}_Far_{stem}_{hkey}", FAR_TRIS, arm, coll, extras=pre)
            SF.limit_influences(far, 4)
            made[far.name] = far
        me = bald.data
        bpy.data.objects.remove(bald, do_unlink=True)
        bpy.data.meshes.remove(me)
    objs = list(made.values()) + list(kit.values())
    for o in [arm] + objs:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
        if o.type == "MESH":
            clean(o)
            if not o.data.materials:
                o.data.materials.append(mat)
            for p in o.data.polygons:
                p.use_smooth = True
    bpy.context.view_layer.update()
    report = {"tris": {}, "weights": {}}
    for o in objs:
        n, bad, mx = SF.weight_report(o)
        report["tris"][o.name] = tris(o)
        report["weights"][o.name] = [n, bad, mx]
        assert bad == 0 and mx <= 4, f"{o.name}: {bad} unweighted vertices, {mx} influences"
    report["tris_total"] = sum(report["tris"].values())
    report["bones"] = len(arm.data.bones)
    actions = {a.name: int(a.get("gp_loop", 0)) for a in bpy.data.actions}
    with open(os.path.join(work, unit, "clips.json")) as fh:
        order = json.load(fh)["order"]
    clips = {n: actions[n] for n in order if n in actions}
    report["clips"] = list(clips)
    # ---- side files
    emblems.write(tex, unit)
    ep = os.path.join(tex, f"{unit}_emblems.json")
    with open(ep) as fh:
        meta = json.load(fh)
    b = facts["banner"]
    y0, y1 = b["y"] - 0.004, b["y"] + 0.004
    meta["banner"] = {"blender": {"x0": round(b["x0"], 4), "w": b["w"], "z_top": round(b["z_top"], 4), "h": b["h"], "y_min": round(y0, 4), "y_max": round(y1, 4)},
                      "gltf": {"x0": round(b["x0"], 4), "w": b["w"], "y_top": round(b["z_top"], 4), "h": b["h"], "z_min": round(-y1, 4), "z_max": round(-y0, 4)}}
    with open(ep, "w") as fh:
        json.dump(meta, fh, indent=2)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tex_rel = f"out/{asset}_tex"
    out = os.path.join(root, tex_rel)
    os.makedirs(out, exist_ok=True)
    for f in (f"{unit}_team.png", f"{unit}_cloth.json", f"{unit}_emblems.png", f"{unit}_emblems.json", f"{unit}_albedo.jpg", f"{unit}_normal.png", f"{unit}_orm.png"):
        shutil.copyfile(os.path.join(tex, f), os.path.join(out, f))
    sp = spec_for(cfg, clips, facts["bodies"], tex_rel)
    with open(os.path.join(root, "specs", asset + ".json"), "w") as fh:
        json.dump(sp, fh, indent=1)
    # ---- QA: the three distances of each body, side by side
    qd = os.path.join(work, unit, "qa")
    paths = []
    for stem in [n.split("_", 1)[1] for n in facts["bodies"].values()]:
        trio = [made[f"{U}_{stem}_LOD0"], made[f"{U}_{stem}_LOD1"], made.get(f"{U}_Far_{stem}_Jingasa") or made[f"{U}_Far_{stem}_Bare"]]
        for i, o in enumerate(trio):
            o.location.x = (i - 1) * 1.15
        bpy.context.view_layer.update()
        paths += qa.shots(trio, os.path.join(qd, f"final_{stem}"), views=("front", "q"), size=1300, span=3.3, focus=(0, 0, 1.05))
        for o in trio:
            o.location.x = 0
    bpy.context.view_layer.update()
    qa.sheet(paths, os.path.join(qd, "final_sheet.jpg"), cols=2)
    for p in paths:
        os.remove(p)
    with open(os.path.join(work, unit, "final.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    bpy.ops.file.pack_all()
    save = os.path.join(root, "fixtures", asset + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=save, compress=True)
    log("FINAL " + json.dumps({"tris_total": report["tris_total"], "bones": report["bones"], "clips": report["clips"], "tris": report["tris"]}))
    return report
