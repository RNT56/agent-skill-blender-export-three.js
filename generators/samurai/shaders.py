"""Procedural PBR materials for the samurai (Cycles-bakeable node graphs). Pattern UV 'pat' units: lamellar = plate / row units,
cloth and tubes = metres. Colours are scene-linear. Every graph ends in ONE Principled BSDF so albedo / roughness / metallic /
normal can be baked and exported as glTF PBR."""
import bpy

CRIMSON = (0.24, 0.012, 0.020, 1)
NAVY = (0.016, 0.030, 0.115, 1)
INDIGO = (0.012, 0.020, 0.058, 1)


class NB:
    def __init__(self, name):
        self.mat = bpy.data.materials.new(name)
        self.mat.use_nodes = True
        self.nt = self.mat.node_tree
        self.nt.nodes.clear()
        self.n = self.nt.nodes
        self.l = self.nt.links
        self._x = 0

    # --- low level
    def node(self, typ, **attrs):
        nd = self.n.new(typ)
        for k, v in attrs.items():
            setattr(nd, k, v)
        return nd

    def put(self, nd, **inputs):
        for k, v in inputs.items():
            sock = next((s for s in nd.inputs if s.name == k.replace("_", " ") and s.enabled), None)
            if sock is None:
                raise KeyError(f"{nd.bl_idname}: no input {k}")
            if isinstance(v, bpy.types.NodeSocket):
                self.l.new(v, sock)
            elif sock.type == "RGBA":
                sock.default_value = v if len(v) == 4 else (*v, 1.0)
            elif sock.type == "VECTOR":
                sock.default_value = v
            else:
                sock.default_value = v
        return nd

    def out(self, nd, name=None):
        if name:
            return next(s for s in nd.outputs if s.name == name)
        return nd.outputs[0]

    # --- value helpers (return output sockets)
    def math(self, op, a, b=None, c=None, clamp=False):
        nd = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                self.l.new(v, nd.inputs[i])
            else:
                nd.inputs[i].default_value = v
        return nd.outputs[0]

    def mix(self, fac, a, b):
        nd = self.node("ShaderNodeMix", data_type="RGBA")
        f = next(s for s in nd.inputs if s.name == "Factor" and s.type == "VALUE")
        sa = next(s for s in nd.inputs if s.name == "A" and s.type == "RGBA")
        sb = next(s for s in nd.inputs if s.name == "B" and s.type == "RGBA")
        for s, v in ((f, fac), (sa, a), (sb, b)):
            if isinstance(v, bpy.types.NodeSocket):
                self.l.new(v, s)
            else:
                s.default_value = v if (s.type != "RGBA" or len(v) == 4) else (*v, 1.0)
        return next(s for s in nd.outputs if s.type == "RGBA")

    def mixf(self, fac, a, b):
        return self.math("ADD", self.math("MULTIPLY", a, self.math("SUBTRACT", 1.0, fac)), self.math("MULTIPLY", b, fac))

    def smoothstep(self, lo, hi, x):
        nd = self.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP", clamp=True)
        self.put(nd, Value=x)
        for nm, v in (("From Min", lo), ("From Max", hi)):
            if isinstance(v, bpy.types.NodeSocket):
                self.l.new(v, nd.inputs[nm])
            else:
                nd.inputs[nm].default_value = v
        return nd.outputs["Result"]

    def remap(self, x, a, b, c, d):
        nd = self.node("ShaderNodeMapRange", interpolation_type="LINEAR", clamp=True)
        self.put(nd, Value=x)
        nd.inputs["From Min"].default_value, nd.inputs["From Max"].default_value = a, b
        nd.inputs["To Min"].default_value, nd.inputs["To Max"].default_value = c, d
        return nd.outputs["Result"]

    def uv(self, name="pat"):
        nd = self.node("ShaderNodeUVMap", uv_map=name)
        sep = self.node("ShaderNodeSeparateXYZ")
        self.l.new(nd.outputs["UV"], sep.inputs["Vector"])
        return nd.outputs["UV"], sep.outputs["X"], sep.outputs["Y"]

    def obj(self):
        tc = self.node("ShaderNodeTexCoord")
        sep = self.node("ShaderNodeSeparateXYZ")
        self.l.new(tc.outputs["Object"], sep.inputs["Vector"])
        return tc.outputs["Object"], sep.outputs["Z"]

    def noise(self, vec, scale, detail=4.0, rough=0.55, distort=0.0):
        nd = self.node("ShaderNodeTexNoise", noise_dimensions="3D")
        self.put(nd, Vector=vec, Scale=scale, Detail=detail, Roughness=rough, Distortion=distort)
        return nd.outputs["Fac"]

    def stretched(self, uvvec, sx, sy, scale, detail=3.0):
        """Noise stretched along one UV axis (brush strokes, fibres, scratches)."""
        mp = self.node("ShaderNodeMapping")
        self.put(mp, Vector=uvvec, Scale=(sx, sy, 1.0))
        return self.noise(mp.outputs["Vector"], scale, detail)

    def voronoi(self, vec, scale, feature="F1", out="Distance"):
        nd = self.node("ShaderNodeTexVoronoi", feature=feature)
        self.put(nd, Vector=vec, Scale=scale)
        return nd.outputs[out]

    def edge_wear(self, radius=0.0022, power=1.0):
        geo = self.node("ShaderNodeNewGeometry")
        bev = self.node("ShaderNodeBevel", samples=6)
        bev.inputs["Radius"].default_value = radius
        dot = self.node("ShaderNodeVectorMath", operation="DOT_PRODUCT")
        self.l.new(geo.outputs["Normal"], dot.inputs[0])
        self.l.new(bev.outputs["Normal"], dot.inputs[1])
        e = self.math("SUBTRACT", 1.0, dot.outputs["Value"])
        return self.smoothstep(0.0, 0.18, self.math("MULTIPLY", e, 6.0 * power))

    def ao_dirt(self, dist=0.04):
        ao = self.node("ShaderNodeAmbientOcclusion", samples=8, inside=False)
        ao.inputs["Distance"].default_value = dist
        return ao.outputs["AO"]

    def bump(self, height, strength=1.0, dist=0.002):
        nd = self.node("ShaderNodeBump")
        self.put(nd, Height=height, Strength=strength, Distance=dist)
        return nd.outputs["Normal"]

    def finish(self, color, rough, metal, normal=None, spec=0.5, team=0.0):
        """`team` (0..1, float or socket) is baked into the team-colour mask: 1 = the engine may tint this texel (lacing, sash)."""
        em = self.node("ShaderNodeEmission")
        em.name = "TEAM"
        if isinstance(team, bpy.types.NodeSocket):
            self.l.new(team, em.inputs["Color"])
        else:
            em.inputs["Color"].default_value = (team, team, team, 1.0)
        p = self.node("ShaderNodeBsdfPrincipled")
        self.put(p, Base_Color=color, Roughness=rough, Metallic=metal)
        p.inputs["Specular IOR Level"].default_value = spec
        if normal is not None:
            self.l.new(normal, p.inputs["Normal"])
        o = self.node("ShaderNodeOutputMaterial")
        self.l.new(p.outputs["BSDF"], o.inputs["Surface"])
        return self.mat


