"""A pass after any arm solve that keeps arms anatomical (2026-11-21, the owner: "arms glitch through the body, an arm is not visible, hands are
swirled"). Shared by the samurai (samurai.anim.Solver) and the soldier units (soldier.clips RefitSolver). Nothing in it moves a WRIST: a clip's hands stay
where it put them, and so do the weapons in them.

  1. the ELBOW: an arm with its hand fixed can still turn about the shoulder-wrist line. Of the turns within +-100 deg the pass takes the one that keeps
     the upper arm and the forearm out of the trunk and the head (the measured body, armour and helmet: `Body`), that hangs the elbow down and out, and
     that asks least of the wrist; it never flips the elbow to bend the wrong way. (A plain pole made the elbow jump sides when the pole lay near the
     shoulder-wrist line, and laid forearms across the belly.)
  2. the FOREARM's roll: most of the twist between hand and forearm is taken by the forearm rolling about its own axis (as a man's radius turns over
     his ulna), up to TWIST_FA; only the rest is left at the wrist. (A hand turned palm-up on an unturned forearm wrung the wrist like a towel.)
  3. the WRIST's bend is held to SWING_MAX (a hand bent back on itself is the last of it).
Weapon bones that hang on a hand (weapon_r, weapon_r2) are put back where they were, so a spear or a sword never moves.
The choice is a pure function of the frame's pose: a looping clip's last frame (a re-solve of the first) gets the same answer.
"""
import math

import numpy as np
from mathutils import Matrix, Quaternion, Vector

V = Vector
ARM_BONES = ("shoulder", "upper_arm", "forearm", "hand", "fingers", "fingers2", "thumb", "index", "middle", "ring", "pinky", "sode")      # (the shoulder guards ride the arms)
TWIST_FA = 85.0          # degrees the forearm may roll to take a wrist's twist
TWIST_SHARE = 0.75       # of a wrist's twist, the share the forearm takes
SWING_MAX = 80.0         # degrees a wrist may bend
R_UPPER, R_FORE, R_HAND = 0.050, 0.042, 0.032
PEN_LOCK = 0.03          # m (summed over the arm's sample points) below which a clip's own elbow is kept


def _is_arm(name):
    return name.split(".")[0].split("_0")[0] in ARM_BONES


