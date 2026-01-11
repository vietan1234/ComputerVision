// backend/server.js
// Chạy:  cd backend && npm i && npm start   → http://localhost:8090
// Yêu cầu extractor Python chạy ở: http://127.0.0.1:5055

require('dotenv').config(); // nếu bạn dùng .env (không bắt buộc)

const express = require('express');
const axios = require('axios');
const cors = require('cors');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');

const {
  createProfile,
  searchProfilesByName,
  saveRawTemplates,
  loadRawTemplates,
  loadAllProfiles,
} = require('./db');
const { db } = require('./db');

const app = express();
const PORT = process.env.PORT || 8090;

// SDK MorFinAuth (Init/Capture)
const MORFIN_BASE = process.env.MORFIN_BASE || 'http://localhost:8030/morfinauth/';
// Python extractor (tự viết)
const EXTRACTOR_BASE = process.env.EXTRACTOR_BASE || 'http://127.0.0.1:5055';

// Cho phép gọi từ Vite 5173 khi dev (nếu bạn dùng Vite)
app.use(cors({ origin: ['http://localhost:5173', 'http://127.0.0.1:5173'], credentials: false }));
app.use(express.json({ limit: '50mb' })); // nhận ảnh base64

// Phục vụ frontend tĩnh khi mở 8090 trực tiếp (không qua Vite)
const FRONTEND_DIR = path.join(__dirname, '..', 'frontend');
app.use(express.static(FRONTEND_DIR));
app.get('/', (_req, res) => res.sendFile(path.join(FRONTEND_DIR, 'index.html')));

// ===== Helpers =====

async function callMorfin(method, data = null, sendBody = true, timeoutMs = 0) {
  const url = MORFIN_BASE + method;
  const r = await axios({
    method: 'post',
    url,
    headers: { 'Content-Type': 'application/json' },
    data: sendBody ? (data || {}) : undefined,
    timeout: timeoutMs, // 0 = không giới hạn
    validateStatus: () => true
  });
  return r.data; // SDK body (giữ nguyên ErrorCode/Description)
}

async function callExtractor(pathname, payload, timeoutMs = 60000) {
  const url = EXTRACTOR_BASE + pathname;
  const r = await axios.post(url, payload, {
    headers: { 'Content-Type': 'application/json' },
    timeout: timeoutMs,
    validateStatus: () => true
  });
  return r.data; // { ok, ... }
}

// ===== State init flag =====
let INIT_OK = false;
function requireInited(_req, res, next) {
  if (!INIT_OK) {
    return res.status(400).json({
      ok: false,
      ErrorCode: -3,
      ErrorDescription: 'Thiết bị chưa khởi tạo. Vui lòng bấm "Connect & Init" trước.'
    });
  }
  next();
}

// ===== API: CONNECT & INIT =====
app.post('/api/connect-and-init', async (req, res) => {
  try {
    const preferName = (req.body?.preferName || '').trim();
    const clientKey = (req.body?.clientKey || '').trim();

    const listData = await callMorfin('connecteddevicelist', null, false, 15000);
    const desc = listData?.ErrorDescription || '';
    const names = (desc.split(':')[1] || '').split(',').map(s => s.trim()).filter(Boolean);

    if (!names.length) {
      INIT_OK = false;
      return res.json({
        ok: true, devices: [], chosen: null,
        init: { ErrorCode: 1, ErrorDescription: 'Không tìm thấy thiết bị để init' }
      });
    }

    const chosen = (preferName && names.includes(preferName)) ? preferName : names[0];
    const initPayload = { ConnectedDvc: chosen, ClientKey: clientKey };
    const initData = await callMorfin('initdevice', initPayload, true, 30000);
    INIT_OK = String(initData?.ErrorCode ?? '1') === '0';

    return res.json({ ok: true, devices: names, chosen, init: initData });
  } catch (e) {
    INIT_OK = false;
    return res.status(500).json({ ok: false, message: String(e) });
  }
});

