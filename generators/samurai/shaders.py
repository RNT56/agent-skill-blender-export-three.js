"""Procedural PBR materials for the samurai (Cycles-bakeable node graphs). Pattern UV 'pat' units: lamellar = plate / row units,
cloth and tubes = metres. Colours are scene-linear. Every graph ends in ONE Principled BSDF so albedo / roughness / metallic /
normal can be baked and exported as glTF PBR."""
import bpy

CRIMSON = (0.20, 0.012, 0.020, 1)
NAVY = (0.020, 0.036, 0.120, 1)
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

    def bump(self, height, strength=1.0, dist=0.002, normal=None):
        nd = self.node("ShaderNodeBump")
        self.put(nd, Height=height, Strength=strength, Distance=dist)
        if normal is not None:
            self.l.new(normal, nd.inputs["Normal"])
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
    """Laced lamellar plates: dark brown-black lacquer with brushed highlights and worn edges, thin cords in the plate gaps, two narrow
    lacing bands per row with a raised knot on every other plate. Only the bands and knots feed the team mask (cords stay navy)."""
    b = NB(name)
    uvv, u, v = b.uv()
    objv, oz = b.obj()
    ui = b.math("ROUND", u)
    d = b.math("ABSOLUTE", b.math("SUBTRACT", u, ui))                              # distance to the nearest plate edge (0..0.5)
    cord = b.math("SUBTRACT", 1.0, b.smoothstep(0.035, 0.070, d))
    fv = b.math("FRACT", v)
    band_d = b.math("MINIMUM", fv, b.math("SUBTRACT", 1.0, fv))
    band = b.math("SUBTRACT", 1.0, b.smoothstep(0.016, 0.038, band_d))
    odd = b.math("MODULO", ui, 2.0)                                                # every other plate carries a knot
    third = b.math("LESS_THAN", b.math("MODULO", ui, 3.0), 0.5)                    # every third cord is crimson, the rest navy
    knot = b.math("MULTIPLY", b.math("MULTIPLY", cord, band), b.math("SUBTRACT", 1.0, odd))
    n1 = b.noise(objv, 110.0, 5.0)
    streak = b.stretched(uvv, 0.15, 10.0, 16.0, 3.0)                              # brush strokes run along the row height
    plate = b.mix(b.smoothstep(0.30, 0.70, n1), (0.022, 0.017, 0.015, 1), (0.040, 0.031, 0.027, 1))
    plate = b.mix(b.math("MULTIPLY", b.smoothstep(0.66, 0.92, streak), 0.30), plate, (0.085, 0.060, 0.045, 1))
    wear = b.edge_wear(0.0018, 0.8)
    plate = b.mix(b.math("MULTIPLY", wear, b.math("SUBTRACT", 1.0, cord)), plate, (0.20, 0.15, 0.085, 1))    # worn lacquer shows gold-brown metal
    cord_col = b.mix(third, NAVY, CRIMSON)
    band_col = b.mix(b.math("MODULO", b.math("FLOOR", b.math("MULTIPLY", u, 0.5)), 2.0), CRIMSON, NAVY)
    col = b.mix(band, plate, band_col)
    col = b.mix(cord, col, cord_col)
    col = b.mix(knot, col, (0.34, 0.035, 0.045, 1))
    braid = b.math("SINE", b.math("ADD", b.math("MULTIPLY", v, 60.0), b.math("MULTIPLY", u, 20.0)))
    scratch = b.stretched(uvv, 0.2, 14.0, 22.0, 3.0)
    dust = b.math("MULTIPLY", b.smoothstep(0.55, 0.85, b.noise(objv, 14.0, 3.0)), b.smoothstep(1.2, 0.7, oz))
    col = b.mix(b.math("MULTIPLY", dust, 0.30), col, (0.085, 0.065, 0.045, 1))
    height = b.math("ADD", b.math("MULTIPLY", cord, 0.50),
                    b.math("ADD", b.math("MULTIPLY", band, 0.28), b.math("ADD", b.math("MULTIPLY", knot, 0.55),
                           b.math("MULTIPLY", b.math("MULTIPLY", braid, b.math("MAXIMUM", cord, band)), 0.10))))
    height = b.math("ADD", height, b.math("MULTIPLY", scratch, 0.05))
    n = b.bump(height, 1.4, 0.0016)
    rough = b.math("ADD", b.mixf(b.math("MAXIMUM", cord, band), 0.30, 0.78), b.math("MULTIPLY", scratch, 0.14))
    return b.finish(col, rough, 0.0, n, team=b.math("MAXIMUM", band, knot))


