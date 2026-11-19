"""Stage `assemble`: the unit's bodies and kit pieces on ONE skeleton, one material, one atlas.

  bodies     each body is its own reconstruction of the same man, rigged on its own: its joints are within a few centimetres of the base body's. Here every
             body is WARPED onto the base skeleton (each vertex moved by its bones' base-rest x own-rest^-1, blended by its weights: the joints then coincide
             exactly) and bound to the base armature. The hair knot gets a bone of its own (`topknot`): an engine shrinks it to nothing under a hat.
  skeleton   the base body's 30 body / hand bones (villager.rig) + weapon_r / weapon_r2 (one per spear, in the right fist's grip, +Y toward the point),
             pennant_1 / 2, banner_1 / 2, flag_1 / 2 / 3. Names are the ashigaru v1's, so the game's wiring (foot planting, the torso's aim, the wind on the
             cloth chains, the bamboo spear laid on `Yari`'s line) finds what it looks for.
  kit        hats seated on the skull (measured: the lowest the rim can sit with the head inside the hat's cone), the two spears built from their head pieces
             and the repeated master shaft segment, the side arm through the sash, the back banner (pole, bar, cloth) and the spear's pennant (procedural:
             they carry the house's colour and crest).
  atlas      4096: the three bodies' own 2048 bakes in three quarters, the kit in the fourth (KIT_CELLS). One material.
  team mask  everything vermilion in the references (head band, sash, sleeve ties, lacing, hat bands) + the cloth swatches. Those texels are also taken to a
             neutral cloth tone in the albedo, so a house's colour is its own hue and not a mixture with red.

    blender -b --factory-startup -P generators/soldier_unit.py -- --unit ashigaru --stage assemble --work <dir>      -> <work>/<unit>/assembled.blend, tex/, qa/
"""
import json
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from villager import ingest, qa, rig as VR

from . import props as PR

V = Vector
ATLAS = 4096
LIVERY_LUM = 0.15                      # linear luminance the livery cloth is brought to (the engine scales the house colour by it: 0.115 read washed out)
QUARTER = {"bare": (0, 2048), "levy": (2048, 2048), "okegawa": (0, 0)}            # x0, y0 px of a body's 2048 quarter (image rows run bottom-up, like v)
KIT0 = (2048, 0)
KIT_CELLS = {"jingasa": (0, 0, 768), "tetsu_jingasa": (768, 0, 768), "yari_head": (1536, 0, 512), "nagae_head": (1536, 512, 512), "tanto": (1536, 1024, 512)}
# a unit with other bodies / pieces has its own layout (run() switches to it)
LAYOUT = {
    "archer": dict(quarter={"bare": (0, 2048), "haramaki": (2048, 2048)},
                   cells={"jingasa": (0, 0, 768), "bowkit": (768, 0, 1024), "ebira": (0, 1280, 768)}),
}
CLOTH_CELL = (0, 768, 512)             # the banner's and the pennant's cloth
WOOD_CELL = (512, 768, 128)            # the banner's pole and bar
DROP_BONES = ("line", "load_shoulder", "load_front", "tool_r", "tool_l")

YARI_LEN, NAGAE_LEN = 2.30, 3.40       # butt to point (samurai-vale content/items.js)
GRIP0 = 0.80                           # where the right hand holds a spear in the rest pose, metres from the butt (ashigaru.rig.GRIP0: the clips are written for it)
PENNANT_BELOW_TIP = 0.335
PENNANT_W, PENNANT_H = 0.085, 0.235
# the back banner (archer.consts: the same cloth, pole and lean; its foot is put on THIS armour's back)
# (2026-11-19, owner: "fix ... the banner": at 0.18 x 0.44 m it read as a second pennant, and its pole stood in the iron hat's brim. A sashimono is a
#  tall narrow flag well clear of the head: the pole stands in a socket at the small of the back and leans back just enough to clear the widest hat.)
CLOTH_W, CLOTH_H, BAN_TOP, BAN_X0 = 0.30, 0.80, 2.66, 0.016
POLE_Z0, POLE_Z1, POLE_LEAN = 1.08, 2.72, 0.360          # POLE_LEAN is the least lean (m per the pole's height); assemble raises it until the hats are cleared
# a war hat rides on a pad ring, not on the skull: `drop` lifts the rim from the lowest it could sit (the brow) to the forehead, so the eyes stay free
# (2026-11-19, owner: "hat height or tilt": lifted 36 mm and tipped forward it perched on the head with daylight at the nape. Now tipped BACK, as they were worn:
#  the nape closes, the brow opens, and the lift can be small. tilt > 0 = tipped BACK (the front rim rises).)
HAT = {"jingasa": dict(node="Helmet_Jingasa", tilt=8.0, drop=0.010), "tetsu_jingasa": dict(node="Helmet_Tetsu", tilt=6.0, drop=0.014)}


def _co(me):
    a = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def _set_co(me, co):
    me.vertices.foreach_set("co", np.ascontiguousarray(co, dtype=np.float64).ravel())
    me.update()


def _uv(me):
    a = np.empty(len(me.loops) * 2, dtype=np.float64)
    me.uv_layers[0].data.foreach_get("uv", a)
    return a.reshape(-1, 2)


def _set_uv(me, a):
    me.uv_layers[0].data.foreach_set("uv", np.ascontiguousarray(a, dtype=np.float64).ravel())
    me.update()


def _load_px(path):
    im = bpy.data.images.load(path)
    w, h = im.size
    a = np.empty(w * h * 4, dtype=np.float32)
    im.pixels.foreach_get(a)
    bpy.data.images.remove(im)
    return a.reshape(h, w, 4)


def _save_px(arr, path, srgb, name):
    h, w = arr.shape[:2]
    im = bpy.data.images.new(name, w, h, alpha=False)
    im.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    im.pixels.foreach_set(np.ascontiguousarray(arr, dtype=np.float32).ravel())
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    return im


def dense_weights(ob, names):
    idx = {n: i for i, n in enumerate(names)}
    gi = {g.index: idx[g.name] for g in ob.vertex_groups if g.name in idx}
    W = np.zeros((len(ob.data.vertices), len(names)))
    for v in ob.data.vertices:
        for g in v.groups:
            j = gi.get(g.group)
            if j is not None:
                W[v.index, j] += g.weight
    return W


