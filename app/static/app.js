/* Noesis PDF Cloner — frontend (vanilla JS).
 * Flusso: griglia dei lavori → tessera "＋" → wizard → job con progresso
 * "liquido" disegnato sulla tessera → drawer di dettaglio (log/annulla/scarica).
 */
"use strict";

const API = "/api/v1";
const ACTIVE = ["queued", "running", "scheduled"];
const TERMINAL = ["done", "error", "cancelled", "interrupted"];
const STEPS = ["File", "Pagine", "Lingue", "Motore", "Output"];
const STATE_LABEL = {
  queued: "in coda", running: "running", done: "done",
  error: "errore", cancelled: "annullato", interrupted: "interrotto",
  scheduled: "programmato",
};

const state = {
  meta: null,
  document: null,          // { doc_id, filename, page_count, size_bytes, pages:[…] }
  jobs: [],
  tiles: new Map(),        // job_id -> { el, cover }
  orderKey: "",
  gridTimer: null,
  gridBusy: false,
  drawer: { id: null, docId: null, timer: null, source: null },
  wizard: { step: 0, rangeMode: "merged", startMode: "now" },
  search: "",
};

const $ = (id) => document.getElementById(id);

/* ── persistenza job (localStorage) ────────────────────────────────────── */

const JOB_IDS_KEY = "noesis_job_ids";
const JOB_IDS_MAX = 40;

function loadJobIds() {
  try {
    const raw = JSON.parse(localStorage.getItem(JOB_IDS_KEY) || "[]");
    return Array.isArray(raw)
      ? [...new Set(raw.filter((id) => typeof id === "string" && id))]
      : [];
  } catch { return []; }
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

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
}

function engineLabel(code) {
  return (state.meta && state.meta.engine_labels && state.meta.engine_labels[code]) || code;
}

function progressPct(job) {
  const total = job.pages_total || 0;
  if (!total) return 0;
  const done = (job.pages_done || 0) + (job.pages_failed || 0);
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}

function toast(message) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.body.append(el);
  setTimeout(() => el.classList.add("gone"), 3600);
  setTimeout(() => el.remove(), 4200);
}

/* ── meta ──────────────────────────────────────────────────────────────── */

async function loadMeta() {
  state.meta = await (await fetch(`${API}/meta`)).json();

  const src = $("src-lang"), dst = $("dst-lang");
  for (const [code, name] of Object.entries(state.meta.languages)) {
    src.append(new Option(name, code));
  }
  for (const [code, name] of Object.entries(state.meta.languages)) {
    if (code === "auto") continue;
    dst.append(new Option(name, code));
  }
  src.value = "auto";
  dst.value = "it";

  const box = $("engines");
  box.textContent = "";
  for (const code of state.meta.engines) {
    const card = document.createElement("label");
    card.className = "card-opt";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "engine";
    radio.value = code;
    radio.checked = code === "google";
    radio.addEventListener("change", () => { markEngine(code); refreshEstimate(); });
    const info = document.createElement("div");
    const title = document.createElement("b");
    title.textContent = engineLabel(code);
    info.append(title);
    card.append(radio, info);
    box.append(card);
  }
  markEngine("google");

  const node = $("service-meta");
  const version = node.dataset.version || node.textContent.replace(/^v/, "").trim();
  node.dataset.version = version;
  node.textContent =
    `v${version} · blocchi da ${state.meta.limits.max_pages_per_block} pagine · ` +
    `max ${state.meta.limits.max_pages_total} pag/job`;
}

function markEngine(code) {
  document.querySelectorAll("#engines .card-opt").forEach((card) => {
    const radio = card.querySelector("input");
    card.classList.toggle("on", !!radio && radio.value === code);
  });
}

function selectedEngine() {
  const radio = document.querySelector('input[name="engine"]:checked');
  return radio ? radio.value : "google";
}

/* ── upload ────────────────────────────────────────────────────────────── */