class Body:
    """The trunk and the head as the arms must keep out of them, measured once from the meshes in their rest pose (body, armour, helmet: whatever
    a man may wear, so the widest). The trunk is a stack of star-shaped slices around the spine (radius by angle), in the space of the bone that carries
    that height (hips below `split`, chest above); the head is a sphere riding the head bone."""

    BINS = 24

    def __init__(self, rig, meshes, log=print, head_pad=0.0):
        self.rig = rig
        H = rig.head
        self.z0 = H["hips"].z - 0.10
        self.split = H["spine1"].z if "spine1" in H else H["chest"].z - 0.15
        sh = max(H["upper_arm.L"].z, H["upper_arm.R"].z)
        self.z1 = sh - 0.05                                                 # (above it the arm starts IN the shoulder)
        pts, hpts = [], []
        for ob in meshes:
            names = {g.index: g.name for g in ob.vertex_groups}
            M = ob.matrix_world
            for v in ob.data.vertices:
                wa = sum(g.weight for g in v.groups if _is_arm(names.get(g.group, "")))
                if wa > 0.25:
                    continue
                co = M @ v.co
                wh = sum(g.weight for g in v.groups if names.get(g.group, "") in ("head", "neck", "topknot"))
                (hpts if wh > 0.5 else pts).append(tuple(co))
        P = np.array(pts)
        self.dz = 0.025
        self.zs = np.arange(self.z0, self.z1, self.dz)
        self.cx = np.zeros(len(self.zs))
        self.cy = np.zeros(len(self.zs))
        self.r = np.zeros((len(self.zs), self.BINS))
        for i, z in enumerate(self.zs):
            m = np.abs(P[:, 2] - z) < self.dz * 0.6
            q = P[m]
            if len(q) < 30:
                continue
            # the trunk's own slice: the points nearest the spine (a sleeve or a scabbard reaching the slice is not the trunk)
            c = np.median(q[:, :2], axis=0)
            d = np.linalg.norm(q[:, :2] - c, axis=1)
            q = q[d < np.percentile(d, 97)]
            self.cx[i], self.cy[i] = float(np.median(q[:, 0])), float(np.median(q[:, 1]))
            ang = np.arctan2(q[:, 1] - self.cy[i], q[:, 0] - self.cx[i])
            rad = np.hypot(q[:, 0] - self.cx[i], q[:, 1] - self.cy[i])
            k = ((ang + math.pi) / (2 * math.pi) * self.BINS).astype(int) % self.BINS
            for b in range(self.BINS):
                sel = rad[k == b]
                self.r[i, b] = float(np.percentile(sel, 90)) if len(sel) > 3 else 0.0
            for b in range(self.BINS):                                          # an empty bin takes its neighbours'
                if self.r[i, b] == 0.0:
                    self.r[i, b] = max(self.r[i, (b - 1) % self.BINS], self.r[i, (b + 1) % self.BINS])
        # the thighs (and what hangs over them): a capsule each, around the thigh bone
        self.thigh_r = {}
        for s in "LR":
            h, t = rig.head[f"thigh.{s}"], rig.tail[f"thigh.{s}"]
            d = (t - h).normalized()
            Q = P[(P[:, 2] < h.z) & (P[:, 2] > t.z + 0.05) & (np.sign(P[:, 0] - 0.0) == (1 if s == "L" else -1))]
            if len(Q) > 30:
                rel = Q - np.array(h)
                along = rel @ np.array(d)
                perp = np.linalg.norm(rel - np.outer(along, np.array(d)), axis=1)
                self.thigh_r[s] = float(np.percentile(perp, 80))
        Hd = np.array(hpts) if hpts else np.zeros((1, 3))
        hb = rig.rest["head"]
        self.hc_local = hb.inverted() @ V(tuple(Hd.mean(0)))
        self.hr = (float(np.percentile(np.linalg.norm(Hd - Hd.mean(0), axis=1), 88)) if len(Hd) > 10 else 0.12) + head_pad      # (+ a helmet's bowl)
        log(f"  arms: trunk measured in {int((self.r.max(1) > 0).sum())} slices {self.z0:.2f}..{self.z1:.2f} m, widest {self.r.max():.3f} m; head sphere {self.hr:.3f} m")

    def depth(self, p, M, pad):
        """how far a sphere of radius `pad` at posed point p (armature space) is inside the trunk or the head (m, <= 0: outside). M = the pose's matrices."""
        best = -1.0
        for bone, lo, hi in (("hips", self.z0, self.split), ("chest", self.split, self.z1)):
            T = M[bone] @ self.rig.rest[bone].inverted()
            q = T.inverted() @ p
            if lo - 0.03 <= q.z < hi + 0.03:
                i = int(round((q.z - self.z0) / self.dz))
                if 0 <= i < len(self.zs) and self.r[i].max() > 0:
                    a = math.atan2(q.y - self.cy[i], q.x - self.cx[i])
                    b = int((a + math.pi) / (2 * math.pi) * self.BINS) % self.BINS
                    best = max(best, self.r[i, b] + pad - math.hypot(q.x - self.cx[i], q.y - self.cy[i]))
        hc = M["head"] @ self.hc_local
        best = max(best, self.hr + pad - (p - hc).length)
        for s, r in self.thigh_r.items():
            a, b = M[f"thigh.{s}"].translation, M[f"thigh.{s}"] @ V((0, self.rig.length[f"thigh.{s}"], 0))
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-9)))
            best = max(best, r + pad - (p - (a + ab * t)).length)
        return best


