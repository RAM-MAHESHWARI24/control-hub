/**
 * Widget: Make It Yours — Card Hide/Reorder & Wall Kiosk Mode (Phase 4D)
 * Persists per-device card visibility and ordering in localStorage cleanly,
 * and manages read-only large-typography Wall Kiosk mode (`?kiosk=1` or toggle).
 */

import { $ } from "../shared/dom.js";
import { escapeHtml } from "../shared/formatters.js";
import { closeModal, openModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { setMenuOpen } from "./header.js";

const LAYOUT_KEY = "hub_card_layout_v1";
const KIOSK_KEY = "hub_kiosk_mode";

const CARD_CATALOG = [
  { id: "overview-apps-card", label: "Quick Launch Apps", view: "Overview" },
  { id: "family-whats-new-panel", label: "What's New & Requests", view: "Overview" },
  { id: "services-matrix-section", label: "Managed Containers", view: "Apps" },
  { id: "torrent-downloads-panel", label: "Current Downloads", view: "Apps" },
  { id: "media-hub-panel", label: "Media Pipeline & Indexers", view: "Apps" },
  { id: "updates-panel", label: "Release Updates", view: "Apps" },
  { id: "history-insights-panel", label: "History & Monthly Insights", view: "System" },
  { id: "integrations-panel", label: "Home Assistant & UPS", view: "System" },
];

function readPrefs() {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return { hidden: [], order: {} };
    const parsed = JSON.parse(raw);
    return {
      hidden: Array.isArray(parsed.hidden) ? parsed.hidden : [],
      order: parsed.order && typeof parsed.order === "object" ? parsed.order : {},
    };
  } catch (_) {
    return { hidden: [], order: {} };
  }
}

function savePrefs(prefs) {
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(prefs));
  } catch (_) { /* ignore */ }
}

export function applyCardLayout() {
  const prefs = readPrefs();
  const hiddenSet = new Set(prefs.hidden || []);

  CARD_CATALOG.forEach((item, defaultIdx) => {
    const card = $(item.id);
    if (!card) return;
    card.dataset.userHidden = hiddenSet.has(item.id) ? "true" : "false";
    const ord = prefs.order && typeof prefs.order[item.id] === "number" ? prefs.order[item.id] : defaultIdx;
    card.style.order = String(ord);
  });
}

function renderCustomizeModalList() {
  const box = $("customize-cards-list");
  if (!box) return;
  const prefs = readPrefs();
  const hiddenSet = new Set(prefs.hidden || []);
  const ordered = [...CARD_CATALOG].sort((a, b) => {
    const oa = typeof prefs.order[a.id] === "number" ? prefs.order[a.id] : 999;
    const ob = typeof prefs.order[b.id] === "number" ? prefs.order[b.id] : 999;
    return oa - ob;
  });

  box.innerHTML = ordered.map((item, idx) => {
    const isHidden = hiddenSet.has(item.id);
    return `
      <div class="panel customize-card-row">
        <div class="customize-card-meta">
          <span class="badge badge-neutral">${escapeHtml(item.view)}</span>
          <strong>${escapeHtml(item.label)}</strong>
        </div>
        <div class="customize-card-actions">
          <button type="button" class="btn-secondary btn-cust-up" data-card-id="${escapeHtml(item.id)}" ${idx === 0 ? "disabled" : ""} aria-label="Move ${escapeHtml(item.label)} up">Up</button>
          <button type="button" class="btn-secondary btn-cust-down" data-card-id="${escapeHtml(item.id)}" ${idx === ordered.length - 1 ? "disabled" : ""} aria-label="Move ${escapeHtml(item.label)} down">Down</button>
          <button type="button" class="btn-secondary btn-cust-toggle" data-card-id="${escapeHtml(item.id)}" aria-pressed="${!isHidden}">
            ${isHidden ? "Show" : "Hide"}
          </button>
        </div>
      </div>
    `;
  }).join("");

  const moveCard = (cardId, dir) => {
    const ids = ordered.map((c) => c.id);
    const curIdx = ids.indexOf(cardId);
    const nxtIdx = curIdx + dir;
    if (curIdx < 0 || nxtIdx < 0 || nxtIdx >= ids.length) return;
    [ids[curIdx], ids[nxtIdx]] = [ids[nxtIdx], ids[curIdx]];
    const nextPrefs = readPrefs();
    ids.forEach((id, i) => { nextPrefs.order[id] = i; });
    savePrefs(nextPrefs);
    applyCardLayout();
    renderCustomizeModalList();
  };

  box.querySelectorAll(".btn-cust-up").forEach((b) => {
    b.addEventListener("click", () => moveCard(b.getAttribute("data-card-id"), -1));
  });
  box.querySelectorAll(".btn-cust-down").forEach((b) => {
    b.addEventListener("click", () => moveCard(b.getAttribute("data-card-id"), 1));
  });
  box.querySelectorAll(".btn-cust-toggle").forEach((b) => {
    b.addEventListener("click", () => {
      const id = b.getAttribute("data-card-id");
      const nextPrefs = readPrefs();
      const set = new Set(nextPrefs.hidden || []);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      nextPrefs.hidden = Array.from(set);
      savePrefs(nextPrefs);
      applyCardLayout();
      renderCustomizeModalList();
    });
  });
}