async function uploadFile(file) {
  if (!file) return;
  $("dropzone").textContent = `Caricamento ${file.name}…`;
  const body = new FormData();
  body.append("file", file);
  let response;
  try {
    response = await fetch(`${API}/documents`, { method: "POST", body });
  } catch {
    resetDropzone();
    toast("Errore di rete durante il caricamento");
    return;
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    resetDropzone();
    toast(`Errore: ${detail.detail || response.status}`);
    return;
  }
  state.document = await response.json();
  resetDropzone();
  $("file-card").classList.remove("hidden");
  $("file-name").textContent = state.document.filename;
  $("file-meta").textContent =
    `${state.document.page_count} pagine · ${(state.document.size_bytes / 1048576).toFixed(1)} MB`;
  const stem = state.document.filename.replace(/\.pdf$/i, "");
  if (!$("output-name").value) $("output-name").value = `${stem}_${$("dst-lang").value}`;
  refreshPreview();
  refreshEstimate();
}

function resetDropzone() {
  $("dropzone").innerHTML = '⬆ &nbsp;Trascina qui il PDF oppure <u>scegli un file</u>';
}

/* ── wizard ────────────────────────────────────────────────────────────── */

function openWizard(step = 0) {
  $("wizard").classList.add("open");
  showStep(step);
}

function closeWizard() {
  $("wizard").classList.remove("open");
}

function renderSteps() {
  const box = $("steps");
  box.textContent = "";
  STEPS.forEach((name, i) => {
    if (i) {
      const sep = document.createElement("div");
      sep.className = "sep";
      box.append(sep);
    }
    const item = document.createElement("div");
    item.className = "s" + (i === state.wizard.step ? " on" : "") + (i < state.wizard.step ? " done" : "");
    const num = document.createElement("i");
    num.textContent = String(i + 1);
    item.append(num, document.createTextNode(name));
    box.append(item);
  });
}

function showStep(step) {
  state.wizard.step = step;
  document.querySelectorAll(".pane").forEach((pane) => {
    pane.hidden = Number(pane.dataset.step) !== step;
  });
  renderSteps();
  $("wizard-prev").style.visibility = step ? "visible" : "hidden";
  $("wizard-next").textContent = step === STEPS.length - 1 ? "Avvia la traduzione" : "Avanti →";
  if (step === 1) refreshPreview();
  if (step === 3) refreshEstimate();
  if (step === 4) refreshSummary();
}

function wizardNext() {
  const step = state.wizard.step;
  if (step === 0 && !state.document) return toast("Carica prima un PDF");
  if (step === 1) {
    const { error } = parsePages($("pages").value, state.document ? state.document.page_count : 0);
    if (error) return toast(error);
  }
  if (step === 2 && $("dst-lang").value === "auto") return toast("Scegli una lingua di destinazione");
  if (step === 3 && !document.querySelector('input[name="engine"]:checked')) return toast("Scegli un motore");
  if (step < STEPS.length - 1) return showStep(step + 1);
  return submitJob();
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
    figure.className = "tw";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "";
    img.src = `${API}/documents/${state.document.doc_id}/thumb?page=${index}&w=180`;
    const caption = document.createElement("figcaption");
    caption.textContent = `fisica ${pageRef.number}` +
      (pageRef.label && pageRef.label !== String(pageRef.number) ? ` · «${pageRef.label}»` : "");
    figure.append(img, caption);
    box.append(figure);
  }
  if (pages.length > 1) {
    const note = document.createElement("p");
    note.className = "hint";
    note.style.alignSelf = "center";
    note.textContent = `${pages.length} pagine selezionate`;
    box.append(note);
  }
}

/* ── stima ─────────────────────────────────────────────────────────────── */