ROLLS = [math.radians(d) for d in range(-85, 86, 5)]


def wrist_cost(F, Fh, Rr):
    """what a hand of world frame Fh asks of the wrist on a forearm of frame F (Rr: the rest relation forearm -> hand)"""
    rel = Rr.inverted() @ F.inverted() @ Fh
    tw = abs(_wrap(_twist_y(rel)))
    bend = math.acos(max(-1.0, min(1.0, Fh.col[1].normalized().dot((F @ Rr.col[1]).normalized()))))
    return 0.5 * (tw / math.pi) ** 2 + 2.0 * max(0.0, bend - math.radians(30)) ** 2 + 0.6 * max(0.0, bend - math.radians(SWING_MAX)) ** 2


def best_roll(F, Fh, Rr, step=1):
    """the forearm roll (about its own axis) that asks least of the wrist, and that cost"""
    y = F.col[1].normalized()
    return min(((wrist_cost(_rot_about(y, r) @ F, Fh, Rr) + 0.05 * (r / math.pi) ** 2, r) for r in ROLLS[::step]), key=lambda c: c[0])


def upper_twist(p, side, Fu):
    """how far an upper arm of frame Fu is rolled about its own axis against its parent (the shoulder), as against the rest pose (radians). A rolled
    humerus wrings the shoulder's skin: the auto-rigs have no twist bones."""
    rig = p.rig
    ua = f"upper_arm.{side}"
    par = rig.parent[ua]
    Fp = p.matrices()[par].to_3x3().normalized()
    Rr = rig.rest_rot[par].inverted() @ rig.rest_rot[ua]
    return abs(_wrap(_twist_y(Rr.inverted() @ Fp.inverted() @ Fu)))


def _rot_about(axis, ang):
    return Quaternion(axis.normalized(), ang).to_matrix()


def _twist_y(Rrel):
    """twist (radians) of a relative rotation about its y axis"""
    q = Rrel.to_quaternion()
    return 2.0 * math.atan2(q.y, q.w)


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _restore(p, name, target):
    """set bone `name` (pose p) so its armature-space matrix is `target` again, given its parent's current pose"""
    rig = p.rig
    par = rig.parent[name]
    base = (p.matrices()[par] @ rig.rel[name]) if par else rig.rel[name]
    B = base.inverted() @ target
    R = rig.rest_rot[name]
    p.D[name] = (R @ B.to_3x3() @ R.inverted()).to_quaternion()
    p.loc[name] = R @ B.to_translation()
    p._M = None


