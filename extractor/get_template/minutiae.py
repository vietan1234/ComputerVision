# extractor/get_template/minutiae.py
from typing import List, Dict
import numpy as np
import cv2
import math

# ---------- util ----------
def _neighbors8(y, x):
    # P2..P9 theo thứ tự ngược chiều kim đồng hồ bắt đầu từ (y-1,x)
    return [
        (y-1, x    ), (y-1, x+1), (y,   x+1), (y+1, x+1),
        (y+1, x    ), (y+1, x-1), (y,   x-1), (y-1, x-1),
    ]


def _crossing_number(patch8: List[int]) -> int:
    """CN: số lần chuyển 0->1 quanh 8-láng giềng (tuần tự, vòng)."""
    s = 0
    for i in range(8):
        s += (patch8[i] == 0 and patch8[(i + 1) % 8] == 1)
    return s


def _bilinear_at(mat: np.ndarray, y: float, x: float) -> float:
    """Lấy giá trị bilinear tại toạ độ float (y, x)."""
    h, w = mat.shape
    if x < 0 or y < 0 or x >= w - 1 or y >= h - 1:
        return float(mat[int(round(max(0, min(h-1, y)))), int(round(max(0, min(w-1, x))))])

    x0, y0 = int(x), int(y)
    dx, dy = x - x0, y - y0
    x1, y1 = x0 + 1, y0 + 1

    v00 = float(mat[y0, x0])
    v01 = float(mat[y0, x1])
    v10 = float(mat[y1, x0])
    v11 = float(mat[y1, x1])

    v0 = v00 * (1 - dx) + v01 * dx
    v1 = v10 * (1 - dx) + v11 * dx
    return v0 * (1 - dy) + v1 * dy


def _nms_distance(pts: List[Dict], min_dist: int = 6) -> List[Dict]:
    """
    Non-maximum suppression theo khoảng cách Euclid (giữ lại điểm quality cao hơn).
    """
    if not pts:
        return []

    pts = sorted(pts, key=lambda p: p.get("quality", 0.0), reverse=True)
    kept = []
    r2 = min_dist * min_dist

    for p in pts:
        ok = True
        for q in kept:
            dx = p["x"] - q["x"]
            dy = p["y"] - q["y"]
            if dx * dx + dy * dy < r2:
                ok = False
                break
        if ok:
            kept.append(p)
    return kept


# ---------- core ----------
def estimate_orientation_map(enhanced: np.ndarray, ksize: int = 11):
    """
    Ước lượng hướng ridge cho mỗi pixel (rad) + coherence 0..1
    dùng cho ảnh đã enhance (uint8).
    """
    if enhanced.ndim != 2:
        raise ValueError("enhanced phải là ảnh gray (H,W).")

    # Chuẩn hoá về [0..1]
    g = enhanced.astype(np.float32) / 255.0

    # Gradient Sobel
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)

    # Tích luỹ block ~16×16 (box filter)
    blk = 16
    ksize_blk = (blk, blk)
    Gxx = cv2.boxFilter(gx * gx, ddepth=-1, ksize=ksize_blk, normalize=True)
    Gyy = cv2.boxFilter(gy * gy, ddepth=-1, ksize=ksize_blk, normalize=True)
    Gxy = cv2.boxFilter(gx * gy, ddepth=-1, ksize=ksize_blk, normalize=True)

    # Orientation thô
    num = 2.0 * Gxy
    den = (Gxx - Gyy)
    theta = 0.5 * np.arctan2(num, den)

    # Coherence
    tmp = np.sqrt((Gxx - Gyy) * (Gxx - Gyy) + 4.0 * Gxy * Gxy)
    lam1 = 0.5 * (Gxx + Gyy + tmp)
    lam2 = 0.5 * (Gxx + Gyy - tmp)
    coh = (lam1 - lam2) / (lam1 + lam2 + 1e-6)
    coh = np.clip(coh, 0.0, 1.0)

    # Làm mượt orientation bằng cos(2θ), sin(2θ)
    cos2 = np.cos(2.0 * theta)
    sin2 = np.sin(2.0 * theta)

    k_gauss = max(3, int(round(ksize)) | 1)  # kernel lẻ
    cos2 = cv2.GaussianBlur(cos2, (k_gauss, k_gauss), 0)
    sin2 = cv2.GaussianBlur(sin2, (k_gauss, k_gauss), 0)

    theta_smooth = 0.5 * np.arctan2(sin2, cos2)
    coh_smooth = cv2.GaussianBlur(coh, (k_gauss, k_gauss), 0)

    return theta_smooth.astype(np.float32), coh_smooth.astype(np.float32)



def extract_minutiae(skel: np.ndarray,
                     bin_img: np.ndarray,
                     orient_map: np.ndarray,
                     coh_map: np.ndarray,
                     margin: int = 8) -> List[Dict]:
    """
    Tìm minutiae bằng Crossing Number trên skeleton.
    - skel: ảnh xương (255 ridge, 0 nền)
    - bin_img: binary gốc (255 ridge, 0 nền)
    - orient_map: hướng ridge (rad)
    - coh_map: coherence 0..1
    """
    # Skeleton: ridge = 1, nền = 0
    I = (skel > 0).astype(np.uint8)
    h, w = I.shape
    pts: List[Dict] = []

    # 1) Quét CN
    for y in range(1 + margin, h - 1 - margin):
        for x in range(1 + margin, w - 1 - margin):
            if I[y, x] == 0:
                continue

            neigh_coords = _neighbors8(y, x)
            patch = [int(I[yy, xx]) for (yy, xx) in neigh_coords]
            cn = _crossing_number(patch)

            if cn == 1:
                mtype = "ending"
            elif cn == 3:
                mtype = "bifurcation"
            else:
                continue

            pts.append({"x": x, "y": y, "type": mtype})

    if not pts:
        return []

    # 2) Gán hướng & quality từ orient_map + coh_map
    enriched = []
    for p in pts:
        y, x = float(p["y"]), float(p["x"])
        ang_rad = float(_bilinear_at(orient_map, y, x))
        ang_deg = (math.degrees(ang_rad) + 180.0) % 180.0  # 0..179
        coh = float(np.clip(_bilinear_at(coh_map, y, x), 0.0, 1.0))

        enriched.append({
            "x": p["x"],
            "y": p["y"],
            "type": p["type"],
            "angle": ang_deg,
            "quality": coh,
        })

    # 3) Lọc theo biên ảnh
    border = 12
    enriched = [
        p for p in enriched
        if border <= p["x"] < w - border and border <= p["y"] < h - border
    ]

    if not enriched:
        return []

    # 4) Lọc theo coherence (quality)
    # giống tinh thần ZIP1: loại vùng orientation không ổn định
    enriched = [p for p in enriched if p["quality"] >= 0.4]

    if not enriched:
        return []

    # 5) NMS theo khoảng cách
    enriched = _nms_distance(enriched, min_dist=8)

    # 6) Giới hạn số minutiae tối đa
    if len(enriched) > 120:
        enriched = sorted(enriched, key=lambda p: p["quality"], reverse=True)[:120]

    return enriched