def lacquer(name="sam_lacquer"):
    b = NB(name)
    objv, oz = b.obj()
    n1 = b.noise(objv, 160.0, 5.0)
    wear = b.edge_wear(0.0025, 1.3)
    base = b.mix(b.smoothstep(0.35, 0.65, n1), (0.020, 0.018, 0.020, 1), (0.040, 0.036, 0.040, 1))
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
    base = b.mix(b.smoothstep(0.3, 0.7, fade), (0.022, 0.034, 0.090, 1), (0.046, 0.068, 0.150, 1))
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.55, 0.9, b.noise(objv, 16.0, 3.0)), b.smoothstep(0.75, 0.05, oz)), base, (0.09, 0.065, 0.04, 1))
    col = b.mix(b.math("MULTIPLY", b.math("ADD", slub, weave), 0.10), col, (0.07, 0.09, 0.16, 1))
    wob = b.noise(objv, 7.0, 3.0)                                                      # folds wander: no two hang alike
    fold = b.math("SINE", b.math("ADD", b.math("MULTIPLY", u, 6.2832 / 0.058), b.math("MULTIPLY", wob, 7.0)))
    fold2 = b.math("SINE", b.math("ADD", b.math("MULTIPLY", u, 6.2832 / 0.021), b.math("MULTIPLY", b.noise(objv, 19.0, 3.0), 9.0)))
    hang = b.smoothstep(1.35, 0.55, oz)                                                # stronger toward the hem than at the shoulders
    crease = b.math("MULTIPLY", b.math("ADD", b.math("MULTIPLY", fold, 0.65), b.math("MULTIPLY", fold2, 0.22)), b.math("ADD", 0.35, b.math("MULTIPLY", hang, 0.65)))
    col = b.mix(b.math("MULTIPLY", b.smoothstep(0.05, 0.85, b.math("SUBTRACT", 0.0, crease)), 0.62), col, (0.006, 0.009, 0.024, 1))    # valleys of the folds go dark, crests keep the dye
    weave_n = b.bump(b.math("ADD", b.math("MULTIPLY", weave, 0.5), b.math("MULTIPLY", slub, 0.3)), 0.9, 0.0016)
    n = b.bump(crease, 2.2, 0.012, normal=weave_n)
    return b.finish(col, b.math("ADD", 0.82, b.math("MULTIPLY", slub, 0.12)), 0.0, n, team=team)


def kabuto(name="sam_kabuto"):
    """Helmet bowl: lacquered iron plates with a row of domed rivets down every plate ridge (24 ridges, a rivet every 16 mm)."""
    import math
    b = NB(name)
    objv, oz = b.obj()
    tc = b.node("ShaderNodeSeparateXYZ")
    b.l.new(objv, tc.inputs["Vector"])
    x, y = tc.outputs["X"], tc.outputs["Y"]
    ang = b.math("ARCTAN2", b.math("SUBTRACT", y, -0.014), x)                          # angle around the helmet axis
    plate = b.math("ADD", b.math("MULTIPLY", b.math("ADD", ang, math.pi / 2), 24.0 / math.tau), 0.5)
    dr = b.math("ABSOLUTE", b.math("SUBTRACT", plate, b.math("ROUND", plate)))         # 0 on a ridge, 0.5 mid-plate
    zf = b.math("SUBTRACT", b.math("FRACT", b.math("MULTIPLY", b.math("SUBTRACT", oz, 1.668), 1.0 / 0.0165)), 0.5)
    dist = b.math("POWER", b.math("ADD", b.math("POWER", b.math("MULTIPLY", dr, 0.026), 2.0), b.math("POWER", b.math("MULTIPLY", zf, 0.0165), 2.0)), 0.5)
    on_dome = b.smoothstep(1.668, 1.69, oz)                                             # only on the bowl, not at the lowest ring
    rivet = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.smoothstep(0.0034, 0.0050, dist)), on_dome)
    n1 = b.noise(objv, 160.0, 5.0)
    wear = b.edge_wear(0.0025, 1.3)
    base = b.mix(b.smoothstep(0.35, 0.65, n1), (0.020, 0.018, 0.020, 1), (0.040, 0.036, 0.040, 1))
    col = b.mix(b.math("MULTIPLY", wear, 0.85), base, (0.12, 0.115, 0.11, 1))
    col = b.mix(b.math("MULTIPLY", rivet, 0.95), col, (0.45, 0.31, 0.10, 1))           # brass-gold rivet heads
    dust = b.math("MULTIPLY", b.smoothstep(0.55, 0.85, b.noise(objv, 12.0, 3.0)), b.smoothstep(1.9, 1.7, oz))
    col = b.mix(b.math("MULTIPLY", dust, 0.30), col, (0.07, 0.05, 0.035, 1))
    fine = b.noise(objv, 900.0, 2.0)
    n = b.bump(b.math("ADD", b.math("MULTIPLY", fine, 0.2), b.math("MULTIPLY", rivet, 1.2)), 0.8, 0.0014)
    rough = b.math("ADD", 0.20, b.math("ADD", b.math("MULTIPLY", wear, 0.3), b.math("MULTIPLY", b.noise(objv, 40.0, 3.0), 0.22)))
    return b.finish(col, b.mixf(rivet, rough, 0.34), b.math("MULTIPLY", rivet, 0.85), n)


