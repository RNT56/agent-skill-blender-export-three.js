"""Stage 6: make it a game asset. The prop strip of the atlas is painted, the tint mask is derived, LOD1 / LOD2 are cut, everything goes into
one collection (`villager_game`) with ONE material, and the fixture is saved for the gate (recipe `character`).

The mask (`villager_team.png`, the body's UVs): R = the jacket, which the engine dyes per trade; G = the contents of a carried basket, tinted by
the good. The jacket is found without painting: the bake stage kept a POSITION map, so a texel knows where on the body it is, and its colour
says whether it is hemp, skin, belt or indigo. Patches and mends stay undyed on purpose.
"""
import json
import os

import bpy
import numpy as np

from samurai import finalize as SF

from . import lowpoly, props as P, qa

LOD_TRIS = {1: 3600, 2: 1150}
GAME_PX = 1024


def _px(img):
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def _box(a, r):
    """box mean over (2r+1)^2 via an integral image"""
    p = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    k = 2 * r + 1
    h, w = a.shape
    return (c[k:k + h, k:k + w] - c[:h, k:k + w] - c[k:k + h, :w] + c[:h, :w]) / (k * k)


def jacket_mask(alb, pos, log=print, scale=1.0, wrist_z=0.92, hand_x=0.36):
    """alb: h x w x 3 display values; pos: h x w x 3 packed positions. -> h x w float mask of the jacket.
    scale = this body's height / the reference's (the heights below are the reference body's); wrist_z, hand_x: where its hands are."""
    x = (pos[..., 0].astype(np.float32) - 0.5) * 2
    y = (pos[..., 1].astype(np.float32) - 0.5) * 2
    z = pos[..., 2].astype(np.float32) * 2 / scale
    zr = pos[..., 2].astype(np.float32) * 2
    covered = (pos[..., 2] > 1e-4)
    s = alb.sum(-1) + 1e-5
    feat = np.stack([alb[..., 0] / s, alb[..., 1] / s, alb.max(-1) * 0.35], -1)        # chroma + a little of the value

    def ref(m):
        m = m & covered
        return np.median(feat[m], axis=0) if m.sum() > 50 else None
    refs = {
        "hemp": ref((z > 1.05) & (z < 1.28) & (np.abs(x) < 0.12) & (y > 0.04)),          # the back panel
        "skin": ref((np.abs(x) > hand_x) & (zr > wrist_z - 0.12) & (zr < wrist_z + 0.01)),   # wrists and hands
        "indigo": ref((z > 0.52) & (z < 0.72)),                                           # the trousers
    }
    names = [k for k, v in refs.items() if v is not None]
    d = np.stack([np.linalg.norm(feat - refs[k], axis=-1) for k in names], -1)
    cls = d.argmin(-1)
    hemp = (cls == names.index("hemp")) & covered & (z > 0.74) & (z < 1.475) & (alb.max(-1) > 0.27)
    m = hemp.astype(np.float32)
    cov = covered.astype(np.float32)
    for _ in range(2):                                                                    # majority filter inside the covered area: no speckle, creases stay dyed
        num, den = _box(m * cov, 3), _box(cov, 3)
        m = ((num / np.maximum(den, 1e-4)) > 0.5).astype(np.float32) * cov
    # bleed into the gutters (bilinear filtering at island borders must not fade the dye) and soften the edge by a texel
    for _ in range(10):
        num, den = _box(m * cov, 1), _box(cov, 1)
        grow = (cov < 0.5) & (den > 0)
        m = np.where(grow, num / np.maximum(den, 1e-4), m)
        cov = np.where(grow, 1.0, cov)
    m = _box(m, 1)
    log(f"  jacket mask: {float((m > 0.5).mean()) * 100:.1f}% of the atlas; references " + json.dumps({k: [round(float(c), 3) for c in refs[k]] for k in names}))
    return m, {k: refs[k] for k in names}