async function refreshEstimate() {
  const box = $("estimate");
  if (!state.document) { box.textContent = ""; return; }
  const dst = $("dst-lang").value;
  if (!dst || dst === "auto") { box.textContent = "Scegli la lingua di destinazione."; return; }
  const payload = {
    doc_id: state.document.doc_id,
    pages: $("pages").value,
    src_lang: $("src-lang").value,
    dst_lang: dst,
    engine: selectedEngine(),
  };
  try {
    const response = await fetch(`${API}/jobs/estimate`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
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
      `già in cache: ${est.pages_cached} · tempo stimato: ~${humanDuration(est.estimated_seconds * 1000)} · ` +
      `costo: ${cost}`;
  } catch { box.textContent = ""; }
}

/* ── riepilogo + submit ────────────────────────────────────────────────── */

function refreshSummary() {
  const box = $("summary");
  const { pages, error } = parsePages($("pages").value, state.document.page_count);
  const range = error ? $("pages").value : (pages.length > 1
    ? `${pages[0] + 1}–${pages[pages.length - 1] + 1} (${pages.length})`
    : String(pages[0] + 1));
  const lines = [
    ["File", `${state.document.filename} · ${range}`],
    ["Lingue", `${$("src-lang").selectedOptions[0].textContent} → ${$("dst-lang").selectedOptions[0].textContent}`],
    ["Motore", engineLabel(selectedEngine())],
    ["Uscita", `${$("output-name").value || "(automatico)"} · ${state.wizard.rangeMode === "single" ? "ZIP pagine singole" : "unico PDF"}`],
  ];
  if (state.wizard.startMode === "later" && $("start-at").value) {
    lines.push(["Avvio", formatTime(new Date($("start-at").value).toISOString())]);
  }
  box.textContent = "";
  for (const [k, v] of lines) {
    const row = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = k;
    row.append(label, document.createTextNode(`   ${v}`));
    box.append(row);
  }
}

async function submitJob() {
  if (!state.document) return;
  const payload = {
    doc_id: state.document.doc_id,
    pages: $("pages").value,
    src_lang: $("src-lang").value,
    dst_lang: $("dst-lang").value,
    engine: selectedEngine(),
    output_name: $("output-name").value || null,
    range_mode: state.wizard.rangeMode,
  };
  if (state.wizard.startMode === "later" && $("start-at").value) {
    payload.start_at = new Date($("start-at").value).toISOString();
  }
  $("wizard-next").disabled = true;
  let response;
  try {
    response = await fetch(`${API}/jobs`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
  } catch {
    $("wizard-next").disabled = false;
    return toast("Errore di rete durante l'avvio del job");
  }
  $("wizard-next").disabled = false;
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    return toast(`Errore: ${detail.detail || response.status}`);
  }
  const job = await response.json();
  addJobId(job.job_id);
  closeWizard();
  await refreshGrid();
  openDrawer(job.job_id);
}

/* ── griglia ───────────────────────────────────────────────────────────── */

function sortJobs(jobs) {
  const rank = { running: 0, queued: 1, scheduled: 2 };
  return [...jobs].sort((a, b) => {
    const ra = rank[a.state] ?? 3;
    const rb = rank[b.state] ?? 3;
    if (ra !== rb) return ra - rb;
    return new Date(b.created) - new Date(a.created);
  });
}

function createTile(job) {
  const el = document.createElement("article");
  el.className = "tile";
  el.tabIndex = 0;

  const cover = document.createElement("div");
  cover.className = "cover";
  const paper = document.createElement("div");
  paper.className = "paper";
  paper.innerHTML = '<div class="band"></div><div class="lines"></div>';
  const img = document.createElement("img");
  img.alt = "";
  img.loading = "lazy";
  img.src = `${API}/jobs/${job.job_id}/cover`;
  img.addEventListener("load", () => cover.classList.add("hascover"));
  const scrim = document.createElement("div");
  scrim.className = "scrim";
  const badge = document.createElement("span");
  badge.className = "badge idle";
  const info = document.createElement("div");
  info.className = "tile-info";
  const chip = document.createElement("span");
  chip.className = "range-chip";
  const name = document.createElement("div");
  name.className = "tile-name";
  const meta = document.createElement("div");
  meta.className = "tile-meta";
  info.append(chip, name, meta);
  const dl = document.createElement("a");
  dl.className = "dl hidden";
  dl.href = `${API}/jobs/${job.job_id}/download`;
  dl.textContent = "⬇ Scarica";
  dl.addEventListener("click", (e) => e.stopPropagation());
  const liquid = document.createElement("div");
  liquid.className = "liquid";

  cover.append(paper, img, scrim, badge, info, dl);
  el.append(cover, liquid);

  const open = () => openDrawer(job.job_id);
  el.addEventListener("click", open);
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
  });
  return { el, cover, badge, name, meta, dl, chip };
}

