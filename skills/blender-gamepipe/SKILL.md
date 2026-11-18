---
name: blender-gamepipe
description: Turn Blender assets (trees, grass, rocks, props, buildings) and procedural PBR textures into verified, game-ready GLB/texture sets with LODs and KTX2/meshopt compression, and prove they render in three.js. Includes a reusable three.js runtime (terrain biomes, wind grass, instanced tree LODs, sky) and a world hand-off tool. Use when asked to export or optimise a Blender asset for a game/web engine, bake/LOD/validate assets, generate tileable ground or building textures, build a three.js world from the assets, or write/debug bpy scripts (bake, export, geometry nodes).
---

# blender-gamepipe

A deterministic **loop around Blender**: spec -> lint -> build -> validate -> export -> inspect the GLB -> engine check.
The agent supplies judgement (recipes, fixes, art direction); the scripts supply the gate. **Nothing ships unless the gate says pass.**

## The one rule
**Never claim an asset is done from your own reading of a render or a log.** Done means ALL of:
1. `bin/gp build <spec>` exited **0** and `out/<asset>/manifest.json` says `"passed": true`.
2. You opened a preview/QA image and **looked** (silent failures look fine in logs: blank bakes, flipped textures, poking geometry).
3. The **engine check** succeeded (the files load in three.js, textures arrive compressed, no console errors, it looks right in the actual lighting).
If any step failed or was skipped, say so plainly.

## Quick start
```bash
bin/gp test                                  # everything (needs Blender; ~5 min)
bin/gp textures specs/biomes.json            # 11 tileable PBR sets (7 biomes + 4 building materials) + seam checks -> out/textures/
bin/gp generate generators/samurai_keep.py   # procedural keep -> fixtures/samurai_keep.blend (needs the textures first)
bin/gp build specs/samurai_keep_01.json      # recipe -> gate -> GLB -> inspect -> manifest -> preview   (-> out/<asset>/)
bin/gp build specs/grass_blades.json         # wind-ready blade pack (no source scene needed)
bin/gp build specs/tree_maple_01.json        # tree LOD0-3 incl. impostor
bin/gp lint my_script.py                     # catch Blender traps BEFORE running bpy code
bin/gp glb out/<asset>/*.glb                 # inspect exported files without Blender
bin/gp view                                  # single-asset viewer: http://localhost:8765/viewer/?asset=<name>
python3 tools/export_world.py --dest ../my-game --models ... --biomes ...   # assemble a game folder (refuses failed assets)
```
Blender is auto-detected on macOS; otherwise `export BLENDER=/path/to/Blender`.

## Pipeline map
| need | tool | output |
|---|---|---|
| tileable ground/biome/building PBR (13 sets: 7 biomes, stone, plaster, 2 woods, roof tile, thatch) | `gp textures` (`gp_texgen.py`) | `<name>_albedo.jpg`, `_normal.png`, `_orm.png` + contact sheet + seam report |
| hero tree -> LODs + impostor | recipe `tree` | `<asset>_LOD0..3.glb` (own textures) |
| rock/prop with procedural material | recipe `prop` | LODs sharing one baked PBR set |
| grass | recipe `grass` | `grass_blades.glb` (3 variants x 2 LODs, 30 tris; uv.y = height along blade) |
| building (multi-material, authored LODs) | `generators/{samurai_keep,minka,teahouse}.py` (shared `gen_common.py`) then recipe `building` | ONE GLB holding LOD0-2, textures shared |
| skinned, animated character | `generators/samurai_unit.py` (kit in `generators/samurai/`) then recipe `character` | skinned LOD0-2 + weapon nodes in ONE GLB, one animation per clip, `clips.json`; read `docs/character.md` first |
| engine | `runtime/*.js` (three.js ES modules) | terrain biomes, wind grass, instanced forests, sky, player |
| hand-off | `tools/export_world.py` | self-contained game folder |

