// frontend/app.js

/********** Helpers **********/
const $ = (q)=>document.querySelector(q);
let currentTab = 'tab1';
// TAB2 state
let selectedProfile = null;
let lastBitmap2 = '';
let rawTemplates3 = [];

function now(){
  const d=new Date();
  return [d.getHours(),d.getMinutes(),d.getSeconds()].map(x=>String(x).padStart(2,'0')).join(':');
}
function addLog(msg, level='info', tabId=currentTab){
  const line=document.createElement('div');
  line.className='log-line ' + (level==='warn'?'log-warn':level==='err'?'log-err':'');
  line.dataset.tab=tabId;
  line.innerHTML=`<span class="log-time">[${now()}]</span> ${msg}`;
  const box=$('#log'); box.appendChild(line);
  const only=$('#chkCurrentTab')?.checked; if(only) filterLogs();
  box.scrollTop=box.scrollHeight;
}
function filterLogs(){
  const only=$('#chkCurrentTab')?.checked;
  document.querySelectorAll('#log .log-line').forEach(l=>{
    l.style.display=(!only || l.dataset.tab===currentTab)?'':'none';
  });
}
function renderSearchResults(items){
  const ul = $('#lstProfiles'); ul.innerHTML = '';
  if(!items.length){ $('#searchInfo').textContent = 'Không có kết quả'; return; }
  $('#searchInfo').textContent = `Tìm thấy ${items.length} hồ sơ`;
  items.forEach(it=>{
    const li = document.createElement('li');
    li.style.padding = '8px';
    li.style.border = '1px solid var(--bd)';
    li.style.borderRadius = '8px';
    li.style.marginBottom = '6px';
    li.style.cursor = 'pointer';
    li.innerHTML = `<strong>#${it.id}</strong> · ${it.full_name} · ${it.gender} · ${it.dob}`;
    li.addEventListener('click', ()=> selectProfile(it));
    ul.appendChild(li);
  });
}
async function searchProfiles(){
  const name = $('#txtSearchName').value.trim();
  setBusy('#busySearch', true);
  addLog(`Tìm hồ sơ theo tên: "${name}"`, 'info', 'tab2');
  const r = await fetchJsonSafe(`/api/profiles/search?name=${encodeURIComponent(name)}`);
  setBusy('#busySearch', false);
  if(!r.ok || !r.data?.ok){
    addLog('Search lỗi: '+(r.text || JSON.stringify(r.data)), 'err', 'tab2');
    return;
  }
  renderSearchResults(r.data.results || []);
}

async function selectProfile(p){
  selectedProfile = p;
  $('#chosenProfile').textContent = `#${p.id} · ${p.full_name} · ${p.gender} · ${p.dob}`;
  addLog(`Chọn hồ sơ #${p.id}`, 'info', 'tab2');

  const r = await fetchJsonSafe(`/api/profiles/${p.id}/raw-templates`);
  if(!r.ok || !r.data?.ok){
    addLog('Không lấy được templates_raw: '+(r.text || JSON.stringify(r.data)), 'err', 'tab2');
    $('#btnCap2').disabled = true;
    $('#btnVerify2').disabled = true;
    return;
  }
  rawTemplates3 = r.data.templates || [];
  const ok = rawTemplates3.length >= 1;
  $('#btnCap2').disabled = !ok;

  // Verify chỉ bật sau khi capture xong
  $('#btnVerify2').disabled = true;

  // reset ảnh/hiển thị
  lastBitmap2 = '';
  $('#preview2').src = '';
  $('#verifyOut').textContent = 'Chưa chạy';
}


