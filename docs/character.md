# Characters: the samurai unit (`recipe: character`)

A skinned, animated hero through the same gate as every other asset: **spec -> generator -> validate -> export -> inspect the GLB -> engine check**.
Nothing here is scanned or hand-sculpted: the model is procedural (`generators/samurai/`), the textures are procedural shaders baked to one atlas, the
animation is authored as code. Be honest about that when you judge the fidelity.

```bash
blender -b --factory-startup -P generators/samurai_unit.py -- --stage all --bake out/samurai_tex --px 2048 --finalize 1 --save fixtures/samurai_unit.blend
bin/gp build specs/samurai_unit_01.json                      # gate + GLB (out/samurai_unit_01/) + manifest + clips.json
blender -b fixtures/samurai_unit.blend -P tests/test_character_golden.py
blender -b fixtures/samurai_unit.blend -P generators/samurai_qa.py   # QA sheets -> out/samurai_unit_01/qa/ (look at them)
bin/gp view   # then http://localhost:8765/viewer/character.html?asset=samurai_unit_01   (engine check: three.js + AnimationMixer)
```
Look-dev: `--stage body`, `--pose lunge`, `--clip walk --frames 8 --view side_c`, `--render out/_x --views front,head` (3 s per build, EEVEE).

## What you get
| | |
|---|---|
| Model | o-yoroi style samurai ~1.74 m (1.84 m with the crest), A-pose rest, faces glTF +Z. Lamellar do, kusazuri, haidate, suneate, kote, sode, kabuto with shikoro / fukigaeshi / maedate, menpo, hemp robe, sash, waraji, katana + saya |
| Budget | LOD0 23.6k / LOD1 7.0k / LOD2 2.1k tris (collapse-decimated, weights kept, <= 4 influences) + three weapon meshes (1.6k) |
| Material | ONE material, 2048 atlas: albedo (KTX2) + tangent normal + ORM (AO / roughness / metal). 7.1 MB GLB, meshopt + KTX2 |
| Rig | 53 deform bones: spine x4, neck, head, 2x(shoulder, arm, forearm, hand, 10 finger bones, thigh, shin, foot, toe, sode, 3 kusazuri), `weapon_hip`, `weapon_r` |
| Clips (30 fps) | `idle` `walk` `run` (sheathed, in place) - `combat_idle` `attack_overhead` `attack_diagonal` `attack_horizontal` `attack_thrust` `block` `hit` `death` (drawn) |

## Using it in a game
- **Facing / scale**: origin between the feet on the ground, +Z forward (glTF), metres. Never rotate the model to fix facing; rotate the unit.
- **Weapons are separate skinned nodes**: `Katana_Sheathed` (hilt on the hip), `Katana_Drawn` (in the hands), `Katana_Saya` (always on the hip). Clip metadata
  `weapon: sheathed|drawn` in `clips.json` says which of the first two to show. Swap at the event frame of your draw / sheathe transition.
- **LODs share one skeleton**: show exactly one `Samurai_LOD<n>` mesh. Suggested switch distances (hero zoom): 0-12 m, 12-35 m, 35+ m.
- **Locomotion is in place**: move the unit yourself and set `action.timeScale = unitSpeed / clip.speed_mps` (walk 1.09 m/s, run 2.63 m/s). Stance feet then do not slide
  (tested: planted-foot speed equals `speed_mps`).
- **Skinned meshes must set `frustumCulled = false`** (or use a bounding sphere that covers the animation): bind-pose bounds cull the unit mid-lunge.
- Loop clips repeat their first pose as the last frame. Use `LoopRepeat` on the whole duration; the exporter keeps one extra identical frame, so the loop holds one frame.
- Team colour is NOT implemented: the lacing colours are baked into the atlas. A mask channel would need a second UV-aligned bake (see limits).

## How it is built (modules in `generators/samurai/`)
`kit` mesh kit (lofts, tubes, slabs, lamellar strips, auto-outward normals) - `body` / `armour` / `katana` parts - `rig` bone table - `skin` weights (rigid parts 100% to
one bone, soft parts by gaussian bone-segment distance, top 4) - `shaders` procedural PBR - `bake` atlas (drops never-seen plate undersides, packs one UV set, bakes
albedo / normal / roughness / metal / AO, rebuilds one glTF material) - `pose` pure-python pose evaluator + two-bone IK - `anim` solver (spine, planted-foot legs, two-handed
sword grip, finger curl, sode / kusazuri follow-through) - `clips` the clips - `finalize` LODs + Actions. Every clip is plain FK keys on deform bones: nothing in the file
depends on constraints.

## Gate additions (new files, shared code touched minimally)
`gp_character.py` (SKIN_NO_ARMATURE, SKIN_NOT_BOUND, SKIN_UNWEIGHTED, SKIN_MAX_INFLUENCE, SKIN_BAD_GROUP, RIG_BONE_BUDGET, ANIM_MISSING, ANIM_SHORT, ANIM_LOOP_MISMATCH,
ANIM_ACTIVE) - `gp_export` exports armature + one animation per Action for `type: character` - `gp_glb.inspect` reports skins / joints / animations and checks `glb_expect.animations`
- `recipes/character.py` writes `clips.json` (frames, loop, weapon state, stride speed) into the manifest - `viewer/character.html` is the engine check.

## Gotchas learned here (candidates for GOTCHAS.md)
1. Blender 5 keeps vertex-group NAMES on the mesh: `vertex_groups.new()` on a copy that already has them creates `chest.001` duplicates (decimated LODs lost their weights).
2. A fully metallic Principled has no diffuse colour: baking DIFFUSE gives black gold / steel. Bake albedo with Metallic forced to 0; carry metal in the ORM map.
3. `bpy.ops.object.join` does not join in list order: tag faces with an int attribute before joining when you must map data (UVs) back to the sources.
4. After toggling edit mode, re-fetch `mesh.uv_layers[name]`: the old wrapper crashes Blender on `.data.foreach_get`.
5. Hand-written outward flags rot: derive plate / slab normals from an inner reference point (`param_surf(..., inside=...)`) or removing "hidden" undersides deletes the outer skin.
6. The glTF exporter reads clip times from the SCENE frame rate (24 by default): set `scene.render.fps = 30` or every clip is 25% slow.
7. Mirror a two-handed grip across the sword's flat plane (left hand = reflected right hand, slid along the hilt) and nudge the sword, not the hands, when a grip is out of reach.

## Limits (not hidden)
Procedural geometry and textures are not sculpted or scanned fidelity: plate edges are chamfered slabs, hands and face are simple, the menpo is a stylised mask. Cloth does not
simulate (kusazuri / sode follow-through is analytic). Animation is authored by code, not motion capture: poses are plausible and foot-planted, not an animator's polish. No team-colour
mask, no facial animation, no draw / sheathe transition clip, no hit-direction variants. Measured in one browser on one GPU (Apple, Metal); frame cost per unit is not profiled.
