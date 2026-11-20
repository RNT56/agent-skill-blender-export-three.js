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


NODES = ("body", "Armour_Oyoroi", "Armour_Kawa", "Helmet", "Helmet_Kawa", "Katana_Drawn", "Katana_Sheathed", "Katana_Saya", "Tachi_Drawn", "Tachi_Sheathed", "Tachi_Saya", "Sashimono")


def main():
    from samurai import build, qa
    from samurai.pose import show_pose
    baked = arg("--bake") is not None
    if baked:
        from samurai import bake, shaders
        from archer import bake as ABk, shaders as AS

        def mat(key):                                          # the face is the archer's (so is the head it is painted on)
            return (bpy.data.materials.get("sam_face") or AS.face("sam_face")) if key == "face" else shaders.procedural(key)

        m = build.build_model(arg("--stage", "all"), mat_fn=mat)
        objs = [m[k] for k in NODES]
        tex_dir = os.path.join(ROOT, arg("--bake"))
        # occlusion per piece: the body is not shaded by a helmet or an armour he may not be wearing; each piece by itself and the body under it.
        # The face, the eyes and the hair get more texels (a bare head is looked at)
        b = m["body"]
        groups = [([b], [])] + [([m[k]], [b]) for k in NODES[1:]]
        ABk.BOOST = {"sam_face": 2.6, "sam_eye": 2.1, "sam_iris": 2.1, "sam_hair": 1.6, "sam_kabuto": 1.2}
        maps = ABk.bake_atlas(objs, tex_dir, "samurai", px=int(arg("--px", 2048)), quality=float(arg("--quality", 1.0)), log=print, ao_groups=groups)
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
        for o in [m[k] for k in NODES]:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            game.objects.link(o)
        body_ob.name = body_ob.data.name = "Samurai_LOD0"
        # LOD1: the body (with the scabbard in it) + the armour's low mesh (the banner is in THAT: he carries it only in armour) + the helmet's low mesh.
        # Far, ONE mesh each: Samurai_LOD2 (armour, banner, helmet), Samurai_Far_Bare (the same, bare-headed), and for a man who has taken his armour off
        # Samurai_Far_Robe_Kabuto / Samurai_Far_Robe_Bare (no armour, no banner).
        lod_tris = [int(x) for x in arg("--lods", "4200,3400,2200,1800").split(",")]
        arm_ob, helm = m["Armour_Oyoroi"], m["Helmet"]
        finalize.decimate_copy(body_ob, "Samurai_LOD1", lod_tris[0], arm, game, extras=(m["Katana_Saya"],))
        finalize.decimate_copy(arm_ob, "Armour_Oyoroi_Low", lod_tris[1], arm, game, extras=(m["Sashimono"],))
        finalize.decimate_copy(helm, "Helmet_Low", lod_tris[3], arm, game)
        far = (arm_ob, m["Katana_Saya"], m["Katana_Sheathed"], m["Sashimono"])
        finalize.decimate_copy(body_ob, "Samurai_LOD2", lod_tris[2], arm, game, extras=far + (helm,))
        finalize.decimate_copy(body_ob, "Samurai_Far_Bare", lod_tris[2], arm, game, extras=far)
        # the rawhide lamellar follows the great armour's scheme: its own low mesh (the banner in it), and far away ONE mesh per helmet. A man in it is a
        # first-age man, so its far meshes carry the tachi (a sliver at that range either way)
        kawa = m["Armour_Kawa"]
        finalize.decimate_copy(kawa, "Armour_Kawa_Low", 1600, arm, game, extras=(m["Sashimono"],))
        kfar = (kawa, m["Tachi_Saya"], m["Tachi_Sheathed"], m["Sashimono"])
        finalize.decimate_copy(body_ob, "Samurai_Far_Kawa_Kabuto", lod_tris[2], arm, game, extras=kfar + (helm,))
        finalize.decimate_copy(body_ob, "Samurai_Far_Kawa_Bare", lod_tris[2], arm, game, extras=kfar)
        robe = (m["Katana_Saya"], m["Katana_Sheathed"])
        finalize.decimate_copy(body_ob, "Samurai_Far_Robe_Kabuto", 1800, arm, game, extras=robe + (helm,))
        finalize.decimate_copy(body_ob, "Samurai_Far_Robe_Bare", 1600, arm, game, extras=robe)
        # the first age's rawhide helmet (Helmet_Kawa): its low mesh, and its far mesh with each armour and with the robe ("KawaKabuto" in the name)
        hk = m["Helmet_Kawa"]
        finalize.decimate_copy(hk, "Helmet_Kawa_Low", 900, arm, game)
        finalize.decimate_copy(body_ob, "Samurai_Far_Oyoroi_KawaKabuto", lod_tris[2], arm, game, extras=far + (hk,))
        finalize.decimate_copy(body_ob, "Samurai_Far_Kawa_KawaKabuto", lod_tris[2], arm, game, extras=kfar + (hk,))
        finalize.decimate_copy(body_ob, "Samurai_Far_Robe_KawaKabuto", 1800, arm, game, extras=robe + (hk,))
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
        for n in (arg("--hide") or "").split(","):                 # --hide Helmet,Armour_Oyoroi: look at what is under a piece
            if n and n in m:
                m[n].hide_render = True
        qa.VIEWS.update({"top": ((0.25, -1.3, 3.5), (0.0, 0.0, 1.50), 80), "head_b": ((-0.55, 0.85, 1.90), (0.0, 0.03, 1.64), 62)})
        views = arg("--views", "front,side,three,head").split(",")
        files = qa.shoot(base, views, res=(int(arg("--w", 600)), int(arg("--h", 900))))
        qa.montage(files, base + "_sheet.png")
        print("sheet", base + "_sheet.png")
    if arg("--save"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT, arg("--save")))


main()