def fix_arm(p, side, body, keep=(), lock_elbow=False):
    """The pass, for one arm of pose p. keep: weapon bones whose world transform must not change."""
    rig = p.rig
    sx = 1.0 if side == "L" else -1.0
    ua, fa, hd = f"upper_arm.{side}", f"forearm.{side}", f"hand.{side}"
    M = p.matrices()
    held = {w: M[w].copy() for w in keep if w in M}
    Fh = M[hd].to_3x3().normalized()
    S, E, W = M[ua].translation.copy(), M[fa].translation.copy(), M[hd].translation.copy()
    axis = W - S
    if axis.length < 1e-4:
        return
    ax = axis.normalized()
    Rr = rig.rest_rot[fa].inverted() @ rig.rest_rot[hd]
    Cm = M["chest"].to_3x3() @ rig.rest_rot["chest"].inverted()
    pref = (Cm @ V((0.42 * sx, 0.40, -0.82))).normalized()                # where an elbow likes to point: down, out, a little back
    e0 = (E - S) - ax * (E - S).dot(ax)
    if e0.length < 1e-5:                                                   # a straight arm: nothing to turn
        lock_elbow = True
    best = (0.0, E)
    if not lock_elbow:
        e0n = e0.normalized()
        def cost_of(ang):
            Ep = S + _rot_about(ax, ang) @ (E - S)
            pen = 0.0
            for t in (0.65, 1.0):
                pen += max(0.0, body.depth(S.lerp(Ep, t), M, R_UPPER))
            for t in (0.3, 0.65):
                pen += max(0.0, body.depth(Ep.lerp(W, t), M, R_FORE))
            ed = (Ep - S) - ax * (Ep - S).dot(ax)
            ed = ed.normalized() if ed.length > 1e-6 else e0n
            # the twist the wrist would be asked for with the forearm aimed this way (as limb() rolls it: z toward the elbow's outside)
            F = _frame(W - Ep, -ed)
            tu = upper_twist(p, side, _frame(Ep - S, -ed))
            return (60.0 * pen + 0.6 * (1.0 - ed.dot(pref)) + best_roll(F, Fh, Rr, step=4)[0] + 2.5 * (ang / math.pi) ** 2
                    + 3.0 * max(0.0, tu - max(tu0, math.radians(35))) ** 2), Ep
        tu0 = upper_twist(p, side, M[ua].to_3x3().normalized())          # (no worse than the clip's own)
        pen0 = sum(max(0.0, body.depth(S.lerp(E, t), M, R_UPPER)) for t in (0.65, 1.0)) + sum(max(0.0, body.depth(E.lerp(W, t), M, R_FORE)) for t in (0.3, 0.65))
        # the clip's own elbow, where its arm is clear of the body, stays (only the roll and the wrist change); the deeper the arm, the more of the turn
        # (a weight, not a switch: from one frame to the next an elbow never jumps)
        u = min(1.0, max(0.0, (pen0 - 0.5 * PEN_LOCK) / PEN_LOCK))
        w_turn = u * u * (3 - 2 * u)
        if w_turn <= 0.0:
            lock_elbow = True
    if not lock_elbow:
        grid = [(cost_of(math.radians(d)), math.radians(d)) for d in range(-60, 61, 5)]
        (c0, _), a0 = min(grid, key=lambda g: g[0][0])
        lo, hi = a0 - math.radians(5), a0 + math.radians(5)
        for _ in range(14):                                                # golden-section on the best cell
            m1, m2 = hi - (hi - lo) * 0.618, lo + (hi - lo) * 0.618
            if cost_of(m1)[0] < cost_of(m2)[0]:
                hi = m2
            else:
                lo = m1
        a = 0.5 * (lo + hi) * w_turn
        best = (a, cost_of(a)[1])
    ang, Ep = best
    ed = (Ep - S) - ax * (Ep - S).dot(ax)
    if ed.length > 1e-6 and abs(ang) > 1e-6:
        p.limb(ua, fa, hd, W, ed.normalized(), -1)                        # the same wrist, the elbow where the search put it
    # the forearm takes most of the wrist's twist
    M = p.matrices()
    Ffa = M[fa].to_3x3().normalized()
    yf = Ffa.col[1].normalized()
    roll = best_roll(Ffa, Fh, Rr)[1]
    if abs(roll) > 1e-4:
        p._place(fa, _rot_about(yf, roll) @ Ffa)
    p._place(hd, Fh)
    # the wrist's bend
    M = p.matrices()
    yf = M[fa].to_3x3().col[1].normalized()
    Fh2 = M[hd].to_3x3().normalized()
    yh = Fh2.col[1].normalized()
    y_rest = (rig.rest_rot[fa].inverted() @ rig.rest_rot[hd]).col[1].normalized()      # the rest pose's own bend between them
    y_ref = (M[fa].to_3x3().normalized() @ y_rest).normalized()
    sw = math.acos(max(-1.0, min(1.0, yh.dot(y_ref))))
    if sw > math.radians(SWING_MAX):
        k = y_ref.cross(yh)
        if k.length > 1e-6:
            p._place(hd, _rot_about(k, -(sw - math.radians(SWING_MAX))) @ Fh2)
    for w, T in held.items():
        _restore(p, w, T)


