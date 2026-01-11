# extractor/verify/matcher.py

from typing import List, Dict, Any
import math
import numpy as np


class _Minu:
    """Internal minutiae representation with (x, y, angle in rad)."""

    __slots__ = ("x", "y", "ang")

    def __init__(self, x: float, y: float, ang_rad: float):
        self.x = float(x)
        self.y = float(y)
        # wrap to [0, pi)
        self.ang = float(ang_rad) % math.pi


def _to_minu_list(minutiae: List[Dict[str, Any]]) -> List[_Minu]:
    """
    Convert JSON minutiae [{x, y, angle, ...}, ...]
    angle is in degree [0, 180)
    """
    res: List[_Minu] = []
    for m in minutiae:
        x = m.get("x", 0.0)
        y = m.get("y", 0.0)
        ang_deg = float(m.get("angle", 0.0))
        ang_rad = math.radians(ang_deg)
        res.append(_Minu(x, y, ang_rad))
    return res


def _angle_diff(a: float, b: float) -> float:
    """Minimal absolute difference between two angles in rad, modulo pi."""
    d = abs(a - b)
    d = d % math.pi
    if d > math.pi / 2:
        d = math.pi - d
    return d


def _accumulate_hough(minu1, minu2,
                      angle_limit: float,
                      angle_set_deg,
                      delta_x_set, delta_y_set,
                      x_root: float, y_root: float):
    """
    Build a 3D accumulator over (deltaX, deltaY, angle) similar to ZIP2.
    Return best (dx, dy, rot_rad) and accumulator peak.
    """
    A = np.zeros((len(delta_x_set), len(delta_y_set), len(angle_set_deg)),
                 dtype=np.int32)

    for m1 in minu1:
        for m2 in minu2:
            # center coordinates around root
            c1x = m1.x - x_root
            c1y = y_root - m1.y
            c2x = m2.x - x_root
            c2y = y_root - m2.y

            for a_idx, a_deg in enumerate(angle_set_deg):
                a_rad = math.radians(a_deg)

                # orientation consistency
                if _angle_diff(m1.ang, m2.ang + a_rad) > angle_limit:
                    continue

                # rotate m2 around root by a_rad
                rx = math.cos(a_rad) * c2x - math.sin(a_rad) * c2y
                ry = math.sin(a_rad) * c2x + math.cos(a_rad) * c2y

                dx = c1x - rx
                dy = c1y - ry

                dx_idx = int(np.argmin(np.abs(delta_x_set - dx)))
                dy_idx = int(np.argmin(np.abs(delta_y_set - dy)))
                A[dx_idx, dy_idx, a_idx] += 1

    best_idx = np.unravel_index(np.argmax(A), A.shape)
    best_dx = float(delta_x_set[best_idx[0]])
    best_dy = float(delta_y_set[best_idx[1]])
    best_angle_deg = float(angle_set_deg[best_idx[2]])
    best_angle_rad = math.radians(best_angle_deg)
    peak = int(A[best_idx])

    return best_dx, best_dy, best_angle_rad, peak


def _transform(m: _Minu,
               dx: float, dy: float,
               rot_rad: float,
               x_root: float, y_root: float) -> _Minu:
    """Apply rotation around (x_root, y_root) and translation (dx, dy)."""
    cx = m.x - x_root
    cy = y_root - m.y

    rx = math.cos(rot_rad) * cx - math.sin(rot_rad) * cy
    ry = math.sin(rot_rad) * cx + math.cos(rot_rad) * cy

    x_new = x_root + rx + dx
    y_new = y_root - ry + dy
    ang_new = (m.ang + rot_rad) % math.pi
    return _Minu(x_new, y_new, ang_new)


def _count_matches(minu1, minu2,
                   dx: float, dy: float, rot_rad: float,
                   x_root: float, y_root: float,
                   dist_limit: float, angle_limit: float) -> int:
    """
    Count matching pairs as trong Functions.CountMinuMatching.
    Mỗi minutiae của minu2 chỉ được match tối đa 1 lần.
    """
    used = [False] * len(minu2)
    count = 0
    for m1 in minu1:
        for j, m2 in enumerate(minu2):
            if used[j]:
                continue
            m2t = _transform(m2, dx, dy, rot_rad, x_root, y_root)
            d = math.hypot(m2t.x - m1.x, m2t.y - m1.y)
            if d > dist_limit:
                continue
            if _angle_diff(m1.ang, m2t.ang) > angle_limit:
                continue
            used[j] = True
            count += 1
            break
    return count


def match_minutiae_ransac_consistency(
    probe: List[Dict[str, Any]],
    gallery: List[Dict[str, Any]],
    debug: bool = False,
) -> Dict[str, Any]:

    minu1 = _to_minu_list(probe)
    minu2 = _to_minu_list(gallery)
    n1, n2 = len(minu1), len(minu2)

    if n1 == 0 or n2 == 0:
        return {"ok": False, "inliers": 0, "score": 0.0,
                "dbg": {"reason": "no_points"}}

    # Tuned thresholds for 500dpi MFS500 sensor
    ANGLE_LIMIT_DEG = 16.0   # Nới từ 14 -> 16 để tolerant hơn với slight rotation
    DIST_LIMIT = 12          # Nới từ 10 -> 12 pixels để tolerant finger placement
    MIN_MATCH = 8            # Giảm từ 9 -> 8 để không miss true matches

    angle_limit = math.radians(ANGLE_LIMIT_DEG)

    # root = tâm của minutiae probe
    xs1 = [m.x for m in minu1]
    ys1 = [m.y for m in minu1]
    x_root = float(sum(xs1)) / len(xs1)
    y_root = float(sum(ys1)) / len(ys1)

    xs_all = xs1 + [m.x for m in minu2]
    ys_all = ys1 + [m.y for m in minu2]
    W = max(xs_all) - min(xs_all) + 1.0
    H = max(ys_all) - min(ys_all) + 1.0

    angle_set_deg = list(range(-30, 31, 3))  # -30..30 step 3
    delta_x_set = np.arange(-W, W + 1, 2.0)
    delta_y_set = np.arange(-H, H + 1, 2.0)

    dx, dy, rot_rad, votes = _accumulate_hough(
        minu1, minu2,
        angle_limit=angle_limit,
        angle_set_deg=angle_set_deg,
        delta_x_set=delta_x_set,
        delta_y_set=delta_y_set,
        x_root=x_root, y_root=y_root,
    )

    inliers = _count_matches(
        minu1, minu2,
        dx, dy, rot_rad,
        x_root, y_root,
        dist_limit=DIST_LIMIT,
        angle_limit=angle_limit,
    )

    min_ref = float(min(n1, n2))
    score = inliers / min_ref if min_ref > 0 else 0.0

    dbg = {}
    if debug:
        dbg = {
            "dx": dx,
            "dy": dy,
            "rot_deg": math.degrees(rot_rad),
            "votes": votes,
            "n1": n1,
            "n2": n2,
        }

    return {
        "ok": True,
        "inliers": int(inliers),
        "score": float(score),
        "dbg": dbg,
        "thresholds": {
            "angle_limit_deg": ANGLE_LIMIT_DEG,
            "dist_limit_px": DIST_LIMIT,
            "min_match": MIN_MATCH,
        },
    }
