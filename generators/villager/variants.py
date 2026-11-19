"""The villager bodies. One table: what differs between them is data, everything else is the same pipeline.

  height      metres to the top of the head (the source mesh is scaled to it)
  src         the image-to-3D mesh (fixtures/villager_src/...)
  mocap       directory of the auto-rig + motion-capture GLBs of THIS body (idle_3, casual_walk, run_02): the joints differ per body, so each has its own
  hand_x      |x| where the hands begin, for the decimation's protection group (None: measured from the mesh's width)
  reference   the body the work clips were authored on: the others get those clips re-fitted to their own shoulders and reach (clips.Body.chest_ref)
  hat_drop    how far the straw hat sits below the measured crown (a head-cloth or a shaved pate changes it)
"""
VARIANTS = {
    "villager_unit_01": dict(who="a young man, topknot and hachimaki", height=1.68, src="fixtures/villager_src/tripo/villager_tripo_h31.glb",
                             mocap="fixtures/villager_src/meshy", hand_x=0.345, reference=True, hat_drop=0.045),
    "villager_unit_02": dict(who="a woman, hair under a white head-cloth", height=1.57, src="fixtures/villager_src/02/tripo.glb",
                             mocap="fixtures/villager_src/02/meshy", hand_x=None, reference=False, hat_drop=0.040),
    "villager_unit_03": dict(who="an old man, grey beard", height=1.63, src="fixtures/villager_src/03/tripo.glb",
                             mocap="fixtures/villager_src/03/meshy", hand_x=None, reference=False, hat_drop=0.045),
    "villager_unit_04": dict(who="a stout man, shaved pate", height=1.71, src="fixtures/villager_src/04/tripo.glb",
                             mocap="fixtures/villager_src/04/meshy", hand_x=None, reference=False, hat_drop=0.078),
}
# the reference body's measures (villager_unit_01): where its shoulders are and how far its arms and legs reach
REF = dict(shoulder_mid=(0.0, 0.0555, 1.302), arm=0.455, leg=0.729, height=1.68)


def get(name):
    if name not in VARIANTS:
        raise SystemExit(f"unknown villager {name!r}: one of {sorted(VARIANTS)}")
    return dict(VARIANTS[name], name=name)


def spec(name):
    """the gate's spec for a body (they differ only in names)."""
    clips = ["idle", "walk", "run", "walk_tool", "run_tool", "carry_shoulder_idle", "carry_shoulder_walk", "carry_shoulder_run", "carry_front_idle", "carry_front_walk",
             "carry_front_run", "chop", "mine", "hoe", "hammer", "chisel", "saw", "cut", "fish", "craft", "crouch_idle", "sneak"]
    return {
        "name": name, "type": "character", "recipe": "character", "source_blend": f"fixtures/{name}.blend" if name != "villager_unit_01" else "fixtures/villager_unit.blend", "preview": False,
        "budgets": {"max_tris": 19000, "max_materials": 1, "max_texture_px": 1024, "max_file_mb": 9},
        "lod_budgets": {"LOD0": 12000, "LOD1": 4000, "LOD2": 1300}, "rules": {"origin_tolerance": 0.05}, "recipe_cfg": {"collection": "villager_game"},
        "character": {"max_bones": 40, "max_influences": 4, "clips": {c: {"loop": True} for c in clips}, "team_mask": f"out/{tex_dir(name)}/villager_team.png"},
        "glb_expect": {"occlusion": ["villager_mat"], "joints_max": 40, "animations": clips},
        "export": {"out_dir": "out", "compress": False},
    }


def tex_dir(name):
    return "villager_tex" if name == "villager_unit_01" else f"{name}_tex"
