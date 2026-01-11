import numpy as np
import cv2
import base64
from typing import Tuple

# Kích thước MFS500: (h, w)
MFS500_SIZE = (354, 296)


def _auto_center_fingerprint(img: np.ndarray, enable: bool = False) -> Tuple[np.ndarray, dict]:
    """
    Căn giữa vùng vân tay trong khung ảnh.
    
    LƯU Ý: Mặc định TẮT (enable=False) vì auto-center có thể gây lệch.
    Chỉ bật khi cần thiết.
    
    Args:
        img: ảnh grayscale (H,W)
        enable: có bật auto-center không
    Returns:
        (image, metadata_dict)
    """
    meta = {"center_dx": 0.0, "center_dy": 0.0, "centered": False}
    
    if not enable or img.ndim != 2:
        return img, meta

    H, W = img.shape

    # Làm mịn nhẹ để giảm noise
    blur = cv2.GaussianBlur(img, (5, 5), 0)

    # Otsu threshold – ridges thường tối, nền sáng → invert mask
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask_fg = 255 - th

    # Morphology để nối vùng và bỏ lỗ nhỏ
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask_fg = cv2.morphologyEx(mask_fg, cv2.MORPH_CLOSE, k, iterations=2)
    mask_fg = cv2.morphologyEx(mask_fg, cv2.MORPH_OPEN, k, iterations=1)

    # Tìm contour lớn nhất
    contours, _ = cv2.findContours(mask_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img, meta

    # Chọn contour có diện tích lớn nhất
    areas = [cv2.contourArea(c) for c in contours]
    max_idx = int(np.argmax(areas))
    max_area = areas[max_idx]
    if max_area < 0.05 * (H * W):
        return img, meta

    x, y, w, h = cv2.boundingRect(contours[max_idx])
    cx = x + w / 2.0
    cy = y + h / 2.0

    # Tâm mục tiêu: giữa khung
    target_cx = W / 2.0
    target_cy = H / 2.0

    # Vector tịnh tiến
    dx = target_cx - cx
    dy = target_cy - cy

    # Chỉ center nếu lệch nhiều (> 20 pixels)
    if abs(dx) < 20 and abs(dy) < 20:
        meta["centered"] = True
        return img, meta

    # Giới hạn dịch chuyển (max 30% chiều ảnh)
    max_dx = W * 0.3
    max_dy = H * 0.3
    dx = max(-max_dx, min(max_dx, dx))
    dy = max(-max_dy, min(max_dy, dy))

    M = np.float32([[1, 0, dx],
                    [0, 1, dy]])

    # warpAffine với borderMode REPLICATE để không tạo viền đen/trắng cứng
    shifted = cv2.warpAffine(
        img, M, (W, H),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE
    )
    
    meta["center_dx"] = float(dx)
    meta["center_dy"] = float(dy)
    meta["centered"] = True
    
    return shifted, meta


def bmp_to_gray_np(bmp_bytes: bytes, expect_size: Tuple[int, int] = (354, 296)) -> np.ndarray:
    """
    Decode BMP/PNG/JPG bytes -> ảnh gray (đã xoay đúng 354x296 nếu cần).
    KHÔNG auto-center (để tránh lệch).
    """
    img, _ = bmp_to_gray_np_with_meta(bmp_bytes, expect_size)
    return img


def bmp_to_gray_np_with_meta(bmp_bytes: bytes, expect_size: Tuple[int, int] = (354, 296)) -> Tuple[np.ndarray, dict]:
    """
    Decode BMP/PNG/JPG bytes -> ảnh gray (đã xoay đúng 354x296 nếu cần).
    Trả về metadata.
    """
    arr = np.frombuffer(bmp_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Không decode được ảnh (BMP/PNG/JPG).")

    H, W = img.shape
    rotated = False
    if (H, W) == (354, 296):
        pass
    elif (H, W) == (296, 354):
        # đưa về (354,296)
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        rotated = True
    else:
        raise ValueError(f"Kích thước ảnh lạ: {H}x{W}, mong đợi (354x296) hoặc (296x354).")

    # KHÔNG auto-center mặc định - giữ nguyên ảnh gốc
    # Nếu cần center, gọi _auto_center_fingerprint riêng với enable=True
    meta = {
        "rotated": rotated,
        "center_dx": 0.0,
        "center_dy": 0.0,
        "centered": False
    }
    
    return img, meta


def b64_to_bytes(b64: str) -> bytes:
    """base64 (không tiền tố) -> bytes."""
    return base64.b64decode(b64)


def b64bmp_to_gray_np(b64_bmp: str, expect_size: Tuple[int, int] = MFS500_SIZE) -> np.ndarray:
    """Ảnh BMP base64 -> gray np.ndarray."""
    return bmp_to_gray_np(b64_to_bytes(b64_bmp), expect_size=expect_size)


def b64bmp_to_gray_np_with_meta(b64_bmp: str, expect_size: Tuple[int, int] = MFS500_SIZE) -> Tuple[np.ndarray, dict]:
    """Ảnh BMP base64 -> gray np.ndarray + metadata."""
    return bmp_to_gray_np_with_meta(b64_to_bytes(b64_bmp), expect_size=expect_size)


def to_b64_png(img_gray: np.ndarray) -> str:
    """
    np.ndarray (H,W) hoặc (H,W,3/4) -> PNG base64 (không có tiền tố data:).
    Dùng để trả ảnh đã enhance/skeleton ra frontend.
    """
    if img_gray.ndim == 2:
        flag = cv2.IMWRITE_PNG_COMPRESSION
        buf = cv2.imencode(".png", img_gray, [flag, 3])[1]
    else:
        buf = cv2.imencode(".png", img_gray)[1]
    return base64.b64encode(buf.tobytes()).decode("ascii")
