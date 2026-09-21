/* Noesis PDF Cloner — frontend (vanilla JS).
 * Flusso: upload → metadati/etichette → anteprima → job → log SSE → download.
 */
"use strict";

const API = "/api/v1";
const state = {
  meta: null,
  document: null,   // { doc_id, filename, page_count, pages:[{index,number,label}] }
  job: null,
  eventSource: null,
  pollTimer: null,
};

const $ = (id) => document.getElementById(id);

/* ── persistenza job (localStorage) ────────────────────────────────────── *
 * L'elenco dei jobId resta nel browser anche chiudendolo: all'avvio si
 * ricontrolla lo stato server-side e si riaggancia l'ultimo job non finito.
 * Il server non notifica nulla: il job continua comunque lato worker.
 */

const JOB_IDS_KEY = "noesis_job_ids";
const JOB_IDS_MAX = 20;
const ACTIVE_STATES = ["queued", "running", "scheduled"];

function loadJobIds() {
  try {
    const raw = JSON.parse(localStorage.getItem(JOB_IDS_KEY) || "[]");
    return Array.isArray(raw)
      ? [...new Set(raw.filter((id) => typeof id === "string" && id))]
      : [];
  } catch {
    return [];
  }
}

function saveJobIds(ids) {
  try {
    const clean = [...new Set(ids.filter((id) => typeof id === "string" && id))];
    localStorage.setItem(JOB_IDS_KEY, JSON.stringify(clean.slice(0, JOB_IDS_MAX)));
  } catch { /* storage non disponibile */ }
}

function addJobId(jobId) {
  saveJobIds([jobId, ...loadJobIds().filter((id) => id !== jobId)]);
}

function removeJobId(jobId) {
  saveJobIds(loadJobIds().filter((id) => id !== jobId));
}

function isActiveJob(job) {
  return ACTIVE_STATES.includes(job.state);
}

/* ── utilità ───────────────────────────────────────────────────────────── */

function parsePages(spec, pageCount) {
  // Ritorna { pages: [0-based...], error } — mirror di app/pages.py.
  const text = (spec || "all").trim().toLowerCase();
  if (text === "" || text === "all" || text === "*") {
    return { pages: [...Array(pageCount).keys()], error: null };
  }
  const set = new Set();
  for (const chunk of text.split(",")) {
    const token = chunk.trim();
    if (!token) continue;
    if (token.includes("-")) {
      const [a, b] = token.split("-").map((v) => parseInt(v.trim(), 10));
      if (Number.isNaN(a) || Number.isNaN(b)) return { pages: [], error: `intervallo non valido: ${token}` };
      const lo = Math.min(a, b), hi = Math.max(a, b);
      if (lo < 1 || hi > pageCount) return { pages: [], error: `pagina oltre il totale (${pageCount})` };
      for (let p = lo; p <= hi; p++) set.add(p - 1);
    } else {
      const n = parseInt(token, 10);
      if (Number.isNaN(n)) return { pages: [], error: `numero non valido: ${token}` };
      if (n < 1 || n > pageCount) return { pages: [], error: `pagina oltre il totale (${pageCount})` };
      set.add(n - 1);
    }
  }
  if (set.size === 0) return { pages: [], error: "nessuna pagina selezionata" };
  return { pages: [...set].sort((a, b) => a - b), error: null };
}

function humanDuration(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
}

/* ── meta ──────────────────────────────────────────────────────────────── */

async function loadMeta() {
  state.meta = await (await fetch(`${API}/meta`)).json();
  const src = $("src-lang"), dst = $("dst-lang"), eng = $("engine");
  for (const [code, name] of Object.entries(state.meta.languages)) {
    src.append(new Option(name, code));
  }
  for (const [code, name] of Object.entries(state.meta.languages)) {
    if (code === "auto") continue;
    dst.append(new Option(name, code));
  }
  for (const code of state.meta.engines) {
    const label = (state.meta.engine_labels && state.meta.engine_labels[code]) || code;
    eng.append(new Option(label, code));
  }
  src.value = "auto";
  dst.value = "it";
  eng.value = "google";
  const version = $("service-meta").dataset.version || $("service-meta").textContent.trim();
  $("service-meta").dataset.version = version;
  $("service-meta").textContent =
    `${version} · blocchi da ${state.meta.limits.max_pages_per_block} pagine · ` +
    `max ${state.meta.limits.max_pages_total} pag/job`;
}