function updateTile(tile, job) {
  const mine = loadJobIds().includes(job.job_id);
  tile.el.className = `tile st-${job.state}` + (mine ? " mine" : "");
  tile.badge.textContent = STATE_LABEL[job.state] || job.state;
  tile.badge.className = `badge ${job.state}`;
  tile.name.textContent = job.output_name || "(senza nome)";
  tile.meta.textContent = tileMeta(job);
  const range = rangeChipText(job);
  tile.chip.textContent = range.text;
  tile.chip.title = range.title;
  tile.dl.classList.toggle("hidden", job.state !== "done");
  tile.el.style.setProperty("--p", job.state === "running" ? progressPct(job) : 0);
  tile.el.dataset.search = `${job.output_name} ${job.state} ${engineLabel(job.engine)} ${job.dst_lang}`.toLowerCase();
}

function tileMeta(job) {
  const eng = engineLabel(job.engine);
  const base = `${eng} → ${job.dst_lang}`;
  if (job.state === "queued") {
    return `${base} · in coda${job.queue_position ? ` (${job.queue_position}°)` : ""}`;
  }
  if (job.state === "scheduled") {
    return `${base} · ${formatTime(job.scheduled_at)}`;
  }
  if (job.state === "done") {
    return `${base} · ${job.pages_total}/${job.pages_total}`;
  }
  return `${base} · ${job.pages_done}/${job.pages_total}`;
}

function rangeChipText(job) {
  const total = job.pages_total || 0;
  const first = job.page_first;
  const last = job.page_last;
  if (first == null) return { text: "—", title: "" };
  if (total === 1 || first === last) {
    return { text: `p. ${first}`, title: `pagina ${first}` };
  }
  if (!job.pages_contiguous) {
    return {
      text: `${total} pagine`,
      title: `${total} pagine sparse, da p. ${first} a p. ${last}`,
    };
  }
  return {
    text: `p. ${first}–${last} · ${total}`,
    title: `pagine ${first}–${last} (${total})`,
  };
}

async function refreshGrid() {
  let jobs;
  try {
    jobs = await (await fetch(`${API}/jobs?limit=100`)).json();
  } catch {
    return;
  }
  state.jobs = jobs;

  // tessera "nuovo" sempre in testa
  if (!state.tiles.has("__new__")) {
    const plus = document.createElement("article");
    plus.className = "tile st-new";
    plus.tabIndex = 0;
    plus.dataset.search = "nuovo";
    plus.innerHTML = '<div class="cover"><div class="plus">＋</div><div class="new-lbl">nuovo</div></div>';
    plus.addEventListener("click", () => openWizard(0));
    plus.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openWizard(0); }
    });
    bindPlusDrop(plus);
    $("grid").append(plus);
    state.tiles.set("__new__", { el: plus });
  }

  const ordered = sortJobs(jobs);
  for (const job of ordered) {
    if (!state.tiles.has(job.job_id)) {
      const tile = createTile(job);
      state.tiles.set(job.job_id, tile);
      $("grid").append(tile.el);
    }
    updateTile(state.tiles.get(job.job_id), job);
  }

  // rimuovi tessere non più presenti
  const alive = new Set(ordered.map((j) => j.job_id));
  for (const [id, tile] of state.tiles) {
    if (id !== "__new__" && !alive.has(id)) { tile.el.remove(); state.tiles.delete(id); }
  }

  // riordina solo se serve
  const orderKey = ["__new__", ...ordered.map((j) => j.job_id)].join(",");
  if (orderKey !== state.orderKey) {
    state.orderKey = orderKey;
    for (const id of orderKey.split(",")) $("grid").append(state.tiles.get(id).el);
  }

  $("empty").classList.toggle("hidden", ordered.length > 0);
  applyFilter();
}