async function capture2(){
  const q = Number($('#txtQ2').value);
  const t = Number($('#txtT2').value);
  setBusy('#busyCap2', true);
  $('#preview2').src = '';
  addLog(`Tab2 capture… (Q=${q},T=${t}s)`, 'info', 'tab2');

  const r = await fetchJsonSafe('/api/capture', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ Quality:q, TimeOut:t })
  });

  setBusy('#busyCap2', false);
  if(!r.ok){
    addLog(`Capture lỗi: ${r.text||('HTTP '+r.status)}`, 'err', 'tab2');
    $('#btnVerify2').disabled = true;
    return;
  }
  const ok = String(r.data?.ErrorCode ?? '1')==='0';
  if(ok && r.data?.BitmapData){
    lastBitmap2 = r.data.BitmapData;
    $('#preview2').src = 'data:image/bmp;base64,' + lastBitmap2;
    $('#btnVerify2').disabled = false;          // có ảnh rồi mới cho verify
    addLog('Capture OK (tab2).', 'info', 'tab2');
  }else{
    addLog('Capture thất bại (tab2): '+(r.data?.ErrorDescription||''), 'err', 'tab2');
    $('#btnVerify2').disabled = true;
  }
}
async function verify2(){
  if(!selectedProfile){ alert('Chưa chọn hồ sơ'); return; }
  if(!lastBitmap2){ alert('Chưa có ảnh sau Capture'); return; }
  setBusy('#busyV2', true);
  addLog(`Verify với hồ sơ #${selectedProfile.id}`, 'info', 'tab2');

  // Gửi trực tiếp ảnh base64, backend sẽ tự extract và so với 3 template
  const r = await fetchJsonSafe(`/api/profiles/${selectedProfile.id}/verify3`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ probe_bitmap_b64: lastBitmap2 })
  });

  setBusy('#busyV2', false);
  if(!r.ok || !r.data?.ok){
    addLog('Verify lỗi: '+(r.text || JSON.stringify(r.data)), 'err', 'tab2');
    $('#verifyOut').textContent = 'Lỗi verify';
    return;
  }

  // Chỉ hiển thị KẾT LUẬN, không liệt kê T1/T2/T3
  const { accepted } = r.data;
  $('#verifyOut').textContent = accepted ? 'KẾT LUẬN: KHỚP' : 'KẾT LUẬN: KHÔNG KHỚP';
  addLog(`Verify: ${accepted?'MATCH':'NO MATCH'}`, accepted?'info':'warn', 'tab2');
}


async function getTemplate2(){
  if(!lastBitmap2){ alert('Chưa có ảnh sau Capture'); return; }
  addLog('Tab2: extract template…', 'info', 'tab2');

  const r = await fetchJsonSafe('/api/get-template', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ bitmapBase64: lastBitmap2 })
  });

  if(!r.ok || !r.data?.ok){
    addLog('Get template tab2 lỗi: '+(r.text || JSON.stringify(r.data)), 'err', 'tab2');
    $('#btnVerify3').disabled = true; return;
  }
  probeJson2 = r.data.json_debug || null;
  $('#t2Info').textContent = `Probe minutiae: ${r.data.minutiae_count}`;
  $('#btnVerify3').disabled = !probeJson2;
}

async function verify3(){
  if(!selectedProfile){ alert('Chưa chọn hồ sơ'); return; }
  if(!probeJson2){ alert('Chưa có template của ảnh mới'); return; }
  setBusy('#busyV3', true);
  addLog(`Verify với 3 template của #${selectedProfile.id}`, 'info', 'tab2');

  const r = await fetchJsonSafe(`/api/profiles/${selectedProfile.id}/verify3`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ probe_json: probeJson2 })
  });

  setBusy('#busyV3', false);
  if(!r.ok || !r.data?.ok){
    addLog('Verify3 lỗi: '+(r.text || JSON.stringify(r.data)), 'err', 'tab2');
    $('#verifyOut').textContent = 'Lỗi verify';
    return;
  }
  const { results, best, accepted } = r.data;
  if (results.length === 1) {
      const x = results[0];
      $('#verifyOut').textContent =
          `score = ${(x.score*100).toFixed(1)}%\n` +
          `matches = ${x.matches}\n` +
          (accepted ? '→ KHỚP' : '→ KHÔNG KHỚP');
  } else {
      const lines = results.map(x =>
          `T${x.idx}: score=${(x.score*100).toFixed(1)}% (matches=${x.matches})`
      );
      lines.push(`→ Best: T${best.idx} = ${(best.score*100).toFixed(1)}% → ${accepted?'ACCEPT':'REJECT'}`);
      $('#verifyOut').textContent = lines.join('\n');
  }

  addLog(`Verify done: best T${best.idx} = ${(best.score*100).toFixed(1)}% → ${accepted?'ACCEPT':'REJECT'}`, accepted?'info':'warn', 'tab2');
}

function setBusy(sel,busy){ const el=$(sel); if(el) el.style.display=busy?'inline-flex':'none'; }
async function fetchJsonSafe(url, opts={}){
  try{
    const r=await fetch(url,opts);
    const text=await r.text();
    let data=null; if(text && text.trim().length){ try{ data=JSON.parse(text);}catch{} }
    const ok=(data && typeof data.ok==='boolean')?data.ok:(r.status>=200 && r.status<300);
    return { ok, status:r.status, data, text };
  }catch(e){ return { ok:false, status:0, text:String(e) }; }
}

