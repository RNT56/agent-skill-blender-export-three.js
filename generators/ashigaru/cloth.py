"""The ashigaru's free cloth: the spear's pennant, the head band's two tails, the banner pole and its flag (the model carries every piece of kit, so every chain;
an engine moves the ones it shows). The samurai's offline solver (Verlet chains pinned to the parent bone's real animated motion, baked DRY into bone keys); the
engine adds the wind (cloth.json, kind per chain)."""
import math

from samurai import cloth as SC
from archer import cloth as AC, rig as AR

from . import rig as R


def chains():
    C = SC.Chain
    out = [C("pennant", ("pennant_1", "pennant_2"), "weapon_r", R.pennant_joints(), k_shape=0.0, damp=0.972, c_n=7.0, c_t=0.9, max_deg=170.0, half=0.012, collide=("ground",), nref=tuple(R.spear_rest()["N"]),
             kind="ribbon", rt=dict(gain=1.8, omega=12.0, zeta=0.45, max_deg=60.0, body_z=0.0, flutter=1.7, flutter_hz=1.4))]
    return out + [c for c in AC.chains() if c.name in ("tail_a", "tail_b", "pole", "flag")]


def simulate(rig, poses, loop, duration, speed=0.0, name="clip"):
    """Simulate every chain on the clip's body motion and write the chain bones' deltas into `poses`. Returns per-chain diagnostics."""
    n = len(poses) - 1
    wind = SC.Wind(name, duration, loop, speed)
    diag = {}
    all_chains = chains()
    for stage in (("pennant", "tail_a", "tail_b", "pole"), ("flag",)):
        for ch in [c for c in all_chains if c.name in stage]:
            Ts = SC._chain_frames(rig, poses, ch)
            kinds = set(ch.collide)
            cols = [AC.frame_colliders(rig, p) if kinds - {"ground"} else None for p in poses]
            rec = SC._simulate(ch, Ts, cols, wind, loop, n)
            if loop:
                rec = SC._close_loop(ch, rec, Ts, n, cols)
            qs = [SC.place_chain(rig, p, ch, SC._directions(rec[f])) for f, p in enumerate(poses)]
            for j, bone in enumerate(ch.bones):
                prevq = None
                for f in range(n + 1):
                    q = qs[f][j]
                    if prevq is not None and q.dot(prevq) < 0.0:
                        q.negate()
                    prevq = q
                if loop:
                    qs[n][j] = qs[0][j].copy()
                for f, p in enumerate(poses):
                    p.D[bone] = qs[f][j]
            for p in poses:
                p._M = None
            ang = max(math.degrees(qs[f][j].angle) for f in range(n + 1) for j in range(len(ch.bones)))
            tip = [(SC._inv_apply(Ts[f], rec[f][-1]) - ch.joints[-1]).length * 100.0 for f in range(n + 1)]
            diag[ch.name] = {"max_deg": round(ang, 1), "tip_cm_max": round(max(tip), 1), "tip_cm_rms": round(math.sqrt(sum(t * t for t in tip) / len(tip)), 1)}
    return diag


def runtime_descriptor():
    """Per chain: kind, parent, bones with rest direction / length in the glTF unit frame (x right, y up, z forward), response parameters. `body_z`: +1 = the body is in
    front of the ribbon, -1 (default) behind it, 0 = nothing to clamp against (the spear's pennant hangs in the open)."""
    def gl(v):
        return [round(v.x, 5), round(v.z, 5), round(-v.y, 5)]

    out = []
    for ch in chains():
        segs = []
        for i, bone in enumerate(ch.bones):
            d = ch.joints[i + 1] - ch.joints[i]
            segs.append({"bone": bone, "dir": gl(d.normalized()), "length": round(d.length, 5)})
        out.append({"name": ch.name, "kind": ch.kind, "parent": ch.parent, "segments": segs, **{k: ch.rt[k] for k in sorted(ch.rt)}})
    return {"version": 1, "baked_wind": SC.BAKED_WIND, "frame": "glTF unit frame: x right, y up, z forward; metres; unit-local (the engine rotates the world wind into it)", "chains": out}


def write_runtime(out_dir, base):
    import json
    import os
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{base}_cloth.json")
    with open(path, "w") as fh:
        json.dump(runtime_descriptor(), fh, indent=2)
    return path
