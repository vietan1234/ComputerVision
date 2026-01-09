# extractor/verify/fuse.py
from typing import List, Dict, Tuple
import numpy as np
import json, base64, math
from collections import Counter, defaultdict

def _circ_mean(angles_deg: List[float]) -> float:
    if not angles_deg:
        return 0.0
    ang = np.deg2rad(np.array(angles_deg, dtype=float))
    s = np.sin(ang).mean()
    c = np.cos(ang).mean()
    return float((np.rad2deg(math.atan2(s, c)) + 360.0) % 360.0)

def _safe_num(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return float(default)

def fuse_templates(templates: List[Dict], debug: bool=False) -> Tuple[Dict, Dict]:
    grid_size = 5.0  # Tăng cho 500 DPI (~0.25mm)
    buckets: Dict[Tuple[int,int], List[Dict]] = defaultdict(list)
    counts_per_in = []

    for t in templates:
        mins = t.get("minutiae", []) or []
        counts_per_in.append(len(mins))
        for m in mins:
            x = _safe_num(m.get("x", 0))
            y = _safe_num(m.get("y", 0))
            ang = _safe_num(m.get("angle", 0.0))
            typ = m.get("type", "ending") or "ending"
            qual = _safe_num(m.get("quality", 1.0))
            key = (int(round(x / grid_size)), int(round(y / grid_size)))
            buckets[key].append({"x": x, "y": y, "angle": ang, "type": str(typ), "quality": qual})

    fused_list = []
    for pts in buckets.values():
        if len(pts) < 2: continue  # Tối ưu: Chỉ fuse nếu xuất hiện >=2 templates (loại noise)
        xs = [p["x"] for p in pts]
        ys = [p["y"] for p in pts]
        angs = [p["angle"] for p in pts]
        types = [p["type"] for p in pts]
        quals = [p["quality"] for p in pts]
        fx = float(np.mean(xs))
        fy = float(np.mean(ys))
        fa = _circ_mean(angs)
        t_major = Counter(types).most_common(1)[0][0]
        q_avg = float(np.mean(quals))
        if q_avg < 0.35: continue  # Loại low quality fused
        fused_list.append({
            "x": int(round(fx)),
            "y": int(round(fy)),
            "angle": float(fa),
            "type": t_major,
            "quality": q_avg
        })

    fused_json = {"minutiae": fused_list}


    bin_bytes = json.dumps(fused_json, separators=(",", ":")).encode("utf-8")
    b64 = base64.b64encode(bin_bytes).decode("utf-8")

    dbg = {
        "input_counts": counts_per_in,
        "fused_count": len(fused_list),
        "grid_size": grid_size
    }

    fused_out = {
        "template_bin_b64": b64,
        "tmpl_format": "ISO19794-2",
        "algo_version": "v1.0-fuse",
        "dpi": 500,  # Cập nhật DPI
        "fused": fused_json
    }
    return fused_out, (dbg if debug else {})