"""gamepipe entry point (run inside Blender).

Headless (default, always for anything slow):
    blender -b scene.blend -P gamepipe/gp_cli.py -- specs/x.json [--report-only] [--no-preview] [--out DIR]
Live Blender session: use gp_live.run_headless_from_live(spec_path)  (saves a copy, runs the line above)

Flow: recipe builds derived assets (if the spec names one) -> contract check -> validate each -> only if zero errors
      export GLB -> size budget -> inspect the GLB file itself -> manifest.json -> preview renders of uncompressed twins.
Output: <repo>/out/<asset>/  (GLBs, textures/, *.report.json, manifest.json, *.preview.png). Exit 0 = pass, 1 = fail.
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import gp_export
import gp_glb
import gp_recipe
import gp_validate


def _fail(rep, code, msg):
    rep["findings"].append({"level": "error", "code": code, "object": "-", "message": msg})
    rep["errors"] += 1
    rep["passed"] = False


def run_asset(spec, out_dir, report_only=False):
    rep = gp_validate.validate(spec)
    rep["export"] = None
    rep["lod"] = spec.get("lod")
    if rep["passed"] and not report_only:
        exp = gp_export.export_glb(spec, out_dir)
        rep["export"] = exp
        limit = rep["budgets"]["max_file_mb"]
        if exp["size_mb"] > limit:
            _fail(rep, "BUDGET_FILE_SIZE", f"exported file {exp['size_mb']} MB exceeds budget {limit} MB")
        for f in gp_glb.check(exp["path"], spec.get("glb_expect")):
            rep["findings"].append(f)
            if f["level"] == "error":
                rep["errors"] += 1
                rep["passed"] = False
            else:
                rep["warnings"] += 1
        rep["glb"] = gp_glb.inspect(exp["path"])
    with open(os.path.join(out_dir, f"{spec['name']}.report.json"), "w") as fh:
        json.dump(rep, fh, indent=2)
    print(gp_validate.format_report(rep))
    if rep["export"]:
        print("  exported:", {k: v for k, v in rep["export"].items() if k != "dropped_options"})
    return rep


def run(spec_path, report_only=False, preview=True, out_override=None):
    with open(spec_path) as fh:
        spec = json.load(fh)
    out_root = out_override or os.path.join(ROOT, spec.get("export", {}).get("out_dir", "out"))
    out_dir = os.path.join(out_root, spec["name"])
    os.makedirs(out_dir, exist_ok=True)

    if "recipe" in spec:
        recipe = importlib.import_module(f"recipes.{spec['recipe']}")
        importlib.reload(recipe)
        probs = gp_recipe.check_recipe_module(recipe, spec)
        if probs:
            print("RECIPE CONTRACT VIOLATION:\n  " + "\n  ".join(probs))
            return {"passed": False, "reports": [], "export": None, "contract": probs}
        specs = recipe.build(spec, out_dir)
        probs = gp_recipe.check_derived(specs)
        if probs:
            print("RECIPE OUTPUT VIOLATION:\n  " + "\n  ".join(probs))
            return {"passed": False, "reports": [], "export": None, "contract": probs}
    else:
        specs = [spec]

    reports = [run_asset(s, out_dir, report_only) for s in specs]
    passed = all(r["passed"] for r in reports)

    if not report_only:
        lods = []
        for r in reports:
            ex = r["export"]
            if r["stats"].get("lod_tris"):                       # one GLB holding several LODs (shared textures)
                for tag, tr in sorted(r["stats"]["lod_tris"].items()):
                    lods.append({"name": tag, "asset": r["asset"], "file": os.path.basename(ex["path"]) if ex else None, "pack": True,
                                 "tris": tr, "size_mb": ex["size_mb"] if ex else None, "compressed": ex["compressed"] if ex else None,
                                 "passed": r["passed"], "dimensions_m": r["stats"].get("dimensions_m")})
            else:
                lods.append({"name": r.get("lod") or r["asset"], "asset": r["asset"], "file": os.path.basename(ex["path"]) if ex else None,
                             "tris": r["stats"].get("tris"), "size_mb": ex["size_mb"] if ex else None,
                             "compressed": ex["compressed"] if ex else None, "passed": r["passed"],
                             "dimensions_m": r["stats"].get("dimensions_m")})
        manifest = {"asset": spec["name"], "recipe": spec.get("recipe"), "passed": passed, "look": spec.get("look", "golden_hour"),
                    "lods": lods}
        cj = os.path.join(out_dir, "clips.json")
        if os.path.exists(cj):
            with open(cj) as fh:
                manifest["clips"] = json.load(fh)
        with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)

    if preview and spec.get("preview", True) and not report_only and passed:
        try:
            import copy
            import gp_preview
            twins = []
            pdir = os.path.join(out_dir, "_preview")
            os.makedirs(pdir, exist_ok=True)
            for s in specs:                      # compressed GLBs may not re-import: preview uncompressed twins
                t = copy.deepcopy(s)
                t.setdefault("export", {})["compress"] = False
                twins.append(gp_export.export_glb(t, pdir)["path"])
            gp_preview.render_previews(twins, out_dir, look=spec.get("look", "golden_hour"))
        except Exception as exc:                 # preview must never fail the pipeline
            print("preview skipped:", exc)

    print(f"\n== {spec['name']}: {'ALL PASS' if passed else 'FAILED'} ({len(reports)} asset(s)) -> {out_dir} ==")
    return reports[0] if len(reports) == 1 else {"passed": passed, "reports": reports, "export": None}


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if not argv:
        print("usage: blender -b file.blend -P gamepipe/gp_cli.py -- spec.json [--report-only] [--no-preview] [--out DIR]")
        sys.exit(2)
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    result = run(argv[0], report_only="--report-only" in argv, preview="--no-preview" not in argv, out_override=out)
    sys.exit(0 if result["passed"] else 1)
