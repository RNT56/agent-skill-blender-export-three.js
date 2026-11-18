# Samurai unit: upgrade plan, frozen interface, status (2026-11-18)

## Frozen game interface (do not rename; model changes must keep this stable)
- GLB `out/samurai_unit_01/samurai_unit_01.glb`; skinned meshes `Samurai_LOD0/1/2` (show exactly one), `Katana_Drawn`, `Katana_Sheathed`, `Katana_Saya`.
- Optional: `Sashimono` (team banner, separate node, hidden by default), `samurai_unit_01_team.png` (team mask, same atlas UV, NoColorSpace, flipY=false).
- Clips: `idle walk run combat_idle attack_overhead attack_diagonal attack_horizontal attack_thrust block hit death` (+ `draw`, `sheathe` when added).
- `clips.json` per clip: `frames fps duration loop weapon(sheathed|drawn) speed_mps` (+ `events` e.g. `{"swap_weapon": 0.42, "impact": 0.6}` in seconds).
- Facing glTF +Z, origin between the feet, metres, in-place locomotion.

## Rest pose parameters changed in this pass (rig.py)
`S_ARM` 32 -> 24 degrees; `LEG_PTS` knee x 0.148, ankle x 0.192 (legs spread ~6 degrees like the reference); shared `TORSO_Z/RX/RY` (chest deeper); skirt flare rx +0.092 / ry +0.010;
shikoro flare rx +0.118 / ry +0.062; wings up and out. Every part that follows the leg uses `rig.leg_center(z)`.

## Gates (report against these, not impressions)
| gate | baseline | now | target |
|---|---|---|---|
| silhouette IoU front / side / back (`generators/samurai_compare.py`) | 0.665 / 0.784 / 0.665 (mean 0.705) | 0.844 / 0.812 / 0.840 (mean 0.832) | ~0.85 mean (the reference is one AI image with its own inconsistencies) |
| armour-to-body clearance (`generators/samurai_clearance.py`) | many parts 20-75 mm deep (no armholes, sode inside sleeves) | 0 parts > 4.5 mm (armholes, sode shell around the arm axis, straps on the surface) | no penetration > 4.5 mm |
| hand: finger segments, palm taper, grip wrap | blocky tubes | TODO | 3 visible phalanges, knuckles, thumb mass |
| grip error | 0 mm (solver), 5-46 mm nudge | keep | <= 6 cm nudge, hands wrap the hilt |
| in-game look at 14 / 62 / 150 m under the autumn grade | not seen | seen at 13 m and 62 m: teams read (red/blue lacing via mask), units sit in the tall grass | readable teams, no black blob |
| frame cost (GPU timer, hidden pane, 64 samurai) | not measured | +10 ms at 40 m, +53 ms when all within 22 m (extreme); optimised (shadows LOD0 only, no weapons at LOD2, out of the reflection) | re-measure on a real GPU |

## Order
1. DONE: rest-pose change verified (golden test) + clearance metric.  2. DONE: working slice in samurai-vale (loader, rigs, clip selection, team colour, draw-while-closing, perf levers).
3. Hands / arms / kote / sode fit.  4. Face, mask, helmet details, lacing + lacquer look.  5. `draw` / `sheathe` clips, run re-authored near the game's 3.7 m/s, team mask, sashimono.
6. In-game tuning (albedo from the game's grade, LOD distances, timing), perf measurement.
