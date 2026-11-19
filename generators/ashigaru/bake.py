"""Atlas baking for the ashigaru: the archer's weighted baker (the face, eyes, hair and the hat get more texels; clean occlusion for bare skin in a hat's shade)."""
from archer import bake as ABk

assign_baked = ABk.assign_baked


def boost():
    p = "ash_"
    return {p + "face": 2.6, p + "eye": 2.1, p + "iris": 2.1, p + "hair": 1.6, p + "jingasa": 1.35, p + "jingasa2": 1.35, p + "teamcloth": 1.2, p + "okegawa": 1.25, p + "haraate": 1.15, p + "pennant": 1.3}


def bake_atlas(objs, out_dir, name, px=2048, quality=1.0, log=print, ao_groups=None):
    ABk.BOOST = boost()                                       # the archer's atlas_uv reads its module's table
    return ABk.bake_atlas(objs, out_dir, name, px=px, quality=quality, log=log, ao_groups=ao_groups)
