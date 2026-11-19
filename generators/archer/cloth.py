"""The archer's free cloth: the two hachimaki tails behind the head, the banner pole and its flag. The samurai's offline solver (samurai/cloth.py: Verlet chains pinned
to the parent bone's real animated motion, baked DRY into bone keys) with the archer's chains and colliders. The engine adds the wind (cloth.json, kind per chain)."""
import math

from mathutils import Vector

from samurai import cloth as SC

from . import rig as R

V = Vector


def chains():
    C = SC.Chain
    return [
        C("tail_a", ("tail_a1", "tail_a2"), "head", R.tail_joints("a"), k_shape=0.005, damp=0.975, c_n=6.5, c_t=0.8, max_deg=80.0, half=0.012, collide=("thigh", "ground"),
          kind="ribbon", rt=dict(gain=1.0, omega=7.5, zeta=0.42, max_deg=40.0, body_z=1.0)),
        C("tail_b", ("tail_b1", "tail_b2"), "head", R.tail_joints("b"), k_shape=0.005, damp=0.975, c_n=6.5, c_t=0.8, max_deg=80.0, half=0.012, collide=("thigh", "ground"),
          kind="ribbon", rt=dict(gain=1.15, omega=6.6, zeta=0.42, max_deg=44.0, body_z=1.0)),
        C("pole", ("banner_1", "banner_2"), "chest", R.POLE, k_shape=0.08, damp=0.97, gravity=False, wind=0.0, run=0.0, max_deg=12.0,
          kind="pole", rt=dict(gain=0.25, omega=9.0, zeta=0.6, max_deg=2.5)),
        C("flag", ("flag_1", "flag_2", "flag_3"), "banner_2", R.flag_joints(), k_shape=0.010, damp=0.982, gravity=False, planar=True, c_n=9.0, c_t=1.2,
          max_deg=70.0, kind="flag", rt=dict(gain=1.0, omega=9.5, zeta=0.32, max_deg=75.0)),
    ]


CHAIN_BONES = [b for c in chains() for b in c.bones]


def frame_colliders(rig, pose):
    """What a hachimaki tail may touch: the skull, the neck, the trunk and the shoulders (capsules from the pose)."""
    M = pose.matrices()
    caps = [(M["head"].translation.copy() + (pose.tail("head") - M["head"].translation) * 0.25, pose.tail("head"), 0.088),
            (M["neck"].translation.copy(), pose.tail("neck"), 0.060),
            (M["spine1"].translation.copy(), pose.tail("chest"), 0.128)]
    for s in "LR":
        caps.append((M[f"shoulder.{s}"].translation.copy(), pose.tail(f"shoulder.{s}"), 0.085))
    return {"caps": caps}


def simulate(rig, poses, loop, duration, speed=0.0, name="clip"):
    """Simulate every chain on the clip's body motion and write the chain bones' deltas into `poses`. Returns per-chain diagnostics."""
    n = len(poses) - 1
    wind = SC.Wind(name, duration, loop, speed)
    diag = {}
    for stage in (("tail_a", "tail_b", "pole"), ("flag",)):
        for ch in [c for c in chains() if c.name in stage]:
            Ts = SC._chain_frames(rig, poses, ch)
            kinds = set(ch.collide)
            cols = [frame_colliders(rig, p) if kinds - {"ground"} else None for p in poses]
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
    """Per chain: kind, parent, bones with rest direction / length in the glTF unit frame (x right, y up, z forward), response parameters. `body_z` = +1 says the body is
    in FRONT of the ribbon (the tails hang behind the head), so the engine clamps a push toward +z instead of -z."""
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
