# Samurai unit: upgrade plan, frozen interface, status (2026-11-18)

## Frozen game interface (do not rename; model changes must keep this stable)
- GLB `out/samurai_unit_01/samurai_unit_01.glb`; skinned meshes `Samurai_LOD0/1/2` (show exactly one), `Katana_Drawn`, `Katana_Sheathed`, `Katana_Saya`.
- `Sashimono` (team banner: pole + two-sided cloth, separate node at LOD0, baked into LOD1/2, flutter bones `banner_1` / `banner_2` keyed in every clip), `samurai_unit_01_team.png` (team mask, same atlas UV, NoColorSpace, flipY=false; the banner cloth is in the mask).
- Clips: `idle walk run combat_idle attack_overhead attack_diagonal attack_horizontal attack_thrust block hit death` (+ `draw`, `sheathe` when added).
- `clips.json` per clip: `frames fps duration loop weapon(sheathed|drawn) speed_mps` (+ `events` e.g. `{"swap_weapon": 0.42, "impact": 0.6}` in seconds).
- Facing glTF +Z, origin between the feet, metres, in-place locomotion.

## Rest pose parameters changed in this pass (rig.py)
`S_ARM` 32 -> 24 degrees; `LEG_PTS` knee x 0.148, ankle x 0.192 (legs spread ~6 degrees like the reference); shared `TORSO_Z/RX/RY` (chest deeper); skirt flare rx +0.092 / ry +0.010;
shikoro flare rx +0.118 / ry +0.062; wings up and out. Every part that follows the leg uses `rig.leg_center(z)`.

## Gates (report against these, not impressions)
| gate | baseline | now | target |
|---|---|---|---|
| silhouette IoU front / side / back (`generators/samurai_compare.py`; body + armour only, weapons and banner hidden; re-run in round 4, unchanged) | 0.665 / 0.784 / 0.665 (mean 0.705) | 0.837 / 0.813 / 0.834 (mean 0.827) | ~0.85 mean (the reference is one AI image with its own inconsistencies) |
| armour-to-body clearance (`generators/samurai_clearance.py`) | many parts 20-75 mm deep (no armholes, sode inside sleeves) | 0 parts > 4.5 mm (armholes, sode shell around the arm axis, straps on the surface) | no penetration > 4.5 mm |
| hand: finger segments, palm taper, grip wrap | blocky tubes | DONE: tapered palm, 3 phalanges per finger with knuckle swelling, thumb mass, fingertip pads; hilt held between curled fingers (grip point moved in front of the palm) | 3 visible phalanges, knuckles, thumb mass |
| grip error | 0 mm (solver), 5-46 mm nudge | keep | <= 6 cm nudge, hands wrap the hilt |
| in-game look at 14 / 62 / 150 m under the autumn grade | not seen | seen at 13 m and 62 m: teams read (red/blue lacing via mask), units sit in the tall grass | readable teams, no black blob |
| frame cost (real Chrome window, real loop, interleaved variants; the game's `tools/perf/run_profile.py`) | not measured | hidden-pane GPU timer queries: +10 ms at 40 m, +53 ms all within 22 m | skinned units +0.5 to 3.5 ms per frame (2-12% of a 16-31 ms frame) for 6-64 samurai on an Apple M4; wind overlay 0.03-0.09 ms | repeat on a low-end GPU |

## Order
1. DONE: rest-pose change verified (golden test) + clearance metric.  2. DONE: working slice in samurai-vale (loader, rigs, clip selection, team colour, draw-while-closing, perf levers).
3. DONE: hands, kote slimmed, sode as a shell around the arm, armholes, almond eyes + brows.  4. DONE: `draw` / `sheathe` / `run_drawn` clips, run re-authored at 3.13 m/s, team mask.
5. DONE (round 3): lacing reworked (thin bands, cords every plate, a knot on every other plate; brown-black lacquer with brush highlights and gold-brown edge wear; base values lifted so dusk keeps form); team mask limited to bands, knots, cord wraps and sash and thresholded in the shader; scabbard baked into LOD1/2 (draw calls per unit 3 / 2 / 1); automatic foot lift on lunges (foot travel at ground height <= 0.20 m in every attack); per-unit loop phase; game-side lighting tune (emissive floor, env 1.25, distance-scaled tint).
6. DONE (round 4): cloth folds in the hemp bump (hanging folds that wander, stronger toward the hem, dark valleys), `kabuto` shader (a brass rivet every 16 mm on all 24 plate ridges), `menpo` shader (red-black lacquer worn to iron on the high points, hammered bump, cheek wrinkles), sashimono banner (55 bones, 232 tris, +0.23k on LOD1/2, flutter in every clip) and the game-side hit flash (shared per-team flash material, flat white emissive).
7. DONE (round 5): free cloth simulated offline and baked (obi tails, sashimono pole, flag: 62 bones; `cloth.py`, measured clearance: static tails penetrated up to 19.7 mm, simulated tails stay within 3.5 mm in every clip) and per-faction crests (eight procedural signed-distance designs, drawn at runtime on the banner by bind-pose position; one asset, any number of factions).
8. DONE (round 6): face band (eyes with lids, lash line, brows; dense head rows only where it shows), dark hair moustache (-300 triangles), tilted-box rosette petals (-190), a cloth lining inside the shikoro, a swept mask rim, a warmer skin shader; LOD0 23,964 (cap 24,000), IoU 0.826, armour clearance unchanged.
9. DONE (round 7): the wind is the engine's: clips baked dry, `cloth.json` descriptor, a runtime overlay (flag streams downwind, tails tilt, pole leans) driven by the game's wind and the unit's own velocity; `viewer/cloth_wind.js` reference + game copy; a real-GPU profile harness (`samurai-vale/tools/perf/`) and measurements: the units add 0.5-3.5 ms per frame on an Apple M4, the overlay 0.03-0.09 ms.
10. OPEN: the mask is still a stylised shape; the robe / trousers have baked folds only (no garment simulation); the plates are rigid with analytic follow-through; the real-GPU profile covers one machine (an Apple M4); skinned ashigaru / archer.
