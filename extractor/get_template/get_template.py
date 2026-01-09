# extractor/get_template/get_template.py
# Entry-point trích xuất minutiae từ ảnh BMP(base64) của MFS500
from typing import Dict, Any
import numpy as np

from get_template.io import b64bmp_to_gray_np, MFS500_SIZE
from get_template import enhance, skeleton, minutiae
from get_template.minutiae import estimate_orientation_map


def get_template_from_b64bmp(b64_bmp: str) -> Dict[str, Any]:
    """
    Input:
      - b64_bmp: chuỗi base64 của ảnh BMP (MFS500)
    Output:
      - dict có dạng:
        {
          "ok": True/False,
          "error": <str nếu có>,
          "shape": {"h": H, "w": W},
          "minutiae_count": n,
          "minutiae": [ {x,y,angle,type,quality}, ... ]
        }
    """
    # 1) Decode base64 -> gray (H,W)
    gray = b64bmp_to_gray_np(b64_bmp, expect_size=MFS500_SIZE)   # (354,296)
    H, W = gray.shape[:2]

    # 2) Enhance (chuẩn hoá + orientation + coherence + Gabor)
    #    enhance.enhance đã trả luôn orient_map, coh_map
    g_enh, orient_map_e, coh_map_e = enhance.enhance(gray)

    # 3) Binarize + thinning để lấy skeleton
    skel, bin_img = skeleton.binarize_and_thin(g_enh)

    # 4) Orientation map cho minutiae
    #    Nếu muốn có thể dùng lại orient_map_e, coh_map_e;
    #    Ở đây để chắc chắn, ta dùng luôn orient_map_e, coh_map_e vừa tính.
    orient_map = orient_map_e
    coh_map = coh_map_e

    # (Nếu cần tinh chỉnh thêm có thể uncomment để ước lượng lại trên g_enh)
    # orient_map, coh_map = estimate_orientation_map(g_enh)

    # 5) Trích minutiae
    pts = minutiae.extract_minutiae(
        skel=skel,
        bin_img=bin_img,
        orient_map=orient_map,
        coh_map=coh_map,
        margin=8,
    )
    n = len(pts)

    # 6) Đánh giá chất lượng: nếu minutiae quá ít thì coi là low_quality
    MIN_MINUTIAE = 20
    if n < MIN_MINUTIAE:
        return {
            "ok": False,
            "error": "low_quality",
            "shape": {"h": int(H), "w": int(W)},
            "minutiae_count": int(n),
            "minutiae": pts,
        }

    return {
        "ok": True,
        "shape": {"h": int(H), "w": int(W)},
        "minutiae_count": int(n),
        "minutiae": pts,
    }