function engineLabel(code) {
  return (state.meta && state.meta.engine_labels && state.meta.engine_labels[code]) || code;
}

/* ── upload ────────────────────────────────────────────────────────────── */

async function uploadFile(file) {
  if (!file) return;
  $("upload-status").textContent = `Caricamento ${file.name}…`;
  $("submit").disabled = true;
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`${API}/documents`, { method: "POST", body });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    $("upload-status").textContent = `Errore: ${detail.detail || response.status}`;
    return;
  }
  state.document = await response.json();
  $("upload-status").textContent =
    `${state.document.filename} · ${state.document.page_count} pagine · ` +
    `caricato`;
  const stem = state.document.filename.replace(/\.pdf$/i, "");
  if (!$("output-name").value) {
    $("output-name").value = `${stem}_${$("dst-lang").value}`;
  }
  $("submit").disabled = false;
  refreshPreview();
  refreshEstimate();
  resetJobView();
}

/* ── anteprima (prima/ultima del range) ────────────────────────────────── */

function refreshPreview() {
  const box = $("preview");
  box.textContent = "";
  if (!state.document) {
    box.innerHTML = '<p class="hint">Carica un PDF per vedere l\'anteprima.</p>';
    return;
  }
  const { pages, error } = parsePages($("pages").value, state.document.page_count);
  if (error) {
    box.innerHTML = `<p class="hint">${error}</p>`;
    return;
  }
  const indices = pages.length === 1 ? [pages[0]] : [pages[0], pages[pages.length - 1]];
  for (const index of indices) {
    const pageRef = state.document.pages[index];
    const figure = document.createElement("figure");
    figure.className = "thumb";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = `${API}/documents/${state.document.doc_id}/thumb?page=${index}&w=180`;
    const caption = document.createElement("figcaption");
    caption.textContent = `Pagina fisica ${pageRef.number}` +
      (pageRef.label && pageRef.label !== String(pageRef.number)
        ? ` · stampata "${pageRef.label}"` : "");
    figure.append(img, caption);
    box.append(figure);
  }
  if (pages.length > 1) {
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = `${pages.length} pagine selezionate (${pages[0] + 1}–${pages[pages.length - 1] + 1})`;
    box.append(note);
  }
}

