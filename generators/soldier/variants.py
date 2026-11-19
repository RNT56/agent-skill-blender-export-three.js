"""The soldier units built from image-to-3D meshes (2026-11-19): what differs between units and between a unit's BODIES is data.

A soldier can take his armour and his helmet off (he can only exchange his weapon), so a unit is several complete bodies of the SAME man on ONE skeleton:
one per body armour and one without any. Each body is its own reconstruction (reference images front / left / back -> Tripo H3.1 multiview); hats, weapons and
the side arm are separate rigid pieces. The engine shows one body and the pieces of his kit.

  height     metres to the top of the hair knot (every body of a unit is scaled to it: the same man)
  base       the body whose auto-rig gives the unit's skeleton (the others are bound to it)
  bodies     key -> dict(src: the image-to-3D mesh, node: the game node's stem, armour: the armour pattern's key in samurai-vale content/tiers.js or None)
"""
UNITS = {
    "ashigaru": dict(
        asset="ashigaru_unit_02", height=1.76, base="bare", src_dir="fixtures/ashigaru_src", tris=18000,
        bodies={
            "bare": dict(src="tripo/bare_a_mv.glb", node="Ashigaru_Bare", armour=None),
            "levy": dict(src="tripo/levy_a_mv.glb", node="Ashigaru_HaraAte", armour="HaraAte"),
            "okegawa": dict(src="tripo/okegawa_a_mv.glb", node="Ashigaru_Okegawa", armour="Okegawa", banner=True),
        },
        props={
            "jingasa": dict(src="tripo/jingasa.glb"), "tetsu_jingasa": dict(src="tripo/tetsu_jingasa.glb"),
            "yari_head": dict(src="tripo/yari_head.glb"), "nagae_head": dict(src="tripo/nagae_head.glb"), "tanto": dict(src="tripo/tanto.glb"),
        },
    ),
    # the archer: a lighter, younger man. His bow and arrow are the v1 archer's own (owner, 2026-11-19: "use the current archer's bow and arrow with the new
    # model"): taken from fixtures/archer_unit_01.blend with their bones; the quiver is a piece; the rawhide hat is the ashigaru's (the same good in the game).
    "archer": dict(
        asset="archer_unit_02", height=1.74, base="bare", src_dir="fixtures/archer_src", tris=18000, weapon="bow", bow_from="fixtures/archer_unit_01.blend",
        bodies={
            "bare": dict(src="tripo/bare_b_mv.glb", node="Archer_Bare", armour=None),
            "haramaki": dict(src="tripo/haramaki_b_mv.glb", node="Archer_Haramaki", armour="Haramaki", banner=True),
        },
        props={"jingasa": dict(src="../ashigaru_src/tripo/jingasa.glb"), "ebira": dict(src="tripo/ebira.glb")},
    ),
}


def get(unit):
    if unit not in UNITS:
        raise SystemExit(f"unknown unit {unit!r}: one of {sorted(UNITS)}")
    return dict(UNITS[unit], unit=unit)