# ------------------------------------------------------------------------------------------------------------- materials
def lamellar(name="sam_lamellar"):
    b = NB(name)
    _, u, v = b.uv()
    uvv, _, _ = b.uv()
    objv, oz = b.obj()
    d = b.math("ABSOLUTE", b.math("SUBTRACT", u, b.math("ROUND", u)))             # distance to the nearest plate edge (0..0.5)
    cord = b.math("SUBTRACT", 1.0, b.smoothstep(0.070, 0.110, d))
    fv = b.math("FRACT", v)
    band_d = b.math("MINIMUM", fv, b.math("SUBTRACT", 1.0, fv))
    band = b.math("SUBTRACT", 1.0, b.smoothstep(0.050, 0.085, band_d))
    parity = b.math("MODULO", b.math("ROUND", u), 2.0)
    cord_col = b.mix(parity, CRIMSON, NAVY)
    band_col = b.mix(parity, NAVY, CRIMSON)
    n1 = b.noise(objv, 90.0, 5.0)
    plate = b.mix(b.smoothstep(0.35, 0.7, n1), (0.010, 0.010, 0.013, 1), (0.020, 0.021, 0.027, 1))
    wear = b.edge_wear(0.0022, 1.1)
    plate = b.mix(b.math("MULTIPLY", wear, b.math("SUBTRACT", 1.0, cord)), plate, (0.16, 0.15, 0.14, 1))
    col = b.mix(band, plate, band_col)
    col = b.mix(cord, col, cord_col)
    # braid texture in the cords: twisted-rope stripes along v
    braid = b.math("SINE", b.math("ADD", b.math("MULTIPLY", v, 60.0), b.math("MULTIPLY", u, 20.0)))
    scratch = b.stretched(uvv, 0.2, 14.0, 22.0, 3.0)
    dust = b.math("MULTIPLY", b.smoothstep(0.55, 0.85, b.noise(objv, 14.0, 3.0)), b.smoothstep(1.2, 0.7, oz))
    col = b.mix(b.math("MULTIPLY", dust, 0.35), col, (0.075, 0.055, 0.035, 1))
    knot = b.math("MULTIPLY", cord, band)
    height = b.math("ADD", b.math("MULTIPLY", cord, 0.55),
                    b.math("ADD", b.math("MULTIPLY", band, 0.30), b.math("ADD", b.math("MULTIPLY", knot, 0.35),
                           b.math("MULTIPLY", b.math("MULTIPLY", braid, cord), 0.10))))
    height = b.math("ADD", height, b.math("MULTIPLY", scratch, 0.05))
    n = b.bump(height, 1.4, 0.0016)
    rough = b.math("ADD", b.mixf(b.math("MAXIMUM", cord, band), 0.26, 0.78), b.math("MULTIPLY", scratch, 0.18))
    return b.finish(col, rough, 0.0, n, team=b.math("MAXIMUM", cord, band))


