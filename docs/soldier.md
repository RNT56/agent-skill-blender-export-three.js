# Soldier units from image-to-3D meshes (`generators/soldier/`, `generators/soldier_unit.py`)

The villager route (`docs/villager.md`: reference image -> image-to-3D -> auto-rig -> clean-up here -> the gate) taken to a soldier who is DRESSED: body
armour, hat, weapon, side arm are goods he is issued, can exchange and (armour, hat) take off. First unit: the ashigaru, `ashigaru_unit_02` (2026-11-19).
Game side and contract: samurai-vale `docs/ASHIGARU_UNIT.md`.

## The shape of the asset
- **One man, one skeleton, several complete bodies.** Image-to-3D returns ONE fused surface per image: an armour cannot be lifted off it as a shell that
  sits clean on another reconstruction. So each body armour is a reference of the same man wearing it (and one of him in his clothes alone), each its own
  mesh, auto-rig and bake. `assemble` warps every body onto the base body's skeleton (per vertex: its bones' base-rest x own-rest^-1, blended by its
  weights; joints were up to 4 cm apart, afterwards they coincide) and binds it there. An engine draws ONE body: the man's armour, or none.
- **Rigid kit** (hats, spear heads, side arm) from their own object references; the banner and the spear's pennant are procedural (house colour, crest).
- **References made as a family** (GPT Image 2.6 through Higgsfield): one approved front view; every other image takes it as reference and changes one thing
  ("the same man without the armour", "back view", "left side view" with the first side view as the pose reference). Tripo H3.1 MULTIVIEW (front, left, back)
  got the backs right; the single-image model invented a back plate on an armour that has none.
- **Livery by colour**: everything that carries the house's colour is vermilion in the references. `assemble.compose` finds it (strict test; a looser one
  next to it and on the head band; never on the face: lips are red too, the body's position map says where the face is), writes the team mask and takes
  those texels to a neutral cloth tone.

## Stages (one Blender process each; see the header of `soldier_unit.py`)
| stage | per | module | what it does |
|---|---|---|---|
| `ingest`, `lowpoly`, `rig` | body | `villager.*` unchanged | clean / scale the 2 M triangle source; LOD0 (18,000) + the upload for the auto-rig; the auto-rig's joints and weights on a clean armature, measured hands |
| `atlas` | body | `villager.atlas` + `soldier.atlasfix` + `soldier.bake` | charts per limb SEGMENT, starved charts cut again, packed over the whole square; bake with a wider cage and a metal channel |
| `props` | piece | `soldier.props` | canonical frame and real size (a hat by its rim circle, a spear head by its shaft, a blade by its length), the hats' dangling cords removed, low mesh, bake |
| `assemble` | unit | `soldier.assemble` | bodies onto one skeleton, hair-knot bone, weapon / pennant / banner bones, hats seated on the measured skull, spears built from head piece + repeated shaft segment, side arm at the measured sash, one 4096 atlas, team mask |
| `clips` | unit | `soldier.clips` | the v1 ashigaru's clips RE-FITTED: every frame is solved on a v1 reference skeleton and carried over (hips and feet by the leg ratio, spear and hands relative to the chest by the arm ratio, a grounded spear stays grounded, a levelled one keeps its point) |
| `finalize` | unit | `soldier.finalize` | LOD1, far meshes (body x head), game textures (4096 JPEG albedo, 2048 PNG normal / ORM), emblems, cloth json, fixture, spec |

## Things learned (candidates for GOTCHAS.md)
1. **Never run two heavy Blender stages at once on a 16 GB machine, and never take a full SVD of an n x 3 point set** (`np.linalg.svd(P)` builds an n x n U:
   50,000 rim points asked for 20 GB and took the machine down). Plane normal = smallest eigenvector of the 3 x 3 covariance. Each early stage peaks at
   4 to 5 GB; run them one after another (a watchdog that kills a job above 7 GB is cheap).
2. **Weld an image-to-3D mesh before decimating it.** It arrives split along every UV seam (thousands of islands): unwelded, collapse decimation returns shards.
3. **Angle-based unwrapping starves narrow parts next to bulging ones** (a gaiter under ballooning breeches got a twentieth of the texels and baked as a
   smear). Cut charts per limb segment, measure texel density per chart afterwards, cut starved ones again. Do NOT fall back to Smart UV Project for whole
   charts (thousands of islands).
