/* Pagina /settings: configurazione del servizio (solo dalla macchina locale).
 *
 * Legge lo schema da GET /api/v1/settings e salva con PUT /api/v1/settings.
 * La chiave OpenRouter è un segreto: non viene mai ricevuta dal server, si può
 * solo scrivere, verificare o rimuovere.
 */
"use strict";

const API = "/api/v1";
const state = { data: null, removeKey: false, initial: {} };

const $ = (sel, root = document) => root.querySelector(sel);

function esc(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, options) {
  const response = await fetch(API + path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || `errore ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function banner(message, kind = "ok") {
  const el = $("#settings-banner");
  el.className = `settings-banner ${kind}`;
  el.textContent = message;
  el.classList.remove("hidden");
}

function badge(spec) {
  if (spec.secret) {
    return spec.present
      ? '<span class="badge ok">impostata</span>'
      : '<span class="badge">assente</span>';
  }
  if (spec.env_override) return '<span class="badge warn">dall\'ambiente</span>';
  if (!spec.in_file) return '<span class="badge">default</span>';
  return "";
}

function control(spec) {
  const name = esc(spec.name);
  if (spec.kind === "bool") {
    const on = String(spec.value).toLowerCase() === "true" ? "checked" : "";
    return `<label class="switch"><input type="checkbox" data-name="${name}" ${on}> attivo</label>`;
  }
  if (spec.kind === "choice") {
    const options = spec.choices
      .map((c) => `<option value="${esc(c)}" ${c === spec.value ? "selected" : ""}>${esc(c)}</option>`)
      .join("");
    return `<select data-name="${name}">${options}</select>`;
  }
  const type = spec.kind === "int" || spec.kind === "float" ? "number" : "text";
  const min = spec.minimum !== null && spec.minimum !== undefined ? ` min="${spec.minimum}"` : "";
  const max = spec.maximum !== null && spec.maximum !== undefined ? ` max="${spec.maximum}"` : "";
  const step = spec.kind === "float" ? ' step="any"' : "";
  return `<input type="${type}" data-name="${name}" value="${esc(spec.value)}"${min}${max}${step}>`;
}

function rowHtml(spec) {
  if (spec.secret) {
    return `
      <div class="settings-row" data-secret="1">
        <div class="settings-label">
          <b>${esc(spec.name)}</b> ${badge(spec)}
          <div class="settings-desc">${esc(spec.desc_it)}</div>
        </div>
        <div class="settings-control">
          <div class="key-row">
            <input type="password" id="key-input" autocomplete="off" spellcheck="false"
                   placeholder="${spec.present ? "••••••••  (impostata)" : "sk-or-…"}">
            <button type="button" class="btn small" id="key-reveal" title="Mostra/nascondi">👁</button>
            <button type="button" class="btn small" id="key-verify">Verifica</button>
            <button type="button" class="btn small ghost" id="key-remove">Rimuovi</button>
          </div>
          <p class="settings-status" id="key-status"></p>
        </div>
      </div>`;
  }
  return `
    <div class="settings-row">
      <div class="settings-label">
        <b>${esc(spec.name)}</b> ${badge(spec)}
        <div class="settings-desc">${esc(spec.desc_it)}</div>
      </div>
      <div class="settings-control">${control(spec)}</div>
    </div>`;
}

function render(data) {
  state.data = data;
  state.initial = {};
  data.groups.forEach((group) =>
    group.settings.forEach((spec) => {
      if (!spec.secret) state.initial[spec.name] = String(spec.value);
    })
  );
  $("#settings-path").textContent = `file: ${data.config_path}`;
  $("#settings-groups").innerHTML = data.groups
    .map(
      (group) => `
      <section class="settings-group">
        <h2>${esc(group.title_it)}</h2>
        ${group.settings.map(rowHtml).join("")}
      </section>`
    )
    .join("");
  $("#settings-loading").classList.add("hidden");
  $("#settings-form").classList.remove("hidden");
  bindKey();
}

function bindKey() {
  const reveal = $("#key-reveal");
  const verify = $("#key-verify");
  const remove = $("#key-remove");
  if (reveal) {
    reveal.addEventListener("click", () => {
      const input = $("#key-input");
      input.type = input.type === "password" ? "text" : "password";
    });
  }
  if (remove) {
    remove.addEventListener("click", () => {
      state.removeKey = true;
      const input = $("#key-input");
      if (input) input.value = "";
      $("#key-status").textContent = "La chiave verrà rimossa quando salvi.";
    });
  }
  if (verify) verify.addEventListener("click", verifyKey);
}

async function verifyKey() {
  const status = $("#key-status");
  const typed = ($("#key-input")?.value || "").trim();
  status.textContent = "Verifica in corso…";
  status.className = "settings-status";
  try {
    const body = typed
      ? await api("/llm/validate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_key: typed }),
        })
      : await api("/settings/verify-key", { method: "POST" });
    const ok = body.status === "ok";
    const warn = body.status === "warn";
    status.className = `settings-status ${ok ? "ok" : warn ? "warn" : "err"}`;
    const label = { ok: "chiave e modello OK", warn: "attenzione", fail: "problema" }[body.status] || body.status;
    status.textContent = `${label} — chiave: ${body.key_valid.status}, credito: ${body.credits.status}, modello: ${body.model.status}`;
  } catch (error) {
    status.className = "settings-status err";
    status.textContent = `Verifica non riuscita: ${error.message}`;
  }
}

function collect() {
  const values = {};
  document.querySelectorAll("[data-name]").forEach((el) => {
    const name = el.dataset.name;
    const value = el.type === "checkbox" ? (el.checked ? "true" : "false") : el.value;
    // Salva solo ciò che è cambiato: il file resta pulito.
    if (value !== state.initial[name]) values[name] = value;
  });
  const reset = [];
  const typed = ($("#key-input")?.value || "").trim();
  if (typed) values.OPENROUTER_API_KEY = typed;
  if (state.removeKey) reset.push("OPENROUTER_API_KEY");
  return { values, reset };
}

async function load() {
  try {
    render(await api("/settings"));
  } catch (error) {
    $("#settings-loading").className = "settings-note err";
    $("#settings-loading").textContent = `Impossibile leggere la configurazione: ${error.message}`;
  }
}

async function save(event) {
  event.preventDefault();
  const button = $("#settings-save");
  button.disabled = true;
  try {
    const { values, reset } = collect();
    await api("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values, reset }),
    });
    state.removeKey = false;
    $("#settings-restart").classList.remove("hidden");
    banner("Impostazioni salvate.", "ok");
    await load();
  } catch (error) {
    banner(`Non salvato: ${error.message}`, "err");
  } finally {
    button.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#settings-form").addEventListener("submit", save);
  $("#settings-reload").addEventListener("click", () => {
    $("#settings-restart").classList.add("hidden");
    $("#settings-banner").classList.add("hidden");
    load();
  });
  load();
});
