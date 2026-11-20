"""Materials for the samurai. PLACEHOLDER pass: flat colours per material key so shapes can be judged. The procedural PBR
networks that get baked into the atlas replace these (see the bake stage)."""
import bpy

KEYS = {
    "skin": ((0.72, 0.48, 0.36), 0.55, 0.0),
    "eye": ((0.9, 0.9, 0.88), 0.3, 0.0),
    "sash": ((0.045, 0.06, 0.12), 0.9, 0.0),
    "hemp": ((0.045, 0.06, 0.12), 0.9, 0.0),
    "lacquer": ((0.02, 0.02, 0.025), 0.35, 0.0),
    "lacing": ((0.45, 0.04, 0.04), 0.7, 0.0),
    "lamellar": ((0.03, 0.03, 0.04), 0.4, 0.0),
    "kawa": ((0.10, 0.05, 0.02), 0.5, 0.0),
    "rawhide": ((0.08, 0.04, 0.02), 0.5, 0.0),
    "lacing2": ((0.04, 0.07, 0.22), 0.7, 0.0),
    "hair": ((0.02, 0.015, 0.012), 0.5, 0.0),
    "kabuto": ((0.02, 0.02, 0.025), 0.35, 0.0),
    "menpo": ((0.07, 0.015, 0.012), 0.45, 0.0),
    "banner": ((0.3, 0.3, 0.3), 0.85, 0.0),
    "gold": ((0.85, 0.62, 0.2), 0.3, 1.0),
    "iron": ((0.12, 0.12, 0.13), 0.5, 1.0),
    "leather": ((0.12, 0.07, 0.04), 0.6, 0.0),
    "straw": ((0.55, 0.45, 0.28), 0.9, 0.0),
    "steel": ((0.75, 0.76, 0.78), 0.2, 1.0),
    "bloom": ((0.50, 0.51, 0.53), 0.3, 1.0),
    "white": ((0.7, 0.7, 0.68), 0.5, 0.0),
    "iris": ((0.01, 0.006, 0.004), 0.2, 0.0),
    "teeth": ((0.8, 0.75, 0.6), 0.4, 0.0),
}


def placeholder(key):
    m = bpy.data.materials.get(f"sam_{key}")
    if m:
        return m
    col, rough, metal = KEYS[key]
    m = bpy.data.materials.new(f"sam_{key}")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*col, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    return m