def run(work, save_path, cfg=None, log=print):
    from . import variants
    cfg = cfg or variants.get("villager_unit_01")
    bpy.ops.wm.open_mainfile(filepath=os.path.join(work, "villager_anim.blend"))
    sc = bpy.context.scene
    sc.render.fps = 30
    arm = bpy.data.objects["VillagerRig"]
    low = bpy.data.objects["Villager_LOD0"]
    mat = low.data.materials[0]
    for m in list(bpy.data.materials):                       # earlier stages left a material of the same name behind: this one is THE material
        if m != mat and m.name.split(".")[0] == "villager_mat":
            bpy.data.materials.remove(m)
    mat.name = "villager_mat"
    tex = os.path.join(work, "tex")
    imgs = {}
    for node in mat.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None:
            to = node.outputs["Color"].links[0].to_node.type if node.outputs["Color"].links else ""
            imgs["albedo" if to == "BSDF_PRINCIPLED" else "normal" if to == "NORMAL_MAP" else "orm"] = node.image
    assert set(imgs) == {"albedo", "normal", "orm"}, imgs
    for k, img in imgs.items():
        img.name = f"villager_{k}"
    px = imgs["albedo"].size[0]
    arr = {k: _px(v).copy() for k, v in imgs.items()}
    pos = np.load(os.path.join(tex, "villager_pos.npy"))
    covered = pos[..., 2] > 1e-4
    # the body band: nothing of the body may reach into the strip
    strip_rows = int(px * P.STRIP_V)
    assert not covered[:strip_rows - 2].any(), "body texels inside the prop strip"
    # a jacket the engine can dye: measure it, then paint the strip
    with open(os.path.join(work, "hands.json")) as fh:
        hands = json.load(fh)
    wz = (hands["L"]["wrist"][2] + hands["R"]["wrist"][2]) * 0.5
    wx = (abs(hands["L"]["wrist"][0]) + abs(hands["R"]["wrist"][0])) * 0.5
    jm, refs = jacket_mask(arr["albedo"][..., :3], pos, log, scale=cfg["height"] / variants.REF["height"], wrist_z=wz, hand_x=wx - 0.05)
    # every body's undyed jacket is brought to the same brightness (the engine's dye scales by it: villager_logic.js TUNIC_BASE_LUM)
    JACKET_LUM = 0.339
    a3 = arr["albedo"][..., :3]
    lin0 = np.where(a3 <= 0.04045, a3 / 12.92, ((a3 + 0.055) / 1.055) ** 2.4)
    lum0 = float((lin0[jm > 0.5] @ np.array([0.2126, 0.7152, 0.0722])).mean())
    gain = JACKET_LUM / max(lum0, 1e-4)
    if abs(gain - 1.0) > 0.03:
        w = np.clip(jm, 0, 1)[..., None]
        lin1 = lin0 * (1 + (gain - 1) * w)
        arr["albedo"][..., :3] = np.clip(np.where(lin1 <= 0.0031308, lin1 * 12.92, 1.055 * np.power(np.maximum(lin1, 1e-8), 1 / 2.4) - 0.055), 0, 1)
        log(f"  jacket brightness {lum0:.3f} -> {JACKET_LUM} (gain {gain:.2f})")
    arr["normal"][:strip_rows, :, :3] = (0.5, 0.5, 1.0)
    arr["orm"][:strip_rows, :, :3] = (1.0, 0.9, 0.0)
    gm = P.paint_strip(arr["albedo"], arr["normal"], arr["orm"], px)
    jm[:strip_rows] = 0.0
    # ---- the game's textures: half the bake's size (GAME_PX), written as plain JPEG / PNG so the engine builds MIP MAPS for them.
    # Hemp weave is all high frequency: as a single-level KTX2 (Blender's encoder writes no mips) it sparkled at RTS distance; averaged down
    # and mip-mapped it reads as cloth. A villager is at most ~150 px tall on screen: 1024 is still 2 to 3 texels per pixel up close.
    def down(a, kind):
        f = px // GAME_PX
        if f == 1:
            return a
        c = a[..., :3]
        if kind == "albedo":
            c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        c = c.reshape(GAME_PX, f, GAME_PX, f, 3).mean(axis=(1, 3))
        if kind == "albedo":
            c = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.maximum(c, 1e-8), 1 / 2.4) - 0.055)
        if kind == "normal":
            n = c * 2 - 1
            n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
            c = n * 0.5 + 0.5
        out = np.ones((GAME_PX, GAME_PX, 4), dtype=np.float32)
        out[..., :3] = np.clip(c, 0, 1)
        return out
    for k, img in list(imgs.items()):
        img.pixels.foreach_set(arr[k].ravel())               # the full-size source stays on disk next to the bake
        img.filepath_raw = os.path.join(tex, f"villager_{k}_src.png")
        img.file_format = "PNG"
        img.save()
        ext, fmt = ("jpg", "JPEG") if k == "albedo" else ("png", "PNG")
        g = bpy.data.images.new(f"villager_{k}_game", GAME_PX, GAME_PX, alpha=False)
        g.colorspace_settings.name = img.colorspace_settings.name
        g.pixels.foreach_set(down(arr[k], k).ravel())
        g.filepath_raw = os.path.join(tex, f"villager_{k}.{ext}")
        g.file_format = fmt
        if fmt == "JPEG":
            sc.render.image_settings.quality = 93
        g.save()
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image == img:
                node.image = g
        bpy.data.images.remove(img)
        g.name = f"villager_{k}"
        g.filepath = os.path.join(tex, f"villager_{k}.{ext}")
        g.reload()
        imgs[k] = g
    k = 2
    half = px // k
    tm = np.zeros((half, half, 4), dtype=np.float32)
    tm[..., 0] = jm.reshape(half, k, half, k).mean(axis=(1, 3))
    tm[..., 1] = gm.reshape(half, k, half, k).mean(axis=(1, 3))
    tm[..., 3] = 1.0
    timg = bpy.data.images.new("villager_team", half, half, alpha=False)
    timg.colorspace_settings.name = "Non-Color"
    timg.pixels.foreach_set(tm.ravel())
    timg.filepath_raw = os.path.join(tex, "villager_team.png")
    timg.file_format = "PNG"
    timg.save()
    bpy.data.images.remove(timg)
    lum = arr["albedo"][..., :3][jm > 0.5]
    lin = np.where(lum <= 0.04045, lum / 12.92, ((lum + 0.055) / 1.055) ** 2.4)
    jacket_lum = float((lin @ np.array([0.2126, 0.7152, 0.0722])).mean())
    # ---- props wear the real material now
    props = [o for o in bpy.data.objects if o.type == "MESH" and o.name.split("_")[0] in ("Tool", "Load", "Hat")]
    pm = bpy.data.materials.get("props_preview")
    for o in props:
        o.data.materials.clear()
        o.data.materials.append(mat)
    if pm:
        bpy.data.materials.remove(pm)
    # ---- LODs (skin weights kept, at most 4 influences)
    coll = bpy.data.collections.new("villager_game")
    sc.collection.children.link(coll)
    lods = {0: low}
    for n, tris in LOD_TRIS.items():
        lods[n] = SF.decimate_copy(low, f"Villager_LOD{n}", tris, arm, coll)
    for o in [arm, low] + props:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    bpy.context.view_layer.update()
    report = {"tris": {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in list(lods.values()) + props},
              "bones": len(arm.data.bones), "clips": sorted(a.name for a in bpy.data.actions), "jacket_linear_luminance": round(jacket_lum, 4),
              "weights": {o.name: SF.weight_report(o) for o in lods.values()}}
    report["tris_total"] = sum(report["tris"].values())
    log("  final " + json.dumps(report))
    # ---- QA: the LODs side by side, and the dressed figure
    for i, o in lods.items():
        o.location.x = i * 0.9
    bpy.context.view_layer.update()
    paths = qa.shots(list(lods.values()), os.path.join(work, "qa", "final_lods"), views=("front", "q"), size=1200, span=2.2, focus=(0.9, 0, 0.9))
    for o in lods.values():
        o.location.x = 0
    bpy.context.view_layer.update()
    dress = [low, bpy.data.objects["Hat_kasa"], bpy.data.objects["Tool_kuwa"]]
    paths += qa.shots(dress, os.path.join(work, "qa", "final_dress"), views=("q",), size=1200, span=2.2, focus=(0, 0, 0.95))
    paths += qa.shots(dress, os.path.join(work, "qa", "final_head"), views=("q",), size=1200, span=0.7, focus=(0, 0, 1.52))
    qa.sheet(paths, os.path.join(work, "qa", "final_sheet.jpg"), cols=4)
    with open(os.path.join(work, "final.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    bpy.ops.file.pack_all()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=save_path, compress=True)
    # the side files the recipe ships next to the GLB
    out = os.path.join(os.path.dirname(os.path.dirname(save_path)), "out", variants.tex_dir(cfg["name"]))
    os.makedirs(out, exist_ok=True)
    import shutil
    for f in ("villager_team.png", "villager_albedo.jpg", "villager_normal.png", "villager_orm.png"):
        shutil.copyfile(os.path.join(tex, f), os.path.join(out, f))
    return report