def menpo(name="sam_menpo"):
    """Half mask: black-red lacquer over hammered iron, bare iron on the high points (cheek bones, nose, chin), brow and cheek wrinkles in the bump."""
    b = NB(name)
    objv, oz = b.obj()
    tc = b.node("ShaderNodeSeparateXYZ")
    b.l.new(objv, tc.inputs["Vector"])
    x = tc.outputs["X"]
    wear = b.edge_wear(0.0028, 1.5)
    n1 = b.noise(objv, 90.0, 5.0)
    hammer = b.noise(objv, 300.0, 3.0)
    base = b.mix(b.smoothstep(0.35, 0.7, n1), (0.050, 0.012, 0.010, 1), (0.085, 0.020, 0.016, 1))        # red-black lacquer
    col = b.mix(b.math("MULTIPLY", wear, 0.9), base, (0.22, 0.21, 0.22, 1))                              # worn through to iron on the high points
    wrink = b.math("SINE", b.math("ADD", b.math("MULTIPLY", oz, 6.2832 / 0.012), b.math("MULTIPLY", b.math("ABSOLUTE", x), 55.0)))
    wr_band = b.math("MULTIPLY", b.smoothstep(1.545, 1.58, oz), b.smoothstep(1.62, 1.585, oz))          # cheek band between mouth and nose
    height = b.math("ADD", b.math("MULTIPLY", hammer, 0.5), b.math("MULTIPLY", b.math("MULTIPLY", wrink, wr_band), 0.7))
    n = b.bump(height, 0.9, 0.0016)
    return b.finish(col, b.math("ADD", 0.42, b.math("MULTIPLY", n1, 0.3)), b.math("MULTIPLY", wear, 0.9), n)