/********** Tabs **********/
function setupTabs(){
  document.querySelectorAll('.tab-btn').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const id=btn.getAttribute('data-tab'); currentTab=id;
      document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
      btn.classList.add('active'); document.getElementById(id).classList.add('active');
      filterLogs();
    });
  });
  $('#chkCurrentTab').addEventListener('change', filterLogs);
  $('#btnClearLog').addEventListener('click', ()=>{ $('#log').innerHTML=''; });
}

/********** DOB smart **********/
function daysInMonth(y,m){
  if(m===2){ return ((y%400===0) || (y%4===0 && y%100!==0)) ? 29 : 28; }
  return [4,6,9,11].includes(m)?30:31;
}
function fillMonths(){
  const sel=$('#dobMonth'); sel.innerHTML='';
  for(let m=1;m<=12;m++){ const o=document.createElement('option'); o.value=m;o.textContent=m; sel.appendChild(o); }
}
function fillDays(){
  const y=Number($('#dobYear').value)||2000;
  const m=Number($('#dobMonth').value)||1;
  const max=daysInMonth(y,m);
  const daySel=$('#dobDay'); const cur=Number(daySel.value)||1;
  daySel.innerHTML='';
  for(let d=1; d<=max; d++){ const o=document.createElement('option'); o.value=d;o.textContent=d; daySel.appendChild(o); }
  daySel.value=String(Math.min(cur,max));
}

/********** State **********/
let pipelineSteps = [];
let pipelineIndex = 0;

let lastBitmapBase64='';
let collectedTemplates=[];

function updateTmplProgress(){
  $('#statusTmpl').textContent = `${collectedTemplates.length}/1`;
  $('#btnSaveRaw3').disabled = (collectedTemplates.length < 1);
}



/********** Actions **********/
async function connectAndInit(){
  const preferName=$('#txtPrefer').value.trim();
  const clientKey=$('#txtClientKey').value.trim();
  setBusy('#busyConnect',true);
  addLog('Bắt đầu Connect & Init','info','tab1');

  const r=await fetchJsonSafe('/api/connect-and-init',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ preferName, clientKey })
  });

  if(!r.ok){
    addLog(`Connect & Init lỗi: ${r.text||('HTTP '+r.status)}`,'err','tab1');
  }else{
    const ok = String(r.data?.init?.ErrorCode ?? '1')==='0';
    addLog(`Init ${ok?'thành công':'thất bại'} • Thiết bị: ${r.data?.chosen||'-'}`,'info','tab1');
  }
  setBusy('#busyConnect',false);
}

async function capture(){
  const btn = $('#btnCapture');
  const q = Number($('#txtQuality').value);
  const t = Number($('#txtTimeout').value);

  // chặn click đúp trong lúc chụp
  if (btn.disabled) return;
  btn.disabled = true;
  setBusy('#busyCapture', true);
  $('#preview').src = '';
  $('#btnGetTemplate').disabled = true;
  addLog(`Đang capture… (Q=${q},T=${t}s)`, 'info', 'tab1');

  try {
    const r = await fetchJsonSafe('/api/capture', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ Quality:q, TimeOut:t })
    });

    if (!r.ok) {
      addLog(`Capture lỗi: ${r.text || ('HTTP '+r.status)}`, 'err', 'tab1');
      $('#tmplInfo').textContent = 'Chưa có ảnh';
      return;
    }

    const ok = String(r.data?.ErrorCode ?? '1') === '0';
    if (ok && r.data?.BitmapData) {
      lastBitmapBase64 = r.data.BitmapData;
      $('#preview').src = 'data:image/bmp;base64,' + lastBitmapBase64;
      $('#btnGetTemplate').disabled = false;
      addLog('Capture thành công.', 'info', 'tab1');
    } else {
      addLog('Capture thất bại: ' + (r.data?.ErrorDescription || ''), 'err', 'tab1');
      $('#tmplInfo').textContent = 'Chưa có ảnh';
    }
  } catch (e) {
    addLog('Capture exception: ' + String(e), 'err', 'tab1');
    $('#tmplInfo').textContent = 'Chưa có ảnh';
  } finally {
    // BẮT BUỘC chạy – dừng spinner & mở lại nút
    setBusy('#busyCapture', false);
    btn.disabled = false;
  }
}


