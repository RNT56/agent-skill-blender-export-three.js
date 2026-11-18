"""Samurai unit generator (run inside Blender):  blender -b --factory-startup -P generators/samurai_unit.py -- [options]

Builds the A-pose rest model (soft body layers + armour + katana), the 53-bone armature and skin weights, then optional QA:
  --stage body|all   --pose bow|twist|arms_up|reach|lunge|squat   --render out/_samurai   --views front,side,...   --save fixtures/samurai_unit.blend
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


def main():
    from samurai import build, qa
    from samurai.pose import show_pose
    baked = arg("--bake") is not None
    if baked:
        from samurai import bake, shaders
        m = build.build_model(arg("--stage", "all"), mat_fn=shaders.procedural)
        objs = [m[k] for k in ("body", "Katana_Drawn", "Katana_Sheathed", "Katana_Saya", "Sashimono")]
        tex_dir = os.path.join(ROOT, arg("--bake"))
        maps = bake.bake_atlas(objs, tex_dir, "samurai", px=int(arg("--px", 2048)), quality=float(arg("--quality", 1.0)), log=print)
        bake.assign_baked(objs, maps, "samurai")
        from samurai import emblems
        print("  emblem sheet:", emblems.write(tex_dir, "samurai"))
        from samurai import cloth as _cloth
        print("  cloth descriptor:", _cloth.write_runtime(tex_dir, "samurai"))        # what the engine needs to add the world's wind on top of the dry-baked cloth     # the faction crests the engine draws on the banner cloth (the atlas carries none)
    else:
        m = build.build_model(arg("--stage", "all"))
    arm = m["arm"]
    if arg("--finalize"):
        bpy.context.scene.render.fps = 30                      # the glTF exporter derives clip times from the scene rate
        bpy.context.scene.render.fps_base = 1.0
        from samurai import finalize
        game = bpy.data.collections.new("samurai_game")
        bpy.context.scene.collection.children.link(game)
        for o in list(m["arm"].users_collection):
            o.objects.unlink(m["arm"])
        game.objects.link(m["arm"])
        body_ob = m["body"]
        for o in (body_ob, m["Katana_Drawn"], m["Katana_Sheathed"], m["Katana_Saya"], m["Sashimono"]):
            for c in list(o.users_collection):
                c.objects.unlink(o)
            game.objects.link(o)
        body_ob.name = body_ob.data.name = "Samurai_LOD0"
        lod_tris = [int(x) for x in arg("--lods", "7000,2200").split(",")]
        # the scabbard is part of the body mesh from LOD1 on (one draw call fewer per unit at range); LOD2 also carries the sheathed hilt
        extras_by_lod = {1: (m["Katana_Saya"], m["Sashimono"]), 2: (m["Katana_Saya"], m["Katana_Sheathed"], m["Sashimono"])}
        for k, t in enumerate(lod_tris, start=1):
            finalize.decimate_copy(body_ob, f"Samurai_LOD{k}", t, arm, game, extras=extras_by_lod.get(k, ()))
        for o in game.objects:
            if o.type == "MESH":
                n, bad, mx = finalize.weight_report(o)
                print(f"  {o.name}: {sum(len(p.vertices) - 2 for p in o.data.polygons)} tris, {n} verts, unweighted={bad}, max influences={mx}")
        finalize.bake_clips(arm)
        arm.pose.bones[0].keyframe_insert  # keep linter quiet about unused
    tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in bpy.data.objects if o.type == "MESH")
    print(f"objects={m['parts']} tris={tris} bones={len(arm.data.bones)}")
    if arg("--pose"):
        show_pose(arm, build.demo_pose(arm, arg("--pose")))
        bpy.context.view_layer.update()
    if arg("--clip"):
        from samurai import anim, clips
        sv = anim.Solver(arm)
        c = clips.CLIPS[arg("--clip")]
        nfr = int(arg("--frames", 6))
        view = arg("--view", "side")
        cam = qa.setup_scene((int(arg("--w", 420)), int(arg("--h", 560))), 12)
        loc, tgt, lens = qa.VIEWS[view]
        sc = bpy.context.scene
        files = []
        for i in range(nfr):
            t = c["duration"] * (i / nfr if c["loop"] else i / max(nfr - 1, 1))
            drawn = clips.weapon_at(arg("--clip"), t) == "drawn"
            m["Katana_Drawn"].hide_render = not drawn
            m["Katana_Sheathed"].hide_render = drawn
            show_pose(arm, sv.solve(c["fn"](t)))
            bpy.context.view_layer.update()
            cam.data.lens = lens
            cam.location = loc
            from mathutils import Vector as _V
            cam.rotation_euler = (_V(tgt) - _V(loc)).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = os.path.join(ROOT, f"out/_clip_{arg('--clip')}_{i}.png")
            bpy.ops.render.render(write_still=True)
            files.append(sc.render.filepath)
        qa.montage(files, os.path.join(ROOT, f"out/_clip_{arg('--clip')}_{view}.png"), cols=int(arg("--cols", nfr)))
        print("clip sheet", f"out/_clip_{arg('--clip')}_{view}.png")
    if arg("--render"):
        base = os.path.join(ROOT, arg("--render"))
        views = arg("--views", "front,side,three,head").split(",")
        files = qa.shoot(base, views, res=(int(arg("--w", 600)), int(arg("--h", 900))))
        qa.montage(files, base + "_sheet.png")
        print("sheet", base + "_sheet.png")
    if arg("--save"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT, arg("--save")))


main()
