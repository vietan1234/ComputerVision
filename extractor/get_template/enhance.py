# extractor/get_template/enhance.py
# Fingerprint Enhancement - Simple Hong-style

import cv2
import numpy as np


def _block_variance_mask(img: np.ndarray, blk: int = 16, thr: float = 100.0) -> np.ndarray:
    """Tạo ROI mask dựa trên variance."""
    h, w = img.shape
    mask = np.zeros_like(img, np.uint8)
    for y in range(0, h, blk):
        for x in range(0, w, blk):
            ye, xe = min(y + blk, h), min(x + blk, w)
            patch = img[y:ye, x:xe]
            if patch.var() > thr:
                mask[y:ye, x:xe] = 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    return mask


def _orientation_field(img: np.ndarray, blk: int = 16):
    """Tính orientation field và coherence."""
    h, w = img.shape
    orient = np.zeros((h, w), dtype=np.float32)
    coh = np.zeros((h, w), dtype=np.float32)

    gx = cv2.Sobel(img.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(img.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)

    for y in range(0, h, blk):
        for x in range(0, w, blk):
            ye, xe = min(y + blk, h), min(x + blk, w)
            gx_blk = gx[y:ye, x:xe]
            gy_blk = gy[y:ye, x:xe]

            Gxx = np.sum(gx_blk * gx_blk)
            Gyy = np.sum(gy_blk * gy_blk)
            Gxy = np.sum(gx_blk * gy_blk)

            theta = 0.5 * np.arctan2(2 * Gxy, Gxx - Gyy)
            orient[y:ye, x:xe] = theta

            denom = Gxx + Gyy
            if denom > 0:
                coh[y:ye, x:xe] = np.sqrt((Gxx - Gyy)**2 + 4*Gxy**2) / denom

    # Smooth orientation
    cos2 = cv2.GaussianBlur(np.cos(2 * orient), (5, 5), 0)
    sin2 = cv2.GaussianBlur(np.sin(2 * orient), (5, 5), 0)
    orient = 0.5 * np.arctan2(sin2, cos2)

    return orient, coh


def _gabor_filter(img: np.ndarray, orient: np.ndarray, mask: np.ndarray,
                  ksize: int = 16, sigma: float = 4.0, lambd: float = 8.0, gamma: float = 0.5):
    """Apply Gabor filter tuned to local orientation."""
    h, w = img.shape
    out = img.astype(np.float32).copy()
    img_f = img.astype(np.float32)

    blk = 16
    for y in range(0, h, blk):
        for x in range(0, w, blk):
            ye, xe = min(y + blk, h), min(x + blk, w)

            if mask[y:ye, x:xe].mean() < 128:
                continue

            theta = float(orient[y + blk//2, x + blk//2] if y + blk//2 < h and x + blk//2 < w else 0)

            kern = cv2.getGaborKernel((ksize, ksize), sigma, theta, lambd, gamma, 0, cv2.CV_32F)
            
            # Filter với padding
            pad = ksize // 2
            y0, y1 = max(0, y - pad), min(h, ye + pad)
            x0, x1 = max(0, x - pad), min(w, xe + pad)
            region = img_f[y0:y1, x0:x1]
            filtered = cv2.filter2D(region, cv2.CV_32F, kern)

            by, bx = y - y0, x - x0
            out[y:ye, x:xe] = filtered[by:by+(ye-y), bx:bx+(xe-x)]

    return out


def enhance(gray: np.ndarray):
    """
    Simple fingerprint enhancement pipeline:
    1. Normalize
    2. Compute orientation + coherence
    3. Apply Gabor filter
    """
    if gray.ndim != 2:
        raise ValueError("Input must be grayscale")

    # Normalize
    g = gray.astype(np.float32)
    g = (g - g.mean()) / (g.std() + 1e-6) * 64 + 128
    g = np.clip(g, 0, 255).astype(np.uint8)

    # ROI mask
    mask = _block_variance_mask(g, blk=16, thr=100)

    # Orientation + coherence
    orient, coh = _orientation_field(g, blk=16)

    # Gabor filtering
    enhanced = _gabor_filter(g, orient, mask, ksize=16, sigma=4.0, lambd=8.0, gamma=0.5)

    # Normalize output
    enhanced = cv2.normalize(enhanced, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # Blend with original outside ROI
    mask_f = mask.astype(np.float32) / 255.0
    enhanced = (enhanced.astype(np.float32) * mask_f + g.astype(np.float32) * (1 - mask_f))
    enhanced = enhanced.astype(np.uint8)

    return enhanced, orient, coh
