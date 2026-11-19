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
| Budget | LOD0 23,964 / LOD1 6,964 / LOD2 2,131 tris (collapse-decimated, weights kept, <= 4 influences) + three weapon meshes (1.6k) + the banner (0.24k); 34,937 of the 36k cap; LOD0 cap 24,000 |
| Material | ONE material, 2048 atlas: albedo (KTX2) + tangent normal + ORM (AO / roughness / metal). 7.1 MB GLB, meshopt + KTX2 |
| Rig | 62 deform bones: spine x4, neck, head, 2x(shoulder, arm, forearm, hand, 10 finger bones, thigh, shin, foot, toe, sode, 3 kusazuri), `weapon_hip`, `weapon_r`, and nine cloth bones: `sash_a1/2`, `sash_b1/2` (obi tails), `banner_1/2` (sashimono pole), `flag_1..3` (the flag). Budget 64 |
| Clips (30 fps) | sheathed, in place: `idle` `walk` `run` - drawn: `run_drawn` (one-handed carry) `combat_idle` `attack_overhead` `attack_diagonal` `attack_horizontal` `attack_thrust` `block` `hit` `death` - transitions: `draw`, `sheathe` (weapon swap at an event time). `clips.json` carries `events` (`impact`, `swap_weapon`), `weapon` / `weapon_end` and `speed_mps` |

## Using it in a game
- **Facing / scale**: origin between the feet on the ground, +Z forward (glTF), metres. Never rotate the model to fix facing; rotate the unit.
- **The team banner (`Sashimono`) is a separate skinned node** (pole, bracket, two-sided cloth; 244 tris) driven by `banner_1/2` (pole) and `flag_1..3` (the flag); the clips carry the SIMULATED motion of those bones (see "Cloth" below). It is baked into LOD1 and LOD2 like the scabbard (a flat cloth decimates to its corners, 3 + 2 triangles for the two faces, which is all a flag needs; a team marker at ~26 m, a few pixels at 60 m): show the node at LOD0 only. The pole sits 21 mm behind the neck guard at rest. Measured on the evaluated skinned meshes over every frame of every clip (`generators/samurai_cloth_check.py`: pole AXIS sampled between ring centres, unsigned distance minus the 7.5 mm radius): at least 15 mm clear in 11 of the 14 clips, 9.1 mm in `hit`, 4.1 mm in `attack_diagonal` (the forearm), and -7.3 mm in `attack_overhead` for 2 of 31 frames (the raised forearm passes through the pole). The first spring pole (k 0.035) flexed up to 7.7 degrees in a hit and touched the head (-1.6 mm); it was stiffened (k 0.08, bamboo) and re-measured.
- **Faction emblems** (`<asset>.emblems.png` + `<asset>.emblems.json`): the albedo carries NO crest; the cloth is plain team colour (all of it is in the team mask). The sheet is 4 x 2 cells of 128 px, 8-bit grey SIGNED DISTANCE (0.5 = the edge, > 0.5 inside, `spread` 0.25 cell half-widths per half range), eight procedural crests (`names` in the json). The engine draws the faction's crest where a fragment's BIND-POSE position (the `position` attribute, which is the bind pose even on a skinned mesh) lies in `banner.gltf` of the json (glTF axes: x, y up, z = -y_blender; the cloth is 3 mm thick, ~1 mm quantised in the GLB, so keep >= 3 mm margins). Cell (c, r) is at `(c / cols, r / rows)`, `v` down, load with `flipY = false`, `NoColorSpace`. The cloth's +x is the viewer's left from behind the unit: flip `u` on the face whose bind normal has `z < 0`, so the crest reads the same on both faces (an asymmetric crest, the crescent, is the test). Select the cell per team with a uniform of the per-team material (and of its hit-flash twin). Reference implementation: `viewer/team_emblem.js`; the game's copy is in samurai-vale. One asset, one material, one draw call serves any number of factions.
- **Weapons are separate skinned nodes**: `Katana_Sheathed` (hilt on the hip), `Katana_Drawn` (in the hands), `Katana_Saya` (always on the hip). Clip metadata
  `weapon: sheathed|drawn` in `clips.json` says which of the first two to show. Swap at the event frame of your draw / sheathe transition.
