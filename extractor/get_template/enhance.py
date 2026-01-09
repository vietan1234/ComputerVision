import cv2
import numpy as np

# -------------------------------------------------
# 1. ROI theo phương sai block (giống RegionSelect)
# -------------------------------------------------
def _block_variance(img: np.ndarray, blk: int = 16, thr: float = 15.0) -> np.ndarray:
    """
    Tạo mask vùng có vân bằng phương sai block.
    img: uint8 (0..255)
    """
    h, w = img.shape
    bh, bw = blk, blk
    mask = np.zeros_like(img, np.uint8)

    for y in range(0, h, bh):
        for x in range(0, w, bw):
            ys, xs = y, x
            ye, xe = min(y + bh, h), min(x + bw, w)
            patch = img[ys:ye, xs:xe]
            if patch.size < 16:
                continue
            if patch.var() >= thr:
                mask[ys:ye, xs:xe] = 255

    # Làm mịn mask cho đỡ răng cưa
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k, iterations=1)
    return mask


# -------------------------------------------------
# 2. Orientation + coherence (structure tensor)
# -------------------------------------------------
# -------------------------------------------------
# 2. Orientation + coherence (Hong / ZIP2 style)
# -------------------------------------------------
def _orientation_and_coherence(gray_f: np.ndarray, sigma: float = 3.0):
    """
    gray_f: float32 [0..1], đã làm mịn nhẹ.
    Trả:
      - orient: rad trong [-π/2..π/2] (hướng ridge)
      - coh: coherence 0..1

    Cách làm (rất gần ZIP2):
      1) Tính gradient Gx, Gy bằng Sobel.
      2) Tính ma trận cấu trúc (structure tensor):
           Jxx = ⟨Gx^2⟩_W, Jyy = ⟨Gy^2⟩_W, Jxy = ⟨Gx·Gy⟩_W
         với ⟨·⟩_W là trung bình/box filter trên cửa sổ 16×16.
      3) Orientation:
           θ = 0.5 * atan2(2 Jxy, Jxx - Jyy)
      4) Coherence:
           λ1,2 = eigenvalues ⇒ coh = (λ1 - λ2) / (λ1 + λ2)
      5) Làm mượt orientation bằng cos(2θ), sin(2θ) để tránh nhảy pha.
    """
    # 1) Gradient
    gx = cv2.Sobel(gray_f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_f, cv2.CV_32F, 0, 1, ksize=3)

    # 2) Tích luỹ trên block 16×16 (giống widthSquare trong ZIP2)
    blk = 16
    ksize = (blk, blk)
    Gxx = cv2.boxFilter(gx * gx, ddepth=-1, ksize=ksize, normalize=True)
    Gyy = cv2.boxFilter(gy * gy, ddepth=-1, ksize=ksize, normalize=True)
    Gxy = cv2.boxFilter(gx * gy, ddepth=-1, ksize=ksize, normalize=True)

    # 3) Orientation thô
    num = 2.0 * Gxy
    den = (Gxx - Gyy)
    theta = 0.5 * np.arctan2(num, den)  # [-π/2..π/2]

    # 4) Coherence từ eigenvalues của structure tensor
    tmp = np.sqrt((Gxx - Gyy) * (Gxx - Gyy) + 4.0 * Gxy * Gxy)
    lam1 = 0.5 * (Gxx + Gyy + tmp)
    lam2 = 0.5 * (Gxx + Gyy - tmp)
    coh = (lam1 - lam2) / (lam1 + lam2 + 1e-6)
    coh = np.clip(coh, 0.0, 1.0)

    # 5) Làm mượt orientation đúng cách (trên cos 2θ, sin 2θ)
    #    để tránh chỗ biên bị nhảy 180°
    cos2 = np.cos(2.0 * theta)
    sin2 = np.sin(2.0 * theta)

    # sigma ở đây dùng như độ mượt không gian (block + gaussian)
    # kernel odd (5,5) là khá ổn
    k_gauss = max(3, int(round(sigma * 2)) | 1)  # bảo đảm số lẻ ≥3
    cos2 = cv2.GaussianBlur(cos2, (k_gauss, k_gauss), 0)
    sin2 = cv2.GaussianBlur(sin2, (k_gauss, k_gauss), 0)

    theta_smooth = 0.5 * np.arctan2(sin2, cos2)
    coh_smooth = cv2.GaussianBlur(coh, (k_gauss, k_gauss), 0)

    return theta_smooth.astype(np.float32), coh_smooth.astype(np.float32)



# -------------------------------------------------
# 3. Gabor filter bank (giống MaskGaborCollection)
# -------------------------------------------------
def _gabor_kernel(ksize: int, sigma: float, theta: float,
                  lambd: float, gamma: float) -> np.ndarray:
    """
    Tạo kernel Gabor giống MaskGabor trong ZIP1.
    theta: rad, hướng ridge.
    """
    return cv2.getGaborKernel(
        (ksize, ksize),
        sigma,
        theta,
        lambd,
        gamma,
        psi=0,
        ktype=cv2.CV_32F,
    )


def _build_gabor_bank(num_orients: int = 16,
                      ksize: int = 21,
                      sigma: float = 4.0,
                      lambd: float = 10.0,
                      gamma: float = 0.6):
    """
    Tạo một bộ mask Gabor cho các góc rời rạc (giống MaskGaborCollection).
    """
    bank = []
    for i in range(num_orients):
        theta = (np.pi * i) / num_orients  # 0..π
        kern = _gabor_kernel(ksize, sigma, theta, lambd, gamma)
        bank.append(kern)
    return bank


