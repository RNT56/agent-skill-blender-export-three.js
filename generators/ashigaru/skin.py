"""Skin weights of the ashigaru: the archer's rules (rigid parts on one bone, soft parts by distance to bone segments, the head band's tails, the flag) plus the
spear's pennant, which hangs from its cord on the shaft."""
from archer import skin as AK

from . import rig as R

join, bind = AK.join, AK.bind


def pennant_weights(co):
    j = R.pennant_joints()
    t = min(max((j[0].z - co.z) / R.PENNANT_H, 0.0), 1.0)
    if t < 0.10:
        return {"weapon_r": 1.0}
    w2 = AK.SS._smooth(0.40, 0.80, t)
    return {n: w for n, w in (("pennant_1", 1.0 - w2), ("pennant_2", w2)) if w > 1e-4}


def apply_weights(ob, arm_obj):
    if (ob.get("gp_soft") or "") == "pennant":
        groups = {}
        for v in ob.data.vertices:
            for n, w in pennant_weights(v.co).items():
                if n not in groups:
                    groups[n] = ob.vertex_groups.get(n) or ob.vertex_groups.new(name=n)
                groups[n].add([v.index], w, "REPLACE")
        return
    AK.apply_weights(ob, arm_obj)