## Workflow
1. **Spec** (`specs/*.json`): name, type, `recipe`, `source_blend`, budgets, `recipe_cfg`, `glb_expect`, `export`. Copy a neighbour.
2. **Lint** any bpy you write (`bin/gp lint`). Fix every `error`.
3. **Build** headless. Never bake/render inside a live Blender session (see Entry points).
4. **Read the report**, not just the exit code: `out/<asset>/*.report.json` has stable finding `code`s.
5. **Fix and rebuild.** Don't raise a budget to pass unless the user agreed.
6. **Look**: open `*.preview.png` (and for generators `--render` QA views). Judge silhouette, materials, scale.
7. **Engine check** (below), then report per-LOD tris, sizes, what was verified and what was not.

## Entry points
- **Headless (default):** `bin/gp build ...` = `blender -b <source.blend> -P gamepipe/gp_cli.py -- <spec>`.
- **Live Blender via MCP:** `gp_live.run_headless_from_live(spec)` saves a COPY of the open scene and runs headless (bake/render in the live session time out and freeze the UI). `execute_blender_code` snippets must assign `result = {...}` (a dict).

## Engine check (three.js) - required
Single asset: `bin/gp view`, open `http://localhost:8765/viewer/?asset=<name>`, wait **>= 5 s** (KTX2 transcodes on a worker), then
`JSON.stringify({state: window.__state, report: window.report})`. Expect `tris` == manifest, `mapIsCompressed:true`, bark `normalMap/aoMap/roughnessFromMap:true`, leaves `alphaTest:0.5`, no console errors.
A whole world: use `runtime/` (see `runtime/index.js`); build the world by wiring these modules together (terrain + biomes, grass, forests, water, sky, post); `tools/export_world.py` assembles the game folder.
Measure real GPU time with `EXT_disjoint_timer_query_webgl2` (`gl.finish()` is a no-op on Metal); rAF is throttled in background/unfocused
tabs so fps from an embedded browser is a lower bound, not a measurement.

## Recipes (gamepipe/recipes/*.py) - contract in `recipes/__init__.py`
`META = {name, version, needs}` + `build(spec, out_dir) -> [derived specs]` (each: `name,type,include_objects,budgets.max_tris,export`). Recipes create NEW objects. Add one: module + spec + test (copy `tests/test_recipes.py`).
| recipe | input | notes |
|---|---|---|
| `tree` | bark mesh + leaf mesh (one island per leaf, **first vertex = leaf base**) | bake albedo/normal/ORM, leaf cards on a generated atlas, LOD1-2 decimated, LOD3 impostor; `leaf_palette`: green/autumn/sakura |
| `prop` | one mesh with procedural material | decimated LODs, shared baked set; flat normal maps are omitted |
| `grass` | none (generated) | blade UV: u across, **v = height 0..1**; Blender Z-up -> glTF Y-up, bend toward -Z |
| `building` | collections of authored LOD objects named `<x>_LOD<n>_<Material>` | pass-through to the gate; `lod_budgets` enforce per-LOD tris; ONE GLB |
| `character` | an armature + skinned LOD meshes + Actions (built by `generators/samurai_unit.py`) | gate adds SKIN_* / RIG_BONE_BUDGET / ANIM_* codes; exports skins + one animation per Action; writes `clips.json` into the manifest. See `docs/character.md` |

## Generators (generators/*.py) - for assets built from code
`samurai_keep.py`: tenshu on an ishigaki base, ~23 m tall. Method = **geometry for silhouette + tileable PBR at fixed world-scale texel density**
(UVs are world-space planar projections: stone/plaster 3 m, wood 1.5 m, tile 1.6 m per repeat). Tris: LOD0 57k, LOD1 16k, LOD2 4.5k.
Render QA views with `--render out/_keep.png --no-save` and LOOK at them. Hard-won rules: open roof surfaces must face up; walls must follow the roof
surface (not a box) or they poke through; tilt quoins by the wall batter; world-space UVs only.

