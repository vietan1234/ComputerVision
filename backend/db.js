// backend/db.js
// SQLite: lưu profiles + templates_raw (3 template JSON cho mỗi hồ sơ)

const path = require('path');
const Database = require('better-sqlite3');

const DB_PATH = path.join(__dirname, 'fingerprints.db');
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

// --- Schema ---
db.exec(`
CREATE TABLE IF NOT EXISTS profiles (
  id          INTEGER PRIMARY KEY,
  full_name   TEXT    NOT NULL,
  gender      TEXT    NOT NULL CHECK (gender IN ('male','female','other')),
  dob         TEXT    NOT NULL,  -- 'YYYY-MM-DD'
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(full_name);
CREATE INDEX IF NOT EXISTS idx_profiles_dob  ON profiles(dob);

CREATE TABLE IF NOT EXISTS templates_raw (
  profile_id  INTEGER NOT NULL,
  idx         INTEGER NOT NULL CHECK (idx IN (1,2,3)),
  json        TEXT    NOT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (profile_id, idx),
  FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);
`);

// --- Prepared statements ---
const stmts = {
  insertProfile: db.prepare(`
    INSERT INTO profiles (full_name, gender, dob)
    VALUES (@full_name, @gender, @dob)
  `),
  getProfileById: db.prepare(`SELECT * FROM profiles WHERE id = ?`),
  searchByName: db.prepare(`
    SELECT id, full_name, gender, dob, created_at
    FROM profiles
    WHERE full_name LIKE ?
    ORDER BY created_at DESC
    LIMIT 50
  `),

  upsertTemplate: db.prepare(`
    INSERT INTO templates_raw (profile_id, idx, json)
    VALUES (@profile_id, @idx, @json)
    ON CONFLICT(profile_id, idx) DO UPDATE SET
      json=excluded.json,
      created_at=CURRENT_TIMESTAMP
  `),
  selectTemplatesByProfile: db.prepare(`
    SELECT idx, json FROM templates_raw
    WHERE profile_id = ?
    ORDER BY idx ASC
  `),
};

// --- APIs dùng ở server.js ---
function createProfile({ full_name, gender, dob }) {
  const info = stmts.insertProfile.run({ full_name, gender, dob });
  return info.lastInsertRowid;
}
function getProfile(id) {
  return stmts.getProfileById.get(id);
}
function searchProfilesByName(q) {
  const like = `%${q}%`;
  return stmts.searchByName.all(like);
}


function saveRawTemplates(profileId, arr) {
  if (!Array.isArray(arr) || arr.length < 1 || arr.length > 3) {
    throw new Error('saveRawTemplates: cần mảng 1..3 template');
  }

  const tx = db.transaction(() => {
    arr.forEach((tmpl, i) => {
      stmts.upsertTemplate.run({
        profile_id: profileId,
        idx: i + 1,                     // vẫn dùng idx 1..3 như schema
        json: JSON.stringify(tmpl),
      });
    });
  });
  tx();
}


// Đọc 3 template JSON theo profileId → trả array object (có thể <3 nếu thiếu)
function loadRawTemplates(profileId) {
  const rows = stmts.selectTemplatesByProfile.all(profileId);
  return rows.map(r => {
    try { return JSON.parse(r.json); }
    catch { return null; }
  }).filter(Boolean);
}

// Lấy tất cả hồ sơ (dùng cho identify 1:N)
function loadAllProfiles() {
  return db.prepare(`
    SELECT id, full_name, gender, dob, created_at
    FROM profiles
    ORDER BY created_at DESC
  `).all();
}

module.exports = {
  db,
  createProfile,
  getProfile,
  searchProfilesByName,
  saveRawTemplates,
  loadRawTemplates,
  loadAllProfiles,
};

