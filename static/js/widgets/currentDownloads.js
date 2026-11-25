/**
 * Widget: Current Downloads & Per-Torrent Controls (qBittorrent 4.x & 5.x, Phase 3A)
 * Keyed zero-flicker rendering, per-torrent pause/resume/priority/delete controls,
 * and global/scheduled alternative speed limits.
 */

import { $, confirmAction, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { renderOverview } from "./overview.js";

const torrentTotalDl = $("torrent-total-dl");
const torrentTotalUp = $("torrent-total-up");
const torrentDownloadsList = $("torrent-downloads-list");
const torrentStatusBanner = $("torrent-status-banner");
const btnPauseTorrents = $("btn-pause-torrents");
const torrentBtnLabel = $("torrent-btn-label");
const btnTorrentAltSpeed = $("btn-torrent-alt-speed");
const btnTorrentLimits = $("btn-torrent-limits");
const limitsModal = $("torrent-limits-modal");
const limitsClose = $("torrent-limits-close");
const limitsDismiss = $("torrent-limits-dismiss");
const limitsForm = $("torrent-limits-form");

let lastRenderedKey = "";

async function runTorrentAction(hash, name, action, triggerEl = null, deleteFiles = false) {
  if (!hash) return;
  if (action === "delete") {
    const ok = await confirmAction({
      title: deleteFiles ? "Delete Torrent & Files?" : "Remove Torrent from Queue?",
      message: deleteFiles
        ? `Delete "${name}" and erase downloaded files from disk?`
        : `Remove "${name}" from qBittorrent (downloaded files stay on disk)?`,
      confirmLabel: deleteFiles ? "Delete Files" : "Remove Torrent",
      danger: deleteFiles,
      triggerEl,
    });
    if (!ok) return;
  }

  if (triggerEl) triggerEl.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.torrentAction(hash), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, delete_files: deleteFiles }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast("Torrent Updated", `${name}: ${action.replace("_", " ")} applied.`, "success");
      lastRenderedKey = "";
    } else {
      showToast("Action Failed", data.error || "qBittorrent rejected the request.", "warning");
    }
  } catch (_) {
    showToast("qBittorrent Error", "Could not reach Control Hub.", "danger");
  } finally {
    if (triggerEl) triggerEl.disabled = false;
  }
}