def append_body(path):
    with bpy.data.libraries.load(path) as (src, dst):
        dst.objects = [n for n in src.objects if n in ("Villager_LOD0", "VillagerRig")]
    mesh = next(o for o in dst.objects if o.type == "MESH")
    arm = next(o for o in dst.objects if o.type == "ARMATURE")
    for o in (mesh, arm):
        bpy.context.scene.collection.objects.link(o)
    return mesh, arm


def warp_to(ob, own, base, names, log=print):
    """move every vertex by its bones' (base rest) x (own rest)^-1: the body's joints land on the base skeleton's"""
    W = dense_weights(ob, names)
    co = _co(ob.data)
    ch = np.c_[co, np.ones(len(co))]
    out = np.zeros_like(co)
    tot = W.sum(1)
    worst = 0.0
    for j, n in enumerate(names):
        if not W[:, j].any():
            continue
        T = np.array(base.data.bones[n].matrix_local) @ np.linalg.inv(np.array(own.data.bones[n].matrix_local))
        moved = (ch @ T.T)[:, :3]
        if (W[:, j] > 0.5).any():
            worst = max(worst, float(np.linalg.norm(moved - co, axis=1)[W[:, j] > 0.5].max()))
        out += W[:, j:j + 1] * moved
    ok = tot > 1e-6
    out[ok] /= tot[ok, None]
    out[~ok] = co[~ok]
    _set_co(ob.data, out)
    log(f"  {ob.name}: warped onto the base skeleton, largest move {worst * 1000:.1f} mm")
    return W


def skull(co):
    """the head's axis, where the hair knot begins (its neck: the narrowest ring above the skull) and every vertex's distance from that axis"""
    top = float(co[:, 2].max())
    band = (co[:, 2] > top - 0.17) & (co[:, 2] < top - 0.10)
    ax = co[band][:, :2].mean(0)
    r = np.hypot(co[:, 0] - ax[0], co[:, 1] - ax[1])
    best, z_neck = 9.0, top - 0.06
    for z in np.arange(top - 0.095, top - 0.015, 0.003):
        m = np.abs(co[:, 2] - z) < 0.0035
        if m.sum() < 6:
            continue
        rr = float(np.quantile(r[m], 0.95))
        if rr < best:
            best, z_neck = rr, float(z)
    return ax, z_neck, best, r


def add_topknot(arm, bodies, log=print):
    """one bone for the hair knot of every body; returns the skull facts per body"""
    facts = {}
    for key, ob in bodies.items():
        co = _co(ob.data)
        ax, z_neck, r_neck, r = skull(co)
        facts[key] = dict(axis=[float(ax[0]), float(ax[1])], z_neck=z_neck, r_neck=r_neck, top=float(co[:, 2].max()))
    b0 = facts[next(iter(bodies))]
    zn = float(np.mean([f["z_neck"] for f in facts.values()]))
    VR.add_bone(arm, "topknot", "head", (b0["axis"][0], b0["axis"][1], zn - 0.004), (0, 0, 1), (0, -1, 0), 0.07)
    log("  hair knot: " + json.dumps({k: {a: (round(b, 4) if isinstance(b, float) else [round(x, 4) for x in b]) for a, b in f.items()} for k, f in facts.items()}))
    return facts, zn


def split_topknot(ob, W, names, f):
    co = _co(ob.data)
    r = np.hypot(co[:, 0] - f["axis"][0], co[:, 1] - f["axis"][1])
    t = np.clip((co[:, 2] - (f["z_neck"] - 0.004)) / 0.010, 0, 1) * (r < max(0.075, f["r_neck"] * 2.6))
    ih, it = names.index("head"), names.index("topknot")
    mv = W[:, ih] * t
    W[:, ih] -= mv
    W[:, it] += mv
    return int((t > 0.5).sum())


# --------------------------------------------------------------------------------------------------------------------- kit
def append_prop(work, unit, name):
    path = os.path.join(work, unit, "props", name + ".blend")
    node = "".join(w.capitalize() for w in name.split("_"))
    with bpy.data.libraries.load(path) as (src, dst):
        dst.objects = [n for n in src.objects if n == node]
    ob = dst.objects[0]
    bpy.context.scene.collection.objects.link(ob)
    with open(os.path.join(work, unit, "props", name + ".json")) as fh:
        facts = json.load(fh)
    return ob, facts


def cell_uv(ob, cell):
    cx, cy, size = cell
    uv = _uv(ob.data)
    uv[:, 0] = (KIT0[0] + cx + uv[:, 0] * size) / ATLAS
    uv[:, 1] = (KIT0[1] + cy + uv[:, 1] * size) / ATLAS
    _set_uv(ob.data, uv)
# the side arm THROUGH the sash at the left hip (2026-11-19, owner: "tanto position": 2 cm proud of the waist at 42 deg it hung in front of him like a bar).
# phi: where on the waist, degrees from straight ahead toward his left; dip: the scabbard's end drops toward the back; out: the blade's axis from the waist's
# surface (negative = sunk into the sash, which is what holds it); along: the piece slid along itself so the guard sits just ahead of the sash.
TANTO = dict(phi=58.0, dip=27.0, out=-0.004, dz=0.012, along=-0.17)


def hat_profile(ob):
    """outer radius of the hat at and above a height over its rim plane (2 mm steps)"""
    co = _co(ob.data)
    r = np.hypot(co[:, 0], co[:, 1])
    zs = np.arange(0.0, float(co[:, 2].max()) + 0.002, 0.002)
    prof = np.zeros(len(zs))
    for i, z in enumerate(zs):
        m = co[:, 2] >= z
        prof[i] = float(r[m].max()) if m.any() else 0.0
    return zs, prof


def seat_hat(ob, skulls, cfg, thickness=0.010, pad=0.006, log=print):
    """Rim height: the lowest at which every body's skull (below the hair knot) is inside the hat's cone with a pad. The hat is tipped a little forward."""
    zs, prof = hat_profile(ob)
    crown = max(s["z_neck"] for s in skulls.values())
    z_rim = crown - 0.16
    while z_rim < crown:
        ok = True
        for s in skulls.values():
            co, r = s["co"], s["r"]
            m = (co[:, 2] > z_rim + 0.004) & (co[:, 2] <= s["z_neck"] + 0.002)
            if not m.any():
                continue
            k = np.clip(((co[m, 2] - z_rim) / 0.002).astype(int), 0, len(prof) - 1)
            if (r[m] + pad > prof[k] - thickness).any():
                ok = False
                break
        if ok:
            break
        z_rim += 0.002
    z_rim += cfg.get("drop", 0.0)
    ax = np.mean([s["axis"] for s in skulls.values()], axis=0)
    M = Matrix.Translation((float(ax[0]), float(ax[1]), z_rim)) @ Matrix.Rotation(math.radians(-cfg.get("tilt", 0.0)), 4, "X")
    ob.data.transform(M)
    ob.data.update()
    log(f"  {cfg['node']}: rim at {z_rim:.3f} m ({(crown - z_rim) * 100:.1f} cm below the crown), apex {float(_co(ob.data)[:, 2].max()):.3f} m")
    return z_rim


