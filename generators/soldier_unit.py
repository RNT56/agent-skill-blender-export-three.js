"""Soldier units from image-to-3D meshes (ashigaru v2 first): one man, several complete bodies (one per body armour, one without), rigid kit pieces, ONE skeleton.

    blender -b --factory-startup -P generators/soldier_unit.py -- --unit ashigaru --stage <stage> [--body bare|levy|okegawa] --work <scratch dir>

Stages (per body unless noted; each reads what the one before saved in <work>/<unit>/<body>/):
    ingest    clean, orient, scale the high-poly source                    (villager.ingest)
    lowpoly   LOD0 by protected decimation + a throwaway bake for the auto-rig upload   (villager.lowpoly)
    rig       the auto-rig's joints and weights on a clean armature, measured hands        (villager.rig; needs fixtures/<unit>_src/meshy/<body>_idle.glb)
    atlas     body-part UV charts + the real bake high -> low, with metalness               (villager.atlas + soldier.bake)
See generators/soldier/variants.py for the bodies; later stages are in generators/soldier/.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, os.path.join(ROOT, "gamepipe")):
    if p not in sys.path:
        sys.path.insert(0, p)


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out, i = {}, 0
    while i < len(a):
        if a[i].startswith("--"):
            if i + 1 < len(a) and not a[i + 1].startswith("--"):
                out[a[i][2:]] = a[i + 1]
                i += 2
            else:
                out[a[i][2:]] = "1"
                i += 1
        else:
            i += 1
    return out


def main():
    A = args()
    from soldier import variants
    cfg = variants.get(A.get("unit", "ashigaru"))
    work = A.get("work") or os.environ.get("SOLDIER_WORK")
    if not work:
        raise SystemExit("--work <dir> (or $SOLDIER_WORK) is required")
    stage = A.get("stage", "")
    rel = lambda p: p if os.path.isabs(p) else os.path.join(ROOT, p)
    bodies = [A["body"]] if "body" in A else list(cfg["bodies"])
    if stage in ("ingest", "lowpoly", "rig", "atlas"):
        for b in bodies:
            w = os.path.join(work, cfg["unit"], b)
            os.makedirs(w, exist_ok=True)
            if stage == "ingest":
                from villager import ingest
                ingest.run(rel(os.path.join(cfg["src_dir"], cfg["bodies"][b]["src"])), w, height=float(A.get("height", cfg["height"])))
            elif stage == "lowpoly":
                from villager import lowpoly
                lowpoly.run(w, tris=int(A.get("tris", cfg["tris"])), px=int(A.get("px", 2048)), samples=int(A.get("samples", 8)), hand_x=None)
            elif stage == "atlas":                           # body-part UV charts over the WHOLE square (a body has its own quarter of the unit's atlas) + the real bake, with metal
                from villager import lowpoly
                from soldier import bake
                lowpoly.BODY_V0 = 0.0
                lowpoly.bake_all = bake.bake_all
                from villager import atlas
                from soldier import atlasfix
                atlasfix.install(atlas)
                atlas.run(w, px=int(A.get("px", 2048)), samples=int(A.get("samples", 48)))
            else:                                            # the auto-rig of THIS body's LOD0 (fixtures/<unit>_src/meshy/<body>_idle.glb): joints, weights, measured hands
                from villager import rig
                rig.run(w, rel(os.path.join(cfg["src_dir"], "meshy", b + "_idle.glb")))
            print("SOLDIER", cfg["unit"], b, stage, "OK")
    else:
        from soldier import stages
        stages.run(stage, cfg, work, A, rel)
    print("SOLDIER STAGE", stage, "OK")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        print("SOLDIER STAGE FAILED")
        sys.exit(1)