def _frame(y, zhint):
    y = V(y).normalized()
    z = V(zhint) - y * V(zhint).dot(y)
    if z.length < 1e-6:
        z = V((0, -1, 0)) - y * y.y * -1
    z.normalize()
    x = y.cross(z).normalized()
    z = x.cross(y).normalized()
    F = Matrix.Identity(3)
    F.col[0], F.col[1], F.col[2] = x, y, z
    return F


def body_meshes(arm_obj, skip=("Low", "LOD1", "LOD2", "Far", "Katana", "Tachi", "Yari", "Sashimono", "Yumi", "Arrow", "Quiver", "Side_", "Take", "Helmet", "_pennant")):
    """the meshes skinned to arm_obj that are a man and what he wears on his trunk (not weapons, hats or lower levels of detail)"""
    import bpy
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH" or any(k in o.name for k in skip):
            continue
        if any(m.type == "ARMATURE" and m.object == arm_obj for m in o.modifiers) or o.parent == arm_obj:
            out.append(o)
    return out


def grip_roll(p, side, body, grip_rest, axis_rest, keep=(), span=40):
    """A hand closed on a round shaft may sit anywhere AROUND it: turn the hand about the shaft (through its grip) to where the wrist is least bent
    and twisted and the arm clear of the body, within +-span degrees of where the clip put it. The shaft does not move (keep: its bones)."""
    rig = p.rig
    ua, fa, hd = f"upper_arm.{side}", f"forearm.{side}", f"hand.{side}"
    M = p.matrices()
    held = {w: M[w].copy() for w in keep if w in M}
    Mh = M[hd]
    Lh = rig.rest[hd].inverted()
    G = Mh @ (Lh @ V(grip_rest))
    D = (Mh.to_3x3() @ (Lh.to_3x3() @ V(axis_rest))).normalized()
    Fh0 = Mh.to_3x3().normalized()
    W0 = Mh.translation.copy()
    Rr = rig.rest_rot[fa].inverted() @ rig.rest_rot[hd]
    sx = 1.0 if side == "L" else -1.0
    pole0 = (M[fa].translation - M[ua].translation)
    tu0 = upper_twist(p, side, M[ua].to_3x3().normalized())

    def place(psi):
        R = _rot_about(D, psi)
        W = G + R @ (W0 - G)
        p.limb(ua, fa, hd, W, pole0, -1)
        F = R @ Fh0
        p._place(hd, F)
        return W, F

    def cost(psi):
        W, F = place(psi)
        Mx = p.matrices()
        S, E = Mx[ua].translation, Mx[fa].translation
        pen = sum(max(0.0, body.depth(S.lerp(E, t), Mx, R_UPPER)) for t in (0.65, 1.0)) + sum(max(0.0, body.depth(E.lerp(W, t), Mx, R_FORE)) for t in (0.3, 0.65))
        reach = (W - S).length / (rig.length[ua] + rig.length[fa])
        tu = upper_twist(p, side, Mx[ua].to_3x3().normalized())
        return (60.0 * pen + best_roll(Mx[fa].to_3x3().normalized(), F, Rr, step=3)[0] + 0.3 * (psi / math.pi) ** 2 + 20.0 * max(0.0, reach - 0.99)
                + 3.0 * max(0.0, tu - max(tu0, math.radians(35))) ** 2)

    grid = [(cost(math.radians(d)), math.radians(d)) for d in range(-span, span + 1, 10)]
    c0, a0 = min(grid)
    lo, hi = a0 - math.radians(10), a0 + math.radians(10)
    for _ in range(10):
        m1, m2 = hi - (hi - lo) * 0.618, lo + (hi - lo) * 0.618
        if cost(m1) < cost(m2):
            hi = m2
        else:
            lo = m1
    place(0.5 * (lo + hi))
    for w, T in held.items():
        _restore(p, w, T)
