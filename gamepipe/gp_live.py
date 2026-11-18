"""Use from a LIVE Blender session (e.g. via the Blender MCP `execute_blender_code`).

Slow work (bakes, renders) must NOT run inside the live session: the MCP bridge times out and the UI freezes.
This saves a *copy* of the open scene (the live session stays untouched and unsaved) and runs the pipeline headless.

    import sys; sys.path.insert(0, "<repo>/gamepipe")
    import gp_live
    result = gp_live.run_headless_from_live("<repo>/specs/tree_autumn_01.json")   # dict, JSON-serialisable
"""
import os
import subprocess
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run_headless_from_live(spec_path, extra_args=(), timeout=1500):
    work = os.path.join(ROOT, "out", "_work")
    os.makedirs(work, exist_ok=True)
    blend = os.path.join(work, "live_copy.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True)       # copy=True: live session stays as it is
    cmd = [bpy.app.binary_path, "-b", blend, "-P", os.path.join(HERE, "gp_cli.py"), "--", spec_path, *extra_args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    tail = [l for l in (r.stdout or "").splitlines() if l.strip() and "DeprecationWarning" not in l and "use_nodes" not in l]
    return {"exit_code": r.returncode, "passed": r.returncode == 0, "log_tail": tail[-40:], "stderr_tail": (r.stderr or "")[-500:]}
