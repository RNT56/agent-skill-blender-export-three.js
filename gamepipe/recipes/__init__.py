"""Recipe contract (checked by gp_recipe.check_contract and by gp_cli):

A recipe is a module in this package that defines

    META  = {"name": str, "version": str, "needs": [<keys required in spec["recipe_cfg"]>]}
    build(spec: dict, out_dir: str) -> list[dict]

`build` runs inside Blender, creates NEW game-ready objects (never edits the source objects) and returns one
"derived spec" per output asset (usually one per LOD). Each derived spec MUST contain:

    name, type, include_objects (list of object names that now exist), budgets (incl. max_tris), export

The validator then gates every derived spec; only assets with zero errors are exported. Add a recipe by dropping a
module here, a spec under specs/, and a test under tests/. Shared bake/decimate/material helpers live in _common.py.
"""