async function getTemplate(){
  if(!lastBitmapBase64){ alert('Chưa có ảnh sau Capture'); return; }
  addLog('Đang extract template…','info','tab1');

  const r=await fetchJsonSafe('/api/get-template',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ bitmapBase64: lastBitmapBase64 })
  });

  if(!r.ok || !r.data?.ok){
    addLog('Get template lỗi: '+(r.text || JSON.stringify(r.data)),'err','tab1');
    return;
  }
const json_debug = r.data.json_debug || {};
collectedTemplates.push(json_debug);
lastDebugStages1 = json_debug;   // ✨ lưu lại

pipelineSteps = [];

const dbg = json_debug;

// Gom tất cả bước từ Python
for (const [key, value] of Object.entries(dbg)) {
  if (key.endsWith("_png_b64")) {
    pipelineSteps.push({
      label: key.replace("_png_b64",""),
      b64: value
    });
  }
}

// Nếu có bước → đặt ảnh cho thumbnail
if (pipelineSteps.length > 0) {
  $('#pipelineThumbImg').src =
      'data:image/png;base64,' + pipelineSteps[0].b64;
}


updateTmplProgress();
addLog(
  `Get template OK (minutiae=${r.data.minutiae_count}). Đã có ${collectedTemplates.length}/1.`,
  'info','tab1'
);


$('#btnGetTemplate').disabled = true;
$('#tmplInfo').textContent = 'Đã lấy template cho ảnh này';

}

function buildDobISO(){
  const y=Number($('#dobYear').value);
  const m=Number($('#dobMonth').value);
  const d=Number($('#dobDay').value);
  return `${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
}

async function saveRaw3(){
  const full_name = $('#fullName').value.trim();
  const gender    = $('#gender').value || 'other';   // DB có CHECK male/female/other
  const dob       = buildDobISO();                   // ghép từ #dobYear/#dobMonth/#dobDay

  if (!full_name){
    addLog('Vui lòng nhập Họ tên trước khi lưu.', 'warn', 'tab1');
    return;
  }
  if (collectedTemplates.length < 1){
    addLog('Chưa có template để lưu hồ sơ.', 'warn', 'tab1');
    return;
  }


  setBusy('#busySave', true);
  addLog('Đang lưu hồ sơ với 3 template raw...', 'info', 'tab1');

  const r = await fetchJsonSafe('/api/profiles/save-raw3', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      full_name, gender, dob,
      templates_json: collectedTemplates
    })
  });

  setBusy('#busySave', false);
  if (!r.ok || !r.data?.ok){
    addLog('Lưu hồ sơ lỗi: ' + (r.text || r.data?.message || 'unknown'), 'error', 'tab1');
    return;
  }

  addLog(`Đã lưu hồ sơ #${r.data.profile_id}`, 'success', 'tab1');
  collectedTemplates = [];
  updateTmplProgress();  // sẽ tắt nút lưu về disabled (0/3)
}

/********** TAB 3 – Identify 1:N **********/
let lastBitmap3 = '';

async function capture3() {
  const q = Number($('#txtQ3').value);
  const t = Number($('#txtT3').value);

  setBusy('#busyCap3', true);
  $('#preview3').src = '';
  $('#btnIdentify3').disabled = true;

  addLog(`Tab3 capture… (Q=${q},T=${t}s)`, 'info', 'tab3');

  const r = await fetchJsonSafe('/api/capture', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ Quality:q, TimeOut:t })
  });

  setBusy('#busyCap3', false);

  if (!r.ok) {
    addLog(`Capture lỗi: ${r.text || ('HTTP '+r.status)}`, 'err', 'tab3');
    return;
  }

  const ok = String(r.data?.ErrorCode ?? '1') === '0';
  if (ok && r.data?.BitmapData) {
    lastBitmap3 = r.data.BitmapData;
    $('#preview3').src = 'data:image/bmp;base64,' + lastBitmap3;
    $('#btnIdentify3').disabled = false;
    addLog('Capture OK (tab3).', 'info', 'tab3');
  } else {
    addLog('Capture thất bại (tab3): ' + (r.data?.ErrorDescription || ''), 'err', 'tab3');
  }
}

