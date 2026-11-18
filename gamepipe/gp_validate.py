"""gamepipe validator: strict, deterministic checks for game-ready assets.

Runs inside Blender (bpy). Pure functions: validate(spec) -> report dict.
Every finding has: level ("error" | "warn"), code, object, message.
An asset passes only if it has zero errors.
"""
import math
import re
import bpy
import bmesh
from mathutils import Vector

# Rules per asset type. Spec "rules" override these.
TYPE_DEFAULTS = {
    "tree":  {"require_uv": True, "allow_non_manifold": True,  "origin_tolerance": 0.6, "max_height": 60},
    "grass": {"require_uv": True, "allow_non_manifold": True,  "origin_tolerance": 0.05, "max_height": 3},
    "rock":  {"require_uv": True, "allow_non_manifold": False, "origin_tolerance": 0.2, "max_height": 30},
    "prop":  {"require_uv": True, "allow_non_manifold": False, "origin_tolerance": 0.05, "max_height": 30},
    "building": {"require_uv": True, "allow_non_manifold": True, "origin_tolerance": 1.0, "max_height": 120, "tiling_uvs": True},
}
BUDGET_DEFAULTS = {"max_tris": 50000, "max_materials": 4, "max_texture_px": 2048, "max_file_mb": 10.0}
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Shader nodes that glTF can represent from a Principled BSDF (everything else = must be baked)
_OK_TEX_NODES = {"TEX_IMAGE", "NORMAL_MAP", "SEPARATE_COLOR", "SEPARATE_RGB", "MATH", "MIX", "MIX_RGB",
                 "UVMAP", "TEX_COORD", "MAPPING", "BSDF_PRINCIPLED", "OUTPUT_MATERIAL", "VALUE", "RGB"}


def _f(level, code, obj, msg):
    return {"level": level, "code": code, "object": obj, "message": msg}


def resolve_objects(spec):
    names = spec.get("include_objects")
    if names:
        objs = [bpy.data.objects.get(n) for n in names]
        missing = [n for n, o in zip(names, objs) if o is None]
        return [o for o in objs if o], missing
    coll = bpy.data.collections.get(spec.get("source_collection", ""))
    if coll is None:
        return [], [spec.get("source_collection", "<none>")]
    return [o for o in coll.all_objects if o.type in {"MESH", "CURVE", "EMPTY"}], []


def _evaluated_mesh(obj, dg):
    ev = obj.evaluated_get(dg)
    return ev, ev.to_mesh()


def _material_findings(mat, max_px, findings, owner):
    if mat is None:
        findings.append(_f("error", "MAT_EMPTY_SLOT", owner, "empty material slot"))
        return
    if not mat.use_nodes or mat.node_tree is None:
        return  # legacy flat material exports fine
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    if out is None:
        findings.append(_f("error", "MAT_NO_OUTPUT", owner, f"material '{mat.name}' has no active output"))
        return
    # walk upstream from output; anything not glTF-representable must be baked
    # the glTF Material Output group hangs off the graph (not upstream of the output), so scan every node, not just upstream
    seen, stack, bad = set(), [out] + [n for n in nt.nodes if n.type == "GROUP"], set()
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        is_gltf_group = n.type == "GROUP" and n.node_tree is not None and n.node_tree.name.startswith("glTF")
        if n.type not in _OK_TEX_NODES and not is_gltf_group:
            bad.add(n.bl_label)
        for s in n.inputs:
            for l in s.links:
                stack.append(l.from_node)
    # alpha-textured materials should be alpha-CUT (Round node => glTF MASK), not blended (sorting artefacts, no shadows)
    pr = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if pr is not None and pr.inputs["Alpha"].is_linked:
        up, st = [], [pr.inputs["Alpha"].links[0].from_node]
        while st:
            n = st.pop(); up.append(n)
            for s in n.inputs:
                for l in s.links: st.append(l.from_node)
        if not any(n.type == "MATH" and n.operation in {"ROUND", "GREATER_THAN", "LESS_THAN"} for n in up):
            findings.append(_f("warn", "ALPHA_BLENDED", owner,
                               f"material '{mat.name}' will export as alphaMode BLEND; route alpha through a Math>Round node for MASK (cutout)"))
    if bad:
        findings.append(_f("error", "MAT_PROCEDURAL", owner,
                           f"material '{mat.name}' uses nodes glTF cannot carry ({', '.join(sorted(bad))}): bake to textures"))
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            w, h = n.image.size
            if max(w, h) > max_px:
                findings.append(_f("error", "TEX_TOO_LARGE", owner, f"image '{n.image.name}' is {w}x{h}, max {max_px}"))
            if w and h and (w & (w - 1) or h & (h - 1)):
                findings.append(_f("warn", "TEX_NOT_POT", owner, f"image '{n.image.name}' {w}x{h} not power-of-two"))
            if not n.image.has_data and not n.image.packed_file and not n.image.filepath:
                findings.append(_f("error", "TEX_MISSING", owner, f"image '{n.image.name}' has no data"))
            else:
                # a failed bake leaves a flat image; the file exists and has the right size, so check the pixels
                try:
                    import numpy as np
                    arr = np.empty(w * h * 4, dtype=np.float32)
                    n.image.pixels.foreach_get(arr)
                    rgb = arr.reshape(-1, 4)[:, :3]
                    if float(rgb.std(axis=0).max()) < 0.01:
                        findings.append(_f("error", "TEX_BLANK", owner,
                                           f"image '{n.image.name}' is flat (std<0.01): bake probably failed"))
                except Exception:
                    pass