def lacquer(name="sam_lacquer"):
    b = NB(name)
    objv, oz = b.obj()
    n1 = b.noise(objv, 160.0, 5.0)
    wear = b.edge_wear(0.0025, 1.3)
    base = b.mix(b.smoothstep(0.35, 0.65, n1), (0.007, 0.007, 0.010, 1), (0.016, 0.017, 0.022, 1))
    col = b.mix(b.math("MULTIPLY", wear, 0.85), base, (0.12, 0.115, 0.11, 1))
    dust = b.math("MULTIPLY", b.smoothstep(0.55, 0.85, b.noise(objv, 12.0, 3.0)), b.smoothstep(1.3, 0.7, oz))
    col = b.mix(b.math("MULTIPLY", dust, 0.30), col, (0.07, 0.05, 0.035, 1))
    fine = b.noise(objv, 900.0, 2.0)
    n = b.bump(b.math("MULTIPLY", fine, 0.25), 0.6, 0.0012)
    rough = b.math("ADD", 0.20, b.math("ADD", b.math("MULTIPLY", wear, 0.3), b.math("MULTIPLY", b.noise(objv, 40.0, 3.0), 0.22)))
    return b.finish(col, rough, 0.0, n)


def hemp(name="sam_hemp", team=0.0):
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    p = 0.0042                                                                        # thread pitch (m)
    wu = b.math("SINE", b.math("MULTIPLY", u, 6.2832 / p))
    wv = b.math("SINE", b.math("MULTIPLY", v, 6.2832 / p))
    weave = b.math("ADD", b.math("MULTIPLY", wu, wv), b.math("MULTIPLY", b.math("ADD", wu, wv), 0.35))
    slub = b.noise(objv, 220.0, 3.0)
    fade = b.noise(objv, 9.0, 4.0)
    base = b.mix(b.smoothstep(0.3, 0.7, fade), (0.012, 0.019, 0.055, 1), (0.026, 0.040, 0.095, 1))
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.55, 0.9, b.noise(objv, 16.0, 3.0)), b.smoothstep(0.75, 0.05, oz)), base, (0.09, 0.065, 0.04, 1))
    col = b.mix(b.math("MULTIPLY", b.math("ADD", slub, weave), 0.10), col, (0.07, 0.09, 0.16, 1))
    n = b.bump(b.math("ADD", b.math("MULTIPLY", weave, 0.5), b.math("MULTIPLY", slub, 0.3)), 0.9, 0.0016)
    return b.finish(col, b.math("ADD", 0.82, b.math("MULTIPLY", slub, 0.12)), 0.0, n, team=team)


