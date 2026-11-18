"""Cloth clearance over every frame of every clip (run inside Blender, no textures needed):
    blender -b --factory-startup -P generators/samurai_cloth_check.py -- [--clips idle,run] [--step 1] [--limit-mm 6]
Builds the model with the sash tails and the banner kept apart from the body, bakes the clips with the CURRENT animation code, then for each frame
evaluates the skinned meshes and measures, for the tails and for the sashimono POLE (axis sampled between ring centres, minus the radius; the lowest ring sits in the bracket by design), the UNSIGNED distance to the body / armour surface (a value near 0 or below = the cloth surface touches or is inside the armour) and the lowest height reached (ground). The sign of a nearest-face test flips on thin
plate backs, so only unsigned distances are used. Signed by ray parity (each plate is a closed slab). Prints one line per clip: worst clearance, the frame, and how many frames are below the limit."""
import os
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from samurai import build, finalize

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(n, d=None):
    return argv[argv.index(n) + 1] if n in argv else d


def evaluated(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    e = ob.evaluated_get(dg)
    me = e.to_mesh()
    verts = [ob.matrix_world @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    e.to_mesh_clear()
    return verts, polys


RAYS = [Vector((0.31, 0.52, 0.79)).normalized(), Vector((-0.7, 0.2, -0.3)).normalized(), Vector((0.1, -0.9, 0.4)).normalized()]


def inside(tree, p):
    """Ray parity against the joined body (every plate is a closed slab): 2 of 3 directions odd = inside some solid."""
    votes = 0
    for d in RAYS:
        o, n = p.copy(), 0
        for _ in range(24):
            loc, nrm, idx, dist = tree.ray_cast(o, d)
            if loc is None:
                break
            n += 1
            o = loc + d * 1e-5
        votes += n & 1
    return votes >= 2


def main():
    mdl = build.build_model("all", split_tails=True)
    arm = mdl["arm"]
    sc = bpy.context.scene
    sc.render.fps = 30
    only = arg("--clips")
    only = only.split(",") if only else None
    finalize.bake_clips(arm, names=only, log=lambda m: print('CLOTHSIM', m.strip()))
    body = mdl["body"]
    watch = {"tails": mdl.get("Sash_Tails"), "banner": mdl.get("Sashimono")}
    # which vertices are the free cloth: chosen on the REST mesh (vertex order survives evaluation). Tail roots touch the knot by design: only the lower part counts
    rest = {k: ob.data.vertices for k, ob in watch.items() if ob is not None}
    from samurai.consts import TOP, YP, YP0
    axis = [Vector(p) for p in ((0, YP0, 1.30), (0, YP, 1.50), (0, YP, 1.70), (0, YP + 0.002, 2.10), (0, YP + 0.005, TOP + 0.04))]
    ring_idx = [[v.index for v in rest["banner"] if (v.co - a).length < 0.0085 and abs(v.co.z - a.z) < 0.006] for a in axis] if "banner" in rest else []
    ring_idx = ring_idx[1:]                                     # the lowest ring sits in the bracket by design: measure from the first ring above it
    pick = {"tails": [v.index for v in rest["tails"] if v.co.z < 0.965], "banner": [i for g in ring_idx for i in g]}
    POLE_R = 0.0075
    limit = float(arg("--limit-mm", 6.0)) / 1000.0
    assert_mm = arg("--assert-mm")
    step = int(arg("--step", 1))
    arm.animation_data_create()
    names = only or [a.name for a in bpy.data.actions]
    gate_min = 9.0
    gate_pole = 9.0
    print("CLOTHCHECK clip | part | worst clearance mm | frame | frames below limit | lowest z (m) | bone of the plate it touches")
    for name in names:
        act = bpy.data.actions[name]
        arm.animation_data.action = act
        if hasattr(arm.animation_data, "action_slot") and act.slots:
            arm.animation_data.action_slot = act.slots[0]
        f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
        worst = {k: (9.0, 0) for k in watch}
        culprit = {k: "-" for k in watch}
        bad = {k: 0 for k in watch}
        low = {k: 9.0 for k in watch}
        for f in range(f0, f1 + 1, step):
            sc.frame_set(f)
            bpy.context.view_layer.update()
            bv, bp = evaluated(body)
            tree = BVHTree.FromPolygons(bv, bp)
            for k, ob in watch.items():
                if ob is None:
                    continue
                vv, _ = evaluated(ob)
                m = 9.0
                pts = [vv[i] for i in pick[k]]
                if k == "banner":                                              # the pole is thin: sample its AXIS between the ring centres (rings are 20-40 cm apart) and subtract the radius
                    cs = [sum((vv[i] for i in g), Vector((0, 0, 0))) / len(g) for g in ring_idx if g]
                    pts = [a + (b - a) * (j / 14.0) for a, b in zip(cs[:-1], cs[1:]) for j in range(15)]
                for v in pts:
                    loc, nrm, idx, d = tree.find_nearest(v)
                    if loc is not None:
                        if k == "banner":
                            d -= POLE_R                                            # axis distance minus the pole radius: negative = the pole surface is inside the armour
                        elif d < 0.02 and inside(tree, v):
                            d = -d                                                 # inside a plate / the skirt: negative
                        if d < worst[k][0]:
                            poly = body.data.polygons[idx]                         # who is it touching: the strongest bone of the nearest plate
                            wsum = {}
                            for vi in poly.vertices:
                                for g in body.data.vertices[vi].groups:
                                    wsum[body.vertex_groups[g.group].name] = wsum.get(body.vertex_groups[g.group].name, 0.0) + g.weight
                            culprit[k] = max(wsum, key=wsum.get) if wsum else "-"
                        m = min(m, d)                                              # signed distance of a cloth surface vertex to the body (negative = penetrating)
                    low[k] = min(low[k], v.z)
                if m < worst[k][0]:
                    worst[k] = (m, f)
                if m < -limit:
                    bad[k] += 1
        for k in watch:
            if watch[k] is not None:
                if k == "tails":
                    gate_min = min(gate_min, worst[k][0])
                else:
                    gate_pole = min(gate_pole, worst[k][0])
                print(f"CLOTHCHECK {name} | {k} | {worst[k][0] * 1000:7.1f} | {worst[k][1]} | {bad[k]}/{(f1 - f0) // step + 1} | {low[k]:.3f} | nearest bone {culprit[k]}")
    if assert_mm is not None:
        ok = gate_min > -float(assert_mm) / 1000.0
        print(f"CLOTHCHECK GATE tails_worst_mm={gate_min * 1000:.1f} limit=-{assert_mm} {'PASS' if ok else 'FAIL'}")
    if arg("--assert-pole-mm") is not None:
        ok = gate_pole > -float(arg("--assert-pole-mm")) / 1000.0
        print(f"CLOTHCHECK GATE pole_worst_mm={gate_pole * 1000:.1f} limit=-{arg('--assert-pole-mm')} {'PASS' if ok else 'FAIL'}")


main()
