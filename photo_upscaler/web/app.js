"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const api = async (path, body) => {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
};

// ---------------------------------------------------------------- settings
const DEFAULTS = { model: "", mode: "scale", scale: 2, longEdge: 6000, printSize: 60, unit: "cm", dpi: 300,
                   strength: 100, fmt: "same", quality: 95, outDir: "", skipBig: true };
let S = { ...DEFAULTS };
try { Object.assign(S, JSON.parse(localStorage.getItem("settings") || "{}")); } catch {}
const persist = () => { try { localStorage.setItem("settings", JSON.stringify(S)); } catch {} };

function segment(id, key, attr, cast = (v) => v) {
  const seg = $(id);
  const paint = () => seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", String(cast(b.dataset[attr])) === String(S[key])));
  seg.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    S[key] = cast(b.dataset[attr]); persist(); paint(); refreshSettings();
  });
  paint();
}
segment("#modeSeg", "mode", "mode");
segment("#scaleSeg", "scale", "scale", Number);
segment("#unitSeg", "unit", "unit");
segment("#dpiSeg", "dpi", "dpi", Number);

const bindInput = (id, key, ev = "input", cast = Number) => {
  const el = $(id);
  if (el.type === "checkbox") el.checked = S[key]; else el.value = S[key];
  el.addEventListener(ev, () => { S[key] = el.type === "checkbox" ? el.checked : cast(el.value); persist(); refreshSettings(); });
};
bindInput("#longEdge", "longEdge");
bindInput("#printSize", "printSize");
bindInput("#strength", "strength");
bindInput("#quality", "quality");
bindInput("#fmt", "fmt", "change", String);
bindInput("#skipBig", "skipBig", "change");

function printLongEdge() {
  const inches = S.unit === "cm" ? S.printSize / 2.54 : S.printSize;
  return Math.round(inches * S.dpi);
}

function refreshSettings() {
  $$(".mode").forEach((m) => (m.hidden = m.dataset.for !== S.mode));
  $("#strengthVal").textContent = S.strength + "%";
  $("#qualityVal").textContent = S.quality;
  $("#qualityRow").hidden = !(S.fmt === "jpeg" || S.fmt === "same");
  $("#outDir").textContent = S.outDir || "An “Upscaled” folder next to each original";
  $("#outDir").title = S.outDir;
  $("#outDir").classList.toggle("rtl", !!S.outDir);
  $("#resetOut").hidden = !S.outDir;
  $$(".model").forEach((el) => el.classList.toggle("on", el.dataset.id === S.model));
  // size hint, using the selected or first photo as an example
  const j = jobs.get(selected) || [...jobs.values()].find((x) => x.in_size);
  let hint = "";
  if (S.mode === "print") hint = `${S.printSize} ${S.unit} at ${S.dpi} dpi = ${printLongEdge().toLocaleString()} px on the long side. `;
  if (j && j.in_size) {
    const [w, h] = j.in_size;
    const f = S.mode === "scale" ? S.scale : (S.mode === "print" ? printLongEdge() : S.longEdge) / Math.max(w, h);
    const tw = Math.round(w * f), th = Math.round(h * f);
    hint += `e.g. ${w}×${h} → ${tw}×${th} (${(tw * th / 1e6).toFixed(0)} MP, ${f.toFixed(2)}×)`;
    if (f > 4.001) hint += " — more than 4×, too big";
    else if (f <= 1) hint += " — already big enough";
  }
  $("#sizeHint").textContent = hint;
}

function payload() {
  const mode = S.mode === "scale" ? "scale" : "long_edge";
  return { model: S.model, mode, scale: S.scale,
           long_edge: S.mode === "print" ? printLongEdge() : S.longEdge,
           dpi: S.mode === "print" ? S.dpi : 0,
           strength: S.strength / 100, fmt: S.fmt, jpeg_quality: S.quality, out_dir: S.outDir, skip_if_big: S.skipBig };
}