def _gabor_enhance_blockwise(
    img: np.ndarray,
    orient_map: np.ndarray,
    mask: np.ndarray,
    coh_map: np.ndarray,
    blk: int = 16,
    num_orients: int = 16,
    ksize: int = 21,
    sigma: float = 4.0,
    lambd: float = 10.0,
    gamma: float = 0.6,
    coh_thr: float = 0.20,
) -> np.ndarray:
    """
    Lọc Gabor theo block:
      - lấy hướng trung bình trong block
      - quy về [0..π), lượng tử hoá -> index
      - dùng kernel từ Gabor bank tương ứng
    Rất giống cách ZIP1 dùng MaskGaborCollection + direct.
    """
    img_f = img.astype(np.float32)
    h, w = img.shape
    out = np.zeros_like(img_f)

    bank = _build_gabor_bank(
        num_orients=num_orients,
        ksize=ksize,
        sigma=sigma,
        lambd=lambd,
        gamma=gamma,
    )

    angle_step = np.pi / num_orients

    for y in range(0, h, blk):
        for x in range(0, w, blk):
            ys, xs = y, x
            ye, xe = min(y + blk, h), min(x + blk, w)

            block_mask = mask[ys:ye, xs:xe]
            if block_mask.mean() < 5:  # gần như nền
                continue

            block_coh = coh_map[ys:ye, xs:xe]
            if block_coh.mean() < coh_thr:
                continue

            # Hướng trung bình (rad) trong block
            block_orient = orient_map[ys:ye, xs:xe]
            # chỉ tính trên vùng có mask
            mean_theta = cv2.mean(block_orient, mask=block_mask)[0]

            # quy về [0..π)
            while mean_theta < 0:
                mean_theta += np.pi
            while mean_theta >= np.pi:
                mean_theta -= np.pi

            # lượng tử hoá -> index bank
            idx = int(round(mean_theta / angle_step)) % num_orients
            kern = bank[idx]

            # lọc ROI
            roi = img_f[ys:ye, xs:xe]
            filtered = cv2.filter2D(roi, cv2.CV_32F, kern)

            out[ys:ye, xs:xe] = filtered

    # normalize 0..255
    out_norm = cv2.normalize(out, None, 0, 255, cv2.NORM_MINMAX)
    out_norm = out_norm.astype(np.uint8)

    # chỉ giữ vùng có vân
    out_norm = cv2.bitwise_and(out_norm, out_norm, mask=mask)

    # nhẹ tay đóng mở để ridges liền mạch hơn (hạn chế đứt)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    out_norm = cv2.morphologyEx(out_norm, cv2.MORPH_CLOSE, k, iterations=1)

    return out_norm


# -------------------------------------------------
# 4. PUBLIC API: enhance(gray)
# -------------------------------------------------
def enhance(gray: np.ndarray):
    """
    Pipeline xử lý ảnh vân tay giống tinh thần ZIP1:
      1) Normalization theo mean/variance (ToNormal).
      2) Mịn nhẹ.
      3) Orientation + coherence (structure tensor).
      4) ROI theo block-variance.
      5) Gabor filter bank theo hướng local (MaskGaborCollection).
    Output:
      - enhanced: uint8, ảnh đã enhance.
      - orient_map: float32, rad.
      - coh_map: float32, 0..1.
    """
    if gray.ndim != 2:
        raise ValueError("Ảnh input phải là gray (H,W).")
    if gray.shape != (354, 296):
        # vẫn cho chạy, chỉ cảnh báo nhẹ
        pass

    # --- Bước 1: Normalization kiểu ZIP1 ---
    g = gray.astype(np.float32)
    m = float(g.mean())
    v = float(g.var() + 1e-6)

    # target mean, variance tương tự các paper cổ điển (Fan, Hong)
    M = 128.0
    V = 128.0 * 128.0

    above = g >= m
    below = ~above
    g_norm = np.zeros_like(g, dtype=np.float32)
    g_norm[above] = M + np.sqrt((g[above] - m) ** 2 * V / v)
    g_norm[below] = M - np.sqrt((g[below] - m) ** 2 * V / v)
    g_norm = np.clip(g_norm, 0, 255).astype(np.uint8)

    # --- Bước 2: Mịn nhẹ để orientation ổn định ---
    # dùng Gaussian cho chắc, bilateral có thể giữ noise không cần thiết
    g_blur = cv2.GaussianBlur(g_norm, (5, 5), 0)

    # --- Bước 3: Orientation + coherence ---
    g_f = g_blur.astype(np.float32) / 255.0
    orient_map, coh_map = _orientation_and_coherence(g_f, sigma=3.0)

    # --- Bước 4: ROI theo phương sai block ---
    mask = _block_variance(g_norm, blk=16, thr=20.0)

    # --- Bước 5: Gabor enhancement theo hướng local ---
    enhanced = _gabor_enhance_blockwise(
        g_norm,
        orient_map,
        mask,
        coh_map,
        blk=16,
        num_orients=16,
        ksize=21,
        sigma=4.0,
        lambd=10.0,
        gamma=0.6,
        coh_thr=0.20,
    )

    return enhanced, orient_map, coh_map