export function renderTorrents(tq = {}) {
  const dlSum = typeof tq.collective_dl_mbs === "number" ? tq.collective_dl_mbs : 0.0;
  const upSum = typeof tq.collective_up_mbs === "number" ? tq.collective_up_mbs : 0.0;
  const items = Array.isArray(tq.items) ? tq.items : [];
  const qbStatus = tq.status || "connected";
  const isConnected = qbStatus === "connected" || qbStatus === "unknown";

  state.torrentsActiveCount = items.length;
  state.torrentsDlMbs = dlSum;
  state.torrentsStatus = qbStatus;
  if (typeof tq.all_paused === "boolean") {
    state.torrentsPaused = tq.all_paused;
  }

  if (torrentTotalDl) torrentTotalDl.textContent = dlSum.toFixed(2);
  if (torrentTotalUp) torrentTotalUp.textContent = upSum.toFixed(2);

  if (btnPauseTorrents) {
    btnPauseTorrents.disabled = !isConnected || (tq.total_count === 0 && items.length === 0);
  }
  if (torrentBtnLabel) {
    torrentBtnLabel.textContent = state.torrentsPaused ? "Resume All" : "Pause All";
  }

  if (torrentStatusBanner) {
    if (!isConnected && tq.status_message) {
      torrentStatusBanner.textContent = tq.status_message;
      torrentStatusBanner.hidden = false;
    } else {
      torrentStatusBanner.hidden = true;
    }
  }

  let summaryTxt = "Queue idle";
  if (!isConnected) {
    summaryTxt = qbStatus === "auth_failed"
      ? "qBittorrent login rejected"
      : (qbStatus === "not_configured" ? "qBittorrent not configured" : "qBittorrent unreachable");
  } else if (items.length > 0) {
    summaryTxt = `${items.length} active · ↓ ${dlSum.toFixed(2)} MB/s`;
  } else if (tq.paused_count > 0) {
    summaryTxt = `${tq.paused_count} paused in queue`;
  }
  setCardSummary("torrent-downloads-panel", summaryTxt);

  if (!torrentDownloadsList) return;

  const key = JSON.stringify([qbStatus, tq.status_message, tq.paused_count, items]);
  if (key === lastRenderedKey && torrentDownloadsList.children.length > 0) return;
  lastRenderedKey = key;

  if (!isConnected) {
    torrentDownloadsList.innerHTML = `<div class="empty-state">${escapeHtml(tq.status_message || "qBittorrent is unavailable.")}</div>`;
    renderOverview();
    return;
  }

  if (items.length === 0) {
    const idleNote = tq.paused_count > 0
      ? `${tq.paused_count} torrent${tq.paused_count === 1 ? "" : "s"} paused · Click Resume All to restart.`
      : "No active torrent downloads · qBittorrent idle";
    torrentDownloadsList.innerHTML = `<div class="empty-state">${escapeHtml(idleNote)}</div>`;
    renderOverview();
    return;
  }

  const existingRows = new Map();
  torrentDownloadsList.querySelectorAll("[data-torrent-key]").forEach((row) => {
    existingRows.set(row.dataset.torrentKey, row);
  });

  if (torrentDownloadsList.querySelector(".empty-state")) {
    torrentDownloadsList.replaceChildren();
  }

  const activeKeys = new Set();

  items.forEach((t) => {
    const tKey = t.hash || t.name;
    activeKeys.add(tKey);

    const stateStr = (t.state || "").toLowerCase();
    const isStalled = stateStr.includes("stalled");
    const isPaused = stateStr.includes("paused") || stateStr.includes("stopped");
    const isDownloading = !isPaused && (stateStr.includes("dl") || (t.dl_mbs && t.dl_mbs > 0));
    const statusClass = isDownloading ? "downloading" : (isStalled ? "stalled" : "");
    const statusText = isPaused ? "Paused" : (isDownloading ? "Downloading" : (isStalled ? "Stalled" : (t.state || "Active")));
    const dlRate = (typeof t.dl_mbs === "number" ? t.dl_mbs : 0.0).toFixed(2);
    const upRate = (typeof t.up_mbs === "number" ? t.up_mbs : 0.0).toFixed(2);
    const pct = Math.min(100, Math.max(0, Number(t.progress) || 0));
    const hasHash = Boolean(t.hash && /^[0-9a-fA-F]{32,64}$/.test(t.hash));

    let card = existingRows.get(tKey);
    if (!card) {
      card = document.createElement("div");
      card.className = "torrent-item-card";
      card.dataset.torrentKey = tKey;
      card.innerHTML = `
        <div class="torrent-top-row">
          <div class="torrent-name-wrap">
            <span class="torrent-name"></span>
            <span class="torrent-cat-badge"></span>
          </div>
          <div class="torrent-speed-badge font-mono"></div>
        </div>
        <div class="torrent-progress-bar-bg">
          <div class="torrent-progress-bar-fill"></div>
        </div>
        <div class="torrent-bottom-row">
          <span class="torrent-prog-text font-mono"></span>
          <span class="torrent-eta-wrap"></span>
        </div>
        <div class="torrent-item-actions" ${hasHash ? "" : "hidden"}>
          <button type="button" class="btn-secondary btn-tor-toggle"></button>
          <button type="button" class="btn-secondary btn-tor-up">Priority Up</button>
          <button type="button" class="btn-secondary btn-tor-down">Priority Down</button>
          <button type="button" class="btn-ghost btn-tor-remove">Remove</button>
          <button type="button" class="btn-ghost btn-tor-delete-files">Delete + Files</button>
        </div>
      `;
      torrentDownloadsList.appendChild(card);
    }

    const nameEl = card.querySelector(".torrent-name");
    if (nameEl) {
      nameEl.textContent = t.name;
      nameEl.title = t.name;
    }
    const catEl = card.querySelector(".torrent-cat-badge");
    if (catEl) {
      const prio = Number(t.priority) > 0 ? ` · #${t.priority}` : "";
      catEl.textContent = `${t.category || "General"}${prio}`;
    }

    const speedEl = card.querySelector(".torrent-speed-badge");
    if (speedEl) {
      speedEl.textContent = t.up_mbs > 0 ? `↓ ${dlRate} · ↑ ${upRate} MB/s` : `↓ ${dlRate} MB/s`;
    }
    const fillEl = card.querySelector(".torrent-progress-bar-fill");
    if (fillEl) fillEl.style.width = `${pct}%`;

    const progEl = card.querySelector(".torrent-prog-text");
    if (progEl) progEl.textContent = `${pct}% (${t.completed_gb} / ${t.size_gb} GB)`;

    const etaWrap = card.querySelector(".torrent-eta-wrap");
    if (etaWrap) {
      etaWrap.innerHTML = `ETA: <strong class="font-mono">${escapeHtml(t.eta)}</strong> &middot; <span class="torrent-status-pill ${statusClass}">${escapeHtml(statusText)}</span>`;
    }

    const actWrap = card.querySelector(".torrent-item-actions");
    if (actWrap && hasHash) {
      actWrap.hidden = false;
      const btnTog = actWrap.querySelector(".btn-tor-toggle");
      const btnUp = actWrap.querySelector(".btn-tor-up");
      const btnDown = actWrap.querySelector(".btn-tor-down");
      const btnRem = actWrap.querySelector(".btn-tor-remove");
      const btnDel = actWrap.querySelector(".btn-tor-delete-files");
      if (btnTog) {
        btnTog.textContent = isPaused ? "Resume" : "Pause";
        btnTog.onclick = () => runTorrentAction(t.hash, t.name, isPaused ? "resume" : "pause", btnTog);
      }
      if (btnUp) btnUp.onclick = () => runTorrentAction(t.hash, t.name, "increase_prio", btnUp);
      if (btnDown) btnDown.onclick = () => runTorrentAction(t.hash, t.name, "decrease_prio", btnDown);
      if (btnRem) btnRem.onclick = () => runTorrentAction(t.hash, t.name, "delete", btnRem, false);
      if (btnDel) btnDel.onclick = () => runTorrentAction(t.hash, t.name, "delete", btnDel, true);
    }
  });

  existingRows.forEach((row, keyName) => {
    if (!activeKeys.has(keyName)) row.remove();
  });

  renderOverview();
}

