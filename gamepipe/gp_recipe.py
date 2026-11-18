"""Recipe contract enforcement (see recipes/__init__.py). Runs inside Blender (needs bpy to confirm objects exist)."""
import bpy

REQUIRED_META = ("name", "version", "needs")
REQUIRED_DERIVED = ("name", "type", "include_objects", "budgets", "export")


def check_recipe_module(mod, spec):
    """Problems with the module/spec BEFORE running it. Returns list of strings."""
    probs = []
    meta = getattr(mod, "META", None)
    if not isinstance(meta, dict) or any(k not in meta for k in REQUIRED_META):
        probs.append(f"recipe '{mod.__name__}' must define META with keys {REQUIRED_META}")
    if not callable(getattr(mod, "build", None)):
        probs.append(f"recipe '{mod.__name__}' must define build(spec, out_dir)")
    cfg = spec.get("recipe_cfg", {})
    for k in (meta or {}).get("needs", []):
        if k not in cfg:
            probs.append(f"spec.recipe_cfg is missing required key '{k}'")
    return probs


def check_derived(derived):
    """Problems with what build() returned. Returns list of strings."""
    probs = []
    if not isinstance(derived, list) or not derived:
        return ["build() must return a non-empty list of derived specs"]
    names = set()
    for d in derived:
        miss = [k for k in REQUIRED_DERIVED if k not in d]
        if miss:
            probs.append(f"derived spec {d.get('name')!r} is missing {miss}")
            continue
        if d["name"] in names:
            probs.append(f"duplicate derived spec name {d['name']!r}")
        names.add(d["name"])
        if "max_tris" not in d["budgets"]:
            probs.append(f"derived spec {d['name']!r} needs budgets.max_tris")
        for o in d["include_objects"]:
            if bpy.data.objects.get(o) is None:
                probs.append(f"derived spec {d['name']!r} lists object {o!r} which does not exist")
    return probs
