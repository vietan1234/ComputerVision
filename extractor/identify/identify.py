from typing import List, Dict, Any
from verify.matcher import match_minutiae_ransac_consistency

def identify_1N(
    probe_minutiae: List[Dict[str, Any]],
    gallery_list: List[List[Dict[str, Any]]],
    profile_ids: List[int],
    score_thr: float = 0.25,    # mạnh hơn
    inlier_thr: int = 12,       # theo chuẩn AFIS (tối thiểu 14)
    top_k: int = 1,
) -> Dict[str, Any]:

    if not probe_minutiae:
        return {"ok": False, "error": "probe_empty"}

    ranking = []

    for pid, gallery in zip(profile_ids, gallery_list):
        if not gallery:
            continue

        r = match_minutiae_ransac_consistency(
            probe_minutiae,
            gallery,
            debug=False
        )

        score = float(r.get("score", 0))
        inl   = int(r.get("inliers", 0))

        # lấy angle chính xác theo key có tồn tại
        angle = abs(
            r.get("angle",
            r.get("theta",
            r.get("rotation", 0)))
        )

        # ❗ Loại nếu xoay quá 40 độ (ngón khác)
        if angle > 40:
            continue

        ranking.append({
            "id": pid,
            "score": score,
            "inliers": inl,
            "angle": angle
        })

    if not ranking:
        return {"ok": True, "best": None, "ranking": []}

    # sort by score mạnh nhất
    ranking.sort(key=lambda x: (x["score"], x["inliers"]), reverse=True)

    best = ranking[0]
    second = ranking[1] if len(ranking) > 1 else None

    # ❗ threshold chính
    if best["score"] < score_thr or best["inliers"] < inlier_thr:
        return {"ok": True, "best": None, "ranking": ranking}

    # ❗ margin rule – chống nhận nhầm
    MARGIN = 0.07   # chênh lệch tối thiểu
    if second and (best["score"] - second["score"] < MARGIN):
        return {"ok": True, "best": None, "ranking": ranking}

    return {
        "ok": True,
        "best": best,
        "ranking": ranking[:top_k]
    }