export async function toggleTorrents() {
  const nextAction = state.torrentsPaused ? "resume" : "pause";
  if (btnPauseTorrents) btnPauseTorrents.disabled = true;

  try {
    const res = await fetch(ENDPOINTS.torrentsToggle, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: nextAction }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      state.torrentsPaused = nextAction === "pause";
      if (torrentBtnLabel) {
        torrentBtnLabel.textContent = state.torrentsPaused ? "Resume All" : "Pause All";
      }
      showToast(
        state.torrentsPaused ? "Torrents Paused" : "Torrents Resumed",
        data.message || `All torrents ${nextAction}d in qBittorrent.`,
        "success"
      );
    } else {
      showToast("Error", data.error || "Failed to toggle torrents", "danger");
    }
  } catch (_) {
    showToast("Error", "Could not connect to qBittorrent API", "danger");
  } finally {
    if (btnPauseTorrents) btnPauseTorrents.disabled = false;
  }
}

async function openLimitsModal(triggerEl = null) {
  if (!limitsModal) return;
  openModal(limitsModal, triggerEl);
  try {
    const res = await fetch(ENDPOINTS.torrentsLimits);
    const data = await res.json();
    if (res.ok && data.success) {
      const setVal = (id, v) => { const el = $(id); if (el) el.value = String(v ?? 0); };
      setVal("inp-dl-limit-kbps", data.dl_limit_kbps);
      setVal("inp-up-limit-kbps", data.up_limit_kbps);
      setVal("inp-alt-dl-kbps", data.alt_dl_limit_kbps);
      setVal("inp-alt-up-kbps", data.alt_up_limit_kbps);
      setVal("inp-sched-from-hour", data.schedule_from_hour);
      setVal("inp-sched-to-hour", data.schedule_to_hour);
      const chk = $("chk-torrent-scheduler");
      if (chk) chk.checked = Boolean(data.scheduler_enabled);
      if (btnTorrentAltSpeed) {
        btnTorrentAltSpeed.setAttribute("aria-pressed", data.alt_speed_enabled ? "true" : "false");
        btnTorrentAltSpeed.textContent = data.alt_speed_enabled ? "Alt Speed: On" : "Alt Speed";
      }
    }
  } catch (_) {
    /* Non-fatal if qBittorrent unreachable */
  }
}

