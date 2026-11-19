"""Ashigaru (spear infantry) generator: ONE model that carries every piece of his kit (run inside Blender):
    blender -b --factory-startup -P generators/ashigaru_unit.py -- [options]

The body is whole on its own; armour (hara-ate, okegawa), hats (rawhide, iron), spears (su-yari, nagae-yari), the side arm and the banner are separate nodes, so an
engine dresses each man from what he was issued. Kit in generators/ashigaru/.
  --bake out/ashigaru_tex --px 2048 --quality 1.0   --finalize 1   --save fixtures/ashigaru_unit.blend
  --pose <clip>@<seconds>   --render out/_ashigaru   --views front,back,three_c,head   --kit haraate,jingasa,yari,tanto   (or okegawa, tetsu, bare, long)
In a LIVE session (Blender MCP) use ashigaru.build.build_model(live=True): it works in its own scene and never bakes."""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

KIT = {"haraate": ("Armour_HaraAte",), "okegawa": ("Armour_Okegawa", "Sashimono"), "jingasa": ("Helmet_Jingasa",), "tetsu": ("Helmet_Tetsu",), "bare": (),
       "yari": ("Yari",), "long": ("Yari_Long",), "tanto": ("Side_Tanto",)}


def arg(name, default=None):
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argv[argv.index(name) + 1] if name in argv else default


def tris(o):
    return sum(len(p.vertices) - 2 for p in o.data.polygons)


def main():
    from ashigaru import build
    from samurai import qa
    base = "ashigaru"
    m = build.build_model()
    arm, body = m["arm"], m["body"]
    kit = [m[n] for n in m["nodes"]]
    nodes = [body] + kit
    if arg("--bake") is not None:
        import json
        from ashigaru import bake, cloth
        from samurai import emblems
        from archer import consts as K
        tex_dir = os.path.join(ROOT, arg("--bake"))
        # occlusion per piece: the body is shaded by nothing he may not be wearing; every piece of kit by itself and the body under it
        groups = [([body], [])] + [([o], [body]) for o in kit]
        maps = bake.bake_atlas(nodes, tex_dir, base, px=int(arg("--px", 2048)), quality=float(arg("--quality", 1.0)), log=print, ao_groups=groups)
        bake.assign_baked(nodes, maps, base)
        emblems.write(tex_dir, base)                                       # the banner's crest region (the archer's banner: same cloth, same place)
        path = os.path.join(tex_dir, f"{base}_emblems.json")
        meta = json.load(open(path))
        zt, y0, y1 = K.TOP - 0.004, K.YC + 0.0015 - 0.003, K.YC + 0.0045 + 0.003
        meta["banner"] = {"blender": {"x0": round(K.X0, 4), "w": K.CLOTH_W, "z_top": round(zt, 4), "h": K.CLOTH_H, "y_min": round(y0, 4), "y_max": round(y1, 4)},
                          "gltf": {"x0": round(K.X0, 4), "w": K.CLOTH_W, "y_top": round(zt, 4), "h": K.CLOTH_H, "z_min": round(-y1, 4), "z_max": round(-y0, 4)}}
        json.dump(meta, open(path, "w"), indent=2)
        print("  emblem sheet:", path)
        print("  cloth descriptor:", cloth.write_runtime(tex_dir, base))
    if arg("--finalize"):
        bpy.context.scene.render.fps = 30                      # the glTF exporter derives clip times from the scene rate
        bpy.context.scene.render.fps_base = 1.0
        from ashigaru import finalize
        from samurai import finalize as SF
        game = bpy.data.collections.new("ashigaru_game")
        bpy.context.scene.collection.children.link(game)
        for o in [arm] + nodes:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            game.objects.link(o)
        finalize.make_lods(m, arm, game)
        bpy.context.view_layer.update()
        for o in game.objects:
            if o.type == "MESH":
                n, bad, mx = SF.weight_report(o)
                print(f"  {o.name}: {tris(o)} tris, {n} verts, unweighted={bad}, max influences={mx}")
        finalize.bake_clips(arm)
    print(f"objects={m['parts']} tris={sum(tris(o) for o in bpy.data.objects if o.type == 'MESH')} bones={len(arm.data.bones)}")
    for o in nodes:
        print(f"  {o.name}: {tris(o)} tris")
    if arg("--pose"):
        from ashigaru import anim, clips
        from samurai.pose import show_pose
        name, _, tt = arg("--pose").partition("@")
        show_pose(arm, anim.Solver(arm).solve(clips.CLIPS[name]["fn"](float(tt or 0.0))))
        bpy.context.view_layer.update()
    if arg("--render"):
        want = {"Ashigaru_LOD0"}
        for k in arg("--kit", "haraate,jingasa,yari,tanto").split(","):
            want |= set(KIT[k])
        for o in bpy.data.objects:
            if o.type == "MESH":
                o.hide_render = o.name not in want
        base_r = os.path.join(ROOT, arg("--render"))
        views = arg("--views", "front,back,three_c,head").split(",")
        qa.VIEWS.update({"top": ((0.25, -1.3, 3.5), (0.0, 0.0, 1.50), 80), "head_b": ((-0.55, 0.85, 1.90), (0.0, 0.03, 1.64), 62), "arm_r": ((-1.2, -0.9, 1.35), (-0.36, 0.0, 1.10), 70),
                         "waist": ((0.9, -1.3, 1.25), (0.0, 0.0, 1.10), 55), "waist_b": ((-0.9, 1.3, 1.25), (0.0, 0.0, 1.12), 55)})
        files = qa.shoot(base_r, views, res=(int(arg("--w", 700)), int(arg("--h", 1000))))
        qa.montage(files, base_r + "_sheet.png")
        for f in files:
            os.remove(f)
        print("sheet", base_r + "_sheet.png")
    if arg("--save"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT, arg("--save")))
    print("ASHIGARU DONE")


main()