- **LODs share one skeleton**: show exactly one `Samurai_LOD<n>` mesh. The scabbard and the banner are baked into LOD1 and LOD2 (and the sheathed hilt into LOD2): hide `Katana_Saya` and `Sashimono` from LOD1 on and both weapon nodes at LOD2. Draw calls per unit: 4 (body, scabbard, blade, banner) / 2 / 1. Suggested switch distances: 0-17 m, 17-42 m, 42+ m.
- **Locomotion is in place**: move the unit yourself and set `action.timeScale = unitSpeed / clip.speed_mps` (walk 1.09 m/s, run 3.13 m/s). Stance feet then do not slide
  (tested: planted-foot speed equals `speed_mps`).
- **Skinned meshes must set `frustumCulled = false`** (or use a bounding sphere that covers the animation): bind-pose bounds cull the unit mid-lunge.
- Loop clips repeat their first pose as the last frame. Use `LoopRepeat` on the whole duration; the exporter keeps one extra identical frame, so the loop holds one frame.
- **Team colour**: `<asset>.team.png` (1024, R = 1 where the lacing, cords and sash are; same atlas UVs; load with `flipY = false`, `NoColorSpace`). Tint in the shader after the map: keep the albedo's luminance, take the team colour, mix by the mask. Use one material per team, not a per-mesh uniform.

## How it is built (modules in `generators/samurai/`)
`kit` mesh kit (lofts, tubes, slabs, lamellar strips, auto-outward normals) - `body` / `armour` / `katana` parts - `rig` bone table - `skin` weights (rigid parts 100% to
one bone, soft parts by gaussian bone-segment distance, top 4) - `shaders` procedural PBR - `bake` atlas (drops never-seen plate undersides, packs one UV set, bakes
albedo / normal / roughness / metal / AO, rebuilds one glTF material) - `pose` pure-python pose evaluator + two-bone IK - `anim` solver (spine, planted-foot legs, two-handed
sword grip, finger curl, sode / kusazuri follow-through) and the two-pass `bake` (solve every frame, simulate the cloth on that motion, then key) - `cloth` offline cloth chains - `emblems` the crest sheet (pure python) - `consts` pure constants shared by banner / shader / emblems - `clips` the clips - `finalize` LODs + Actions. Every clip is plain FK keys on deform bones: nothing in the file
depends on constraints.

## Gate additions (new files, shared code touched minimally)
`gp_character.py` (SKIN_NO_ARMATURE, SKIN_NOT_BOUND, SKIN_UNWEIGHTED, SKIN_MAX_INFLUENCE, SKIN_BAD_GROUP, RIG_BONE_BUDGET, ANIM_MISSING, ANIM_SHORT, ANIM_LOOP_MISMATCH,
ANIM_ACTIVE) - `gp_export` exports armature + one animation per Action for `type: character` - `gp_glb.inspect` reports skins / joints / animations and checks `glb_expect.animations`
- `recipes/character.py` writes `clips.json` (frames, loop, weapon state, stride speed) into the manifest and copies the team mask and (when the spec declares `character.emblems`) the emblem sheet + json (a declared but missing sheet fails the build) - `viewer/character.html?team=0|1` is the engine check (team tint + emblem via `viewer/team_emblem.js`).

