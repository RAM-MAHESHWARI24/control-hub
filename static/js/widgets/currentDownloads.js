/**
 * Widget: Current Downloads (qBittorrent Ingest Pipeline)
 * Renders live active download queue, progress bars, collective speeds,
 * and emergency pause/resume all control.
 */

import { $ } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";

const torrentTotalDl = $("torrent-total-dl");
const torrentTotalUp = $("torrent-total-up");
const torrentDownloadsList = $("torrent-downloads-list");
const btnPauseTorrents = $("btn-pause-torrents");
const torrentBtnLabel = $("torrent-btn-label");

export function renderTorrents(tq = {}) {
  const dlSum = tq.collective_dl_mbs !== undefined ? tq.collective_dl_mbs : 0.0;
  const upSum = tq.collective_up_mbs !== undefined ? tq.collective_up_mbs : 0.0;

  if (torrentTotalDl) torrentTotalDl.textContent = dlSum.toFixed(2);
  if (torrentTotalUp) torrentTotalUp.textContent = upSum.toFixed(2);

  if (!torrentDownloadsList) return;

  if (tq.items && tq.items.length > 0) {
    torrentDownloadsList.innerHTML = tq.items.map(t => {
      const isStalled = t.state && t.state.toLowerCase().includes("stalled");
      const isDownloading = t.state && (t.state.toLowerCase().includes("dl") || (t.dl_mbs && t.dl_mbs > 0));
      const statusClass = isDownloading ? "downloading" : (isStalled ? "stalled" : "");
      const statusText = isDownloading ? "Downloading" : (isStalled ? "Stalled" : t.state);
      const safeName = escapeHtml(t.name);
      const cat = escapeHtml(t.category || "General");
      const dlRate = (t.dl_mbs !== undefined ? t.dl_mbs : 0.0).toFixed(2);
      const upRate = (t.up_mbs !== undefined ? t.up_mbs : 0.0).toFixed(2);

      return `
        <div class="torrent-item-card">
          <div class="torrent-top-row">
            <div class="torrent-name-wrap">
              <span class="torrent-name" title="${safeName}">${safeName}</span>
              <span class="torrent-cat-badge">${cat}</span>
            </div>
            <div class="torrent-speed-badge">
              <span class="stat-arrow dl-arrow">&darr;</span> ${dlRate} MB/s
              ${t.up_mbs > 0 ? `<span class="stat-arrow up-arrow">&uarr;</span> ${upRate} MB/s` : ""}
            </div>
          </div>
          <div class="torrent-progress-bar-bg">
            <div class="torrent-progress-bar-fill" style="width: ${Math.min(100, Math.max(0, t.progress))}%"></div>
          </div>
          <div class="torrent-bottom-row">
            <span>Progress: <strong>${t.progress}%</strong> (${t.completed_gb} / ${t.size_gb} GB)</span>
            <span>ETA: <strong>${t.eta}</strong> &bull; <span class="torrent-status-pill ${statusClass}">${statusText}</span></span>
          </div>
        </div>
      `;
    }).join("");
  } else {
    torrentDownloadsList.innerHTML = `
      <div class="ops-empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 22px; height: 22px; margin-bottom: 6px; opacity: 0.6; display: block; margin-left: auto; margin-right: auto;">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <div>No active torrent downloads in queue &bull; qBittorrent Idle</div>
      </div>
    `;
  }
}

export async function toggleTorrents() {
  const nextAction = state.torrentsPaused ? "resume" : "pause";
  if (btnPauseTorrents) btnPauseTorrents.disabled = true;

  try {
    const res = await fetch(ENDPOINTS.torrentsToggle, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: nextAction })
    });
    const data = await res.json();
    if (data.success) {
      state.torrentsPaused = (nextAction === "pause");
      if (torrentBtnLabel) {
        torrentBtnLabel.textContent = state.torrentsPaused ? "Resume Torrents" : "Pause Torrents";
      }
      showToast(
        state.torrentsPaused ? "Torrents Paused" : "Torrents Resumed",
        `All active downloads ${nextAction}d in qBittorrent.`,
        state.torrentsPaused ? "⏸️" : "▶️"
      );
    } else {
      showToast("Error", data.error || "Failed to toggle torrents", "❌");
    }
  } catch (err) {
    showToast("Error", "Could not connect to qBittorrent API", "❌");
  } finally {
    if (btnPauseTorrents) btnPauseTorrents.disabled = false;
  }
}

export function setupCurrentDownloads() {
  if (btnPauseTorrents) {
    btnPauseTorrents.addEventListener("click", toggleTorrents);
  }
}
