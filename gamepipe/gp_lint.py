"""bpy linter: catches the Blender traps that silently burned us, BEFORE the script runs. Plain Python (no Blender).

    python3 gamepipe/gp_lint.py script.py [more.py ...]      exit 1 if any error-level finding

Heuristic by design: it flags likely mistakes, not proofs. Each rule documents the failure it prevents (see GOTCHAS.md).
"""
import ast
import re
import sys

_BPY_NAMES = re.compile(r"(node|socket|obj|ob\b|mat\b|mesh|bone|modifier|collection|image|img)", re.I)


def _name(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return n.attr
    if isinstance(n, ast.Subscript):
        return _name(n.value)
    return ""


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.f = []
        self.loop_depth = 0

    def add(self, node, level, code, msg):
        self.f.append({"line": getattr(node, "lineno", 0), "level": level, "code": code, "message": msg})

    def visit_Compare(self, node):
        for op, right in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Is, ast.IsNot)):
                left = node.left
                consts = (ast.Constant,)
                if isinstance(right, consts) or isinstance(left, consts):
                    continue                       # `x is None` is fine
                if _BPY_NAMES.search(_name(left)) or _BPY_NAMES.search(_name(right)):
                    self.add(node, "error", "BPY_IS_IDENTITY",
                             "`is` on bpy objects/nodes/sockets: bpy returns a fresh Python wrapper on every access, so `is` is "
                             "always False. Use == (this once left no node selected and the bake silently did nothing).")
        self.generic_visit(node)

    def _loop(self, node):
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    visit_For = visit_While = _loop

    def visit_Call(self, node):
        full = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
        if self.loop_depth and full.startswith("bpy.ops.mesh.primitive_"):
            self.add(node, "warn", "BPY_OPS_IN_LOOP",
                     "bpy.ops.mesh.primitive_* inside a loop is slow and churns selection; build with bmesh / bpy.data instead")
        self.generic_visit(node)

    def visit_Assign(self, node):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "result" and not isinstance(node.value, (ast.Dict, ast.Call, ast.Name, ast.DictComp)):
                self.add(node, "warn", "MCP_RESULT_NOT_DICT",
                         "the Blender MCP requires `result` to be a dict (`result = {...}`); a bare str/number/list errors AFTER the code ran")
            if isinstance(t, ast.Attribute) and t.attr == "use_nodes" and isinstance(node.value, ast.Constant) and node.value.value is True:
                self.add(node, "warn", "BPY_USE_NODES", "Material.use_nodes is deprecated (removed in Blender 6.0); fine on 5.3, plan to drop it")
            if isinstance(t, ast.Attribute) and t.attr == "blend_method":
                self.add(node, "error", "BPY_BLEND_METHOD",
                         "blend_method is ignored by the Blender 5.x glTF exporter: alpha mode comes from the node graph "
                         "(alpha -> Math Round -> Principled Alpha gives MASK)")
        self.generic_visit(node)


def lint_source(src):
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [{"line": exc.lineno or 0, "level": "error", "code": "SYNTAX", "message": str(exc)}]
    v = _Visitor()
    v.visit(tree)
    f = v.f

    def has(pattern):
        return re.search(pattern, src) is not None

    if has(r"\.matrix_world|evaluated_get\(|\.bound_box") and has(r"objects\.new\(|\.parent\s*=|\.location\s*=|\.rotation_euler\s*=") \
            and not has(r"view_layer\.update\(|depsgraph.*\.update\(|dg\.update\("):
        f.append({"line": 0, "level": "warn", "code": "BPY_NO_UPDATE",
                  "message": "reads matrix_world/evaluated data after creating or moving objects without bpy.context.view_layer.update(): "
                             "you will read stale transforms"})
    if has(r"bpy\.ops\.object\.(bake|mode_set|modifier_apply|convert|join|origin_set|shade_)") \
            and not has(r"view_layer\.objects\.active\s*="):
        f.append({"line": 0, "level": "warn", "code": "BPY_OPS_NO_ACTIVE",
                  "message": "bpy.ops.object.* needs an ACTIVE object (and selection); set view_layer.objects.active and select_set explicitly"})
    if has(r"bpy\.ops\.object\.bake") and not has(r"nodes\.active\s*="):
        f.append({"line": 0, "level": "error", "code": "BAKE_NO_ACTIVE_NODE",
                  "message": "bake without setting nodes.active: Cycles needs an ACTIVE *and selected* Image Texture node, otherwise it "
                             "prints one INFO line and bakes nothing"})
    if has(r"mode_set\(\s*mode\s*=\s*['\"]EDIT['\"]") and not has(r"mode_set\(\s*mode\s*=\s*['\"]OBJECT['\"]"):
        f.append({"line": 0, "level": "warn", "code": "BPY_EDIT_MODE_LEAK",
                  "message": "enters Edit mode but never returns to Object mode; later data access and export will misbehave"})
    if has(r"FunctionNodeRandomValue") and has(r"\.inputs\[\s*\d+\s*\]"):
        f.append({"line": 0, "level": "warn", "code": "GN_INDEX_SOCKETS",
                  "message": "Random Value (and Math/Mix) nodes have several same-named sockets; filter by name AND .enabled, not index"})
    if has(r"GeometryNodeDistributePointsOnFaces") and has(r"Density Factor") and not has(r"POISSON"):
        f.append({"line": 0, "level": "error", "code": "GN_DENSITY_FACTOR",
                  "message": "'Density Factor' only exists in POISSON mode. In RANDOM mode 'Density' is the field (multiply your mask in), "
                             "and it is evaluated PER FACE: a single-quad emitter gives one value for the whole plane"})
    return sorted(f, key=lambda x: (x["level"] != "error", x["line"]))


def lint_file(path):
    with open(path) as fh:
        return lint_source(fh.read())


if __name__ == "__main__":
    bad = False
    for p in sys.argv[1:]:
        for x in lint_file(p):
            print(f"{p}:{x['line']}: {x['level'].upper()} {x['code']}: {x['message']}")
            bad |= x["level"] == "error"
    sys.exit(1 if bad else 0)
