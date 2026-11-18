# Blender 5.3 gotchas (each one cost real time; each is covered by a test or a lint rule where possible)

| # | Trap | What happens | Do this | Guard |
|---|---|---|---|---|
| 1 | `n is node` on bpy nodes/objects | always False (bpy returns a fresh wrapper per access); e.g. no node selected -> bake does nothing | use `==` | `gp lint` BPY_IS_IDENTITY |
| 2 | Bake without an **active AND selected** Image Texture node | Cycles prints one `Info:` line and bakes nothing; image stays flat; export "passes" | `nodes.active = node` and `node.select = True` (others False) | lint BAKE_NO_ACTIVE_NODE, validator TEX_BLANK |
| 3 | glTF alpha mode | Blender 5.x exporter ignores `blend_method`; reads the node graph | Image alpha -> Math **Round** -> Principled Alpha = `MASK`; otherwise `BLEND` | lint BPY_BLEND_METHOD, validator ALPHA_BLENDED, GLB check |
| 4 | Geometry Nodes *Distribute Points on Faces* (Random) | `Density Factor` does not exist (Poisson only); `Density` is the field | multiply your mask into `Density` | lint GN_DENSITY_FACTOR |
| 5 | Same field, per face | density field is evaluated per FACE: a single-quad emitter gets one value (0 near origin = no points) | subdivide the emitter (e.g. 200x200 grid) | - |
| 6 | Nodes with several same-named sockets (Random Value, Math, Mix) | indexing `.inputs[2]` picks the wrong one | filter by name **and** `.enabled` | lint GN_INDEX_SOCKETS |
| 7 | Blender MCP `execute_blender_code` | `result` must be a dict; a str errors **after** the code ran | `result = {...}` | lint MCP_RESULT_NOT_DICT |
| 8 | Reading `matrix_world`/evaluated data after creating or moving objects | stale transforms | `bpy.context.view_layer.update()` first | lint BPY_NO_UPDATE |
| 9 | Removing objects | `view_layer.objects` keeps stale `None` entries until updated -> `NoneType.select_set` | `view_layer.update()` after removal; skip `None` | - |
| 10 | Bump/procedural normal bake | a material with no bump bakes a perfectly flat normal map | recipes omit flat normals (and say so) | validator treats flat textures as failures unless omitted |
| 11 | glTF exporter KTX2 | KTX2 is only *added* next to the original PNG/JPEG: every texture ships twice (21 MB vs 9 MB) | `gp_glb.strip_fallback_images` (done in `gp_export`) | GLB check, golden test |
| 12 | Re-importing compressed GLBs for previews | may not decode in Blender | preview renders an **uncompressed twin** (`out/<asset>/_preview/`) | - |
| 13 | `bpy.ops.wm.read_factory_settings` (used by preview) | wipes the open scene | headless runs only; never in the live session | - |
| 14 | `get_screenshot_of_window_as_image` (MCP) | flaky "Unterminated string" error | pass `size_limit_in_bytes` (e.g. 500000); or render to a file | - |
| 15 | Physical sky enum | `NISHITA` no longer exists in 5.3 (`MULTIPLE_SCATTERING`/`SINGLE_SCATTERING`); `dust_density` renamed | check enum items first; a hand-built gradient world is more controllable | - |
| 16 | `Material.use_nodes` | deprecated, removed in 6.0 | fine on 5.3; plan to drop | lint BPY_USE_NODES |
| 17 | Edit mode left open | later data access/export misbehaves | always return to Object mode | lint BPY_EDIT_MODE_LEAK |
| 18 | `bpy.ops.mesh.primitive_*` in loops | slow, churns selection | bmesh / `bpy.data` | lint BPY_OPS_IN_LOOP |
| 19 | KTX2 in three.js is async | screenshot too early shows missing/transparent textures (alpha-cut leaves vanish) | wait >= 5 s after load, then read `window.report` | SKILL.md engine check |
| 20 | Network installs from an agent | `npx`/`npm` downloads are blocked by the permission layer | use Blender's built-in meshopt + KTX2 (already wired) | - |
| 21 | Blender image pixels are **bottom-up** | writing a top-down numpy array flips the image; every tangent normal map ends up with an inverted green channel, tile laps flip | flip at the IO boundary (`gp_texgen.save_img/load_img`) | `tests/test_texgen.py` orientation round trip |
| 22 | ORM / normal maps saved as JPEG | chroma subsampling mixes the independent AO/roughness/metal channels (seam checker failed on it) | JPEG for albedo only; PNG for normal + ORM | texgen test "would NOT survive JPEG" |
| 23 | Seam metric choice | mean-based seam ratios flag designed hard edges (tile rows, plank gaps) as seams; p95 still misses them | seam diff / the LARGEST neighbour-line diff; always include a negative test (a checker that cannot fail proves nothing) | `tests/test_texgen.py` |
| 24 | Box walls under roofs | a wall box with a fixed top pokes through (or leaves a gap under) a roof whose height varies around the wall | build wall polygons whose top edge follows the roof surface minus the tile relief | QA render |
| 25 | Open roof surfaces | `faces.new` winding is yours to get right; recalc-normals picks arbitrarily on open meshes | build CCW from above; force `normal.z >= 0` for roof faces | QA render |
| 26 | Multi-LOD building in one GLB | per-LOD GLBs duplicate every texture (x3 download, x3 VRAM) | one GLB, nodes named `<x>_LOD<n>_<Material>`, per-LOD budgets via `lod_budgets` | validator BUDGET_LOD_TRIS |
| 27 | `requestAnimationFrame` as a loading "yield" | rAF is paused in background tabs: the loader hangs forever | `setTimeout(r, 0)` | - |
| 28 | fps from an embedded/unfocused browser | rAF throttled to ~30 fps regardless of GPU; `gl.finish()` is a no-op on Metal | use `EXT_disjoint_timer_query_webgl2` for GPU ms; pin `?dpr=` for sharp screenshots | measured: shadows 4 ms, grass 3.4 ms, terrain 3 ms @614x460 |
| 29 | Look colours | `new THREE.Color(r,g,b)` is scene-LINEAR: colours picked as "display" values render washed out | author look colours linear (more saturated numbers) or `setRGB(..., SRGBColorSpace)`; grass tints are squared in the shader | screenshot review |
| 30 | InstancedBufferGeometry sharing attributes | `geometry.dispose()` deletes GL buffers of shared attributes | clone the BufferAttribute (share the typed array) per geometry | - |
| 31 | Instanced-mesh shadows | all LODs casting shadows made the shadow pass the largest GPU cost | only LOD0-1 cast; tighten LOD distances | GPU timer |
| 32 | `preview_start` config location | the tool reads `.claude/launch.json` from the session's ORIGINAL folder, not the folder you moved to | put the server config there (or serve with a plain `python3 -m http.server`) | - |
| 33 | Browser pane hidden (embedded browser) | `innerWidth/innerHeight` are 0: every render target is zero-sized, WebGL spams "Framebuffer is incomplete"; rAF is throttled | `resize_window` emulation (e.g. 1024x768) gives the page a real size even when the pane is hidden; the game skips frames when it has no area | `world`'s zero-size guard |
| 34 | Water plane over a bounding box | any natural dip inside the box below the water level floods with a straight-edged "diamond" pond | give `Water` a `mask(x,z)` for the carved basin; carve + terrace the terrain so the shore is a real slope | screenshot review |
| 35 | Planar reflection | below-surface geometry leaks into the mirror; grass/particles double the cost; the shadow map re-renders | oblique near plane = water plane; hide grass + particles; freeze `shadowMap.autoUpdate` during the pass; skip when the camera is underwater | `runtime/water.js` |
| 36 | Post chain order | tone-mapping materials before bloom clips highlights; grading before tonemap is HDR-unsafe | HDR MSAA target (HalfFloat, samples 4) -> bloom -> OutputPass (ACES + sRGB) -> LDR grade (sat/contrast/split-tone/vignette) | `runtime/post.js` |
| 37 | `renderer.info` with a composer | `autoReset` clears per pass: the HUD shows only the last pass | `info.autoReset = false` and `info.reset()` once per frame | HUD numbers |
| 38 | Lumpy (thatch) roofs vs plaster walls | wall tops poke through the relief as white slivers | sink wall tops `relief + margin` (0.22 m) below the roof surface; the thick eave hides the gap | minka QA render |
| 39 | Atmosphere is cheap if it follows the sun | a uniform fog colour flattens golden hour | tint the fog colour per frame toward the sun colour by `pow(dot(viewDirXZ, sunDirXZ), 3)`; add a cool no-shadow fill light opposite the sun so shade stays readable | screenshot review |
| 40 | Grass on roads | tall blades lean over the verge; a blurred splat map cannot cut cleanly | a sparse 0.5 m road-distance grid (exact near roads, 99 elsewhere); density 0 inside the road edge, feathered verge; test with the real style function on the road centreline | JS probe: 0/71 road samples carry grass |
