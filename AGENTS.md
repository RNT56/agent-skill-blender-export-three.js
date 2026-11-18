# blend-up: agent guide (Claude Code, Codex, any coding agent)

Pipeline that turns Blender assets into verified game-ready GLBs (LODs, baked PBR, KTX2 + meshopt) and checks them in three.js.
**Start with `skills/blender-gamepipe/SKILL.md`**; it is the full workflow. This file is the short version.

## Commands (repo root)
```bash
bin/gp test                      # all tests (needs Blender)
bin/gp build specs/<spec>.json   # recipe -> validate -> export -> inspect -> manifest -> previews, into out/<asset>/
bin/gp validate specs/<spec>.json
bin/gp lint <script.py>          # Blender-trap linter, no Blender needed
bin/gp glb <file.glb>            # inspect exported GLBs, no Blender needed
bin/gp view                      # three.js viewer: http://localhost:8765/viewer/?asset=<name>
bin/gp textures specs/biomes.json   # tileable PBR sets (seam-checked)
bin/gp generate generators/<x>.py   # procedural assets -> fixtures/*.blend
python3 tools/export_world.py --dest <game> --models ... --biomes ...   # hand-off to a game folder
```

## Rules
- **Done = exit code 0 + `out/<asset>/manifest.json` passed + you looked at the preview PNG + three.js engine check.** Never claim success from logs alone.
- Never run bakes/renders inside a live Blender session; use `gamepipe/gp_live.py` (copies the scene, runs headless).
- Run `bin/gp lint` on any bpy you write; read `GOTCHAS.md` first.
- Recipes create new objects only, return derived specs per the contract in `gamepipe/recipes/__init__.py`.
- Don't raise budgets to make something pass without asking. Don't download/install tools (compression is built into Blender's exporter).
- Keep core logic as plain Python + the CLI; agent-specific wrappers stay thin.

## Layout
`gamepipe/` core (texgen, validate, export, glb, lint, cli, live, preview, recipes/) | `generators/` | `runtime/` (three.js engine) | `tools/` | `specs/` asset specs | `looks/` shared lighting look |
`viewer/` three.js engine check | `fixtures/` golden input (.blend) | `tests/` | `skills/` agent skill | `out/` build output (git-ignored)