def build_spear(ob, facts, length, G, D, N, name):
    """ob: the prop in its pole frame (head piece + master segment, attribute `master` on the segment's faces). Returns the whole spear in the rest fist."""
    me = ob.data
    L = facts["length"]
    a, b = facts["y_m0"], facts["y_cut"]
    ml = b - a
    y_butt = L - length
    bm = bmesh.new()
    bm.from_mesh(me)
    lay = bm.faces.layers.int.get("master")
    master = [f for f in bm.faces if f[lay] == 1]
    uvl = bm.loops.layers.uv.verify()
    k = 1
    while a - (k - 1) * ml > y_butt + 1e-6:
        mirror = k % 2 == 1
        vmap = {}
        for f in master:
            vs = []
            for v in f.verts:
                if v not in vmap:
                    y = (2 * a - v.co.y - (k - 1) * ml) if mirror else (v.co.y - k * ml)
                    vmap[v] = bm.verts.new((v.co.x, max(y, y_butt), v.co.z))
                vs.append(vmap[v])
            loops = list(f.loops)
            if mirror:
                vs = vs[::-1]
                loops = loops[::-1]
            if len(set(vs)) < 3:
                continue
            nf = bm.faces.new(vs)
            nf.smooth = True
            for nl, ol in zip(nf.loops, loops):
                nl[uvl].uv = ol[uvl].uv
        k += 1
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    # the butt: a cap
    ring = [v for v in bm.verts if abs(v.co.y - y_butt) < 1e-5]
    if len(ring) >= 3:
        ring.sort(key=lambda v: math.atan2(v.co.z, v.co.x))
        try:
            cap = bm.faces.new(ring)
            uvc = master[0].loops[0][uvl].uv.copy()
            for l in cap.loops:
                l[uvl].uv = uvc
        except ValueError:
            pass
    degenerate = [f for f in bm.faces if f.calc_area() < 1e-10]
    if degenerate:
        bmesh.ops.delete(bm, geom=degenerate, context="FACES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    if "master" in me.attributes:
        me.attributes.remove(me.attributes["master"])
    # into the fist: y -> D, the blade's flat (x) across the palm normal
    D = V(D).normalized()
    ex = (V(N) - D * V(N).dot(D)).normalized()
    ez = ex.cross(D)
    R = Matrix.Identity(4)
    for i in range(3):
        R[i][0], R[i][1], R[i][2] = ex[i], D[i], ez[i]
    T = Matrix.Translation(V(G) + D * (length - L - GRIP0)) @ R
    me.transform(T)
    me.update()
    ob.name = me.name = name
    return ob


def quad_grid(name, origin, du, dv, nu, nv, cell, uv0=(0.04, 0.04), uv1=(0.96, 0.96)):
    """a flat nu x nv grid from `origin` along du (u) and dv (v); UVs into the kit cell's rectangle uv0..uv1"""
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.verify()
    vs = [[bm.verts.new(V(origin) + V(du) * (i / nu) + V(dv) * (j / nv)) for i in range(nu + 1)] for j in range(nv + 1)]
    cx, cy, size = cell
    for j in range(nv):
        for i in range(nu):
            f = bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
            for l, (a, b) in zip(f.loops, ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))):
                u = uv0[0] + (uv1[0] - uv0[0]) * a / nu
                v = uv0[1] + (uv1[1] - uv0[1]) * b / nv
                l[uvl].uv = ((KIT0[0] + cx + u * size) / ATLAS, (KIT0[1] + cy + v * size) / ATLAS)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.uv_layers[0].name = "UVMap"
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def rod(name, p0, p1, radius, cell, sides=6, cuts=1):
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.verify()
    p0, p1 = V(p0), V(p1)
    d = (p1 - p0).normalized()
    a = d.cross(V((1, 0, 0)))
    if a.length < 0.3:
        a = d.cross(V((0, 1, 0)))
    a.normalize()
    b = d.cross(a)
    rings = []
    for k in range(cuts + 1):
        c = p0.lerp(p1, k / cuts)
        rings.append([bm.verts.new(c + (a * math.cos(2 * math.pi * i / sides) + b * math.sin(2 * math.pi * i / sides)) * radius) for i in range(sides)])
    cx, cy, size = cell
    for k in range(cuts):
        for i in range(sides):
            j = (i + 1) % sides
            f = bm.faces.new((rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]))
            f.smooth = True
            for l, (uu, vv) in zip(f.loops, ((i, k), (i + 1, k), (i + 1, k + 1), (i, k + 1))):
                l[uvl].uv = ((KIT0[0] + cx + (0.1 + 0.8 * uu / sides) * size) / ATLAS, (KIT0[1] + cy + (0.1 + 0.8 * vv / cuts) * size) / ATLAS)
    for ring, flip in ((rings[0], True), (rings[-1], False)):
        f = bm.faces.new(ring[::-1] if flip else ring)
        for l in f.loops:
            l[uvl].uv = ((KIT0[0] + cx + 0.5 * size) / ATLAS, (KIT0[1] + cy + 0.5 * size) / ATLAS)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.uv_layers[0].name = "UVMap"
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def join(obs, name):
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obs[0]
    if len(obs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = name
    return ob


def bind_rigid(ob, arm, weights):
    """weights: callable(co array) -> {bone: per-vertex weight array}, or a bone name"""
    for g in list(ob.vertex_groups):
        ob.vertex_groups.remove(g)
    co = _co(ob.data)
    W = {weights: np.ones(len(co))} if isinstance(weights, str) else weights(co)
    for bone, w in W.items():
        vg = ob.vertex_groups.new(name=bone)
        q = np.round(w * 1000).astype(int)
        for lvl in np.unique(q):
            if lvl > 0:
                vg.add(np.nonzero(q == lvl)[0].tolist(), float(lvl) / 1000.0, "REPLACE")
    for m in list(ob.modifiers):
        ob.modifiers.remove(m)
    ob.parent = arm
    md = ob.modifiers.new("Armature", "ARMATURE")
    md.object = arm
    md.use_vertex_groups = True


# --------------------------------------------------------------------------------------------------------------------- textures
def vermilion(alb):
    """(strict, loose) tests for the references' vermilion, texel by texel. Strict: the cloth itself. Loose: its washed-out highlights and dark creases
    (and a man's lips: the caller decides where loose counts). Row by row: the atlas is 16 M texels."""
    h, w = alb.shape[:2]
    strict = np.zeros((h, w), dtype=bool)
    loose = np.zeros((h, w), dtype=bool)
    faint = np.zeros((h, w), dtype=bool)                     # a sun-bleached end of the head band (only counted where the band is)
    step = 512
    for y in range(0, h, step):
        hue, sat, val = PR._hsv(alb[y:y + step, :, :3].reshape(-1, 3).astype(np.float64))
        strict[y:y + step] = (((hue < 16) | (hue > 346)) & (sat > 0.50) & (val > 0.22)).reshape(-1, w)
        loose[y:y + step] = (((hue < 15) | (hue > 343)) & (sat > 0.24) & (val > 0.10)).reshape(-1, w)
        faint[y:y + step] = (((hue < 10) | (hue > 335)) & (sat > 0.11) & (val > 0.25)).reshape(-1, w)
    return strict, loose, faint


def head_zones(work, unit, body, f):
    """from a body's baked position map: which of its texels are the FACE (never livery: lips and nostrils are red too) and which are where the head band is"""
    pos = np.load(os.path.join(work, unit, body, "tex", "villager_pos.npy")).astype(np.float32)
    x, y, z = (pos[..., 0] - 0.5) * 2.0, (pos[..., 1] - 0.5) * 2.0, pos[..., 2] * 2.0
    ax, ay = f["axis"]
    zn = f["z_neck"]
    covered = pos[..., 2] > 1e-4
    face = covered & (z > zn - 0.27) & (z < zn - 0.090) & (y < ay + 0.035) & (np.abs(x - ax) < np.where(z > zn - 0.16, 0.085, 0.058))     # (narrower below the eyes: a band end can hang beside the jaw)
    face |= covered & ((z < 0.14) | (np.abs(x) > 0.40))            # ... nor bare feet and hands (sun-reddened skin passes the cloth's test; no livery is worn there)
    r = np.hypot(x - ax, y - ay)
    band = covered & ~face & (z < zn + 0.01) & (((z > zn - 0.19) & (r < 0.16)) | ((y > ay + 0.02) & (z > zn - 0.33) & (r < 0.19)) | ((np.abs(x - ax) > 0.068) & (y > ay - 0.035) & (z > zn - 0.33) & (z < zn - 0.09) & (r < 0.19)))   # ... and an end that hangs beside the jaw     # ... and its knot and ends at the nape
    return face, band, ~covered


def box_blur(a, k):
    if k <= 0:
        return a
    c = np.cumsum(np.pad(a, ((k + 1, k), (0, 0)), mode="edge"), axis=0)
    a = (c[2 * k + 1:] - c[:-(2 * k + 1)]) / (2 * k + 1)
    c = np.cumsum(np.pad(a, ((0, 0), (k + 1, k)), mode="edge"), axis=1)
    return (c[:, 2 * k + 1:] - c[:, :-(2 * k + 1)]) / (2 * k + 1)


def compose(cfg, work, log=print, skulls=None):
    unit = cfg["unit"]
    A = {"albedo": np.zeros((ATLAS, ATLAS, 4), np.float32), "normal": np.zeros((ATLAS, ATLAS, 4), np.float32), "orm": np.zeros((ATLAS, ATLAS, 4), np.float32)}
    A["albedo"][..., :3] = 0.35
    A["normal"][..., :3] = (0.5, 0.5, 1.0)
    A["orm"][..., :3] = (1.0, 0.85, 0.0)
    for a in A.values():
        a[..., 3] = 1.0
    for body, (x0, y0) in QUARTER.items():
        if body not in cfg["bodies"]:
            continue
        for k in A:
            px = _load_px(os.path.join(work, unit, body, "tex", f"villager_{k}.png"))
            assert px.shape[0] == 2048, px.shape
            A[k][y0:y0 + 2048, x0:x0 + 2048] = px
    for name, (cx, cy, size) in KIT_CELLS.items():
        if name not in cfg["props"] and name != "bowkit":
            continue
        x0, y0 = KIT0[0] + cx, KIT0[1] + cy
        for k in A:
            src = os.path.join(work, unit, "bow_tex", f"bow_{k}." + ("jpg" if k == "albedo" else "png")) if name == "bowkit" else os.path.join(work, unit, "props", name + "_tex", f"villager_{k}.png")
            px = _load_px(src)
            assert px.shape[0] == size, (name, px.shape)
            A[k][y0:y0 + size, x0:x0 + size] = px
        # image-to-3D gives no metalness: steel (a spear's head) and gilding (the iron hat's disc) are found by their colour
        alb = A["albedo"][y0:y0 + size, x0:x0 + size, :3]
        hue, sat, val = (v.reshape(size, size) for v in PR._hsv(alb.reshape(-1, 3).astype(np.float64)))
        orm = A["orm"][y0:y0 + size, x0:x0 + size]
        if name in ("yari_head", "nagae_head"):
            steel = np.clip((0.20 - sat) / 0.08, 0, 1) * np.clip((val - 0.36) / 0.12, 0, 1)
            orm[..., 2] = np.maximum(orm[..., 2], 0.88 * steel)
            orm[..., 1] = orm[..., 1] * (1 - steel) + 0.36 * steel
        if name == "tetsu_jingasa":
            gilt = np.clip((sat - 0.34) / 0.12, 0, 1) * np.clip((val - 0.46) / 0.12, 0, 1) * ((hue > 28) & (hue < 58))
            orm[..., 2] = np.maximum(orm[..., 2], 0.90 * gilt)
            orm[..., 1] = orm[..., 1] * (1 - gilt) + 0.34 * gilt
    # ---- the cloth swatch (banner, pennant): undyed hemp, a plain weave; the wood swatch: black lacquer
    rng = np.random.default_rng(7)
    cx, cy, size = CLOTH_CELL
    x0, y0 = KIT0[0] + cx, KIT0[1] + cy
    yy, xx = np.mgrid[0:size, 0:size]
    weave = 0.5 + 0.5 * np.sin(xx * math.pi / 2.0) * np.sin(yy * math.pi / 2.0)
    slub = box_blur(rng.normal(0, 1, (size, size)), 3) * 2.2
    streak = rng.normal(0, 1, (size, 1)).repeat(size, 1) * 0.012 + rng.normal(0, 1, (1, size)).repeat(size, 0) * 0.012
    tone = np.clip(0.80 + 0.045 * (weave - 0.5) + 0.03 * slub + streak, 0.55, 0.95)
    A["albedo"][y0:y0 + size, x0:x0 + size, :3] = tone[..., None] * np.array((1.0, 0.975, 0.93))
    A["normal"][y0:y0 + size, x0:x0 + size, 0] = 0.5 - np.gradient(weave, axis=1) * 0.09
    A["normal"][y0:y0 + size, x0:x0 + size, 1] = 0.5 - np.gradient(weave, axis=0) * 0.09
    A["normal"][y0:y0 + size, x0:x0 + size, 2] = 1.0
    A["orm"][y0:y0 + size, x0:x0 + size, :3] = (1.0, 0.93, 0.0)
    cx, cy, size = WOOD_CELL
    x0, y0 = KIT0[0] + cx, KIT0[1] + cy
    grain = box_blur(rng.normal(0, 1, (size, size)), 2)
    A["albedo"][y0:y0 + size, x0:x0 + size, :3] = np.clip(0.060 + 0.02 * grain, 0.03, 0.12)[..., None] * np.array((1.0, 0.92, 0.86))
    A["normal"][y0:y0 + size, x0:x0 + size, :3] = (0.5, 0.5, 1.0)
    A["orm"][y0:y0 + size, x0:x0 + size, :3] = (1.0, 0.42, 0.0)
    # ---- the house's colour: mask, and those texels to a neutral cloth tone
    strict, loose, faint = vermilion(A["albedo"])
    face = np.zeros((ATLAS, ATLAS), dtype=bool)
    band = np.zeros((ATLAS, ATLAS), dtype=bool)
    for body, (bx, by) in QUARTER.items():
        if body in cfg["bodies"] and skulls and body in skulls:
            fz, bz, uz = head_zones(work, unit, body, skulls[body])
            face[by:by + 2048, bx:bx + 2048] = fz
            band[by:by + 2048, bx:bx + 2048] = bz | uz                    # (texels the position bake missed: a thin cloth end's far side. Red there is cloth: skin margins are not this red)
    strict &= ~face
    near = box_blur(strict.astype(np.float32), 7) > 0.04                 # the looser test counts next to cloth that passed the strict one, and on the head band
    mask = (strict | (loose & (near | band) & ~face) | (faint & band & ~face)).astype(np.float32)
    del strict, loose, near, faint
    kx, ky, ks = CLOTH_CELL
    kx0, ky0 = KIT0[0] + kx, KIT0[1] + ky
    plain = [n for n in KIT_CELLS if n not in HAT]
    for name in plain:                                                   # lacquer red on a pike's shaft (an arrow's nock) is lacquer, not livery
        cx, cy, size = KIT_CELLS[name]
        mask[KIT0[1] + cy:KIT0[1] + cy + size, KIT0[0] + cx:KIT0[0] + cx + size] = 0.0
    hard = (mask > 0.5).astype(np.float32)
    red = hard > 0.5                                                     # the texels painted vermilion (not the swatch: it is pale already)
    hard[ky0:ky0 + ks, kx0:kx0 + ks] = 1.0
    for name in plain:
        cx, cy, size = KIT_CELLS[name]
        hard[KIT0[1] + cy:KIT0[1] + cy + size, KIT0[0] + cx:KIT0[0] + cx + size] = 0.0
    mask = np.clip(box_blur(hard, 1) * 1.3, 0, 1).astype(np.float32)
    red = red | (mask > 0.3)                                             # the rim of every patch goes neutral with it (no red fringe)
    red[ky0:ky0 + ks, kx0:kx0 + ks] = False
    # red cloth is dark in luminance: lift it to where the engine's tint (it scales the house colour by luminance) reads as dyed cloth, and keep its folds
    alb = A["albedo"]
    med, gain = LIVERY_LUM, 1.0
    lums = []
    for y in range(0, ATLAS, 512):
        rgb = alb[y:y + 512, :, :3].astype(np.float64)
        lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        lum = lin @ np.array((0.2126, 0.7152, 0.0722))
        sel = red[y:y + 512]
        if sel.any():
            lums.append(lum[sel][::7])
    if lums:
        med = float(np.median(np.concatenate(lums)))
        gain = LIVERY_LUM / max(med, 1e-4)
    for y in range(0, ATLAS, 512):
        rgb = alb[y:y + 512, :, :3].astype(np.float64)
        lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        lum = lin @ np.array((0.2126, 0.7152, 0.0722))
        neutral = np.clip(lum * gain, 0.0, 0.9)[..., None] * np.array((1.0, 0.985, 0.955))
        ns = np.where(neutral <= 0.0031308, neutral * 12.92, 1.055 * np.power(np.maximum(neutral, 1e-8), 1 / 2.4) - 0.055)
        w = np.where(red[y:y + 512], mask[y:y + 512], 0.0)[..., None]
        alb[y:y + 512, :, :3] = (rgb * (1 - w) + ns * w).astype(np.float32)
    log(f"  livery: {float(hard.mean()) * 100:.1f}% of the atlas, red cloth luminance {med:.3f} x{gain:.2f}")
    tex = os.path.join(work, unit, "tex")
    os.makedirs(tex, exist_ok=True)
    imgs = {k: _save_px(A[k], os.path.join(tex, f"{unit}_{k}_src.png"), k == "albedo", f"{unit}_{k}") for k in A}
    m4 = np.zeros((ATLAS // 2, ATLAS // 2, 4), np.float32)
    m4[..., 0] = mask.reshape(ATLAS // 2, 2, ATLAS // 2, 2).mean(axis=(1, 3))
    m4[..., 3] = 1.0
    tm = _save_px(m4, os.path.join(tex, f"{unit}_team.png"), False, f"{unit}_team")
    bpy.data.images.remove(tm)
    return imgs


# --------------------------------------------------------------------------------------------------------------------- the stage
def run(cfg, work, A=None, rel=lambda p: p, log=print):
    from recipes import _common as C
    global QUARTER, KIT_CELLS
    unit = cfg["unit"]
    if unit in LAYOUT:
        QUARTER, KIT_CELLS = LAYOUT[unit]["quarter"], LAYOUT[unit]["cells"]
    is_bow = cfg.get("weapon") == "bow"
    U = unit.capitalize()
    ingest.reset_scene()
    base_key = cfg["base"]
    order = [base_key] + [b for b in cfg["bodies"] if b != base_key]
    bodies, own = {}, {}
    for b in order:
        mesh, arm = append_body(os.path.join(work, unit, b, "villager_skin.blend"))
        mesh.name = mesh.data.name = cfg["bodies"][b]["node"]
        arm.name = arm.data.name = f"{U}Rig" if b == base_key else f"_rig_{b}"
        bodies[b], own[b] = mesh, arm
    arm = own[base_key]
    with open(os.path.join(work, unit, base_key, "hands.json")) as fh:
        hands = json.load(fh)
    # ---- every body onto the base skeleton
    names0 = [bn.name for bn in arm.data.bones]
    Ws = {}
    for b in order:
        if b == base_key:
            Ws[b] = dense_weights(bodies[b], names0)
        else:
            off = {n: (own[b].data.bones[n].head_local - arm.data.bones[n].head_local).length for n in names0 if n in own[b].data.bones}
            log(f"  {b}: joints off the base by up to {max(off.values()) * 1000:.1f} mm ({max(off, key=off.get)})")
            Ws[b] = warp_to(bodies[b], own[b], arm, names0, log)
    for b in order:
        if b != base_key:
            d = own[b].data
            bpy.data.objects.remove(own[b], do_unlink=True)
            bpy.data.armatures.remove(d)
    # ---- the skeleton: drop the labourer's prop bones, add the hair knot and the soldier's
    for o in bpy.context.view_layer.objects:
        o.select_set(o == arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for n in DROP_BONES:
        eb = arm.data.edit_bones.get(n)
        if eb is not None:
            arm.data.edit_bones.remove(eb)
    bpy.ops.object.mode_set(mode="OBJECT")
    keep = [i for i, n in enumerate(names0) if n not in DROP_BONES]
    names = [names0[i] for i in keep]
    for b in order:
        Ws[b] = Ws[b][:, keep]
    sk, z_neck = add_topknot(arm, bodies, log)
    names.append("topknot")
    for b in order:
        Ws[b] = np.hstack([Ws[b], np.zeros((len(Ws[b]), 1))])
        n = split_topknot(bodies[b], Ws[b], names, sk[b])
        Ws[b], bad = VR.limit_normalise(Ws[b], 4)
        assert not bad, f"{b}: {bad} vertices without a weight"
        log(f"  {b}: {n} hair-knot vertices")
    HR = hands["R"]
    G, D, N = V(HR["grip"]), V(HR["c"]).normalized(), V(HR["n"]).normalized()
    N = (N - D * N.dot(D)).normalized()

    def sp(s):
        return G + D * (s - GRIP0)
    bow = None
    pen_at = sp(YARI_LEN - PENNANT_BELOW_TIP)
    pj = [pen_at + V((0, 0, -0.016)), pen_at + V((0, 0, -0.016 - PENNANT_H * 0.5)), pen_at + V((0, 0, -0.016 - PENNANT_H))]
    if is_bow:                                                                 # the v1 archer's bow and arrow, in THIS man's grip (soldier.bowkit)
        from . import bowkit
        bow = bowkit.build(arm, hands, os.path.join(work, unit, "bow_tex"), KIT_CELLS["bowkit"][2], log)
        weapon_bones = [n for n, _ in bowkit.BOW_BONES]
    else:
        VR.add_bone(arm, "weapon_r", "hand.R", sp(GRIP0 - 0.10), D, N, 0.30)
        VR.add_bone(arm, "weapon_r2", "hand.R", sp(GRIP0 - 0.10), D, N, 0.30)
        VR.add_bone(arm, "pennant_1", "weapon_r", pj[0], pj[1] - pj[0], D, (pj[1] - pj[0]).length)
        VR.add_bone(arm, "pennant_2", "pennant_1", pj[1], pj[2] - pj[1], D, (pj[2] - pj[1]).length)
        weapon_bones = ["weapon_r", "weapon_r2", "pennant_1", "pennant_2"]
    # the banner's foot: on the back of the armour that carries one
    ban_body = next((b for b in order if cfg["bodies"][b].get("banner")), order[-1])
    cb = _co(bodies[ban_body].data)
    m = (np.abs(cb[:, 0]) < 0.035) & (cb[:, 2] > POLE_Z0 - 0.02) & (cb[:, 2] < POLE_Z0 + 0.06)
    yb = float(cb[m][:, 1].max()) + 0.006
    lean = [POLE_LEAN]
    pole_y = lambda z: yb + lean[0] * (z - POLE_Z0) / (POLE_Z1 - POLE_Z0)
    P = [V((0, yb, POLE_Z0)), V((0, pole_y(1.76), 1.76)), V((0, pole_y(POLE_Z1), POLE_Z1))]
    yc = pole_y(BAN_TOP) + 0.002
    VR.add_bone(arm, "banner_1", "chest", P[0], P[1] - P[0], (0, -1, 0), (P[1] - P[0]).length)
    VR.add_bone(arm, "banner_2", "banner_1", P[1], P[2] - P[1], (0, -1, 0), (P[2] - P[1]).length)
    fz = BAN_TOP - 0.004 - CLOTH_H * 0.5
    fj = [V((BAN_X0 + CLOTH_W * i / 3.0, yc + 0.003, fz)) for i in range(4)]
    for i in range(3):
        VR.add_bone(arm, f"flag_{i + 1}", "banner_2" if i == 0 else f"flag_{i}", fj[i], fj[i + 1] - fj[i], (0, -1, 0), (fj[i + 1] - fj[i]).length)
    extra = weapon_bones + ["banner_1", "banner_2", "flag_1", "flag_2", "flag_3"]
    for b in order:
        VR.write_weights(bodies[b], np.hstack([Ws[b], np.zeros((len(Ws[b]), len(extra)))]), names + extra, arm)
        x0, y0 = QUARTER[b]
        uv = _uv(bodies[b].data)
        uv[:, 0] = (x0 + uv[:, 0] * 2048) / ATLAS
        uv[:, 1] = (y0 + uv[:, 1] * 2048) / ATLAS
        _set_uv(bodies[b].data, uv)
    # where the sash is (the side arm goes through it): the vermilion band around the base body's waist, read from its own bake
    sash_z = None
    try:
        alb = _load_px(os.path.join(work, unit, base_key, "tex", "villager_albedo.png"))
        me0 = bodies[base_key].data
        uv0 = _uv(me0) * ATLAS
        uv0[:, 0] -= QUARTER[base_key][0]
        uv0[:, 1] -= QUARTER[base_key][1]
        lv = np.empty(len(me0.loops), dtype=np.int64)
        me0.loops.foreach_get("vertex_index", lv)
        vu = np.zeros((len(me0.vertices), 2))
        vu[lv] = uv0
        px = alb[np.clip(vu[:, 1].astype(int), 0, 2047), np.clip(vu[:, 0].astype(int), 0, 2047), :3].astype(np.float64)
        hue, sat, val = PR._hsv(px)
        c0 = _co(me0)
        hz0 = float(arm.data.bones["hips"].head_local.z)
        red = ((hue < 16) | (hue > 346)) & (sat > 0.5) & (val > 0.22) & (np.abs(c0[:, 2] - hz0) < 0.16) & (np.abs(c0[:, 0]) < 0.22) & (c0[:, 1] > 0.0)
        if red.sum() > 30:                                                     # the BACK of the waist: the knot and its hanging ends are in front
            sash_z = float(np.median(c0[red, 2]))
            log(f"  sash: {int(red.sum())} vertices, centre z = {sash_z:.3f} m (hips joint {hz0:.3f})")
    except Exception as exc:
        log("  sash not measured: " + repr(exc))
    # ---- kit
    kit = {}
    skulls = {}
    for b in order:
        co = _co(bodies[b].data)
        ax = np.array(sk[b]["axis"])
        skulls[b] = dict(co=co, r=np.hypot(co[:, 0] - ax[0], co[:, 1] - ax[1]), z_neck=sk[b]["z_neck"], axis=ax)
    seats = {}
    for pname, hc in HAT.items():
        if pname not in cfg["props"]:
            continue
        ob, pf = append_prop(work, unit, pname)
        cell_uv(ob, KIT_CELLS[pname])
        seats[hc["node"]] = seat_hat(ob, skulls, hc, log=log)
        ob.name = ob.data.name = hc["node"]
        bind_rigid(ob, arm, "head")
        kit[hc["node"]] = ob
    for pname, node, length, bone in (("yari_head", "Yari", YARI_LEN, "weapon_r"), ("nagae_head", "Yari_Long", NAGAE_LEN, "weapon_r2")):
        if pname not in cfg["props"]:
            continue
        ob, pf = append_prop(work, unit, pname)
        cell_uv(ob, KIT_CELLS[pname])
        build_spear(ob, pf, length, G, D, N, node)
        if node == "Yari":                                                     # the pennant: a ribbon of the house's colour under the head
            pen = quad_grid("_pennant", pen_at + D * (-PENNANT_W * 0.5) + V((0, 0, -0.016)), D * PENNANT_W, V((0, 0, -PENNANT_H)), 1, 2, CLOTH_CELL, uv0=(0.70, 0.05), uv1=(0.95, 0.75))
            nsp = len(ob.data.vertices)
            ob = join([ob, pen], node)

            def wy(co, nsp=nsp, z0=float(pj[0].z), z2=float(pj[2].z)):
                w = {"weapon_r": np.zeros(len(co)), "pennant_1": np.zeros(len(co)), "pennant_2": np.zeros(len(co))}
                w["weapon_r"][:nsp] = 1.0
                t = np.clip((z0 - co[nsp:, 2]) / max(z0 - z2, 1e-6), 0, 1)        # 0 at the cord, 1 at the free end
                w["pennant_1"][nsp:] = np.where(t < 0.25, 1.0, np.where(t < 0.75, 0.5, 0.0))
                w["pennant_2"][nsp:] = 1.0 - w["pennant_1"][nsp:]
                return w
            bind_rigid(ob, arm, wy)
        else:
            bind_rigid(ob, arm, bone)
        kit[node] = ob
    if "tanto" in cfg["props"]:
        ob, pf = append_prop(work, unit, "tanto")
        cell_uv(ob, KIT_CELLS["tanto"])
        hz = sash_z if sash_z is not None else float(arm.data.bones["hips"].head_local.z)
        phi = math.radians(TANTO["phi"])
        d = np.array((math.sin(phi), -math.cos(phi)))
        per = {}
        for b in order:
            co = _co(bodies[b].data)
            q = co[:, :2]
            m = (np.abs(co[:, 2] - hz) < 0.035) & ((q @ d) > 0.8 * np.linalg.norm(q, axis=1)) & (np.abs(co[:, 0]) < 0.30)
            per[b] = float((q[m] @ d).max()) if m.any() else 0.15
        Rs = float(np.median(list(per.values())))
        tan = V((math.cos(phi), math.sin(phi), 0.0))
        t = (tan * math.cos(math.radians(TANTO["dip"])) + V((0, 0, -1)) * math.sin(math.radians(TANTO["dip"]))).normalized()
        out = V((d[0], d[1], 0.0))
        ex = (V((0, 0, 1)) - t * t.z).normalized()                             # the wide axis (guard, edge) up
        ez = ex.cross(t)
        R = Matrix.Identity(4)
        for i in range(3):
            R[i][0], R[i][1], R[i][2] = ex[i], t[i], ez[i]
        contact = V((0, 0, hz + TANTO["dz"])) + out * (Rs + TANTO["out"])
        ob.data.transform(Matrix.Translation(contact) @ R @ Matrix.Translation((0, TANTO["along"], 0)))
        ob.data.update()
        ob.name = ob.data.name = "Side_Tanto"
        bind_rigid(ob, arm, "hips")
        kit["Side_Tanto"] = ob
        log(f"  Side_Tanto: waist radius by body {json.dumps({k: round(v, 3) for k, v in per.items()})}, seated at {Rs + TANTO["out"]:.3f} m")
    if bow is not None:
        yumi, arrow, bow_facts = bow
        for ob in (yumi, arrow):
            cell_uv(ob, KIT_CELLS["bowkit"])
            kit[ob.name] = ob
        if "ebira" in cfg["props"]:
            ob, pf = append_prop(work, unit, "ebira")
            cell_uv(ob, KIT_CELLS["ebira"])
            hz = sash_z if sash_z is not None else float(arm.data.bones["hips"].head_local.z)
            bow_facts["quiver"] = bowkit.place_quiver(ob, [_co(bodies[b].data) for b in order], hz, log)
            ob.name = ob.data.name = "Quiver"
            bind_rigid(ob, arm, "hips")
            kit["Quiver"] = ob
    # the back banner: its pole clears the widest hat's brim (the bones were placed with the least lean; a pole that would stand in a brim leans further)
    need = 0.0
    for node, ob in kit.items():
        if node.startswith("Helmet"):
            hc = _co(ob.data)
            for z in np.arange(float(hc[:, 2].min()), float(hc[:, 2].max()), 0.01):
                mm = (np.abs(hc[:, 2] - z) < 0.012) & (np.abs(hc[:, 0]) < 0.05)
                if mm.any() and z > POLE_Z0 + 0.2:
                    need = max(need, (float(hc[mm][:, 1].max()) + 0.022 - yb) * (POLE_Z1 - POLE_Z0) / (z - POLE_Z0))
    if need > lean[0] + 1e-4:
        raise SystemExit(f"banner pole: lean {lean[0]:.3f} stands in a hat brim; POLE_LEAN must be at least {need:.3f}")
    log(f"  banner: pole lean {lean[0]:.3f} m over {POLE_Z1 - POLE_Z0:.2f} m (the hats need {need:.3f})")
    pole = rod("_pole", P[0] + V((0, -0.004, -0.03)), P[2], 0.0085, WOOD_CELL, cuts=6)
    bar = rod("_bar", V((-0.004, yc, BAN_TOP)), V((BAN_X0 + CLOTH_W + 0.006, yc, BAN_TOP)), 0.006, WOOD_CELL)
    cloth = quad_grid("_cloth", (BAN_X0, yc + 0.003, BAN_TOP - 0.004), (CLOTH_W, 0, 0), (0, 0, -CLOTH_H), 3, 6, CLOTH_CELL, uv0=(0.04, 0.96), uv1=(0.62, 0.04))
    npole, nbar = len(pole.data.vertices), len(bar.data.vertices)
    sash = join([pole, bar, cloth], "Sashimono")

    def wb(co, npole=npole, nbar=nbar):
        n = len(co)
        w = {k: np.zeros(n) for k in ("banner_1", "banner_2", "flag_1", "flag_2", "flag_3")}
        z = co[:npole, 2]
        w["banner_2"][:npole] = np.clip((z - (1.76 - 0.05)) / 0.10, 0, 1)
        w["banner_1"][:npole] = 1.0 - w["banner_2"][:npole]
        w["banner_2"][npole:npole + nbar] = 1.0
        c0 = npole + nbar
        k = np.clip(np.round((co[c0:, 0] - BAN_X0) / (CLOTH_W / 3.0)).astype(int), 0, 3)
        w["flag_1"][c0:] = np.where(k == 0, 1.0, np.where(k == 1, 0.5, 0.0))
        w["flag_2"][c0:] = np.where((k == 1) | (k == 2), 0.5, 0.0)
        w["flag_3"][c0:] = np.where(k == 2, 0.5, np.where(k == 3, 1.0, 0.0))
        return w
    bind_rigid(sash, arm, wb)
    kit["Sashimono"] = sash
    for o in list(bodies.values()) + list(kit.values()):
        for p in o.data.polygons:
            p.use_smooth = True
    # ---- one atlas, one material
    imgs = compose(cfg, work, log, skulls=sk)
    mat = C.pbr_material(f"{unit}_mat", imgs, double_sided=True)
    for o in list(bodies.values()) + list(kit.values()):
        o.data.materials.clear()
        o.data.materials.append(mat)
    facts = {
        "unit": unit, "bones": [b.name for b in arm.data.bones], "bodies": {b: bodies[b].name for b in order}, "kit": sorted(kit),
        "tris": {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in list(bodies.values()) + list(kit.values())},
        "spear": {"G": list(G), "D": list(D), "N": list(N), "grip0": GRIP0, "yari": YARI_LEN, "nagae": NAGAE_LEN, "pennant": [list(p) for p in pj]},
        "bow": bow[2] if bow is not None else None,
        "banner": {"pole": [list(p) for p in P], "flag": [list(p) for p in fj], "x0": BAN_X0, "w": CLOTH_W, "z_top": BAN_TOP - 0.004, "h": CLOTH_H, "y": yc + 0.003},
        "skull": sk, "hat_rims": seats, "z_neck": z_neck,
    }
    with open(os.path.join(work, unit, "assembled.json"), "w") as fh:
        json.dump(facts, fh, indent=1)
    with open(os.path.join(work, unit, "hands.json"), "w") as fh:
        json.dump(hands, fh, indent=1)
    # ---- QA: the three bodies in three kits (rest pose)
    qd = os.path.join(work, unit, "qa")
    tk = arm.pose.bones["topknot"]
    sets = [("bare", ["Yari"], False), ("levy", ["Helmet_Jingasa", "Side_Tanto", "Yari"], True), ("okegawa", ["Helmet_Tetsu", "Side_Tanto", "Sashimono", "Yari_Long"], True)]
    if is_bow:
        sets = [("bare", ["Yumi", "Quiver"], False), ("haramaki", ["Helmet_Jingasa", "Yumi", "Arrow_Nocked", "Quiver", "Sashimono"], True)]
    full, det = [], []
    for b, pieces, hat in sets:
        if b not in bodies:
            continue
        tk.scale = (1e-4, 1e-4, 1e-4) if hat else (1, 1, 1)
        bpy.context.view_layer.update()
        obs = [bodies[b]] + [kit[p] for p in pieces if p in kit]
        full += qa.shots(obs, os.path.join(qd, f"asm_{b}"), views=("front", "q", "side", "back"), size=1100, focus=(0, 0, 1.12), span=2.4)
        det += qa.shots(obs, os.path.join(qd, f"asm_{b}_head"), views=("front", "q", "q_back"), size=900, focus=(0, 0.02, 1.60), span=0.62)
        det += qa.shots(obs, os.path.join(qd, f"asm_{b}_waist"), views=("q",), size=900, focus=(0.05, 0, 1.03), span=0.62)
    tk.scale = (1, 1, 1)
    qa.sheet(full, os.path.join(qd, "assembled_sheet.jpg"), cols=4)
    qa.sheet(det, os.path.join(qd, "assembled_detail.jpg"), cols=4)
    for p in full + det:
        os.remove(p)
    bpy.ops.outliner.orphans_purge(do_recursive=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(work, unit, "assembled.blend"), compress=True)
    log("ASSEMBLED " + json.dumps({k: facts[k] for k in ("bodies", "kit", "tris", "hat_rims")}))
    return facts