def banner(name="sam_banner"):
    """Sashimono cloth: plain dyed cotton in the team mask (the engine tints the whole cloth), a stitched border, NO emblem: the engine draws the faction's mon from
    emblems.png at runtime (one asset serves every faction)."""
    from .consts import BOTTOM, CLOTH_W, X0
    b = NB(name)
    objv, oz = b.obj()
    tc = b.node("ShaderNodeSeparateXYZ")
    b.l.new(objv, tc.inputs["Vector"])
    x = tc.outputs["X"]
    border = b.math("SUBTRACT", 1.0, b.smoothstep(0.0, 0.0045, b.math("MINIMUM", b.math("ABSOLUTE", b.math("SUBTRACT", x, X0)),
                    b.math("MINIMUM", b.math("ABSOLUTE", b.math("SUBTRACT", x, X0 + CLOTH_W)), b.math("ABSOLUTE", b.math("SUBTRACT", oz, BOTTOM))))))
    p = 0.0050
    wu = b.math("SINE", b.math("MULTIPLY", x, 6.2832 / p))
    wv = b.math("SINE", b.math("MULTIPLY", oz, 6.2832 / p))
    weave = b.math("ADD", b.math("MULTIPLY", wu, wv), b.math("MULTIPLY", b.math("ADD", wu, wv), 0.35))
    slub = b.noise(objv, 240.0, 3.0)
    cloth = b.mix(b.math("MULTIPLY", b.math("ADD", slub, weave), 0.10), (0.30, 0.30, 0.30, 1), (0.36, 0.36, 0.36, 1))
    col = b.mix(b.math("MULTIPLY", border, 0.5), cloth, (0.20, 0.20, 0.20, 1))
    n = b.bump(b.math("ADD", b.math("MULTIPLY", weave, 0.5), b.math("ADD", b.math("MULTIPLY", slub, 0.3), b.math("MULTIPLY", border, 0.5))), 0.9, 0.0014)
    return b.finish(col, b.math("ADD", 0.84, b.math("MULTIPLY", slub, 0.1)), 0.0, n, team=1.0)


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
    col = b.mix(b.smoothstep(0.35, 0.7, n1), (0.050, 0.050, 0.055, 1), (0.120, 0.118, 0.125, 1))
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
    """Weathered warm skin: two-tone mottling, shadowed eye sockets, flushed cheeks (the band between the visor and the mask is the only face that shows), fine pores."""
    b = NB(name)
    objv, oz = b.obj()
    tc = b.node("ShaderNodeSeparateXYZ")
    b.l.new(objv, tc.inputs["Vector"])
    ax = b.math("ABSOLUTE", tc.outputs["X"])
    n1 = b.noise(objv, 40.0, 4.0)
    col = b.mix(b.smoothstep(0.3, 0.7, n1), (0.325, 0.176, 0.112, 1), (0.420, 0.232, 0.150, 1))
    d_eye = b.math("POWER", b.math("ADD", b.math("POWER", b.math("DIVIDE", b.math("SUBTRACT", ax, 0.031), 0.020), 2.0),
                                   b.math("POWER", b.math("DIVIDE", b.math("SUBTRACT", oz, 1.652), 0.012), 2.0)), 0.5)
    sock = b.math("SUBTRACT", 1.0, b.smoothstep(0.35, 1.25, d_eye))
    d_ck = b.math("POWER", b.math("ADD", b.math("POWER", b.math("DIVIDE", b.math("SUBTRACT", ax, 0.052), 0.026), 2.0),
                                  b.math("POWER", b.math("DIVIDE", b.math("SUBTRACT", oz, 1.612), 0.024), 2.0)), 0.5)
    flush = b.math("SUBTRACT", 1.0, b.smoothstep(0.30, 1.10, d_ck))
    col = b.mix(b.math("MULTIPLY", sock, 0.60), col, (0.19, 0.095, 0.066, 1))
    col = b.mix(b.math("MULTIPLY", flush, 0.40), col, (0.53, 0.245, 0.160, 1))
    pores = b.noise(objv, 900.0, 2.0)
    n = b.bump(b.math("MULTIPLY", pores, 0.3), 0.4, 0.001)
    return b.finish(col, b.math("ADD", 0.50, b.math("MULTIPLY", n1, 0.08)), 0.0, n)


def hair(name="sam_hair"):
    """Moustache and brows: coarse black-brown hair with a few grey strands."""
    b = NB(name)
    objv, oz = b.obj()
    fib = b.noise(objv, 520.0, 3.0)
    grey = b.smoothstep(0.62, 0.80, b.noise(objv, 160.0, 2.0))
    col = b.mix(b.smoothstep(0.35, 0.70, fib), (0.008, 0.007, 0.006, 1), (0.036, 0.028, 0.021, 1))
    col = b.mix(b.math("MULTIPLY", grey, 0.55), col, (0.10, 0.095, 0.09, 1))
    n = b.bump(b.math("MULTIPLY", fib, 0.6), 0.8, 0.0008)
    return b.finish(col, b.math("ADD", 0.46, b.math("MULTIPLY", fib, 0.2)), 0.0, n, spec=0.45)


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
    return b.finish((0.62, 0.57, 0.50, 1), 0.22, 0.0, spec=0.7)


def iris(name="sam_iris"):
    b = NB(name)
    return b.finish((0.028, 0.015, 0.009, 1), 0.14, 0.0, spec=0.8)


BUILDERS = {
    "lamellar": lamellar, "lacquer": lacquer, "hemp": hemp, "gold": gold, "iron": iron, "steel": steel, "skin": skin,
    "hair": hair, "kabuto": kabuto, "menpo": menpo, "banner": banner, "straw": straw, "white": white, "teeth": teeth, "eye": eye, "iris": iris,
    "lacing": lambda: cord("sam_lacing", CRIMSON), "lacing2": lambda: cord("sam_lacing2", NAVY),
    "sash": lambda: hemp("sam_sash", team=0.9),
}


def procedural(key):
    m = bpy.data.materials.get(f"sam_{key}")
    return m if m else BUILDERS[key]()
