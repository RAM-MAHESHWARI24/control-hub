/**
 * Widget: Current Downloads (qBittorrent 4.x & 5.x Ingest Pipeline)
 * Keyed zero-flicker rendering, honest connection/auth state banners,
 * and Pause/Resume All synchronized with backend queue state.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";
import { renderOverview } from "./overview.js";

const torrentTotalDl = $("torrent-total-dl");
const torrentTotalUp = $("torrent-total-up");
const torrentDownloadsList = $("torrent-downloads-list");
const torrentStatusBanner = $("torrent-status-banner");
const btnPauseTorrents = $("btn-pause-torrents");
const torrentBtnLabel = $("torrent-btn-label");

let lastRenderedKey = "";

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

  // Keyed patching per torrent row
  const existingRows = new Map();
  torrentDownloadsList.querySelectorAll("[data-torrent-key]").forEach((row) => {
    existingRows.set(row.dataset.torrentKey, row);
  });

  // Clear empty state if present
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
      `;
      torrentDownloadsList.appendChild(card);
    }

    const nameEl = card.querySelector(".torrent-name");
    if (nameEl) {
      nameEl.textContent = t.name;
      nameEl.title = t.name;
    }
    const catEl = card.querySelector(".torrent-cat-badge");
    if (catEl) catEl.textContent = t.category || "General";

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

export function setupCurrentDownloads() {
  if (btnPauseTorrents) {
    btnPauseTorrents.addEventListener("click", toggleTorrents);
  }
}
