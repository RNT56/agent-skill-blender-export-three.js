"""The villager unit: an image-to-3D mesh (reference image -> Tripo H3.1) turned into a rigged, animated, game-ready character.

    blender -b --factory-startup -P generators/villager_unit.py -- --stage <stage> [--name villager_unit_02] [options]

Stages (each reads what the one before saved in --work, default /Volumes/△/_scratch/claude-villager-<date>/ or $VILLAGER_WORK):
    ingest   --src <tripo.glb>            clean, orient, scale the high-poly source           -> villager_high.blend, ingest.json, qa/
    lowpoly  [--tris 11000] [--px 2048]   LOD0 from the high poly + new UVs + baked atlas     -> villager_low.blend, tex/, villager_low.glb
    rig      --rig <meshy_rigged.glb>     adopt the auto-rig, rename, add hand / prop bones   -> villager_rig.blend
    atlas    [--px 2048]                  body-part UV charts + the real bake                 -> villager_skin.blend, tex/
    clips    [--mocap <dir>]              mocap bases + authored work clips                   -> villager_anim.blend
    finalize                              LODs, props, team mask, fixture                     -> fixtures/villager_unit.blend
See docs/villager.md.
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
    out = {}
    i = 0
    while i < len(a):
        if a[i].startswith("--"):
            k = a[i][2:]
            if i + 1 < len(a) and not a[i + 1].startswith("--"):
                out[k] = a[i + 1]
                i += 2
            else:
                out[k] = "1"
                i += 1
        else:
            i += 1
    return out


def main():
    A = args()
    from villager import variants
    name = A.get("name", "villager_unit_01")                 # which body (generators/villager/variants.py)
    cfg = variants.get(name)
    work = A.get("work") or os.environ.get("VILLAGER_WORK")
    if not work:
        raise SystemExit("--work <dir> (or $VILLAGER_WORK) is required")
    if name != "villager_unit_01" and os.path.basename(os.path.normpath(work)) != name:
        work = os.path.join(work, name)                      # every body has its own intermediates
    os.makedirs(work, exist_ok=True)
    stage = A.get("stage", "")
    rel = lambda p: p if os.path.isabs(p) else os.path.join(ROOT, p)
    if stage == "ingest":
        from villager import ingest
        ingest.run(rel(A.get("src", cfg["src"])), work, height=float(A.get("height", cfg["height"])))
    elif stage == "lowpoly":
        from villager import lowpoly
        lowpoly.run(work, tris=int(A.get("tris", 11500)), px=int(A.get("px", 2048)), samples=int(A.get("samples", 8)), hand_x=cfg["hand_x"])
    elif stage == "rig":
        from villager import rig
        rig.run(work, rel(A.get("rig", os.path.join(cfg["mocap"], "idle_3.glb"))))
    elif stage == "atlas":
        from villager import atlas
        atlas.run(work, px=int(A.get("px", 2048)), samples=int(A.get("samples", 48)))
    elif stage == "clips":
        from villager import clips
        clips.run(work, rel(A.get("mocap", cfg["mocap"])), only=A.get("only"), cfg=cfg)
    elif stage == "finalize":
        from villager import finalize
        sp = variants.spec(name)
        import json
        with open(os.path.join(ROOT, "specs", name + ".json"), "w") as fh:
            json.dump(sp, fh, indent=1)
        finalize.run(work, rel(A.get("save", sp["source_blend"])), cfg=cfg)
    else:
        raise SystemExit("unknown --stage " + repr(stage))
    print("VILLAGER STAGE", stage, "OK")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        print("VILLAGER STAGE FAILED")
        sys.exit(1)
