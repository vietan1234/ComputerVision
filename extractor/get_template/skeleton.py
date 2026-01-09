# extractor/get_template/skeleton.py
import cv2
import numpy as np

def _guo_hall_thinning(bin_img: np.ndarray) -> np.ndarray:
    """Binary (ridges=255) -> 1-pixel skeleton using vectorized Guo–Hall."""
    I = (bin_img > 0).astype(np.uint8)
    prev = np.zeros_like(I)
    changed = True
    while changed:
        # sub-iteration A
        P2 = np.roll(I, -1, axis=0)
        P3 = np.roll(np.roll(I, -1, axis=0),  1, axis=1)
        P4 = np.roll(I,  1, axis=1)
        P5 = np.roll(np.roll(I,  1, axis=0),  1, axis=1)
        P6 = np.roll(I,  1, axis=0)
        P7 = np.roll(np.roll(I,  1, axis=0), -1, axis=1)
        P8 = np.roll(I, -1, axis=1)
        P9 = np.roll(np.roll(I, -1, axis=0), -1, axis=1)

        C = ((P2 == 0) & (P3 == 1)).astype(np.uint8) + ((P3 == 0) & (P4 == 1)).astype(np.uint8) + \
            ((P4 == 0) & (P5 == 1)).astype(np.uint8) + ((P5 == 0) & (P6 == 1)).astype(np.uint8) + \
            ((P6 == 0) & (P7 == 1)).astype(np.uint8) + ((P7 == 0) & (P8 == 1)).astype(np.uint8) + \
            ((P8 == 0) & (P9 == 1)).astype(np.uint8) + ((P9 == 0) & (P2 == 1)).astype(np.uint8)
        N1 = (P9 | P2) + (P3 | P4) + (P5 | P6) + (P7 | P8)
        N2 = (P2 | P3) + (P4 | P5) + (P6 | P7) + (P8 | P9)
        N  = np.minimum(N1, N2)
        mA = (C == 1) & (N >= 2) & (N <= 3) & ((P2 & P4 & P6) == 0) & ((P4 & P6 & P8) == 0)
        I  = I & (~mA)

        # sub-iteration B
        P2 = np.roll(I, -1, axis=0)
        P3 = np.roll(np.roll(I, -1, axis=0),  1, axis=1)
        P4 = np.roll(I,  1, axis=1)
        P5 = np.roll(np.roll(I,  1, axis=0),  1, axis=1)
        P6 = np.roll(I,  1, axis=0)
        P7 = np.roll(np.roll(I,  1, axis=0), -1, axis=1)
        P8 = np.roll(I, -1, axis=1)
        P9 = np.roll(np.roll(I, -1, axis=0), -1, axis=1)

        C = ((P2 == 0) & (P3 == 1)).astype(np.uint8) + ((P3 == 0) & (P4 == 1)).astype(np.uint8) + \
            ((P4 == 0) & (P5 == 1)).astype(np.uint8) + ((P5 == 0) & (P6 == 1)).astype(np.uint8) + \
            ((P6 == 0) & (P7 == 1)).astype(np.uint8) + ((P7 == 0) & (P8 == 1)).astype(np.uint8) + \
            ((P8 == 0) & (P9 == 1)).astype(np.uint8) + ((P9 == 0) & (P2 == 1)).astype(np.uint8)
        N1 = (P9 | P2) + (P3 | P4) + (P5 | P6) + (P7 | P8)
        N2 = (P2 | P3) + (P4 | P5) + (P6 | P7) + (P8 | P9)
        N  = np.minimum(N1, N2)
        mB = (C == 1) & (N >= 2) & (N <= 3) & ((P2 & P4 & P8) == 0) & ((P2 & P6 & P8) == 0)
        I2 = I & (~mB)

        changed = not np.array_equal(I2, prev)
        prev = I = I2
    return (I * 255).astype(np.uint8)

def _prune_spurs(skel: np.ndarray, iterations: int = 3):  # Tăng iterations cho pruning tốt hơn
    s = (skel > 0).astype(np.uint8)
    K = np.array([[1,1,1],[1,10,1],[1,1,1]], np.uint8)
    for _ in range(iterations):
        conv = cv2.filter2D(s, -1, K)
        leaves = (conv == 11).astype(np.uint8)
        s = s & (~leaves)
    # Tối ưu: Loại connected components nhỏ (isolated noise)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(s, connectivity=8)
    for i in range(1, len(stats)):
        if stats[i, cv2.CC_STAT_AREA] < 5:  # Loại component <5 px
            s[labels == i] = 0
    return (s*255).astype(np.uint8)

def binarize_and_thin(enhanced: np.ndarray):
    # Tối ưu: Adaptive threshold cho ảnh MFS500 (thường contrast cao)
    bin_img = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)
    bin_img = 255 - bin_img
    bin_img = cv2.medianBlur(bin_img, 3)
    skel = _guo_hall_thinning(bin_img)
    skel = _prune_spurs(skel, iterations=3)  # Tăng để loại spurs tốt hơn
    return skel, bin_img