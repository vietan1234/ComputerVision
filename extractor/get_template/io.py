import numpy as np
import cv2
import base64
from typing import Tuple

# Kích thước MFS500: (h, w)
MFS500_SIZE = (354, 296)


def _auto_center_fingerprint(img: np.ndarray) -> np.ndarray:
    """
    Căn giữa vùng vân tay trong khung ảnh.
    - Tìm vùng fingerprint bằng threshold + morphology.
    - Tính bounding box lớn nhất.
    - Dịch toàn bộ ảnh sao cho tâm vùng vân tay trùng tâm khung (W/2, H/2).
    Nếu không tìm được vùng hợp lý thì trả lại ảnh gốc.
    """
    if img.ndim != 2:
        return img

    H, W = img.shape

    # Làm mịn nhẹ để giảm noise
    blur = cv2.GaussianBlur(img, (5, 5), 0)

    # Otsu threshold – ridges thường tối, nền sáng → invert mask
    # th: nền ~255, vân tay ~0 → mask_fg: vùng vân tay = 255
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask_fg = 255 - th

    # Morphology để nối vùng và bỏ lỗ nhỏ
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask_fg = cv2.morphologyEx(mask_fg, cv2.MORPH_CLOSE, k, iterations=2)
    mask_fg = cv2.morphologyEx(mask_fg, cv2.MORPH_OPEN, k, iterations=1)

    # Tìm contour lớn nhất
    contours, _ = cv2.findContours(mask_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        # Không tìm được gì rõ ràng → giữ nguyên
        return img

    # Chọn contour có diện tích lớn nhất
    areas = [cv2.contourArea(c) for c in contours]
    max_idx = int(np.argmax(areas))
    max_area = areas[max_idx]
    if max_area < 0.05 * (H * W):
        # Vùng quá nhỏ, có thể chỉ là noise → giữ nguyên
        return img

    x, y, w, h = cv2.boundingRect(contours[max_idx])
    cx = x + w / 2.0
    cy = y + h / 2.0

    # Tâm mục tiêu: giữa khung
    target_cx = W / 2.0
    target_cy = H / 2.0

    # Vector tịnh tiến
    dx = target_cx - cx
    dy = target_cy - cy

    # Nếu dịch quá nhiều (vd > 1/2 chiều ảnh) thì có thể ước lượng sai → bỏ qua
    if abs(dx) > W * 0.5 or abs(dy) > H * 0.5:
        return img

    M = np.float32([[1, 0, dx],
                    [0, 1, dy]])

    # Dùng mean intensity làm border để tránh viền đen gắt
    shifted = cv2.warpAffine(
        img, M, (W, H),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE
    )
    return shifted


def bmp_to_gray_np(bmp_bytes: bytes, expect_size: Tuple[int, int] = (354, 296)) -> np.ndarray:
    """
    Decode BMP/PNG/JPG bytes -> ảnh gray (đã xoay đúng 354x296 nếu cần)
    + AUTO-CENTER fingerprint trong khung.
    """
    arr = np.frombuffer(bmp_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Không decode được ảnh (BMP/PNG/JPG).")

    H, W = img.shape
    if (H, W) == (354, 296):
        pass
    elif (H, W) == (296, 354):
        # đưa về (354,296)
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    else:
        raise ValueError(f"Kích thước ảnh lạ: {H}x{W}, mong đợi (354x296) hoặc (296x354).")

    # Sau khi xoay đúng chiều, tiến hành căn giữa fingerprint
    img_centered = _auto_center_fingerprint(img)
    return img_centered


def b64_to_bytes(b64: str) -> bytes:
    """base64 (không tiền tố) -> bytes."""
    return base64.b64decode(b64)


def b64bmp_to_gray_np(b64_bmp: str, expect_size: Tuple[int, int] = MFS500_SIZE) -> np.ndarray:
    """Ảnh BMP base64 -> gray np.ndarray (đã auto-center)."""
    return bmp_to_gray_np(b64_to_bytes(b64_bmp), expect_size=expect_size)


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