def cord(name, color):
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    twist = b.math("SINE", b.math("ADD", b.math("MULTIPLY", v, 520.0), b.math("MULTIPLY", u, 190.0)))
    fib = b.noise(objv, 400.0, 3.0)
    col = b.mix(b.math("MULTIPLY", b.math("ADD", twist, 1.0), 0.18), color, tuple(c * 1.6 for c in color[:3]) + (1,))
    col = b.mix(b.math("MULTIPLY", fib, 0.25), col, (0.0, 0.0, 0.0, 1))
    n = b.bump(b.math("ADD", b.math("MULTIPLY", twist, 0.5), b.math("MULTIPLY", fib, 0.2)), 0.9, 0.0012)
    return b.finish(col, 0.78, 0.0, n, team=1.0)


def gold(name="sam_gold"):
    b = NB(name)
    objv, oz = b.obj()
    wear = b.edge_wear(0.002, 1.2)
    n1 = b.noise(objv, 60.0, 5.0)
    col = b.mix(b.smoothstep(0.4, 0.7, n1), (0.78, 0.50, 0.11, 1), (0.55, 0.33, 0.06, 1))
    col = b.mix(b.math("MULTIPLY", wear, 0.6), col, (0.95, 0.72, 0.28, 1))
    dirt = b.math("MULTIPLY", b.smoothstep(0.6, 0.9, b.noise(objv, 25.0, 3.0)), 0.5)
    col = b.mix(dirt, col, (0.11, 0.06, 0.02, 1))
    n = b.bump(b.math("MULTIPLY", b.noise(objv, 500.0, 2.0), 0.3), 0.4, 0.001)
    return b.finish(col, b.math("ADD", 0.30, b.math("MULTIPLY", n1, 0.25)), 1.0, n)


def iron(name="sam_iron"):
    b = NB(name)
    objv, oz = b.obj()
    wear = b.edge_wear(0.0025, 1.0)
    n1 = b.noise(objv, 70.0, 5.0)
    col = b.mix(b.smoothstep(0.35, 0.7, n1), (0.030, 0.030, 0.034, 1), (0.075, 0.074, 0.078, 1))
    rust = b.math("MULTIPLY", b.smoothstep(0.62, 0.8, b.noise(objv, 38.0, 4.0)), 0.55)
    col = b.mix(rust, col, (0.14, 0.055, 0.02, 1))
    col = b.mix(b.math("MULTIPLY", wear, 0.5), col, (0.30, 0.30, 0.32, 1))
    hammer = b.noise(objv, 260.0, 3.0)
    n = b.bump(b.math("MULTIPLY", hammer, 0.5), 0.8, 0.0015)
    return b.finish(col, b.math("ADD", 0.38, b.math("MULTIPLY", n1, 0.3)), b.math("SUBTRACT", 1.0, b.math("MULTIPLY", rust, 0.8)), n)