// ---------------------------------------------------------------- models
async function loadModels() {
  const list = await api("/api/models");
  const box = $("#models");
  if (!list.length) { box.innerHTML = '<p class="error">No AI models found. Run scripts/setup_engine.py.</p>'; return; }
  if (!list.some((m) => m.id === S.model)) S.model = list[0].id;
  box.innerHTML = list.map((m) => `
    <div class="model" data-id="${m.id}">
      <div class="t"><span>${m.label}</span><span class="sp">${m.speed}</span></div>
      <div class="d">${m.description}</div>
    </div>`).join("");
  box.addEventListener("click", (e) => {
    const el = e.target.closest(".model"); if (!el) return;
    S.model = el.dataset.id; persist(); refreshSettings();
  });
  refreshSettings();
}

// ---------------------------------------------------------------- adding photos
const hasBridge = () => window.pywebview && window.pywebview.api;
async function addPaths(paths) { if (paths && paths.length) { await api("/api/add", { paths }); poll(); } }
$("#addFiles").onclick = async () => hasBridge() ? addPaths(await window.pywebview.api.pick_files())
  : showError("Open the app with “Start Photo Upscaler” to use the file picker.");
$("#addFolder").onclick = async () => hasBridge() && addPaths(await window.pywebview.api.pick_folder());
$("#pickOut").onclick = async () => {
  if (!hasBridge()) return;
  const d = await window.pywebview.api.pick_output();
  if (d) { S.outDir = d; persist(); refreshSettings(); }
};
$("#resetOut").onclick = () => { S.outDir = ""; persist(); refreshSettings(); };

// Drops are received by Python (which gets the real file paths); here we only show the overlay.
let dragDepth = 0;
window.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; $("#dropCover").hidden = false; });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("#dropCover").hidden = true; } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => { e.preventDefault(); dragDepth = 0; $("#dropCover").hidden = true; setTimeout(poll, 300); });