// ===== API: CAPTURE (SDK) =====
app.post('/api/capture', requireInited, async (req, res) => {
  try {
    const q = Number(req.body?.Quality);
    const t = Number(req.body?.TimeOut);
    if (!Number.isFinite(q) || q < 1 || q > 100) {
      return res.status(400).json({ ok: false, ErrorCode: 2, ErrorDescription: 'Quality phải trong [1..100]' });
    }
    if (!Number.isFinite(t) || t < 0) {
      return res.status(400).json({ ok: false, ErrorCode: 3, ErrorDescription: 'TimeOut không hợp lệ (>=0)' });
    }
    const effTimeoutSec = Math.floor(t);
    const axiosTimeoutMs = effTimeoutSec > 0 ? effTimeoutSec * 1000 : 0;
    const capData = await callMorfin('capture', { Quality: q, TimeOut: effTimeoutSec }, true, axiosTimeoutMs);
    return res.json({ ok: true, ...capData });
  } catch (e) {
    return res.status(500).json({ ok: false, message: 'Lỗi capture', error: String(e) });
  }
});

// ===== API: GET-TEMPLATE (gọi Python extractor), input là ảnh base64 BMP =====
app.post('/api/get-template', async (req, res) => {
  try {
    const { bitmapBase64 } = req.body || {};
    if (!bitmapBase64 || typeof bitmapBase64 !== 'string') {
      return res.status(400).json({ ok: false, message: 'bitmapBase64 thiếu hoặc sai' });
    }
    // THÊM debug: 1 để Python trả cả ảnh từng bước
    const r = await callExtractor('/extract', {
      image_b64: bitmapBase64,
      debug: 1
    });
    return res.json(r);
  } catch (e) {
    return res.status(500).json({ ok: false, message: 'Lỗi get-template', error: String(e) });
  }
});


// NEW: Lưu hồ sơ với 1–3 template raw + enrolled image
app.post('/api/profiles/save-raw3', async (req, res) => {
  try {
    const { full_name, gender, dob, templates_json, enrolled_image } = req.body || {};
    if (!full_name || !Array.isArray(templates_json) || templates_json.length < 1 || templates_json.length > 3) {
      return res.status(400).json({ ok: false, message: 'Thiếu full_name hoặc templates_json không nằm trong khoảng 1..3' });
    }

    // 1) Tạo profile
    const profileId = createProfile({ full_name, gender: gender || 'other', dob: dob || '1970-01-01' });

    // 2) Chuẩn bị templates với enrolled image (nếu có)
    const templatesWithImage = templates_json.map((tmpl, idx) => {
      // enrolled_image được gửi cùng, áp dụng cho template đầu tiên
      if (idx === 0 && enrolled_image) {
        return {
          template: tmpl,
          image_b64: enrolled_image.image_b64 || null,
          image_mime: enrolled_image.image_mime || 'image/bmp',
          captured_at: enrolled_image.captured_at || new Date().toISOString(),
        };
      }
      return { template: tmpl };
    });

    // 3) Lưu templates vào DB
    saveRawTemplates(profileId, templatesWithImage);

    return res.status(200).json({ ok: true, profile_id: profileId });
  } catch (e) {
    return res.status(500).json({ ok: false, message: 'Lỗi save-raw3 (server)', error: String(e) });
  }
});

// ==================== DELETE PROFILE ====================
app.post('/api/delete-person', async (req, res) => {
  try {
    const { person_id } = req.body;
    if (!person_id) {
      return res.json({ ok: false, message: "Thiếu person_id" });
    }

    // Xóa trong bảng profiles
    db.prepare("DELETE FROM profiles WHERE id = ?").run(person_id);

    // Xóa template liên quan (tùy bảng bạn dùng)
    db.prepare("DELETE FROM templates_fused WHERE person_id = ?").run(person_id);

    return res.json({ ok: true, message: "Đã xóa hồ sơ" });
  } catch (err) {
    return res.json({ ok: false, message: "Lỗi khi xóa hồ sơ", error: err.toString() });
  }
});


// GET /api/profiles/search?name=...
app.get('/api/profiles/search', (req, res) => {
  try {
    const q = String(req.query.name || '').trim();
    if (!q) return res.json({ ok: true, results: [] });
    const rows = searchProfilesByName(q);
    return res.json({ ok: true, results: rows });
  } catch (e) {
    return res.status(500).json({ ok: false, message: 'Lỗi search', error: String(e) });
  }
});

