"""Light archer generator (run inside Blender):  blender -b --factory-startup -P generators/archer_unit.py -- [options]

Builds the A-pose rest model (body, clothes, belly wrap, quiver; the war hat, the yumi, the nocked arrow and the back banner as their own skinned nodes), the 59-bone
armature and skin weights, then optionally bakes the one-atlas PBR set, makes the LODs and bakes the clips:
  --bake out/archer_tex --px 2048 --quality 1.0   --finalize 1 [--lods 7600,2400]   --save fixtures/archer_unit.blend
  --pose <clip>@<seconds>   --render out/_archer --views front,side,...   (QA: LOOK at the sheets)
In a LIVE session (Blender MCP) use archer.build.build_model(live=True) instead: it works in its own scene and never bakes.
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def arg(name, default=None):
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index(name) + 1] if name in argv else default


def tris(o):
    return sum(len(p.vertices) - 2 for p in o.data.polygons)


def main():
    from archer import build
    from samurai import qa
    m = build.build_model()
    arm = m["arm"]
    nodes = [m[k] for k in ("body", "Helmet", "Yumi", "Yumi_Low", "Arrow_Nocked", "Sashimono")]
    if arg("--bake") is not None:
        from samurai import emblems
        from archer import bake, cloth, consts as K
        import json
        tex_dir = os.path.join(ROOT, arg("--bake"))
        # occlusion per piece: the body is not shaded by a hat he may not be wearing, and the two bows (full and low, in the same place) do not shade each other
        b = m["body"]
        groups = [([b], []), ([m["Helmet"]], [b]), ([m["Yumi"]], [b]), ([m["Yumi_Low"]], [b]), ([m["Arrow_Nocked"]], [b, m["Yumi"]]), ([m["Sashimono"]], [b])]
        maps = bake.bake_atlas(nodes, tex_dir, "archer", px=int(arg("--px", 2048)), quality=float(arg("--quality", 1.0)), log=print, ao_groups=groups)
        bake.assign_baked(nodes, maps, "archer")
        emblems.write(tex_dir, "archer")                                   # the same eight crests; the region is THIS unit's banner cloth
        path = os.path.join(tex_dir, "archer_emblems.json")
        meta = json.load(open(path))
        zt, y0, y1 = K.TOP - 0.004, K.YC + 0.0015 - 0.003, K.YC + 0.0045 + 0.003
        meta["banner"] = {"blender": {"x0": round(K.X0, 4), "w": K.CLOTH_W, "z_top": round(zt, 4), "h": K.CLOTH_H, "y_min": round(y0, 4), "y_max": round(y1, 4)},
                          "gltf": {"x0": round(K.X0, 4), "w": K.CLOTH_W, "y_top": round(zt, 4), "h": K.CLOTH_H, "z_min": round(-y1, 4), "z_max": round(-y0, 4)}}
        json.dump(meta, open(path, "w"), indent=2)
        print("  emblem sheet:", path)
        print("  cloth descriptor:", cloth.write_runtime(tex_dir, "archer"))
    if arg("--finalize"):
        bpy.context.scene.render.fps = 30                      # the glTF exporter derives clip times from the scene rate
        bpy.context.scene.render.fps_base = 1.0
        from archer import finalize
        from samurai import finalize as SF
        game = bpy.data.collections.new("archer_game")
        bpy.context.scene.collection.children.link(game)
        for o in [arm] + nodes:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            game.objects.link(o)
        body = m["body"]
        body.name = body.data.name = "Archer_LOD0"
        # the hat is its own node at LOD0 and LOD1; far away it is in the mesh (Archer_LOD2), with a second far mesh for a man who has none (Archer_Far_Bare)
        lod_tris = [int(x) for x in arg("--lods", "6800,2400").split(",")]
        finalize.lod_copy(body, "Archer_LOD1", lod_tris[0], arm, game, pre=(m["Sashimono"],), post=(m["Yumi"],))
        finalize.lod_copy(body, "Archer_LOD2", lod_tris[1], arm, game, pre=(m["Sashimono"], m["Helmet"]), post=(m["Yumi_Low"],))
        finalize.lod_copy(body, "Archer_Far_Bare", lod_tris[1], arm, game, pre=(m["Sashimono"],), post=(m["Yumi_Low"],))
        bpy.data.objects.remove(m["Yumi_Low"], do_unlink=True)          # it lives on inside LOD2 only
        bpy.context.view_layer.update()
        for o in game.objects:
            if o.type == "MESH":
                n, bad, mx = SF.weight_report(o)
                print(f"  {o.name}: {tris(o)} tris, {n} verts, unweighted={bad}, max influences={mx}")
        finalize.bake_clips(arm)
    print(f"objects={m['parts']} tris={sum(tris(o) for o in bpy.data.objects if o.type == 'MESH')} bones={len(arm.data.bones)}")
    if arg("--pose"):
        from archer import anim, clips
        from samurai.pose import show_pose
        name, _, tt = arg("--pose").partition("@")
        show_pose(arm, anim.Solver(arm).solve(clips.CLIPS[name]["fn"](float(tt or 0.0))))
        m["Arrow_Nocked"].hide_render = not clips.arrow_at(name, float(tt or 0.0))
        bpy.context.view_layer.update()
    if arg("--render"):
        for o in bpy.data.objects:
            if o.type == "MESH" and (o.name.startswith("Archer_LOD") and o.name != "Archer_LOD0"):
                o.hide_render = True
        if "Yumi_Low" in bpy.data.objects:
            bpy.data.objects["Yumi_Low"].hide_render = True
        base = os.path.join(ROOT, arg("--render"))
        views = arg("--views", "front,back,three_c,head").split(",")
        files = qa.shoot(base, views, res=(int(arg("--w", 700)), int(arg("--h", 1000))))
        qa.montage(files, base + "_sheet.png")
        for f in files:
            os.remove(f)
        print("sheet", base + "_sheet.png")
    if arg("--save"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT, arg("--save")))
    print("ARCHER DONE")


main()