def validate(spec):
    atype = spec.get("type", "prop")
    rules = dict(TYPE_DEFAULTS.get(atype, TYPE_DEFAULTS["prop"]))
    rules.update(spec.get("rules", {}))
    budgets = dict(BUDGET_DEFAULTS)
    budgets.update(spec.get("budgets", {}))

    findings, stats = [], {}
    objs, missing = resolve_objects(spec)
    for m in missing:
        findings.append(_f("error", "SRC_MISSING", m, "object/collection from spec not found"))
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        findings.append(_f("error", "NO_MESH", "-", "asset contains no mesh objects"))
        return _report(spec, findings, stats, budgets, rules)

    dg = bpy.context.evaluated_depsgraph_get()
    total_tris, total_verts = 0, 0
    mats = {}
    bb_min = Vector((1e9, 1e9, 1e9)); bb_max = Vector((-1e9, -1e9, -1e9))
    root = bpy.data.objects.get((spec.get("root_object") or ""))
    root_inv = root.matrix_world.inverted() if root else None

    per_obj = {}
    lod_tris = {}
    for o in meshes:
        # --- naming
        if not NAME_RE.match(o.name):
            findings.append(_f("warn", "NAME_CHARS", o.name, "use only A-Z a-z 0-9 _ in object names"))
        # --- transforms (world-space scale)
        sc = o.matrix_world.to_scale()
        if min(sc) <= 0:
            findings.append(_f("error", "XFORM_NEG_SCALE", o.name, f"negative/zero scale {tuple(round(v,3) for v in sc)}"))
        elif max(sc) - min(sc) > 1e-3:
            findings.append(_f("warn", "XFORM_NONUNIFORM", o.name, f"non-uniform scale {tuple(round(v,3) for v in sc)}: apply scale"))
        elif abs(sc.x - 1.0) > 1e-3:
            findings.append(_f("warn", "XFORM_NONUNIT", o.name, f"scale {sc.x:.3f} is not 1: apply scale"))
        # --- modifiers that don't export as-is
        for md in o.modifiers:
            if md.type == "NODES" and md.show_viewport:
                findings.append(_f("warn", "MOD_GEONODES", o.name,
                                   f"Geometry Nodes '{md.name}' is applied (realized) on export: instance-heavy setups explode in size; "
                                   "export blade/instance meshes and rebuild scattering in engine"))
        # --- evaluated geometry
        ev, me = _evaluated_mesh(o, dg)
        try:
            me.calc_loop_triangles()
            tris = len(me.loop_triangles)
            total_tris += tris; total_verts += len(me.vertices)
            per_obj[o.name] = {"tris": tris, "verts": len(me.vertices)}
            for tag in spec.get("lod_budgets", {}):
                if f"_{tag}_" in o.name or o.name.endswith(f"_{tag}"):
                    lod_tris[tag] = lod_tris.get(tag, 0) + tris
            # --- UVs
            if rules["require_uv"]:
                if not me.uv_layers:
                    findings.append(_f("error", "UV_MISSING", o.name, "no UV map"))
                else:
                    uv = me.uv_layers.active.data
                    oob = sum(1 for l in uv if not (-0.001 <= l.uv.x <= 1.001 and -0.001 <= l.uv.y <= 1.001))
                    if oob and len(uv) and not rules.get("tiling_uvs"):
                        findings.append(_f("warn", "UV_OUT_OF_RANGE", o.name,
                                           f"{oob}/{len(uv)} UV loops outside 0-1 (fine only if tiling is intended)"))
            # --- hygiene (bmesh on evaluated mesh)
            bm = bmesh.new(); bm.from_mesh(me)
            loose_v = sum(1 for v in bm.verts if not v.link_edges)
            loose_e = sum(1 for e in bm.edges if not e.link_faces)
            zero = sum(1 for f in bm.faces if f.calc_area() < 1e-10)
            nonman = sum(1 for e in bm.edges if not e.is_manifold and e.link_faces)
            bm.free()
            if loose_v: findings.append(_f("warn", "MESH_LOOSE_VERTS", o.name, f"{loose_v} loose vertices"))
            if loose_e: findings.append(_f("warn", "MESH_LOOSE_EDGES", o.name, f"{loose_e} wire/loose edges"))
            if zero: findings.append(_f("error", "MESH_ZERO_AREA", o.name, f"{zero} zero-area faces"))
            if nonman and not rules["allow_non_manifold"]:
                findings.append(_f("error", "MESH_NON_MANIFOLD", o.name, f"{nonman} non-manifold edges"))
            # --- bounds in asset space
            mw = o.matrix_world if root_inv is None else root_inv @ o.matrix_world
            for v in me.vertices:
                p = mw @ v.co
                bb_min = Vector((min(bb_min.x, p.x), min(bb_min.y, p.y), min(bb_min.z, p.z)))
                bb_max = Vector((max(bb_max.x, p.x), max(bb_max.y, p.y), max(bb_max.z, p.z)))
        finally:
            ev.to_mesh_clear()
        for slot in o.material_slots:
            mats[slot.material.name if slot.material else f"<empty:{o.name}>"] = (slot.material, o.name)
        if not o.material_slots:
            findings.append(_f("warn", "MAT_NONE", o.name, "no material assigned"))

    # --- budgets
    for tag, lim in spec.get("lod_budgets", {}).items():
        got = lod_tris.get(tag, 0)
        if got == 0:
            findings.append(_f("error", "LOD_MISSING", "-", f"no objects found for {tag} (names must contain '_{tag}_')"))
        elif got > lim:
            findings.append(_f("error", "BUDGET_LOD_TRIS", "-", f"{tag}: {got:,} triangles exceeds its budget {lim:,}"))
    if total_tris > budgets["max_tris"]:
        findings.append(_f("error", "BUDGET_TRIS", "-", f"{total_tris:,} triangles exceeds budget {budgets['max_tris']:,}"))
    if len(mats) > budgets["max_materials"]:
        findings.append(_f("error", "BUDGET_MATERIALS", "-", f"{len(mats)} materials exceeds budget {budgets['max_materials']}"))
    for name, (m, owner) in mats.items():
        _material_findings(m, budgets["max_texture_px"], findings, owner)

    # --- dimensions / origin
    dims = bb_max - bb_min
    height = dims.z
    if height > rules["max_height"] or max(dims) <= 0.02:
        findings.append(_f("error", "DIM_SANITY", "-", f"asset size {tuple(round(v,3) for v in dims)} m looks wrong (units/scale?)"))
    if abs(bb_min.z) > rules["origin_tolerance"]:
        findings.append(_f("warn", "ORIGIN_NOT_AT_BASE", "-",
                           f"lowest point is {bb_min.z:.3f} m from the origin; expected within {rules['origin_tolerance']} m of ground"))
    stats.update({"tris": total_tris, "verts": total_verts, "materials": len(mats),
                  "dimensions_m": [round(v, 3) for v in dims], "bounds_min": [round(v, 3) for v in bb_min],
                  "objects": per_obj, **({"lod_tris": lod_tris} if lod_tris else {})})
    return _report(spec, findings, stats, budgets, rules)


def _report(spec, findings, stats, budgets, rules):
    errors = [f for f in findings if f["level"] == "error"]
    return {"asset": spec.get("name"), "type": spec.get("type"), "passed": not errors,
            "errors": len(errors), "warnings": len(findings) - len(errors),
            "stats": stats, "budgets": budgets, "findings": findings}


def format_report(rep):
    lines = [f"[{'PASS' if rep['passed'] else 'FAIL'}] {rep['asset']} ({rep['type']})  "
             f"{rep['errors']} error(s), {rep['warnings']} warning(s)"]
    s = rep["stats"]
    if s:
        lines.append(f"  tris={s.get('tris'):,} verts={s.get('verts'):,} materials={s.get('materials')} dims_m={s.get('dimensions_m')}")
    for f in sorted(rep["findings"], key=lambda f: (f["level"] != "error", f["code"])):
        lines.append(f"  {f['level'].upper():5} {f['code']:<18} {f['object']:<16} {f['message']}")
    return "\n".join(lines)