export function setKioskMode(enabled, persist = true) {
  const on = Boolean(enabled);
  document.documentElement.dataset.kiosk = on ? "true" : "false";
  const exitBtn = $("btn-kiosk-exit");
  if (exitBtn) exitBtn.hidden = !on;
  const toggleBtn = $("btn-kiosk-toggle");
  if (toggleBtn) toggleBtn.setAttribute("aria-pressed", on ? "true" : "false");
  if (persist) {
    try { localStorage.setItem(KIOSK_KEY, on ? "true" : "false"); } catch (_) { /* ignore */ }
  }
}

export function setupCustomizeAndKiosk() {
  applyCardLayout();

  const modal = $("customize-layout-modal");
  const openBtn = $("btn-open-customize");
  const closeBtn = $("customize-modal-close");
  const dismissBtn = $("customize-modal-dismiss");
  const resetBtn = $("btn-customize-reset");

  if (openBtn && modal) {
    openBtn.addEventListener("click", () => {
      setMenuOpen(false);
      renderCustomizeModalList();
      openModal(modal, openBtn);
    });
  }
  if (closeBtn && modal) closeBtn.addEventListener("click", () => closeModal(modal));
  if (dismissBtn && modal) dismissBtn.addEventListener("click", () => closeModal(modal));
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      try { localStorage.removeItem(LAYOUT_KEY); } catch (_) { /* ignore */ }
      applyCardLayout();
      renderCustomizeModalList();
      showToast("Layout Reset", "All cards restored to default order and visibility.", "success");
    });
  }

  // Kiosk mode via URL (?kiosk=1) or localStorage
  let initialKiosk = false;
  try {
    const params = new URLSearchParams(window.location.search || (window.location.hash.split("?")[1] || ""));
    if (params.get("kiosk") === "1") initialKiosk = true;
    else if (params.get("kiosk") === "0") initialKiosk = false;
    else initialKiosk = localStorage.getItem(KIOSK_KEY) === "true";
  } catch (_) {
    initialKiosk = false;
  }
  setKioskMode(initialKiosk, false);

  const toggleBtn = $("btn-kiosk-toggle");
  const exitBtn = $("btn-kiosk-exit");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      setMenuOpen(false);
      const next = document.documentElement.dataset.kiosk !== "true";
      setKioskMode(next, true);
      if (next && document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else if (!next && document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }
    });
  }
  if (exitBtn) {
    exitBtn.addEventListener("click", () => {
      setKioskMode(false, true);
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }
    });
  }
}
