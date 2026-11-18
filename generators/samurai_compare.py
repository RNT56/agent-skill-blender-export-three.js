"""Silhouette comparison against the reference turnaround (run inside Blender):
    blender -b --factory-startup -P generators/samurai_compare.py -- [--views front,side,back] [--out out/samurai_unit_01/qa]
Renders orthographic alpha silhouettes of the rest pose (body + armour, no weapons, no banner), segments the same view from
out/samurai_unit_01/concept/concept_turnaround.png, aligns them (feet + best x shift) and prints IoU and a width-by-height profile
(mine / reference, per band) so proportion errors are numbers, not impressions. Writes an overlay PNG per view
(red = reference only, green = mine only, yellow = both)."""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from samurai import build

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(n, d=None):
    return argv[argv.index(n) + 1] if n in argv else d


OUT = os.path.join(ROOT, arg("--out", "out/samurai_unit_01/qa"))
os.makedirs(OUT, exist_ok=True)
REF = os.path.join(ROOT, "out/samurai_unit_01/concept/concept_turnaround.png")
H_PX = 960


def load_ref():
    im = bpy.data.images.load(REF)
    w, h = im.size
    a = np.empty(w * h * 4, dtype=np.float32)
    im.pixels.foreach_get(a)
    a = a.reshape(h, w, 4)[::-1, :, :3]                    # bpy is bottom-up
    bpy.data.images.remove(im)
    bg = np.median(np.concatenate([a[:60, :200].reshape(-1, 3), a[-60:, :200].reshape(-1, 3)]), axis=0)
    mask = (np.abs(a - bg).sum(axis=2) > 0.16)
    col = mask.sum(axis=0) > 20
    runs, s = [], None
    for x in range(w):
        if col[x] and s is None:
            s = x
        if not col[x] and s is not None:
            runs.append((s, x))
            s = None
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < 60:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)
    merged = [r for r in merged if r[1] - r[0] > 150]
    out = {}
    for name, (x0, x1) in zip(("front", "side", "back", "side_r"), merged):
        m = mask[:, max(0, x0 - 8):x1 + 8]
        rows = np.where(m.any(axis=1))[0]
        m = m[rows.min():rows.max() + 1]
        out[name] = m
    return out


def to_height(m, h=H_PX):
    sc = h / m.shape[0]
    ys = (np.arange(h) / sc).astype(int).clip(0, m.shape[0] - 1)
    xs = (np.arange(int(m.shape[1] * sc)) / sc).astype(int).clip(0, m.shape[1] - 1)
    return m[ys][:, xs]


def render_mask(view, cam, res_h=1200):
    sc = bpy.context.scene
    loc = {"front": (0, -9, 0.95), "side": (9, 0, 0.95), "back": (0, 9, 0.95)}[view]
    cam.location = loc
    cam.rotation_euler = (Vector((0, 0, 0.95)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = os.path.join(OUT, f"_sil_{view}.png")
    bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(sc.render.filepath)
    w, h = im.size
    a = np.empty(w * h * 4, dtype=np.float32)
    im.pixels.foreach_get(a)
    a = a.reshape(h, w, 4)[::-1, :, 3]
    bpy.data.images.remove(im)
    os.remove(sc.render.filepath)
    m = a > 0.5
    rows = np.where(m.any(axis=1))[0]
    return m[rows.min():rows.max() + 1]


def best_iou(a, b):
    """Align mask b to a (same height): brute-force x shift; returns iou, shifted b, shift."""
    h = a.shape[0]
    W = max(a.shape[1], b.shape[1]) + 120
    A = np.zeros((h, W), bool)
    A[:, 60:60 + a.shape[1]] = a
    best = (-1, None, 0)
    for dx in range(-60, 61, 2):
        B = np.zeros((h, W), bool)
        x0 = 60 + dx + (a.shape[1] - b.shape[1]) // 2
        lo, hi = max(0, x0), min(W, x0 + b.shape[1])
        if hi <= lo:
            continue
        B[:, lo:hi] = b[:, lo - x0:hi - x0]
        iou = (A & B).sum() / max((A | B).sum(), 1)
        if iou > best[0]:
            best = (iou, B, dx)
    return best[0], A, best[1]


def profile(m, bands=14):
    h = m.shape[0]
    out = []
    for i in range(bands):
        seg = m[int(h * i / bands):int(h * (i + 1) / bands)]
        out.append(float(seg.any(axis=0).sum()) if seg.size else 0.0)
    return out


def main():
    ref = load_ref()
    mdl = build.build_model("all")
    for k in ("Katana_Drawn", "Katana_Sheathed", "Katana_Saya", "Sashimono"):
        mdl[k].hide_render = True
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.resolution_x, sc.render.resolution_y = 900, 1200
    sc.display.shading.light = "FLAT"
    sc.display.shading.color_type = "SINGLE"
    cd = bpy.data.cameras.new("cmp")
    cd.type = "ORTHO"
    cd.ortho_scale = 2.4
    cam = bpy.data.objects.new("cmp", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    total = []
    print("view   IoU   (profile ratio mine/ref per height band, top -> feet)")
    for view in arg("--views", "front,side,back").split(","):
        mine = to_height(render_mask(view, cam), H_PX)
        r = to_height(ref[view], H_PX)
        iou, A, B = best_iou(r, mine)
        total.append(iou)
        pr_m, pr_r = profile(B), profile(A)
        ratios = " ".join(f"{m / max(r_, 1):4.2f}" for m, r_ in zip(pr_m, pr_r))
        print(f"{view:6s} {iou:.3f}  {ratios}")
        rgb = np.zeros(A.shape + (3,), np.float32)
        rgb[..., 0] = A
        rgb[..., 1] = B
        rgb[..., 2] = 0.0
        rgb = np.where((A & B)[..., None], np.array([1.0, 0.9, 0.1]), rgb)
        img = bpy.data.images.new("ov", A.shape[1], A.shape[0], alpha=False)
        px = np.ones(A.shape + (4,), np.float32)
        px[..., :3] = rgb[::-1]
        img.pixels.foreach_set(px.ravel())
        img.filepath_raw = os.path.join(OUT, f"silhouette_{view}.png")
        img.file_format = "PNG"
        img.save()
    print(f"MEAN IoU {sum(total) / len(total):.3f}")


main()