## Cloth (what is simulated and what is not)
**Simulated, offline, baked into bones** (`generators/samurai/cloth.py`): the two obi tails (2 bones each), the sashimono pole (2 bones, a stiff spring: lags the chest by a few degrees) and the flag (3 bones). Each chain is a short Verlet particle chain (8 substeps per frame, 8 constraint iterations) pinned to its parent bone's REAL animated motion (the pose evaluator gives the body's matrices per frame): rigid segments, a weak pull back to the rest shape in the parent frame, gravity, air drag against a unit-local wind (a weak breeze + periodic gusts + the headwind of the clip's own locomotion), collisions, and a clamp on how far a segment may turn. The tails collide with the front kusazuri (an ellipse cone evaluated in the swinging panel's own frame), the thighs / shins, the trunk, the forearms / hands and the ground, using their half WIDTH (a ribbon that swings sideways presents its width to the armour). Loops: 4 cycles are simulated and the last recorded, then the residual between its end and its start is removed with a linear ramp and the collisions are re-resolved, so the first and last keys are identical; one-shots settle on their first pose for 1.5 s before the recording. The result is ordinary quaternion keys (hemisphere-continuous per bone). Nothing runs in the game but the skeleton.
**Wind is NOT baked.** The clips are baked DRY (`cloth.BAKED_WIND = False`): inertia, gravity, collisions and still-air drag only. The engine adds the world's wind on top of the keys at runtime, so the flag, the tails and the pole react to the game's wind direction, strength and gusts and to the unit's own velocity through the air (a baked, unit-local wind streamed every flag the same way whatever the weather). The contract:
- `<asset>.cloth.json` (written by `cloth.runtime_descriptor()`, copied by the recipe, required when the spec declares `character.cloth`): per chain (`sash_a`, `sash_b` = ribbon, `pole`, `flag`) its kind, parent bone, per-bone rest direction and length in the glTF unit frame (x right, y up, z forward), and the response parameters (`gain`, `omega`, `zeta`, `max_deg`).
- Per frame, AFTER the AnimationMixer: `air = relativeAir(world wind direction, strength, gust, the unit's world velocity, the unit's yaw)`; per chain a damped second-order spring per bone toward a wind-driven target plus a travelling flutter; the rotation is composed onto the animated quaternion (in the parent bone's frame). Flag: streams downwind in the horizontal plane (a yaw about +Y), hangs and flutters when the air comes from its tip; ribbons (tails): tilt downwind, a push INTO the body is clamped to 0.7 degrees (3 mm of tip travel, the baked tails rest on the kusazuri); pole: leans at most 2.5 degrees.
- BEFORE the mixer: `restore()` puts the chain bones back to their rest orientation. The glTF exporter drops constant animation tracks, so in clips where a chain bone does not move (most of them, now that the bake is dry) the mixer never rewrites it and a per-frame overlay would accumulate.
- Reference implementation: `viewer/cloth_wind.js` (pure core + a thin `ClothWindRig`, no imports: the THREE namespace is passed in); the game keeps an identical copy (`src/view/samurai_wind.js`). The viewer takes `?wind=<m/s>&winddir=<degrees>` (0 = toward +x, 90 = toward +z); a clip with `speed_mps` adds its own headwind.
- Cost: LOD0 and LOD1 rigs only (9 bones, a few microseconds per rig); measured in the game's real-GPU profile: 0.03 to 0.09 ms per frame for 6 to 20 rigs, below the noise floor of a frame-time measurement.

**Not simulated**: the robe and trousers (skinned; the folds are a baked normal map), the lamellar skirt and shoulder plates (rigid plates with the analytic follow-through of `anim.secondary`), the hair, collisions of the cloth with anything the clips did not bake (the wind overlay cannot push a tail into the body because of the clamp above, but a hand or a sword that moves differently at runtime is not seen).

**Measured** (`generators/samurai_cloth_check.py`, every frame of every clip, signed distance of the tail surface to the armour by ray parity): the static tails penetrated the skirt by up to 19.7 mm in walk, run and death; the simulated tails stay within 3.5 mm (touching) in every clip. Tip travel from the rest shape, rms / max: idle 1-3 / 3 cm, walk 5-9 / 18 cm, run 11-14 / 24 cm, attack_horizontal 11-13 / 37 cm, flag tip in a hit 12 / 25 cm. Gates in `tests/test_character_golden.py`: chains finite (bone turn < 125 deg, tip travel < 60 cm), loops exact, two runs identical, `place_chain` error < 0.05 deg, run moves many times more than idle, tails out of the armour (worst > -6 mm), bone budget.

## Face and head (round 6)
The only face that shows is the band between the visor and the mask (z 1.59-1.70 m). The head loft is dense there only (rows every 7 mm, columns every 10 degrees across the front, sparse behind and below), the eyes are 25 mm wide with a sclera, a partly covered iris, upper and lower lids, a dark lash line and thick angled brows (`hair` material), the skin shader shadows the sockets and flushes the cheeks, the moustache is two dark swept tufts per side (the first version was six white tubes: 600 triangles), the menpo rim sweeps down toward the cheeks, and a cloth lining closes the inside of the shikoro (the plates are single-sided: from the front the far side was bare lacing). The rosette petals are tilted boxes (12 triangles, spheres were 24). Net LOD0 change +16 triangles.

## Gotchas learned here (candidates for GOTCHAS.md)
1. Blender 5 keeps vertex-group NAMES on the mesh: `vertex_groups.new()` on a copy that already has them creates `chest.001` duplicates (decimated LODs lost their weights).
2. A fully metallic Principled has no diffuse colour: baking DIFFUSE gives black gold / steel. Bake albedo with Metallic forced to 0; carry metal in the ORM map.
3. `bpy.ops.object.join` does not join in list order: tag faces with an int attribute before joining when you must map data (UVs) back to the sources.
4. After toggling edit mode, re-fetch `mesh.uv_layers[name]`: the old wrapper crashes Blender on `.data.foreach_get`.
5. Hand-written outward flags rot: derive plate / slab normals from an inner reference point (`param_surf(..., inside=...)`) or removing "hidden" undersides deletes the outer skin.
6. The glTF exporter reads clip times from the SCENE frame rate (24 by default): set `scene.render.fps = 30` or every clip is 25% slow.
7. Mirror a two-handed grip across the sword's flat plane (left hand = reflected right hand, slid along the hilt) and nudge the sword, not the hands, when a grip is out of reach.
8. A flat cloth (banner) is two quads after collapse-decimation: keep it two-sided (`slab(..., two_sided=True)`: the back face is a real textured face, because hidden-face stripping deletes an untextured underside and glTF materials are single-sided) and give it several rows of vertices at LOD0 so the flutter bends it.
9. Cloth that must loop: simulate several cycles and record the last, then ramp the end-to-start residual out linearly on the offset from the rest shape (in the parent's frame) and RE-RESOLVE the collisions afterwards (the ramp moves particles after the solver did: one frame of the run penetrated 13 mm until the second collision pass).
10. Bone-chain keys need quaternion hemisphere continuity per bone (negate when `q . q_prev < 0`), and the last key of a loop must be set equal to the first: Blender interpolates quaternion keys componentwise and would spin the bone the long way round.
11. Place a chain bone with the shortest arc from its rest axis to `inverse(accumulated parent delta) @ direction`; with the pose evaluator's convention (`orientation = parent_delta x q x rest`) that is exact (test: placement error 0.000 deg). Do not recompute the whole hierarchy per bone: carry `parent_delta = parent_delta x q` down the chain.
12. Measure clearance as an UNSIGNED distance, and sign it by ray parity only when the point is within a couple of centimetres: the sign of a nearest-face normal test flips on the backs of thin plates (a -99 mm "penetration" that was a 9 cm-away plate back). Measure SURFACE vertices, not an axis plus a radius, and sample between rings (a pole with rings at 1.30 and 1.70 m hid a 27 mm clip at z = 1.5).
13. A ribbon's collision radius is its half WIDTH, not its half thickness: the first tuning left 12-15 mm clips whenever a tail swung sideways.
14. Collide in the frame of the thing that moves: the kusazuri panels swing with the legs, so test the tail in the front panel's own rest frame (transform the particle by the inverse of the panel's pose-from-rest transform), not in the hips frame.
15. A crest drawn at runtime, not baked: keep the albedo emblem-free, ship a signed-distance sheet and locate the cloth by BIND-POSE position (`position` is the bind pose on a skinned mesh; no second UV set is needed and it works on every LOD). glTF axes are (x, z, -y_blender); positions are quantised by meshopt (about 1 mm here), so the region box needs >= 3 mm of margin.
16. Keep constants that several pure scripts need (`consts.py`) free of `bpy` / `mathutils`: the emblem sheet generator is plain python and must run without Blender.
17. Blender `-b -P` swallows exceptions: the exit code is 0 even after a Traceback, so a test must print a result line and the wrapper must parse stdout (and a test that shells out to Blender, like the cloth clearance gate, parses `CLOTHCHECK GATE ... PASS`).
18. Do not use a recognisable trademark shape as a crest: three triangles in a triangle read as a well-known video-game symbol; the crest set is procedural silhouettes in the manner of kamon, none a registered clan mon.
22. The glTF exporter DROPS constant animation channels: a bone whose key never changes in a clip has no track, so the mixer never rewrites it. Any runtime that adds to a bone's animated rotation must reset the bone first (`restore()` to the rest orientation before the mixer); otherwise the overlay accumulates every frame (found when a calm wind left the flag turned: the first version of the wind overlay did exactly that).
23. Wind belongs to the engine, not to the clips: a baked unit-local wind streams every unit's flag the same way whatever the weather and the unit's yaw; bake the inertia, add the world's wind per frame from the unit's relative air (world wind minus the unit's velocity, rotated into its frame).
19. `Part.slab(surf, ...)` takes surface parameters in 0..1 (the strips take real heights): a surface written for `strip` but passed to `slab` silently builds a cone near the ground (the shikoro lining was invisible for exactly that reason). The visible face of a slab is the one the closed solid's recomputed normal points along, so for an INWARD-facing lining give `param_surf` an `inside` callable that returns a point far outside (`p + (p - axis) * 5`) and the thickness goes outward.
20. Spend vertices where the camera can see them: rows and columns of the head loft are dense only on the visible band, everything under the mask, the visor and the bowl stays coarse.
21. A texture without mips minifies by point-ish bilinear sampling: the built KTX2 images have one level (Blender's encoder has no mip option; the build has no toktx / basisu). Measured in the game with the same unit and the PNG sources with mips + 4x anisotropy: -10% frame-to-frame flicker of the unit's pixels at 30 m, nothing measurable at 9-45 m once the 4x MSAA of the post chain is on, so it was left (see the spec).

## Measurement tools (numbers, not impressions)
- `generators/samurai_compare.py`: silhouette IoU vs the reference turnaround (front / side / back) + a width-by-height profile and overlay PNGs. 0.705 -> 0.83 (the reference is one AI image with its own inconsistencies; do not chase 1.0).
- `generators/samurai_clearance.py`: signed distance of every armour part to the cloth below (per-mesh ray parity): fails on penetration > 4.5 mm, reports floating hugging parts.
- `generators/samurai_cloth_check.py`: the tails and the banner pole against the armour over every frame of every clip (`--clips`, `--step`, `--assert-mm 6` prints a `CLOTHCHECK GATE ... PASS|FAIL` line); `generators/samurai_cloth_strip.py`: contact strips of the BAKED clips (cloth included; the pose-only strips of `samurai_unit.py --clip` skip the simulation).
- `tests/test_character_golden.py`: pose math = Blender skinning (< 0.2 mm), IK reach, planted-foot speed = `speed_mps`, grips never open (sword nudge < 6 cm), draw starts at the hip carry pose, events, team mask, gate, GLB contents, negative tests.

## In a game (samurai-vale is the reference integration)
Clip choice is a pure state machine (`src/view/samurai_logic.js`): the sim has no wind-up, so the swing clip starts at `impact - cd` and its impact frame lands exactly when the sim damages; a unit running at a target inside 14 m draws on the way;
locomotion playback = measured speed / `speed_mps`; death is fitted into the sim's corpse time; far units get LOD2, no weapon nodes, no shadow, a lower animation rate. See that repo's `tests/view/samurai_logic.test.mjs`.

## Pace: the shared gait, and a wind fix every engine copy needs (2026-11-19)
- `generators/samurai/gait.py` `cycle(t, T, ahead, behind, duty, lift, bob, sink, ...)` is the planted-foot cycle of all three characters: an asymmetric stance (a foot lands
  `ahead` of the hips and leaves `behind` them; ground speed = (ahead + behind) / (duty * T), `duty_for(speed, ...)` solves the duty), the heel coming up at push-off (`rise`), a
  Hermite swing that follows through and is moving back when it lands, hips highest at mid-stance for a walk and lowest for a run (`run=True`). Author a locomotion clip AT the unit's
  game speed with a natural cadence (a march about 120 steps a minute, a run about 170): an engine that matches playback to ground speed then plays it near 1.0.
  Keep `ahead` inside the leg's reach at the strike (0.82 m leg, hips 0.08 m down: about 0.26 m) or the knee locks and the foot lands short.
- Idles breathe every 4 s (every 2 s on guard); a fall is authored in real time.
- **`ClothWindRig.restore(animated)`** (`viewer/cloth_wind.js`): pass the Set of bone names the current clip has a rotation track for (`clipChainBones(gltf.animations)[clip]`).
  three.js's mixer writes a value only when it changed since its last write; restoring a chain bone to its REST orientation every frame therefore leaves it at rest on every frame its
  key did not change. A chain whose rest pose is not how it hangs (a pennant on a spear) flickers. Bones the clip animates now go back to what the mixer last wrote.
- `cloth.json` chains may carry `flutter` (amplitude x) and `flutter_hz` (frequency x): a small light cloth flutters wider and faster than a head band's tail.

## A third character: the ashigaru (2026-11-19)
`generators/ashigaru_unit.py` (kit in `generators/ashigaru/`) builds one spearman who can be dressed two ways from one code base: the levy (rawhide hat, a laced
belly guard, bare forearms) and the man in lent armour (iron hat with a neck cloth, a cuirass of riveted lames, tassets, splint sleeves and greaves, a back banner).
It was first built as two tier models (`--tier 1|2`, two GLBs); it is ONE model with its gear as nodes now: the next section. Spec `specs/ashigaru_unit_01.json`,
fixture `fixtures/ashigaru_unit.blend`, checks `tests/test_ashigaru_golden.py`. What it adds to the pattern:
- **Kit is parts lists, not forks.** `gear.haraate_set()`, `gear.okegawa_set()`, `gear.helmet_parts(kind)` pick parts; one material table (`ash_*`); the head, the
  kosode, the lower legs and the hat's cords are the archer's functions, the tassets and the greaves the samurai's. A second armour costs about 150 lines.
- **A two-handed polearm.** The spear is modelled in the right fist (shaft along the fist's axis, head on the thumb side) on a weapon bone that hangs on `hand.R` and
  SLIDES along its own axis (a location key): the hand's place on the shaft changes between standing at ease (the butt on the ground), the march (on the shoulder) and
  the guard. A clip says where the shaft is and how far apart the hands are; the solver puts both hands on that line (`anim.Solver.grip`). The weapon follows the hand
  through every crossfade, which a root-parented weapon does not.
- **Two weapons, one set of clips.** Both spears are nodes of the GLB (`Yari`, `Yari_Long`) on two weapon bones; the pike's bone slides 0.6 m further (`pike_up`)
  wherever the spear is levelled, so it is held further up and its point ends 0.5 m beyond the short spear's instead of 1.1 m. An engine shows one node.
- **A free ribbon.** The spear's pennant is a ribbon chain on the weapon bone with `body_z: 0` in `cloth.json` (nothing in front of or behind it to clamp against)
  and `k_shape = 0` in the offline solve (it hangs by gravity whatever the shaft's direction).
- `viewer/character.html?asset=ashigaru_unit_01&spear=long` shows the pike.

## Gear as pieces: one body, a kit of nodes (2026-11-19)
The ashigaru is ONE model now (`generators/ashigaru_unit.py`, no `--tier`): a body that is whole on its own and eight pieces of kit as separate skinned nodes on
one 62-bone skeleton (`ashigaru/gear.py` `nodes()`: `Armour_HaraAte`, `Armour_Okegawa`, `Helmet_Jingasa`, `Helmet_Tetsu`, `Yari`, `Yari_Long`, `Side_Tanto`,
`Sashimono`). An engine shows the pieces a unit has. The archer's war hat is the node `Helmet` the same way.
- **Occlusion per piece**: `samurai/bake.py` `bake_atlas(..., ao_groups=[(own, others), ...])`. The texels of `own` are occluded by `own` and `others` and nothing
  else: the body by itself, each piece by itself and the body. A bare head keeps no hat shade; two hats in one place do not black each other out; the archer's
  full and low bow no longer shade each other. Passes bake only their own texels (margin 0); `_dilate` fills the gutters of the composed map.
- **`ao_alone`** (on for archer and ashigaru): the source objects are hidden while the joined copy is baked. They lie exactly on it and half-occluded every open
  surface: this was the real cause of the occlusion grain blamed on sample counts below.
- **Levels**: `Ashigaru_LOD0/1` are the body; `Armour_<x>_Low` the armour at LOD1; `Ashigaru_Far_<armour>_<head>` (2 x 3, 2,400 triangles each) are body, armour
  and hat in one mesh for the far level, where a crowd is. Far meshes with the iron hat are built without the head band's tails (`finalize._without_groups`).
  A far mesh must not end in `_LOD<n>`: engines find body levels by that ending.
- **The body is whole**: `archer/body.py` `hair_parts` has a round crown and a tied knot (it clears every hat's lining by 8 mm or more); `ashigaru/body.py`
  has bare forearms under the lent armour's sleeves (`gear.kote_parts` goes over them).
- **Viewer**: `?show=Armour_Okegawa,Helmet_Tetsu,Side_Tanto,Sashimono` dresses a model that has optional nodes (default: the first armour, the first helmet, the
  side pieces); `__view.dress([...])` changes it without a reload; LOD2 shows the matching far mesh.
- **QA sheet of one kit, no bake**: `ashigaru_unit.py -- --render out/_ash --kit okegawa,tetsu,long,tanto --views front,back,head,top,head_b`.
- **`equip`** (ashigaru and archer, `clips.py`): 1.6 s, one-shot, event `take` at 0.85 s. Standing at ease he leans to a rack, the free hand closes on a
  piece, he lifts it to himself. An engine that lets a unit fetch gear plays it at the store and changes the shown nodes at `take`.
- Golden tests: `tests/test_ashigaru_golden.py` (on `fixtures/ashigaru_unit.blend`), `tests/test_archer_golden.py`.

## Build id, occlusion grain, viewer hooks (2026-11-19)
- `manifest.json` carries `build`: the first 12 hex digits of the SHA-1 of the exported GLB(s). An engine should fetch the manifest uncached and append the id to every
  URL of the asset (GLB, team mask, emblem sheet, clips, cloth): a rebuilt GLB with last build's team mask from the browser cache paints team colour on the wrong texels.
- `samurai.bake.bake_atlas(..., ao_samples=N, ao_blur=True)`: N FIXED occlusion samples and a 5 x 5 binomial filter. The default (40 adaptive samples) leaves grain that
  lacquer hides and bare skin in a hat's shade shows as a stipple (there the image light times the occlusion is all the light there is). The archer bakes with 192 + blur.
- Sub-texel shader noise (pores at 900 / m on a face that is 170 texels wide) bakes into random normals: leave it out.
- `viewer/character.html`: `window.__view.frame(pos, target, fov)` renders one frame synchronously (captures from a hidden tab, where no animation frames run),
  `__view.step(dt)` advances the mixer and the wind; hard-edged PCF shadows with a normal bias (a hat brim over a face).

## A second character: the light archer (`generators/archer_unit.py`, kit in `generators/archer/`)
```bash
blender -b --factory-startup -P generators/archer_unit.py -- --bake out/archer_tex --px 2048 --quality 1.0 --finalize 1 --save fixtures/archer_unit.blend
bin/gp build specs/archer_unit_01.json && blender -b fixtures/archer_unit.blend -P tests/test_archer_golden.py      # gate, then 30 checks
bin/gp view   # http://localhost:8765/viewer/character.html?asset=archer_unit_01&clip=aim
```
Same recipe, gate and contract; it imports the samurai's `kit`, `pose`, `bake`, `finalize`, cloth solver and shared body parts and changes none of them. What is new:
- **Nodes**: `Archer_LOD0..2`, `Yumi` (the bow), `Arrow_Nocked`, `Sashimono`. The bow and the banner are in the body mesh from LOD1 on (joined AFTER decimation: a thin bow does not survive it; LOD2 gets its own low-poly bow).
- **The bow rig**: `weapon_l` (child of `hand.L`; the bow is modelled in the grip), `bow_u1/u2`, `bow_l1/l2` (the limbs flex), `bow_nock` (translates: the string's two strands end on it), `arrow`. `anim.BowModel` solves the limb angle that keeps the string's length for a given pull.
- **Clips** (13): `idle walk run ready stand_down combat_idle shoot aim crouch_idle sneak crouch_shoot hit death`. `clips.json`: `weapon` is `none` or `arrow` (the nocked-arrow node is visible for the whole clip); shot clips carry `events.arrow` (show the node) and `events.release` (hide it: the engine's projectile flies).
- **Cloth**: two hachimaki tails behind the head (`kind: ribbon`, `body_z: 1`: the engine clamps a push toward +z instead of -z), the pole and the flag.
- **Live session**: `archer.build.build_model(live=True)` builds in its own scene (`Archer`) and clears only that scene. Bakes stay headless.

## Limits (not hidden)
Procedural geometry and textures are not sculpted or scanned fidelity: plate edges are chamfered slabs, hands and face are simple, the menpo is a stylised mask. The free cloth (tails, flag, pole) is simulated offline per clip and baked; the garments are skinned with baked folds and the plates are rigid with analytic follow-through (see Cloth). Animation is authored by code, not motion capture: poses are plausible and foot-planted, not an animator's polish. Cloth folds are a baked normal-map detail (the robe does not simulate), the kabuto rivets and the mask wrinkles are shader detail, not geometry. No facial animation, no hit-direction variants; eight crest designs (more cells = a bigger sheet, no new asset). Measured in one browser on one GPU (Apple, Metal); frame cost per unit is not profiled.
