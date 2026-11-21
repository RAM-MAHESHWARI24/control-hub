/**
 * Widget: Indexer picker (Prowlarr)
 * Shows a one-time "Pick indexers" banner while Prowlarr has no indexers,
 * syncs desktop & dropdown Indexers button, and renders an accessible modal.
 */

import { $ } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { closeModal, openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { state } from "../state.js";

const DISMISS_KEY = "homelab_indexer_banner_dismissed";

const banner = $("indexer-banner");
const bannerOpen = $("btn-indexer-banner-open");
const bannerSkip = $("btn-indexer-banner-skip");
const headerBtn = $("btn-open-indexers");
const menuItemBtn = $("menu-item-indexers");

const modal = $("indexer-modal");
const modalClose = $("indexer-modal-close");
const modalCancel = $("indexer-modal-cancel");
const modalAdd = $("indexer-modal-add");
const search = $("indexer-search");
const filterProtocol = $("indexer-filter-protocol");
const filterPrivacy = $("indexer-filter-privacy");
const list = $("indexer-list");
const summary = $("indexer-summary");
const resultBox = $("indexer-results");
const forceCheck = $("indexer-force-save");

let available = [];
let configured = new Set();
const selected = new Map();

function dismissed() {
  try { return localStorage.getItem(DISMISS_KEY) === "1"; } catch (_) { return false; }
}

export async function fetchIndexerStatus() {
  if (!banner && !headerBtn && !menuItemBtn) return true;
  try {
    const res = await fetch(ENDPOINTS.indexersStatus);
    if (!res.ok) return false;
    const data = await res.json();
    const installed = Boolean(data.installed);
    state.modules.indexers = installed;
    if (headerBtn) headerBtn.style.display = installed ? "" : "none";
    if (menuItemBtn) menuItemBtn.style.display = installed ? "" : "none";
    if (banner) {
      const show = installed && data.reachable && data.configured === 0 && !dismissed();
      state.indexersNeedsSetup = show;
      banner.style.display = show ? "flex" : "none";
    }
    return true;
  } catch (_) {
    return false;
  }
}

function renderList() {
  if (!list) return;
  const q = (search?.value || "").trim().toLowerCase();
  const proto = filterProtocol?.value || "all";
  const priv = filterPrivacy?.value || "all";
  const rows = available.filter((ix) =>
    (!q || ix.name.toLowerCase().includes(q) || (ix.description || "").toLowerCase().includes(q)) &&
    (proto === "all" || ix.protocol === proto) &&
    (priv === "all" || ix.privacy === priv)
  );
  if (!rows.length) {
    list.innerHTML = '<div class="empty-state">No indexers match this search.</div>';
    updateSummary();
    return;
  }
  list.innerHTML = rows.slice(0, 400).map((ix) => {
    const isDone = configured.has(ix.name);
    const isSel = selected.has(ix.name);
    const fields = (ix.fields || []).map((f) => {
      const val = selected.get(ix.name)?.fields?.[f.name] ?? "";
      return `<label class="indexer-field"><span>${escapeHtml(f.label)}</span>
        <input type="${f.type === "password" ? "password" : "text"}" data-ix="${escapeHtml(ix.name)}" data-field="${escapeHtml(f.name)}" value="${escapeHtml(val)}" autocomplete="off" placeholder="${escapeHtml(f.help || "")}"></label>`;
    }).join("");
    return `
      <div class="indexer-row ${isDone ? "is-configured" : ""} ${isSel ? "is-selected" : ""}" data-name="${escapeHtml(ix.name)}">
        <label class="indexer-row-main">
          <input type="checkbox" class="indexer-check" data-name="${escapeHtml(ix.name)}" ${isSel ? "checked" : ""} ${isDone ? "disabled" : ""}>
          <span class="indexer-name">${escapeHtml(ix.name)}</span>
          <span class="indexer-badge badge-${escapeHtml(ix.protocol || "torrent")}">${escapeHtml(ix.protocol || "")}</span>
          <span class="indexer-badge badge-${escapeHtml(ix.privacy || "public")}">${escapeHtml(ix.privacy || "")}</span>
          ${ix.language ? `<span class="text-muted">${escapeHtml(ix.language)}</span>` : ""}
          ${isDone ? '<span class="badge-status-synced">configured</span>' : ""}
        </label>
        ${ix.description ? `<div class="indexer-desc">${escapeHtml(ix.description)}</div>` : ""}
        ${isSel && fields ? `<div class="indexer-fields">${fields}</div>` : ""}
      </div>`;
  }).join("") + (rows.length > 400 ? `<div class="empty-state">Showing 400 of ${rows.length}; refine the search.</div>` : "");
  updateSummary();
}

function updateSummary() {
  if (summary) summary.textContent = `${selected.size} selected · ${configured.size} already configured · ${available.length} available`;
  if (modalAdd) modalAdd.disabled = selected.size === 0;
}

async function openIndexerModal(triggerEl = null) {
  if (!modal) return;
  openModal(modal, triggerEl);
  if (resultBox) resultBox.innerHTML = "";
  if (list) list.innerHTML = '<div class="empty-state">Loading Prowlarr’s indexer definitions…</div>';
  try {
    const res = await fetch(ENDPOINTS.indexersAvailable);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    available = data.indexers || [];
    configured = new Set(data.configured || []);
    renderList();
  } catch (err) {
    if (list) list.innerHTML = `<div class="empty-state">Could not load the list: ${escapeHtml(err.message)}</div>`;
  }
}

async function addSelected() {
  if (!selected.size) return;
  const payload = {
    indexers: [...selected.entries()].map(([name, v]) => ({ name, fields: v.fields || {} })),
    force: Boolean(forceCheck?.checked),
  };
  modalAdd.disabled = true;
  modalAdd.textContent = "Adding…";
  try {
    const res = await fetch(ENDPOINTS.indexersAdd, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const lines = (data.results || []).map((r) => `<div class="${r.ok ? "ok" : "fail"}">${r.ok ? "✓" : "✗"} ${escapeHtml(r.name)} — ${escapeHtml(r.detail)}</div>`);
    if (resultBox) resultBox.innerHTML = lines.join("");
    (data.results || []).forEach((r) => {
      if (r.ok) {
        configured.add(r.name);
        selected.delete(r.name);
      }
    });
    renderList();
    if (data.added > 0) {
      showToast("Indexers added", `${data.added} indexer(s) added to Prowlarr and synced to Radarr/Sonarr.`, "success");
      try { localStorage.setItem(DISMISS_KEY, "1"); } catch (_) { /* ignore */ }
      fetchIndexerStatus();
    }
  } catch (err) {
    if (resultBox) resultBox.innerHTML = `<div class="fail">✗ ${escapeHtml(err.message)}</div>`;
  } finally {
    modalAdd.textContent = "Add selected";
    updateSummary();
  }
}

export function setupIndexers() {
  registerModal(modal, { closeButtons: [modalClose, modalCancel] });

  if (bannerOpen) bannerOpen.addEventListener("click", () => openIndexerModal(bannerOpen));
  if (headerBtn) headerBtn.addEventListener("click", () => openIndexerModal(headerBtn));
  if (bannerSkip) {
    bannerSkip.addEventListener("click", () => {
      try { localStorage.setItem(DISMISS_KEY, "1"); } catch (_) { /* ignore */ }
      if (banner) banner.style.display = "none";
      showToast("Skipped for now", "Add indexers any time from Indexers in the header or menu.", "info");
    });
  }
  if (modalAdd) modalAdd.addEventListener("click", addSelected);
  [search, filterProtocol, filterPrivacy].forEach((el) => el && el.addEventListener("input", renderList));

  if (list) {
    list.addEventListener("change", (e) => {
      const t = e.target;
      if (t.classList.contains("indexer-check")) {
        const name = t.dataset.name;
        if (t.checked) selected.set(name, { fields: {} });
        else selected.delete(name);
        renderList();
      }
    });
    list.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset && t.dataset.ix && t.dataset.field) {
        const entry = selected.get(t.dataset.ix) || { fields: {} };
        entry.fields[t.dataset.field] = t.value;
        selected.set(t.dataset.ix, entry);
      }
    });
  }
}

export function closeIndexerModal() {
  closeModal(modal);
}
