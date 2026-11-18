"""Pure-python pose evaluator and analytic IK for the samurai rig (needs only mathutils).

Pose input is a rotation DELTA per bone in armature-aligned axes (X = character's left, Y = back, Z = up) that rides on its
parent's motion, plus optional translation for hips/root. This makes spine/neck/head authoring independent of bone rolls, and
mirrors trivially. Limbs are solved analytically (two-bone IK with a pole) and written back as the same deltas, so every clip
ends up as plain FK keys on the deform bones: nothing in the exported file depends on constraints or on Blender's solver.
"""
import math

from mathutils import Matrix, Quaternion, Vector

V = Vector


def _q(rot):
    """Accept a Quaternion, a Matrix, or a (rx, ry, rz) degrees tuple (applied Z, then Y, then X: 'XYZ' euler)."""
    if isinstance(rot, Quaternion):
        return rot
    if isinstance(rot, Matrix):
        return rot.to_quaternion()
    from mathutils import Euler
    return Euler([math.radians(a) for a in rot], "XYZ").to_quaternion()


class Rig:
    """Rest data copied from a Blender armature object (so the python solver can never disagree with the skinning)."""

    def __init__(self, arm_obj):
        bones = arm_obj.data.bones
        self.names = [b.name for b in bones]
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in bones}
        self.rest = {b.name: b.matrix_local.copy() for b in bones}
        self.rest_rot = {n: self.rest[n].to_3x3() for n in self.names}
        self.head = {b.name: b.head_local.copy() for b in bones}
        self.tail = {b.name: b.tail_local.copy() for b in bones}
        self.length = {b.name: b.length for b in bones}
        self.rel = {}
        for n in self.names:
            p = self.parent[n]
            self.rel[n] = self.rest[p].inverted() @ self.rest[n] if p else self.rest[n].copy()

    def order(self):
        return self.names           # Blender stores parents before children


class Pose:
    def __init__(self, rig):
        self.rig = rig
        self.D = {}                 # name -> Quaternion (armature-aligned delta)
        self.loc = {}               # name -> Vector (armature-aligned translation delta)
        self._M = None

    def copy(self):
        p = Pose(self.rig)
        p.D = {k: v.copy() for k, v in self.D.items()}
        p.loc = {k: v.copy() for k, v in self.loc.items()}
        return p

    def rot(self, name, r):
        self.D[name] = _q(r)
        self._M = None

    def mul(self, name, r):
        self.D[name] = _q(r) @ self.D.get(name, Quaternion())
        self._M = None

    def move(self, name, v):
        self.loc[name] = Vector(v)
        self._M = None

    # ---- evaluation ----
    def basis(self, n):
        R = self.rig.rest_rot[n]
        q = self.D.get(n, Quaternion())
        rot = (R.inverted() @ q.to_matrix() @ R)
        loc = R.inverted() @ self.loc.get(n, Vector())
        B = Matrix.Translation(loc) @ rot.to_4x4()
        return B

    def matrices(self):
        if self._M is not None:
            return self._M
        M = {}
        for n in self.rig.order():
            p = self.rig.parent[n]
            base = (M[p] @ self.rig.rel[n]) if p else self.rig.rel[n]
            M[n] = base @ self.basis(n)
        self._M = M
        return M

    def head(self, n):
        return self.matrices()[n].translation.copy()

    def tail(self, n):
        return (self.matrices()[n] @ V((0, self.rig.length[n], 0))).copy()

    def axis(self, n):
        return (self.matrices()[n].to_3x3() @ V((0, 1, 0))).normalized()

    # ---- inverse kinematics ----
    def _place(self, n, frame):
        """Set bone n so its armature-space orientation is `frame` (3x3), given the parent's current pose."""
        p = self.rig.parent[n]
        Pm = self.matrices()[p] if p else Matrix.Identity(4)
        inherited = (Pm @ self.rig.rel[n]).to_3x3()
        basis_rot = inherited.inverted() @ frame
        R = self.rig.rest_rot[n]
        self.D[n] = (R @ basis_rot @ R.inverted()).to_quaternion()
        self._M = None

    @staticmethod
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

    def aim(self, n, direction, zhint):
        self._place(n, self._frame(direction, zhint))

    def limb(self, upper, lower, end, target, pole, z_sign):
        """Two-bone IK: put the tail of `lower` (wrist / ankle) at `target`, bending toward the `pole` direction.

        Returns the unclamped reach ratio (distance / chain length). z_sign: -1 for arms (elbow bulges back), +1 for legs."""
        P = self.rig.parent[upper]
        Pm = self.matrices()[P] if P else Matrix.Identity(4)
        S = (Pm @ self.rig.rel[upper]).translation
        L1, L2 = self.rig.length[upper], self.rig.length[lower]
        T = V(target)
        to = T - S
        dist = max(to.length, 1e-5)
        reach = dist / (L1 + L2)
        dsolve = min(max(dist, abs(L1 - L2) + 1e-4), L1 + L2 - 1e-4)
        dirST = to.normalized()
        cosA = (L1 * L1 + dsolve * dsolve - L2 * L2) / (2 * L1 * dsolve)
        a = math.acos(max(-1.0, min(1.0, cosA)))
        pole = V(pole)
        perp = pole - dirST * pole.dot(dirST)
        if perp.length < 1e-5:
            perp = V((0, -1, 0)) - dirST * dirST.dot(V((0, -1, 0)))
        perp.normalize()
        E = S + dirST * (math.cos(a) * L1) + perp * (math.sin(a) * L1)
        W = S + dirST * dsolve
        zh = perp * z_sign
        self.aim(upper, E - S, zh)
        self.aim(lower, W - E, zh)
        return reach

    def orient(self, n, y_axis, z_hint):
        self.aim(n, y_axis, z_hint)


def mirror_rot(r):
    """Mirror an armature-aligned rotation across the X=0 plane (for L<->R): X component kept, Y and Z negated."""
    q = _q(r)
    return Quaternion((q.w, q.x, -q.y, -q.z))


def key_pose(arm_obj, pose, frame, bones=None):
    """Write the pose into the armature's pose bones and insert rotation/location keyframes."""
    for n in (bones or pose.rig.names):
        pb = arm_obj.pose.bones[n]
        B = pose.basis(n)
        pb.rotation_quaternion = B.to_quaternion()
        pb.location = B.to_translation()
        pb.keyframe_insert("rotation_quaternion", frame=frame)
        if n in pose.loc:
            pb.keyframe_insert("location", frame=frame)


def show_pose(arm_obj, pose):
    for n in pose.rig.names:
        pb = arm_obj.pose.bones[n]
        B = pose.basis(n)
        pb.rotation_quaternion = B.to_quaternion()
        pb.location = B.to_translation()