async function refreshEstimate() {
  const box = $("estimate");
  if (!state.document) {
    box.textContent = "";
    return;
  }
  const payload = {
    doc_id: state.document.doc_id,
    pages: $("pages").value,
    src_lang: $("src-lang").value,
    dst_lang: $("dst-lang").value,
    engine: $("engine").value,
  };
  try {
    const response = await fetch(`${API}/jobs/estimate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      box.textContent = `stima non disponibile: ${detail.detail || response.status}`;
      return;
    }
    const est = await response.json();
    const cost = est.cost_cents > 0
      ? `${(est.cost_cents / 100).toFixed(4)} ${est.currency}`
      : "gratis / non configurato";
    box.textContent =
      `Da tradurre: ${est.pages_to_translate} di ${est.pages_total} · ` +
      `già in cache: ${est.pages_cached} · ` +
      `tempo stimato: ~${humanDuration(est.estimated_seconds * 1000)} · ` +
      `costo: ${cost}`;
  } catch {
    box.textContent = "";
  }
}

/* ── log collassabile ──────────────────────────────────────────────────── */

let logCollapsed = false;

function setLogCollapsed(value) {
  logCollapsed = value;
  const log = $("log");
  const toggle = $("log-toggle");
  if (!log || !toggle) return;
  log.classList.toggle("collapsed", value);
  toggle.classList.toggle("collapsed", value);
  toggle.setAttribute("aria-expanded", String(!value));
  try { localStorage.setItem("noesis_log_collapsed", value ? "1" : "0"); } catch { /* ignore */ }
}

function bindLogToggle() {
  const toggle = $("log-toggle");
  if (!toggle) return;
  let initial = false;
  try { initial = localStorage.getItem("noesis_log_collapsed") === "1"; } catch { /* ignore */ }
  setLogCollapsed(initial);
  toggle.onclick = () => setLogCollapsed(!logCollapsed);
}

/* ── job ───────────────────────────────────────────────────────────────── */

async function submitJob(event) {
  event.preventDefault();
  if (!state.document) return;
  const rangeMode = document.querySelector('input[name="range_mode"]:checked').value;
  const payload = {
    doc_id: state.document.doc_id,
    pages: $("pages").value,
    src_lang: $("src-lang").value,
    dst_lang: $("dst-lang").value,
    engine: $("engine").value,
    output_name: $("output-name").value || null,
    range_mode: rangeMode,
  };
  const startAt = $("start-at").value;
  if (startAt) payload.start_at = new Date(startAt).toISOString();
  resetJobView();
  const response = await fetch(`${API}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    appendLog(`ERRORE: ${detail.detail || response.status}`);
    return;
  }
  state.job = await response.json();
  addJobId(state.job.job_id);
  appendLog(`job ${state.job.job_id.slice(0, 8)} accodato (${state.job.pages_total} pagine, ${engineLabel(state.job.engine)})`);
  if (logCollapsed) setLogCollapsed(false);  // mostra subito il log del nuovo job
  $("cancel").disabled = false;
  openStream(state.job.job_id);
  startPolling(state.job.job_id);
}

function openStream(jobId) {
  if (state.eventSource) state.eventSource.close();
  const source = new EventSource(`${API}/jobs/${jobId}/events`);
  state.eventSource = source;
  source.onmessage = (event) => {
    try {
      const record = JSON.parse(event.data);
      appendLog(formatEvent(record));
    } catch { /* ignora righe non JSON */ }
  };
  source.addEventListener("end", () => source.close());
  source.onerror = () => source.close();
}

function formatEvent(record) {
  const page = record.page_number ? `p${record.page_number} ` : "";
  const ms = record.duration_ms ? ` (${humanDuration(record.duration_ms)})` : "";
  const marker = record.level === "error" ? "✗" : record.level === "warning" ? "⚠" : "•";
  return `${marker} ${page}${record.message}${ms}`;
}

function startPolling(jobId) {
  stopPolling();
  const tick = async () => {
    const response = await fetch(`${API}/jobs/${jobId}`);
    if (!response.ok) return;
    const job = await response.json();
    state.job = job;
    renderJob(job);
    if (["done", "error", "cancelled", "interrupted"].includes(job.state)) {
      stopPolling();
      if (state.eventSource) state.eventSource.close();
      $("cancel").disabled = true;
      refreshHistory();
      return;
    }
    // I job programmati si controllano raramente.
    state.pollTimer = setTimeout(tick, job.state === "scheduled" ? 30000 : 1500);
  };
  tick();
}

function stopPolling() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

/* ── riaggancio job (persistenza localStorage) ─────────────────────────── */

async function fetchJob(jobId) {
  try {
    const response = await fetch(`${API}/jobs/${jobId}`);
    if (response.status === 404) { removeJobId(jobId); return null; }
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;  // rete assente: non tocco lo storage, ritento al prossimo avvio
  }
}

function attachJob(job) {
  state.job = job;
  stopPolling();
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
  renderJob(job);
  $("cancel").disabled = !isActiveJob(job);
  if (isActiveJob(job)) startPolling(job.job_id);
}

async function restoreJobs() {
  const ids = loadJobIds();
  if (!ids.length) return;
  let chosen = null;
  for (const id of ids) {
    const job = await fetchJob(id);
    if (job && !chosen) chosen = job;  // ids in ordine recente-primo
  }
  if (!chosen) return;
  attachJob(chosen);
  appendLog(
    isActiveJob(chosen)
      ? `job ${chosen.job_id.slice(0, 8)} ripreso (${chosen.state})`
      : `job ${chosen.job_id.slice(0, 8)}: ${chosen.state}`
  );
}

function renderJob(job) {
  const badge = $("job-state");
  badge.textContent = job.state;
  badge.className = `badge ${job.state}`;
  $("queue-pos").textContent =
    job.state === "queued" && job.queue_position
      ? `posizione in coda: ${job.queue_position}`
      : job.state === "scheduled" && job.scheduled_at
        ? `avvio programmato: ${new Date(job.scheduled_at).toLocaleString()}`
        : "";
  const total = job.pages_total || 0;
  const done = job.pages_done + job.pages_failed;
  $("progress-fill").style.width = total ? `${Math.round((done / total) * 100)}%` : "0%";
  $("counter-pages").textContent = `${job.pages_done} / ${total} pagine (${job.pages_failed} fallite)`;
  if (job.started && job.state === "running") {
    const elapsed = Date.now() - new Date(job.started).getTime();
    const rate = job.pages_done > 0 ? elapsed / job.pages_done : 0;
    const remaining = rate * (total - job.pages_done);
    $("counter-eta").textContent = remaining > 0 ? `ETA ~${humanDuration(remaining)}` : "";
  } else {
    $("counter-eta").textContent = job.duration_ms ? `durata ${humanDuration(job.duration_ms)}` : "";
  }
  const link = $("download");
  if (job.download_url && job.state === "done") {
    link.href = job.download_url;
    const ext = job.range_mode === "single" ? "zip" : "pdf";
    link.setAttribute("download", `${job.output_name}.${ext}`);
    link.classList.remove("hidden");
  } else {
    link.classList.add("hidden");
  }
}

async function cancelJob() {
  if (!state.job) return;
  await fetch(`${API}/jobs/${state.job.job_id}/cancel`, { method: "POST" });
  appendLog("richiesta di annullamento inviata");
}

function appendLog(line) {
  const log = $("log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
  log.textContent += line + "\n";
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function resetJobView() {
  stopPolling();
  if (state.eventSource) state.eventSource.close();
  state.eventSource = null;
  $("log").textContent = "";
  $("progress-fill").style.width = "0%";
  $("counter-pages").textContent = "0 / 0 pagine";
  $("counter-eta").textContent = "";
  $("job-state").textContent = "in attesa";
  $("job-state").className = "badge idle";
  $("queue-pos").textContent = "";
  $("download").classList.add("hidden");
}

/* ── storico ───────────────────────────────────────────────────────────── */

async function refreshHistory() {
  const jobs = await (await fetch(`${API}/jobs?limit=10`)).json();
  const mine = new Set(loadJobIds());
  const list = $("history");
  list.textContent = "";
  for (const job of jobs) {
    const item = document.createElement("li");
    if (mine.has(job.job_id)) item.classList.add("mine");
    item.tabIndex = 0;
    item.title = "apri questo job";
    item.onclick = () => openHistoryJob(job.job_id);
    item.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openHistoryJob(job.job_id);
      }
    };
    const left = document.createElement("span");
    left.textContent = `${job.output_name} · ${job.pages_done}/${job.pages_total} · ${engineLabel(job.engine)}→${job.dst_lang}`;
    const right = document.createElement("span");
    right.textContent = job.state;
    right.className = ["done"].includes(job.state) ? "s-ok" : ["error", "cancelled", "interrupted"].includes(job.state) ? "s-err" : "";
    item.append(left, right);
    list.append(item);
  }
}

async function openHistoryJob(jobId) {
  const job = await fetchJob(jobId);
  if (!job) return;
  attachJob(job);
  if (loadJobIds().includes(jobId)) addJobId(jobId);  // aggiorna la recenza
}

/* ── init ──────────────────────────────────────────────────────────────── */

function bind() {
  const dropzone = $("dropzone");
  const input = $("file-input");
  bindLogToggle();
  $("browse").onclick = () => input.click();
  input.onchange = () => uploadFile(input.files[0]);
  ["dragenter", "dragover"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); }));
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });
  $("pages").addEventListener("input", () => {
    setTimeout(refreshPreview, 200);
    setTimeout(refreshEstimate, 250);
  });
  for (const id of ["engine", "src-lang", "dst-lang"]) {
    $(id).addEventListener("change", refreshEstimate);
  }
  $("job-form").addEventListener("submit", submitJob);
  $("cancel").onclick = cancelJob;
  $("dst-lang").addEventListener("change", () => {
    if (!state.document) return;
    const stem = state.document.filename.replace(/\.pdf$/i, "");
    $("output-name").value = `${stem}_${$("dst-lang").value}`;
  });
}

(async function main() {
  bind();
  try {
    await loadMeta();
    await refreshHistory();
    await restoreJobs();
  } catch (error) {
    appendLog(`impossibile contattare il servizio: ${error}`);
  }
})();
