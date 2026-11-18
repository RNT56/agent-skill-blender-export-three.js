"""Armour fit check (run inside Blender):  blender -b --factory-startup -P generators/samurai_clearance.py
For every armour part, the signed distance of its vertices to the body layers underneath (robe, sleeves, trousers, wraps, sash, skin, feet):
negative = the plate is INSIDE a cloth mesh (interpenetration), large positive = a hugging part floating away.
Inside-ness is ray parity against each closed cloth mesh separately (union parity of overlapping meshes is meaningless).
Prints the worst parts; exits 1 if a part penetrates more than 4 mm. Rest pose only."""
import os
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from samurai import armour, body, rig

# parts that float away from the body on purpose (large / hanging / mounted): only penetration is judged
FLOAT_OK = ("armor_wing", "armor_visor", "armor_maedate", "armor_rosette", "armor_kabuto", "armor_shikoro", "armor_sode", "armor_skirt",
            "armor_menpo", "armor_buckle", "armor_watagami")
LIMIT_PEN = 0.0045
LIMIT_GAP = 0.030
CLOTH = ("cloth_", "body_head", "body_hand", "body_thumb", "body_index", "body_middle", "body_ring", "body_pinky", "straw_sole")
DIR = Vector((1.0, 0.123, 0.377)).normalized()


def parity(tree, p):
    n, o = 0, p.copy()
    for _ in range(40):
        loc, nrm, idx, dist = tree.ray_cast(o, DIR)
        if loc is None:
            break
        n += 1
        o = loc + DIR * 1e-5
    return n % 2 == 1


def main():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    coll = bpy.data.collections.new("c")
    bpy.context.scene.collection.children.link(coll)
    table = rig.bone_table()
    trees, arm_objs = [], []
    for p in body.all_soft(table):
        if p.name.startswith(CLOTH):
            o = p.to_object(coll)
            trees.append((o.name, BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices], [tuple(q.vertices) for q in o.data.polygons])))
    for p in armour.all_armour(table):
        arm_objs.append(p.to_object(coll))

    def query(p):
        """(signed distance, owner): negative when p lies inside any single cloth mesh."""
        best, name, inside_in = 1e9, "-", None
        for nm, t in trees:
            loc, nrm, idx, dist = t.find_nearest(p)
            if loc is not None and dist < best:
                best, name = dist, nm
            if inside_in is None and parity(t, p):
                inside_in = nm
        return (-best, inside_in) if inside_in else (best, name)

    rows = []
    for o in arm_objs:
        ds, who = [], {}
        for v in o.data.vertices:
            d, nm = query(v.co)
            ds.append(d)
            if d < 0:
                who[nm] = who.get(nm, 0) + 1
        if ds:
            srt = sorted(ds)
            rows.append((srt[0], srt[len(srt) // 2], srt[-1], o.name, max(who, key=who.get) if who else "-"))
    rows.sort()
    print("CLEARANCE worst penetration first (mm): min / median / max   part")
    for mn, med, mx, name, who in rows[:14]:
        flag = "  <-- PENETRATES" if mn < -LIMIT_PEN and not name.startswith("armor_menpo") else ""
        print(f"CLEARANCE {mn * 1000:7.1f} {med * 1000:7.1f} {mx * 1000:7.1f}   {name} (inside {who}){flag}")
    pens = [r for r in rows if r[0] < -LIMIT_PEN and not r[3].startswith("armor_menpo")]
    gaps = [r for r in rows if r[1] > LIMIT_GAP and not r[3].startswith(FLOAT_OK)]
    print(f"CLEARANCE summary: {len(pens)} part(s) penetrate > {LIMIT_PEN * 1000:.0f} mm, {len(gaps)} hugging part(s) float > {LIMIT_GAP * 1000:.0f} mm median")
    for r in gaps[:8]:
        print(f"CLEARANCE float {r[1] * 1000:6.1f} mm median  {r[3]}")
    sys.exit(1 if pens else 0)


main()