function applyFilter() {
  const needle = state.search.trim().toLowerCase();
  for (const [id, tile] of state.tiles) {
    if (id === "__new__") continue;
    tile.el.classList.toggle("hidden", !!needle && !(tile.el.dataset.search || "").includes(needle));
  }
}

function bindPlusDrop(tile) {
  ["dragenter", "dragover"].forEach((ev) =>
    tile.addEventListener(ev, (e) => { e.preventDefault(); tile.classList.add("st-new"); }));
  tile.addEventListener("drop", async (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    await uploadFile(file);
    if (state.document) openWizard(1);
  });
}

async function gridTick() {
  if (state.gridBusy) return;
  state.gridBusy = true;
  try {
    await refreshGrid();
    if (state.drawer.id) scheduleDrawerTick();
  } finally {
    state.gridBusy = false;
    const hasActive = state.jobs.some((j) => ACTIVE.includes(j.state));
    state.gridTimer = setTimeout(gridTick, hasActive ? 2500 : 12000);
  }
}

/* ── drawer di dettaglio ───────────────────────────────────────────────── */

async function openDrawer(jobId) {
  state.drawer.id = jobId;
  state.drawer.docId = null;
  setActivePageChip(null);
  $("drawer").classList.add("open");
  $("drawer-log").textContent = "";
  $("drawer-pages").textContent = "";
  $("drawer-pages-wrap").classList.add("hidden");
  setDrawerImage(`${API}/jobs/${jobId}/cover`, null);

  openDrawerStream(jobId);
  scheduleDrawerTick();

  const job = await fetchJob(jobId);
  if (!job || state.drawer.id !== jobId) return;
  state.drawer.docId = job.doc_id;
  renderDrawer(job);
  const doc = await fetchDocument(job.doc_id);
  if (state.drawer.id !== jobId) return;
  renderDrawerPages(job, doc);
}

/* La copertina mostra la prima pagina dell'intervallo; i chip permettono di
 * scorrere le altre. Le anteprime sono pagine *originali*: il risultato
 * tradotto resta il PDF/ZIP da scaricare. */

function setDrawerImage(src, fallback, onFallback) {
  const cover = $("drawer-cover");
  const preview = $("drawer-preview");
  preview.classList.remove("failed");
  cover.onerror = () => {
    cover.onerror = null;
    if (fallback) {
      cover.src = fallback;
    } else {
      preview.classList.add("failed");
    }
    if (onFallback) onFallback();
  };
  cover.src = src;
}

function setActivePageChip(chip) {
  document.querySelectorAll("#drawer-pages .page-chip").forEach((c) => {
    c.classList.toggle("active", c === chip);
  });
}

function showDrawerPage(index, chip) {
  const docId = state.drawer.docId;
  const jobId = state.drawer.id;
  if (!docId || !jobId) return;
  const fallback = `${API}/jobs/${jobId}/cover`;
  const thumb = `${API}/documents/${docId}/thumb?page=${index}&w=800`;
  setDrawerImage(thumb, fallback, () => setActivePageChip(null));
  setActivePageChip(chip);
}