4. **Thin double-walled things do not decimate** (an iron hat with a cloth curtain folds through itself and tears). Build the low mesh on the measured outer
   surface instead (a lathe of the radial profile, a sheet over the angles where cloth hangs) and let the bake carry the detail.
5. **Image-to-3D guesses the unseen dimension**: a spear blade photographed from the side came back as wide as a trowel. Measure sections along the shaft and
   bring the blade back to a spear's section. Its metalness channel was empty everywhere: find steel and gilding by colour.
6. **A hat's "lowest fit" is at the brow**: seat it from the skull's profile, then lift it by the pad a real one rides on, or it covers the eyes.
7. **A bake cage for armour**: 16 mm / 48 mm rays (the villager's 10 / 28 left tasset tips and the ration tube black).
8. **Re-fitting authored clips across proportions**: absolute targets fail in a fall (the hips' drop scales with the legs, the trunk's thickness does not):
   check spheres on the spine against the ground and lift; a free hand that reaches the ground must be laid flat.

## The archer (`--unit archer`, 2026-11-19)
Two bodies (bare, haramaki), the ashigaru's rawhide hat (`../ashigaru_src/tripo/jingasa.glb`), a quiver piece (`ebira`, kind "blade": a long piece from its
foot; `flip` because the fletchings are its widest section). **Bow and arrow are the v1 archer's** (the owner preferred them): `soldier/bowkit.py` builds
`archer.bow` parts with their procedural materials, bakes them into one atlas cell and moves them rigidly from the v1 hand's grip to this man's
(`hands.json`: grip, fingers `a`, palm `n`; the thumb's side is `-(a x n)` on the left), bones included. Clips: `soldier/clips_archer.py`
(`archer.anim.Solver` subclass; the quiver's nocks are found where `bowkit.place_quiver` hung it). A unit with other bodies / pieces has its own atlas
layout (`assemble.LAYOUT`).

9. **Carry points over relative to each hand's own shoulder**, not the chest's middle: on narrower shoulders every target came in toward the trunk and the
   elbows winged out. A clip's elbow hints written for a broad v1 body need blending toward "down and back" wherever the hand is low.
10. **A free arm in a gait is better synthesised than re-fitted** (`clips.swing_arm`): pendulum in a walk, right angle in a run.
11. **An auto-rig's feet are not mirror images**: use each foot's own rest direction, or one sole's pitch puts the other foot's toes in the ground.
12. **Sun-reddened skin passes a red-cloth test** (feet, hands, ears): exclude by position, not by colour.
13. A game camera may have a NEAR plane of metres (samurai-vale: 2.5 m): an "invisible" unit in a close screenshot is clipped, not broken. And a 4096 texture
    decodes asynchronously: the first frames after load draw shadows but no body.

## Arms (2026-11-21): `samurai/armfix.py`, shared by the samurai and the soldier units
The owner: "arms glitch through the body, an arm is not visible, hands are swirled". After every frame is solved, per arm, with the WRIST and the weapons
left where the clip put them:
- **a hand on a round shaft turns about it** (`grip_roll`, +-40 deg) to where the wrist is least bent and twisted: a clip written for another hand often
  asked for a wrist bent 150 deg, which smeared the palm off the shaft (the hand's heel is skinned partly to the forearm);
- **the elbow turns about the shoulder-wrist line** only where the clip's own arm is inside the trunk, the thighs or the head (`Body`: star-shaped
  slices of the trunk measured from body + armour, capsules for the thighs, a sphere for the head + helmet); gradually, never by a switch;
- **the forearm rolls about its own axis** to take the wrist's twist (up to 85 deg), chosen against twist AND bend together;
- **the wrist's bend is held to 80 deg**; the upper arm may not roll more than the clip's own (a rolled humerus wrings the shoulder: no twist bones).
Measured on the real meshes (wrist twist / bend, centre line inside body + armour) every clip of both units: twists from up to 179 deg to under 95,
bends from up to 175 deg to at most 80. A few arms still touch the body where the clip's hand target itself is on it (the samurai's sheathing hand at
the obi, a hand resting on the scabbard).

## Not done
No golden tests for `ashigaru_unit_02` / `archer_unit_02` in `tests/` yet. The samurai is still the procedural build. One head-band end on the ashigaru's bare body was hard to get into the livery mask (texels the position bake missed now count as band).
