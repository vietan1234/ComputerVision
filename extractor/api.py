# extractor/api.py
import cv2
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import base64

from verify.matcher import match_minutiae_ransac_consistency
from verify.fuse import fuse_templates

from get_template.io import bmp_to_gray_np, to_b64_png
from get_template.enhance import enhance
from get_template.skeleton import binarize_and_thin
from get_template.minutiae import extract_minutiae
from get_template.get_template import get_template_from_b64bmp





app = FastAPI(title="Fingerprint Extractor & Verifier", version="1.2.0")

# --- helper: chuẩn hoá object về {"minutiae":[...]}
def _to_minutiae_obj(obj: Any) -> Dict[str, List[Dict[str, Any]]]:
    if isinstance(obj, dict):
        if isinstance(obj.get("minutiae"), list):
            return {"minutiae": obj["minutiae"]}
        jd = obj.get("json_debug")
        if isinstance(jd, dict) and isinstance(jd.get("minutiae"), list):
            return {"minutiae": jd["minutiae"]}
    return {"minutiae": []}

# ====== SCHEMAS ======
class ExtractReq(BaseModel):
    image_b64: str                 # BMP (base64, không prefix "data:")
    debug: Optional[int] = 0

class ExtractResp(BaseModel):
    ok: bool
    minutiae_count: int
    json_debug: Dict[str, Any] = {}
    error: Optional[str] = None

class FuseReq(BaseModel):
    templates_json: List[dict]
    debug: Optional[int] = 0

class FuseResp(BaseModel):
    ok: bool
    fused: dict = {}
    json_debug: Dict[str, Any] = {}
    error: Optional[str] = None

class Verify3Req(BaseModel):
    probe_json: Optional[dict] = None          # hoặc...
    probe_bitmap_b64: Optional[str] = None     # ảnh BMP base64
    templates_json: List[dict]
    debug: Optional[int] = 0

class Verify3In(BaseModel):
    probe_minutiae: List[Dict[str, Any]] | None = None
    probe_bmp_b64: str | None = None
    gallery_minutiae_list: List[List[Dict[str, Any]]]

class Verify3Resp(BaseModel):
    ok: bool
    score: float = 0.0
    inliers: int = 0
    best_index: int = -1
    json_debug: Dict[str, Any] = {}
    error: Optional[str] = None


# ====== ROUTES ======
@app.post("/extract", response_model=ExtractResp)
def extract(req: ExtractReq):
    try:
        img_bytes = base64.b64decode(req.image_b64.encode("utf-8"))
        gray = bmp_to_gray_np(img_bytes)

        # enhance() trả (enh, orient, coh)
        enh, orient, coh = enhance(gray)
        skel, bin_img = binarize_and_thin(enh)

        # extract_minutiae(skel, binary, orient, coh)
        mins = extract_minutiae(skel, bin_img, orient, coh)


        debug_imgs = {
            "minutiae": mins,
            "gray_png_b64": to_b64_png(gray),
            "enhance_png_b64": to_b64_png(enh),
            "binary_png_b64": to_b64_png(bin_img),
            "skeleton_png_b64": to_b64_png(skel),
        }

        # -------- Orientation (HSV) --------
        ori = (orient % np.pi) / np.pi
        h = (ori * 179).astype("uint8")
        s = np.full_like(h, 255, dtype="uint8")
        v = np.full_like(h, 255, dtype="uint8")
        hsv = np.stack([h, s, v], axis=2)
        ori_bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        debug_imgs["orientation_png_b64"] = to_b64_png(ori_bgr)

        # -------- Coherence (Heatmap) --------
        coh_norm = (coh * 255).astype("uint8")
        coh_color = cv2.applyColorMap(coh_norm, cv2.COLORMAP_JET)
        debug_imgs["coherence_png_b64"] = to_b64_png(coh_color)


        return {
            "ok": True,
            "minutiae_count": len(mins),
            "json_debug": debug_imgs if req.debug else {"minutiae": mins},
        }


    except Exception as ex:
        return {"ok": False, "minutiae_count": 0, "json_debug": {}, "error": f"{ex}"}


@app.post("/fuse", response_model=FuseResp)
def fuse(req: FuseReq):
    try:
        fused, dbg = fuse_templates(req.templates_json, debug=bool(req.debug))
        return {"ok": True, "fused": fused, "json_debug": dbg}
    except Exception as ex:
        return {"ok": False, "fused": {}, "json_debug": {}, "error": f"{ex}"}

@app.post("/verify3")
def verify3_route(body: Verify3In):
    # 1) Lấy probe minutiae (ưu tiên truyền sẵn; nếu không có thì extract từ ảnh BMP base64)
    if body.probe_minutiae is not None:
        P = body.probe_minutiae
    elif body.probe_bmp_b64 is not None:
        res = get_template_from_b64bmp(body.probe_bmp_b64)
        if not res.get("ok") or not res.get("minutiae"):
            return {"ok": False, "accepted": False, "error": "Extract probe failed"}
        P = res["minutiae"]
    else:
        return {"ok": False, "accepted": False, "error": "Missing probe"}

    # 2) So khớp lần lượt với 3 template đã enroll
    results = []
    for idx, G in enumerate(body.gallery_minutiae_list):
        r = match_minutiae_ransac_consistency(P, G, debug=True)
        r["idx"] = idx
        results.append(r)

    # 3) Quy tắc 1-trong-3: ĐỖ nếu một trong 3 đủ “khớp mạnh”
    ACCEPT_INLIERS = 10     # trước 12
    ACCEPT_SCORE   = 0.22   # trước 0.40

    accepted = any(
        r.get("ok")
        and r.get("inliers", 0) >= ACCEPT_INLIERS
        and r.get("score", 0.0) >= ACCEPT_SCORE
        for r in results
    )

    # Best để hiển thị/log như cũ
    best = max(results, key=lambda r: (r.get("inliers", 0), r.get("score", 0.0)), default={})


    return {
        "ok": True,
        "accepted": bool(accepted),
        "best": best,
        "all": results,
        "thresholds": {"inliers": ACCEPT_INLIERS, "score": ACCEPT_SCORE},
    }
@app.post("/identify_n")
async def identify_n(payload: dict):
    probe = payload.get("probe_minutiae", [])
    gallery = payload.get("gallery_list", [])
    profile_ids = payload.get("profile_ids", [])

    from identify.identify import identify_1N
    r = identify_1N(probe, gallery, profile_ids)
    return r