def steel(name="sam_steel"):
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    nz = b.stretched(uvv, 1.0, 0.02, 600.0, 3.0)                                     # grain along the blade
    hamon_edge = b.math("ADD", 0.0058, b.math("MULTIPLY", b.noise(objv, 38.0, 3.0), 0.0035))
    hamon = b.smoothstep(b.math("ADD", hamon_edge, 0.0006), b.math("SUBTRACT", hamon_edge, 0.0006), u)
    body = (0.58, 0.60, 0.65, 1)
    hard = (0.80, 0.81, 0.84, 1)
    col = b.mix(hamon, body, hard)
    col = b.mix(b.math("MULTIPLY", nz, 0.12), col, (0.35, 0.37, 0.40, 1))
    n = b.bump(b.math("MULTIPLY", nz, 0.25), 0.3, 0.0005)
    return b.finish(col, b.math("ADD", 0.16, b.math("ADD", b.math("MULTIPLY", nz, 0.14), b.math("MULTIPLY", hamon, -0.06))), 1.0, n)


def skin(name="sam_skin"):
    b = NB(name)
    objv, oz = b.obj()
    n1 = b.noise(objv, 40.0, 4.0)
    col = b.mix(b.smoothstep(0.3, 0.7, n1), (0.40, 0.205, 0.135, 1), (0.50, 0.265, 0.175, 1))
    pores = b.noise(objv, 900.0, 2.0)
    n = b.bump(b.math("MULTIPLY", pores, 0.3), 0.4, 0.001)
    return b.finish(col, 0.52, 0.0, n)


def straw(name="sam_straw"):
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    fib = b.stretched(uvv, 1.0, 40.0, 60.0, 3.0)
    n1 = b.noise(objv, 30.0, 4.0)
    col = b.mix(b.smoothstep(0.3, 0.7, fib), (0.18, 0.115, 0.045, 1), (0.42, 0.30, 0.13, 1))
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.55, 0.85, n1), 0.4), col, (0.09, 0.06, 0.035, 1))
    n = b.bump(fib, 0.9, 0.0016)
    return b.finish(col, 0.9, 0.0, n)


def white(name="sam_white"):
    b = NB(name)
    objv, oz = b.obj()
    fib = b.noise(objv, 700.0, 2.0)
    col = b.mix(b.smoothstep(0.3, 0.7, fib), (0.30, 0.29, 0.27, 1), (0.56, 0.54, 0.50, 1))
    return b.finish(col, 0.75, 0.0, b.bump(fib, 0.5, 0.0008))


def teeth(name="sam_teeth"):
    b = NB(name)
    objv, oz = b.obj()
    n1 = b.noise(objv, 300.0, 3.0)
    col = b.mix(b.smoothstep(0.3, 0.7, n1), (0.42, 0.34, 0.20, 1), (0.60, 0.50, 0.32, 1))
    return b.finish(col, 0.35, 0.3)


def eye(name="sam_eye"):
    b = NB(name)
    return b.finish((0.55, 0.50, 0.44, 1), 0.3, 0.0)


def iris(name="sam_iris"):
    b = NB(name)
    return b.finish((0.012, 0.007, 0.005, 1), 0.2, 0.0)


BUILDERS = {
    "lamellar": lamellar, "lacquer": lacquer, "hemp": hemp, "gold": gold, "iron": iron, "steel": steel, "skin": skin,
    "straw": straw, "white": white, "teeth": teeth, "eye": eye, "iris": iris,
    "lacing": lambda: cord("sam_lacing", CRIMSON), "lacing2": lambda: cord("sam_lacing2", NAVY),
    "sash": lambda: hemp("sam_sash", team=0.9),
}


def procedural(key):
    m = bpy.data.materials.get(f"sam_{key}")
    return m if m else BUILDERS[key]()