function renderDrawerPages(job, doc) {
  const box = $("drawer-pages");
  box.textContent = "";
  const indices = job.pages || [];
  if (!indices.length) {
    $("drawer-pages-wrap").classList.add("hidden");
    return;
  }
  const labels = new Map();
  if (doc && Array.isArray(doc.pages)) {
    for (const page of doc.pages) labels.set(page.index, page.label);
  }
  const available = !!doc;  // documento rimosso => niente anteprime
  const LIMIT = 60;
  const chips = [];
  for (const index of indices.slice(0, LIMIT)) {
    const physical = index + 1;
    const label = labels.get(index);
    let chip;
    if (available) {
      chip = document.createElement("button");
      chip.type = "button";
      chip.title = `vedi la pagina ${physical} (originale, non tradotta)`;
      chip.addEventListener("click", () => showDrawerPage(index, chip));
    } else {
      chip = document.createElement("span");
      chip.title = "anteprima non disponibile: documento originale rimosso";
    }
    chip.className = "page-chip" + (available ? "" : " disabled");
    chip.textContent = label && label !== String(physical)
      ? `${physical} · «${label}»`
      : String(physical);
    box.append(chip);
    chips.push(chip);
  }
  if (indices.length > LIMIT) {
    const more = document.createElement("span");
    more.className = "page-more";
    more.textContent = `+${indices.length - LIMIT} altre`;
    box.append(more);
  }
  $("drawer-pages-wrap").classList.remove("hidden");
  setActivePageChip(chips[0] || null);
}