// ===== API: GET 3 RAW JSON BY PROFILE (with enrolled images) =====
app.get('/api/profiles/:id/raw-templates', (req, res) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isFinite(id)) return res.status(400).json({ ok: false, message: 'id không hợp lệ' });

    // Include images for display in verification tab
    const arr = loadRawTemplates(id, true); // array length 0..3
    const templates = arr.map((tmpl, i) => {
      const result = { idx: i + 1, tmpl_json: tmpl };
      // Extract enrolled image if present
      if (tmpl._enrolled_image) {
        result.enrolled_image = tmpl._enrolled_image;
        delete tmpl._enrolled_image; // Don't pollute template data
      }
      return result;
    });
    return res.json({ ok: true, count: templates.length, templates });
  } catch (e) {
    return res.status(500).json({ ok: false, message: 'Lỗi get raw', error: String(e) });
  }
});


app.post('/api/profiles/:id/verify3', async (req, res) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isFinite(id)) {
      return res.status(400).json({ ok: false, message: 'id không hợp lệ' });
    }

    const arr = loadRawTemplates(id); // array object (1..3)
    if (arr.length < 1) {
      return res.status(404).json({ ok: false, message: 'Hồ sơ chưa có template nào' });
    }
    const templates_json = arr;

    // 2) Chuẩn bị probe
    let { probe_json, probe_bitmap_b64 } = req.body || {};
    if (!probe_json && !probe_bitmap_b64) {
      return res.status(400).json({ ok: false, message: 'Thiếu probe_json hoặc probe_bitmap_b64' });
    }

    // Nếu chỉ gửi ảnh, tự extract trước
    if (!probe_json && probe_bitmap_b64) {
      const ext = await callExtractor('/extract', { image_b64: probe_bitmap_b64 }, 15000);
      if (!ext?.ok || !ext?.json_debug) {
        return res.status(500).json({ ok: false, message: 'Extract thất bại trước verify', detail: ext });
      }
      probe_json = ext.json_debug;
    }

    const probe_minutiae = probe_json?.minutiae || [];

    const payload = {
      probe_minutiae,
      gallery_minutiae_list: templates_json.map(t => (t.minutiae || [])),
    };

    const r = await callExtractor('/verify3', payload, 15000);
    return res.status(200).json(r);
  } catch (e) {
    return res.status(500).json({ ok: false, message: 'Lỗi verify3 (server)', error: String(e) });
  }
});


// ===============================
//      API: Identify (1:N)
// ===============================
app.post('/api/identify', async (req, res) => {
  try {
    // 1. Nhận probe từ FE
    const probe = req.body?.probe_minutiae || [];
    if (!probe.length) {
      return res.json({ ok: false, message: 'probe_minutiae trống' });
    }

    // 2. Lấy tất cả hồ sơ
    const profiles = db.prepare("SELECT * FROM profiles").all();

    const gallery_list = [];
    const profile_ids = [];

    // 3. Lấy 1..N template của mỗi hồ sơ
    for (const p of profiles) {
      const arr = loadRawTemplates(p.id);   // [{minutiae}, {minutiae}, ...]
      if (!arr.length) continue;

      for (const t of arr) {
        gallery_list.push(t.minutiae || []);
        profile_ids.push(p.id);
      }
    }

    // 4. Gọi extractor identify_n
    const payload = {
      probe_minutiae: probe,
      gallery_list,
      profile_ids
    };

    const r = await callExtractor('/identify_n', payload, 15000);

    // 5. Không tìm thấy
    if (!r.ok || !r.best) {
      return res.json({ ok: true, result: null });
    }

    // 6. Trả hồ sơ tốt nhất
    const bestId = r.best.id;
    const prof = profiles.find(x => x.id === bestId);

    return res.json({
      ok: true,
      result: prof,
      score: r.best.score,
      inliers: r.best.inliers
    });

  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e) });
  }
});



app.listen(PORT, () => {
  console.log(`Backend running at http://localhost:${PORT}`);
});