// ---------------------------------------------------------------- queue
const jobs = new Map();
let selected = null, running = false;
const fmtTime = (s) => s == null ? "" : s < 60 ? `${Math.ceil(s)}s` : s < 3600 ? `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s` : `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
const dims = (s) => s ? `${s[0]}×${s[1]}` : "?";

function jobEl(j) {
  const li = document.createElement("li");
  li.className = "job"; li.dataset.id = j.id;
  li.innerHTML = `<img src="/api/thumb/${j.id}" alt=""><div style="min-width:0"><div class="name"></div>
    <div class="meta"></div><div class="msg"></div><div class="bar"><i></i></div></div><button class="x" title="Remove">×</button>`;
  li.querySelector(".name").textContent = j.name;
  li.querySelector(".name").title = j.path;
  li.querySelector(".x").onclick = async (e) => { e.stopPropagation(); await api(`/api/remove/${j.id}`, {}); poll(); };
  li.onclick = () => { const cur = jobs.get(j.id); if (cur && cur.status === "done") select(j.id); };
  return li;
}

function renderJobs(list) {
  const ul = $("#jobs"); const seen = new Set();
  for (const j of list) {
    seen.add(j.id);
    let li = ul.querySelector(`[data-id="${j.id}"]`);
    if (!li) { li = jobEl(j); ul.appendChild(li); }
    li.className = `job st-${j.status}` + (j.status === "done" ? " done" : "") + (j.id === selected ? " sel" : "");
    li.querySelector(".meta").textContent = j.out_size ? `${dims(j.in_size)} → ${dims(j.out_size)}` : dims(j.in_size);
    const msg = { queued: "Waiting", running: `Upscaling… ${Math.round(j.progress * 100)}%` + (j.eta ? ` · ${fmtTime(j.eta)} left` : ""),
                  done: `Done in ${fmtTime(j.seconds)}` + (j.message ? ` · ${j.message}` : "") }[j.status] || j.message;
    li.querySelector(".msg").textContent = msg;
    li.querySelector(".msg").title = j.message || "";
    li.querySelector(".bar").style.visibility = j.status === "running" ? "visible" : "hidden";
    li.querySelector(".bar i").style.width = `${j.progress * 100}%`;
    li.querySelector(".x").hidden = j.status === "running";
  }
  ul.querySelectorAll(".job").forEach((li) => { if (!seen.has(+li.dataset.id)) li.remove(); });
  $("#queueEmpty").hidden = list.length > 0;
  ul.hidden = list.length === 0;
}

async function poll() {
  let q;
  try { q = await api("/api/queue"); } catch { return; }
  const prev = new Map(jobs);
  jobs.clear(); q.jobs.forEach((j) => jobs.set(j.id, j));
  renderJobs(q.jobs);
  running = q.running;
  const queued = q.jobs.filter((j) => j.status === "queued").length;
  const done = q.jobs.filter((j) => j.status === "done").length;
  $("#queueSummary").textContent = q.jobs.length ? `${done} of ${q.jobs.length} done` : "";
  $("#start").hidden = running; $("#cancel").hidden = !running;
  $("#start").disabled = !queued && !q.jobs.some((j) => ["error", "cancelled"].includes(j.status) && j.in_size);
  $("#etaTotal").textContent = running && q.eta_total ? `About ${fmtTime(q.eta_total)} left for ${queued + 1} photo${queued ? "s" : ""}` : "";
  // auto-open a photo the moment it finishes, unless the user is looking at another one
  for (const j of q.jobs) {
    const p = prev.get(j.id);
    if (j.status === "done" && p && p.status !== "done" && (selected == null || !jobs.get(selected))) select(j.id);
  }
  if (selected != null && !jobs.has(selected)) clearViewer();
  if (!prev.size && q.jobs.length) refreshSettings();
}
setInterval(poll, 700);

$("#start").onclick = async () => {
  hideError();
  try { await api("/api/start", payload()); poll(); } catch (e) { showError(e.message); }
};
$("#cancel").onclick = async () => { await api("/api/cancel", {}); poll(); };
$("#clearDone").onclick = async () => { await api("/api/clear", {}); poll(); };
$("#reveal").onclick = () => selected != null && api(`/api/reveal/${selected}`, {});
function showError(m) { $("#error").textContent = m; $("#error").hidden = false; }
function hideError() { $("#error").hidden = true; }

// ---------------------------------------------------------------- viewer
const stage = $("#stage"), cmp = $("#compare"), imgB = $("#imgBefore"), imgA = $("#imgAfter"), handle = $("#handle");
let zoom = "fit", split = 0.5, center = null, rect = null, loadToken = 0;
const dpr = () => window.devicePixelRatio || 1;

function clearViewer() {
  selected = null; cmp.hidden = true; $("#stageEmpty").hidden = false; $("#reveal").hidden = true; $("#viewerTitle").textContent = "";
}
function select(id) {
  selected = id; center = null; setZoom("fit");
  const j = jobs.get(id);
  $("#viewerTitle").textContent = `${j.name}   ·   ${dims(j.in_size)} → ${dims(j.out_size)}`;
  $("#reveal").hidden = false; $("#stageEmpty").hidden = true; cmp.hidden = false;
  renderJobs([...jobs.values()]); refreshSettings(); draw();
}
function setZoom(z) {
  zoom = z;
  $$("#zoomSeg button").forEach((b) => b.classList.toggle("on", b.dataset.zoom === String(z)));
}
$("#zoomSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b || selected == null) return;
  setZoom(b.dataset.zoom === "fit" ? "fit" : Number(b.dataset.zoom)); draw();
});

function loadPair(urlB, urlA) {
  const token = ++loadToken; $("#loading").hidden = false;
  const a = new Image(), b = new Image(); let n = 0;
  const done = () => { if (++n < 2 || token !== loadToken) return;
    imgB.src = b.src; imgA.src = a.src; $("#loading").hidden = true; layout(); };
  a.onload = b.onload = done; a.onerror = b.onerror = () => { $("#loading").hidden = true; };
  b.src = urlB; a.src = urlA;
}

// Where the images sit in the stage (CSS px)
function draw() {
  const j = jobs.get(selected); if (!j || !j.out_size) return;
  const sw = stage.clientWidth, sh = stage.clientHeight, [W, H] = j.out_size;
  cmp.classList.toggle("fit", zoom === "fit"); cmp.classList.toggle("zoomed", zoom !== "fit");
  cmp.classList.toggle("px", zoom !== "fit");
  if (zoom === "fit") {
    const s = Math.min(sw / W, sh / H), dw = Math.round(W * s), dh = Math.round(H * s);
    rect = { x: Math.round((sw - dw) / 2), y: Math.round((sh - dh) / 2), w: dw, h: dh };
    const q = `w=${Math.round(dw * dpr())}&h=${Math.round(dh * dpr())}`;
    loadPair(`/api/preview/${selected}?which=before&${q}`, `/api/preview/${selected}?which=after&${q}`);
  } else {
    const z = zoom, rw = Math.min(W, Math.round(sw * dpr() / z)), rh = Math.min(H, Math.round(sh * dpr() / z));
    if (!center) center = [W / 2, H / 2];
    const x0 = Math.round(Math.max(0, Math.min(W - rw, center[0] - rw / 2)));
    const y0 = Math.round(Math.max(0, Math.min(H - rh, center[1] - rh / 2)));
    center = [x0 + rw / 2, y0 + rh / 2];
    const cw = rw * z / dpr(), ch = rh * z / dpr();
    rect = { x: Math.round((sw - cw) / 2), y: Math.round((sh - ch) / 2), w: cw, h: ch, x0, y0, rw, rh };
    const q = `x=${x0}&y=${y0}&w=${rw}&h=${rh}&zoom=${z}`;
    loadPair(`/api/crop/${selected}?which=before&${q}`, `/api/crop/${selected}?which=after&${q}`);
  }
}

function layout(dx = 0, dy = 0) {
  if (!rect) return;
  for (const im of [imgB, imgA]) {
    im.style.left = rect.x + dx + "px"; im.style.top = rect.y + dy + "px";
    im.style.width = rect.w + "px"; im.style.height = rect.h + "px";
  }
  const hx = stage.clientWidth * split;
  handle.style.left = hx + "px";
  const cut = Math.max(0, Math.min(rect.w, hx - rect.x - dx));
  imgA.style.clipPath = `inset(0 0 0 ${cut}px)`;
}

// slider handle
let draggingHandle = false;
handle.addEventListener("pointerdown", (e) => { draggingHandle = true; handle.setPointerCapture(e.pointerId); e.stopPropagation(); });
handle.addEventListener("pointermove", (e) => {
  if (!draggingHandle) return;
  const r = stage.getBoundingClientRect();
  split = Math.max(0.01, Math.min(0.99, (e.clientX - r.left) / r.width)); layout();
});
handle.addEventListener("pointerup", () => (draggingHandle = false));

// click to zoom in, drag to pan
let pan = null;
cmp.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  pan = { x: e.clientX, y: e.clientY, moved: false }; cmp.setPointerCapture(e.pointerId);
});
cmp.addEventListener("pointermove", (e) => {
  if (!pan) return;
  const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) pan.moved = true;
  if (pan.moved && zoom !== "fit") { cmp.classList.add("dragging"); layout(dx, dy); }
});
cmp.addEventListener("pointerup", (e) => {
  if (!pan) return;
  const dx = e.clientX - pan.x, dy = e.clientY - pan.y, moved = pan.moved; pan = null;
  cmp.classList.remove("dragging");
  const j = jobs.get(selected); if (!j || !rect) return;
  const r = stage.getBoundingClientRect();
  if (zoom === "fit" && !moved) {          // zoom to 100% where clicked
    const fx = (e.clientX - r.left - rect.x) / rect.w, fy = (e.clientY - r.top - rect.y) / rect.h;
    if (fx < 0 || fy < 0 || fx > 1 || fy > 1) return;
    center = [fx * j.out_size[0], fy * j.out_size[1]]; setZoom(1); draw();
  } else if (zoom !== "fit" && moved) {
    const k = dpr() / zoom;
    center = [center[0] - dx * k, center[1] - dy * k]; draw();
  }
});
cmp.addEventListener("dblclick", () => { if (zoom !== "fit") { setZoom("fit"); draw(); } });
let resizeTimer; window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(draw, 150); });

// ---------------------------------------------------------------- boot
refreshSettings();
loadModels().catch((e) => showError(e.message));
poll();