## Buildings built so far (all procedural, all through the same gate)
| asset | what | tris LOD0/1/2 | notes |
|---|---|---|---|
| `samurai_keep_01` | castle keep (tenshu) on ishigaki base, ~23 m | 57k / 16k / 4.5k | 5 materials incl. gold finials |
| `minka_01` | thatched farmhouse, hip roof, shoji veranda | 12k / 3.4k / 0.9k | thatch = lumpy height-field; walls sink 0.22 m under it |
| `teahouse_01` | waterside teahouse on 28 stilts + pier + lanterns | 20k / 6.5k / 0.8k | **origin = water surface**, +Y = toward shore; needs `origin_tolerance` 3.6 (stilts) |
Each generator: `bin/gp generate generators/<x>.py [--render out/_x.png --no-save]` -> look at the QA renders -> save fixture -> `bin/gp build specs/<x>_01.json`.

## Runtime (runtime/*.js) - copy into a game via export_world
`assets.js` (GLB loader w/ meshopt+KTX2, biome texture arrays) - `terrain.js` (7-biome splat, anti-tiling, tangent frame, distant autumn canopy + snow line) - `grass.js` + `grass_clump.js` (chunked tiers, GPU wind, trampling; `clumps: true` = tall rice-field clumps with seed heads) - `water.js` + `water_waves.js` (shared GPU / CPU wave model, baked-bed shoreline + foam, absorption, caustics, planar reflection, ripples; `heightAt/normalAt/depthAt` for floating things) - `post.js` (MSAA HDR -> bloom -> ACES -> grade) -
`foliage.js`/`trees.js` (instanced LOD buckets, sway, translucency) - `sky.js` (3-stop gradient, sun halo, lit cumulus + cirrus) - `look.js` (shared `looks/*.json`, incl. fill light) - `player.js` - `scatter.js` - `quality.js` (adaptive resolution) - `noise.js` - `noisetex.js` (one tileable 4-channel noise texture) - **day / night, seasons, weather**: `env_clock.js` (solar + lunar astronomy), `env_atmosphere.js` (keyframes by sun elevation from `looks/atmosphere.json`), `env_seasons.js` (grass / leaf / ground / snow state + appliers), `env_weather.js`, `env_sky.js`, `env_lighting.js`, `env_grade.js` - **life**: `aquatic.js` (reeds, lily pads, flotsam, shore rocks), `fauna.js` (koi, ducks, dragonflies).
The `looks/golden_hour.json` look is an AUTUMN low-sun look (sun 16 deg from the west, warm sky, cool fill, bloom + grade). Colour authoring: look JSON colours are **scene-linear** (they are NOT sRGB); grass tints are authored as display colours and squared in the shader.

## Validator codes (fix, don't silence)
BUDGET_TRIS/BUDGET_LOD_TRIS/BUDGET_FILE_SIZE/BUDGET_MATERIALS (over budget) | UV_MISSING | MAT_PROCEDURAL (bake it) | TEX_BLANK (a bake silently failed) |
TEX_TOO_LARGE | ALPHA_BLENDED/GLB_ALPHA_BLEND (route alpha via Math Round -> MASK) | XFORM_NEG_SCALE/NONUNIFORM | ORIGIN_NOT_AT_BASE | MESH_ZERO_AREA/NON_MANIFOLD |
MOD_GEONODES | GLB_* (problems in the exported FILE). Texture generator: NOT_TILEABLE, TEX_FLAT, ALBEDO_RANGE, NORMAL_TOO_STRONG.

## Gotchas
Read `GOTCHAS.md` before writing bpy or shader code. Highlights: `==` not `is` on nodes; bake needs an active+selected image node; Blender images are
**bottom-up** (flip at IO or every normal map is inverted); ORM/normal maps must be PNG (JPEG chroma subsampling corrupts data channels);
glTF alpha mode comes from a Round node; KTX2 is exported twice unless stripped; never trust fps from a background tab.

## Not covered (be honest)
Motion capture / hand-polished animation (the `character` recipe's clips are authored by code, see docs/character.md), rivers/underwater, terrain streaming/collision beyond circle colliders, audio, rigid-body physics (water surface physics for floating things IS covered), precipitation (the weather state carries `precip` for it). Lower tree LODs reuse LOD0's normal map.
Roughness is derived from albedo luminance. Procedural modelling is not hand-sculpted/scanned fidelity. KTX2 verified in one browser/GPU (Apple M4 / Metal).