async function identify3() {
  if (!lastBitmap3) {
    alert('Chưa có ảnh sau Capture');
    return;
  }

  setBusy('#busyId3', true);
  $('#identifyOut').textContent = 'Đang identify…';
  $('#identifyInfo').textContent = '–';
  addLog('Đang identify 1:N…', 'info', 'tab3');

  // 1) Extract template từ bitmap (như tab1)
  const tmp = await fetchJsonSafe('/api/get-template', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bitmapBase64: lastBitmap3 })
  });

  if (!tmp.ok || !tmp.data?.ok) {
    setBusy('#busyId3', false);
    addLog('Lỗi extract: ' + (tmp.text || JSON.stringify(tmp.data)), 'err', 'tab3');
    $('#identifyOut').textContent = 'Lỗi extract template.';
    return;
  }

  const count = tmp.data.minutiae_count || 0;
  if (count < 10) {   // tuỳ bạn, 10–15
    setBusy('#busyId3', false);
    addLog(`Ảnh quá kém (minutiae_count=${count}).`, 'warn', 'tab3');
    $('#identifyOut').textContent = `Ảnh quá kém (minutiae=${count}).`;
    return;
  }

  const probeMinutiae = tmp.data.json_debug?.minutiae || [];
  if (!probeMinutiae.length) {
    setBusy('#busyId3', false);
    addLog('Không có minutiae trong json_debug.', 'err', 'tab3');
    $('#identifyOut').textContent = 'Thiếu dữ liệu template.';
    return;
  }

  // 2) Gọi identify 1:N
  const iden = await fetchJsonSafe('/api/identify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ probe_minutiae: probeMinutiae })
  });

  setBusy('#busyId3', false);

  if (!iden.ok || !iden.data?.ok) {
    addLog('Identify lỗi: ' + (iden.text || JSON.stringify(iden.data)), 'err', 'tab3');
    $('#identifyOut').textContent = 'Lỗi identify.';
    return;
  }

  // Không tìm thấy
  if (!iden.data.result) {
    addLog('❌ Không tìm thấy hồ sơ phù hợp', 'warn', 'tab3');
    $('#identifyOut').textContent = '❌ Không tìm thấy hồ sơ phù hợp';
    $('#identifyInfo').textContent = '–';
    return;
  }

  // Có hồ sơ
  const p = iden.data.result;
  addLog(`✔ Tìm thấy hồ sơ #${p.id}`, 'info', 'tab3');

  $('#identifyOut').textContent = '✔ Tìm thấy hồ sơ phù hợp';
  $('#identifyInfo').textContent =
    `ID: ${p.id}
Tên: ${p.full_name}
Giới tính: ${p.gender}
Năm sinh: ${p.dob}
`;
}




/********** Init **********/
document.addEventListener('DOMContentLoaded', ()=>{
  setupTabs();

  // DOB init
  fillMonths();
  $('#dobMonth').value='1';
  fillDays();
  $('#dobMonth').addEventListener('change', fillDays);
  $('#dobYear').addEventListener('input', fillDays);

  // Events
  $('#btnConnectInit').addEventListener('click', connectAndInit);
  $('#btnCapture').addEventListener('click', capture);
  $('#btnGetTemplate').addEventListener('click', getTemplate);
  $('#btnSaveRaw3').addEventListener('click', saveRaw3);

  // TAB2 events
  $('#btnSearch').addEventListener('click', searchProfiles);
  $('#btnCap2').addEventListener('click', capture2);
  $('#btnVerify2').addEventListener('click', verify2);

  updateTmplProgress();

// mở popup
$('#pipelineThumb').addEventListener('click',()=>{
  if (pipelineSteps.length === 0) return alert("Chưa có pipeline.");
  pipelineIndex = 0;
  showPipelineStep();
  $('#pipelineModal').classList.remove('hidden');
});

// đóng popup
$('#pipelineClose').addEventListener('click',()=>{
  $('#pipelineModal').classList.add('hidden');
});

// chuyển trái phải
$('#pipelinePrev').addEventListener('click',()=>{
  if (pipelineIndex > 0) pipelineIndex--;
  showPipelineStep();
});
$('#pipelineNext').addEventListener('click',()=>{
  if (pipelineIndex < pipelineSteps.length-1) pipelineIndex++;
  showPipelineStep();
});
// TAB3 events
$('#btnCap3').addEventListener('click', capture3);
$('#btnIdentify3').addEventListener('click', identify3);

function showPipelineStep(){
  const st = pipelineSteps[pipelineIndex];
  $('#pipelineImage').src = 'data:image/png;base64,' + st.b64;
  $('#pipelineStepLabel').textContent =
      `${st.label} (${pipelineIndex+1}/${pipelineSteps.length})`;
}

});