async function toggleAltSpeed() {
  if (!btnTorrentAltSpeed) return;
  btnTorrentAltSpeed.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.torrentsLimits, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ toggle_alt_speed: true }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const next = btnTorrentAltSpeed.getAttribute("aria-pressed") !== "true";
      btnTorrentAltSpeed.setAttribute("aria-pressed", next ? "true" : "false");
      btnTorrentAltSpeed.textContent = next ? "Alt Speed: On" : "Alt Speed";
      showToast("Speed Mode Switched", next ? "Alternative speed cap active." : "Global speed limits active.", "info");
    } else {
      showToast("Toggle Failed", data.error || "Could not switch speed mode.", "warning");
    }
  } catch (_) {
    showToast("Error", "Could not reach Control Hub.", "danger");
  } finally {
    btnTorrentAltSpeed.disabled = false;
  }
}

export function setupCurrentDownloads() {
  if (btnPauseTorrents) {
    btnPauseTorrents.addEventListener("click", toggleTorrents);
  }
  if (btnTorrentAltSpeed) {
    btnTorrentAltSpeed.addEventListener("click", toggleAltSpeed);
  }
  if (limitsModal) {
    registerModal(limitsModal, { closeButtons: [limitsClose, limitsDismiss] });
  }
  if (btnTorrentLimits) {
    btnTorrentLimits.addEventListener("click", () => openLimitsModal(btnTorrentLimits));
  }
  if (limitsForm) {
    limitsForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const saveBtn = $("btn-save-torrent-limits");
      if (saveBtn) saveBtn.disabled = true;
      try {
        const res = await fetch(ENDPOINTS.torrentsLimits, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dl_limit_kbps: Number($("inp-dl-limit-kbps")?.value || 0),
            up_limit_kbps: Number($("inp-up-limit-kbps")?.value || 0),
            alt_dl_limit_kbps: Number($("inp-alt-dl-kbps")?.value || 0),
            alt_up_limit_kbps: Number($("inp-alt-up-kbps")?.value || 0),
            scheduler_enabled: Boolean($("chk-torrent-scheduler")?.checked),
            schedule_from_hour: Number($("inp-sched-from-hour")?.value || 18),
            schedule_to_hour: Number($("inp-sched-to-hour")?.value || 23),
          }),
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast("Limits Saved", "Updated qBittorrent global and evening alternative speed caps.", "success");
          if (limitsDismiss) limitsDismiss.click();
        } else {
          showToast("Save Failed", data.error || "Could not save limits.", "warning");
        }
      } catch (_) {
        showToast("Error", "Could not reach Control Hub.", "danger");
      } finally {
        if (saveBtn) saveBtn.disabled = false;
      }
    });
  }
}