async function fetchDocument(docId) {
  if (!docId) return null;
  try {
    const response = await fetch(`${API}/documents/${docId}`);
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function closeDrawer() {
  state.drawer.id = null;
  $("drawer").classList.remove("open");
  if (state.drawer.source) { state.drawer.source.close(); state.drawer.source = null; }
  if (state.drawer.timer) { clearTimeout(state.drawer.timer); state.drawer.timer = null; }
}

function openDrawerStream(jobId) {
  if (state.drawer.source) state.drawer.source.close();
  const source = new EventSource(`${API}/jobs/${jobId}/events`);
  state.drawer.source = source;
  source.onmessage = (event) => {
    try { appendDrawerLog(formatEvent(JSON.parse(event.data))); } catch { /* ignora */ }
  };
  source.addEventListener("end", () => source.close());
  source.onerror = () => source.close();
}

function appendDrawerLog(line) {
  const log = $("drawer-log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
  log.textContent += line + "\n";
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function scheduleDrawerTick() {
  if (state.drawer.timer) clearTimeout(state.drawer.timer);
  const jobId = state.drawer.id;
  if (!jobId) return;
  const tick = async () => {
    if (state.drawer.id !== jobId) return;
    const job = await fetchJob(jobId);
    if (!job) return;
    renderDrawer(job);
    if (TERMINAL.includes(job.state)) {
      if (state.drawer.source) { state.drawer.source.close(); state.drawer.source = null; }
      return;
    }
    state.drawer.timer = setTimeout(tick, job.state === "scheduled" ? 30000 : 1500);
  };
  state.drawer.timer = setTimeout(tick, 400);
}

function renderDrawer(job) {
  $("drawer-title").textContent = job.output_name || job.job_id.slice(0, 8);
  const badge = $("drawer-badge");
  badge.textContent = STATE_LABEL[job.state] || job.state;
  badge.className = `badge ${job.state}`;
  $("drawer-meta").textContent = `${engineLabel(job.engine)} → ${job.dst_lang} · ${job.pages_done}/${job.pages_total} pagine (${job.pages_failed} fallite)`;
  $("drawer-fill").style.width = `${progressPct(job)}%`;
  let eta = "";
  if (job.state === "running" && job.started && job.pages_done > 0) {
    const elapsed = Date.now() - new Date(job.started).getTime();
    const remaining = (elapsed / job.pages_done) * (job.pages_total - job.pages_done);
    eta = remaining > 0 ? `ETA ~${humanDuration(remaining)}` : "";
  } else if (job.duration_ms) {
    eta = `durata ${humanDuration(job.duration_ms)}`;
  } else if (job.state === "queued" && job.queue_position) {
    eta = `posizione in coda: ${job.queue_position}`;
  } else if (job.state === "scheduled" && job.scheduled_at) {
    eta = `avvio ${formatTime(job.scheduled_at)}`;
  } else if (job.error) {
    eta = job.error;
  }
  $("drawer-eta").textContent = eta;
  $("drawer-cancel").disabled = !ACTIVE.includes(job.state);

  const link = $("drawer-download");
  if (job.state === "done" && job.download_url) {
    link.href = job.download_url;
    link.classList.remove("hidden");
  } else {
    link.classList.add("hidden");
  }
}

async function cancelDrawerJob() {
  if (!state.drawer.id) return;
  await fetch(`${API}/jobs/${state.drawer.id}/cancel`, { method: "POST" });
  appendDrawerLog("richiesta di annullamento inviata");
}

async function fetchJob(jobId) {
  try {
    const response = await fetch(`${API}/jobs/${jobId}`);
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function formatEvent(record) {
  const page = record.page_number ? `p${record.page_number} ` : "";
  const ms = record.duration_ms ? ` (${humanDuration(record.duration_ms)})` : "";
  const marker = record.level === "error" ? "✗" : record.level === "warning" ? "⚠" : "•";
  return `${marker} ${page}${record.message}${ms}`;
}

/* ── init ──────────────────────────────────────────────────────────────── */

function bind() {
  // wizard: file
  const drop = $("dropzone");
  const input = $("file-input");
  drop.addEventListener("click", () => input.click());
  input.addEventListener("change", () => uploadFile(input.files[0]));
  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) uploadFile(f); });

  // wizard: navigazione
  $("wizard-next").addEventListener("click", wizardNext);
  $("wizard-prev").addEventListener("click", () => showStep(Math.max(0, state.wizard.step - 1)));
  $("wizard-close").addEventListener("click", closeWizard);
  $("wizard-cancel").addEventListener("click", closeWizard);
  $("wizard").addEventListener("click", (e) => { if (e.target === $("wizard")) closeWizard(); });

  // wizard: pagine
  $("pages").addEventListener("input", () => {
    clearTimeout(state.previewTimer);
    state.previewTimer = setTimeout(() => { refreshPreview(); refreshEstimate(); }, 250);
  });
  document.querySelectorAll("#pages-preset button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#pages-preset button").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      if (btn.dataset.preset === "all") $("pages").value = "all";
      else { $("pages").value = ""; $("pages").focus(); }
      refreshPreview();
      refreshEstimate();
    });
  });

  for (const id of ["src-lang", "dst-lang"]) {
    $(id).addEventListener("change", refreshEstimate);
  }
  $("dst-lang").addEventListener("change", () => {
    if (!state.document) return;
    const stem = state.document.filename.replace(/\.pdf$/i, "");
    $("output-name").value = `${stem}_${$("dst-lang").value}`;
  });

  // wizard: output
  document.querySelectorAll("#range-mode button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#range-mode button").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      state.wizard.rangeMode = btn.dataset.rm;
      refreshSummary();
    });
  });
  document.querySelectorAll("#start-mode button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#start-mode button").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      state.wizard.startMode = btn.dataset.sm;
      $("start-at-wrap").classList.toggle("hidden", btn.dataset.sm !== "later");
      refreshSummary();
    });
  });
  $("start-at").addEventListener("change", refreshSummary);
  $("output-name").addEventListener("input", refreshSummary);

  // ricerca
  $("search").addEventListener("input", () => {
    state.search = $("search").value;
    applyFilter();
  });

  // drawer
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-cancel").addEventListener("click", cancelDrawerJob);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeWizard(); closeDrawer(); }
  });
}

(async function main() {
  bind();
  try {
    await loadMeta();
    await refreshGrid();
    const hasActive = state.jobs.some((j) => ACTIVE.includes(j.state));
    state.gridTimer = setTimeout(gridTick, hasActive ? 2500 : 12000);
  } catch (error) {
    toast(`Impossibile contattare il servizio: ${error}`);
  }
})();
