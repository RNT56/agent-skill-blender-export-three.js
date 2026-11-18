#!/usr/bin/env python3
"""Assemble a self-contained three.js game folder from blend-up outputs (plain Python, no Blender, no dependencies).

    python3 tools/export_world.py --dest ../my-game \
        --models grass_blades samurai_keep_01 tree_autumn_01 tree_maple_01 tree_sakura_01 \
        --biomes meadow dry_grass forest_floor rocky_gravel dirt_road sakura_petals zen_gravel

Copies:   runtime/*.js            -> <dest>/src/runtime/
          looks/*.json            -> <dest>/assets/looks/
          out/<model>/*.glb       -> <dest>/assets/models/        (+ writes assets/models/<model>.manifest.json)
          out/textures/<biome>_*  -> <dest>/assets/textures/biomes/
Refuses to export a model whose manifest says passed=false (the gate applies to hand-off too). Never touches anything else in <dest>.
"""
import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True)
    ap.add_argument("--models", nargs="*", default=[])
    ap.add_argument("--biomes", nargs="*", default=[])
    a = ap.parse_args()
    dest = os.path.abspath(a.dest)
    bad = []
    for m in a.models:
        mf = os.path.join(ROOT, "out", m, "manifest.json")
        if not os.path.exists(mf):
            bad.append(f"{m}: no manifest (run bin/gp build first)")
        elif not json.load(open(mf)).get("passed"):
            bad.append(f"{m}: manifest says passed=false")
    if bad:
        print("REFUSING TO EXPORT:\n  " + "\n  ".join(bad))
        return 1
    rt = os.path.join(dest, "src", "runtime")
    os.makedirs(rt, exist_ok=True)
    for f in os.listdir(os.path.join(ROOT, "runtime")):
        if f.endswith(".js"):
            shutil.copy2(os.path.join(ROOT, "runtime", f), os.path.join(rt, f))
    lk = os.path.join(dest, "assets", "looks")
    os.makedirs(lk, exist_ok=True)
    for f in os.listdir(os.path.join(ROOT, "looks")):
        shutil.copy2(os.path.join(ROOT, "looks", f), os.path.join(lk, f))
    md = os.path.join(dest, "assets", "models")
    os.makedirs(md, exist_ok=True)
    total = 0
    for m in a.models:
        src = os.path.join(ROOT, "out", m)
        for f in sorted(os.listdir(src)):
            if f.endswith(".glb"):
                shutil.copy2(os.path.join(src, f), os.path.join(md, f))
                total += os.path.getsize(os.path.join(md, f))
        shutil.copy2(os.path.join(src, "manifest.json"), os.path.join(md, f"{m}.manifest.json"))
    tx = os.path.join(dest, "assets", "textures", "biomes")
    os.makedirs(tx, exist_ok=True)
    for b in a.biomes:
        for k in ("albedo.jpg", "normal.png", "orm.png"):
            shutil.copy2(os.path.join(ROOT, "out", "textures", f"{b}_{k}"), os.path.join(tx, f"{b}_{k}"))
            total += os.path.getsize(os.path.join(tx, f"{b}_{k}"))
    print(f"exported {len(a.models)} models + {len(a.biomes)} biomes ({total / 1048576:.1f} MB) -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
