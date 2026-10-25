/**
 * ServerFF Control Hub - Modular Master Orchestrator
 * Connects all independent GUI widget controllers via native browser ES modules.
 */

import { $ } from "./shared/dom.js";
import { state } from "./state.js";
import { showToast } from "./shared/toast.js";

// Import all 8 visual widget controllers + Header
import { setupHeader } from "./widgets/header.js";
import { fetchSleepStatus, setupSleepGuard } from "./widgets/sleepGuard.js";
import { fetchSpeedometers, setupNetworkSpeed } from "./widgets/networkSpeed.js";
import { setupCurrentDownloads } from "./widgets/currentDownloads.js";
import { fetchBackupStatus, setupBackupSync } from "./widgets/backupSync.js";
import { fetchVitals } from "./widgets/systemVitals.js";
import { fetchCronTasks, setupCronTasks } from "./widgets/cronTasks.js";
import { fetchServices, setupServiceMatrix } from "./widgets/serviceMatrix.js";
import { fetchTvUpdaterStatus, setupTvUpdater } from "./widgets/tvUpdater.js";
import { setupConfigCenter } from "./widgets/configCenter.js";

const btnModeHover = $("btn-mode-hover");
const btnModeRealtime = $("btn-mode-realtime");
const hudModeChip = $("hud-mode-chip");
const speedoBadgeText = $("speedo-badge-text");
const speedoPulseDot = $("speedo-pulse-dot");
const speedoTelemetryBadge = $("speedo-telemetry-badge");
const footerRefreshBtn = $("footer-refresh-btn");

// ==========================================================================
// 1. Centralized Telemetry Stream Manager (Eco Hover vs Real-Time All)
// ==========================================================================

export function startRealtimeAll() {
  stopRealtimeAll();

  // 1. Speedometers, Ingest Downloads & Disk Throughput (1s)
  state.realtimeTimers.speedo = setInterval(fetchSpeedometers, 1000);

  // 2. Hardware Vitals: CPU, RAM, SSD/HDD Headroom (2s)
  state.realtimeTimers.vitals = setInterval(fetchVitals, 2000);

  // 3. Sleep Guard Status & 24h Timeline (3s)
  state.realtimeTimers.sleep = setInterval(fetchSleepStatus, 3000);

  // 4. Google Drive Cloud Sync & Multi-Stage Stepper (3s)
  state.realtimeTimers.backup = setInterval(fetchBackupStatus, 3000);

  // 5. Android TV App Updater (3s)
  state.realtimeTimers.tvUpdater = setInterval(fetchTvUpdaterStatus, 3000);

  // 6. Automated System Tasks / Cron Jobs (4s)
  state.realtimeTimers.cron = setInterval(fetchCronTasks, 4000);

  // 7. Docker Container Health & Latency Pings (4s)
  state.realtimeTimers.services = setInterval(fetchServices, 4000);
}

export function stopRealtimeAll() {
  Object.keys(state.realtimeTimers).forEach(key => {
    if (state.realtimeTimers[key]) {
      clearInterval(state.realtimeTimers[key]);
      state.realtimeTimers[key] = null;
    }
  });
}

export function setStreamMode(newMode, notifyUser = false) {
  state.streamMode = (newMode === "realtime") ? "realtime" : "hover";
  try {
    localStorage.setItem("serverff_stream_mode", state.streamMode);
  } catch (e) {}

  if (state.streamMode === "realtime") {
    document.body.classList.add("realtime-all-active");

    if (btnModeRealtime) btnModeRealtime.classList.add("active");
    if (btnModeHover) btnModeHover.classList.remove("active");

    if (hudModeChip) {
      hudModeChip.className = "hud-chip chip-stream-mode mode-realtime";
      hudModeChip.innerHTML = '<span class="chip-dot"></span> Real-Time All';
    }

    if (speedoBadgeText) speedoBadgeText.textContent = "● REAL-TIME ALL ACTIVE (1s)";
    if (speedoPulseDot) speedoPulseDot.classList.add("active-pulse");
    if (speedoTelemetryBadge) speedoTelemetryBadge.classList.add("is-live");

    startRealtimeAll();

    if (notifyUser) {
      showToast("Real-Time All Active", "Continuous live telemetry enabled across all cards and metrics.", "⚡");
    }
  } else {
    document.body.classList.remove("realtime-all-active");

    if (btnModeHover) btnModeHover.classList.add("active");
    if (btnModeRealtime) btnModeRealtime.classList.remove("active");

    if (hudModeChip) {
      hudModeChip.className = "hud-chip chip-zero-ram chip-stream-mode mode-hover";
      hudModeChip.innerHTML = '<span class="chip-dot"></span> Eco Hover Mode';
    }

    if (speedoBadgeText) speedoBadgeText.textContent = "Hover Card to Stream Live";
    if (speedoPulseDot) speedoPulseDot.classList.remove("active-pulse");
    if (speedoTelemetryBadge) speedoTelemetryBadge.classList.remove("is-live");

    stopRealtimeAll();

    if (notifyUser) {
      showToast("Hover-Only Mode Active", "Metrics refresh on card hover to conserve Haswell CPU & RAM.", "🍃");
    }
  }
}

function bindHoverPolling(targetElement, pollFunction, intervalMs = 1500, onEnterCallback = null, onLeaveCallback = null) {
  if (!targetElement) return;
  let intervalTimer = null;

  targetElement.addEventListener("mouseenter", () => {
    targetElement.classList.add("card-hover-live");
    if (onEnterCallback) onEnterCallback();

    if (state.streamMode === "realtime") return;

    pollFunction();
    if (!intervalTimer) {
      intervalTimer = setInterval(pollFunction, intervalMs);
    }
  });

  targetElement.addEventListener("mouseleave", () => {
    targetElement.classList.remove("card-hover-live");
    if (onLeaveCallback) onLeaveCallback();

    if (intervalTimer) {
      clearInterval(intervalTimer);
      intervalTimer = null;
    }
  });
}

function setupHoverLiveStreaming() {
  // 1. Dual Speedometers Section
  const speedoSection = $("speedometers");
  bindHoverPolling(
    speedoSection,
    fetchSpeedometers,
    1000,
    () => {
      if (speedoBadgeText) {
        speedoBadgeText.textContent = (state.streamMode === "realtime")
          ? "● REAL-TIME ALL ACTIVE (1s)"
          : "● LIVE STREAMING (1s)";
      }
      if (speedoPulseDot) speedoPulseDot.classList.add("active-pulse");
      if (speedoTelemetryBadge) speedoTelemetryBadge.classList.add("is-live");
    },
    () => {
      if (state.streamMode === "realtime") {
        if (speedoBadgeText) speedoBadgeText.textContent = "● REAL-TIME ALL ACTIVE (1s)";
        if (speedoPulseDot) speedoPulseDot.classList.add("active-pulse");
        if (speedoTelemetryBadge) speedoTelemetryBadge.classList.add("is-live");
      } else {
        if (speedoBadgeText) speedoBadgeText.textContent = "Hover Card to Stream Live";
        if (speedoPulseDot) speedoPulseDot.classList.remove("active-pulse");
        if (speedoTelemetryBadge) speedoTelemetryBadge.classList.remove("is-live");
      }
    }
  );

  // 2. Current Downloads Panel
  bindHoverPolling($("torrent-downloads-panel"), fetchSpeedometers, 1000);

  // 3. Storage Operations Panel
  bindHoverPolling($("storage-ops-panel"), fetchSpeedometers, 1000);

  // 4. Hardware Vitals Section
  bindHoverPolling($("vitals-section"), fetchVitals, 1500);

  // 5. Cloud Backup & Google Drive Section
  bindHoverPolling($("backup-section"), fetchBackupStatus, 2500);

  // 6. Android TV App Updater Section
  bindHoverPolling($("tv-updater-section"), fetchTvUpdaterStatus, 2500);

  // 7. Docker Container Matrix
  bindHoverPolling($("services-matrix"), fetchServices, 4000);

  // 8. Sleep Guard Hero Card
  bindHoverPolling($("sleep-guard-card"), fetchSleepStatus, 3000);

  // 9. Automated System Tasks & Cron Engine
  bindHoverPolling($("automation-section"), fetchCronTasks, 4000);
}

function setupStreamModeSwitcher() {
  if (btnModeHover) {
    btnModeHover.addEventListener("click", () => {
      if (state.streamMode !== "hover") setStreamMode("hover", true);
    });
  }

  if (btnModeRealtime) {
    btnModeRealtime.addEventListener("click", () => {
      if (state.streamMode !== "realtime") setStreamMode("realtime", true);
    });
  }

  if (speedoTelemetryBadge) {
    speedoTelemetryBadge.addEventListener("click", () => {
      const nextMode = (state.streamMode === "hover") ? "realtime" : "hover";
      setStreamMode(nextMode, true);
    });
  }
}

// Global modal overlay backdrop click dismissal
window.addEventListener("click", (e) => {
  const backupLogModal = $("backup-log-modal");
  const dozzleModal = $("dozzle-modal");
  const dozzleIframe = $("dozzle-iframe");
  const cronLogModal = $("cron-log-modal");
  const immichLibraryModal = $("immich-library-modal");
  const sleepScheduleModal = $("sleep-schedule-modal");
  const tvDetailModal = $("tv-updater-detail-modal");
  const tvLogModal = $("tv-updater-log-modal");
  const configModal = $("config-center-modal");
  const aiModal = $("ai-copilot-modal");

  if (e.target === backupLogModal && backupLogModal) backupLogModal.style.display = "none";
  if (e.target === dozzleModal && dozzleModal) {
    dozzleModal.style.display = "none";
    if (dozzleIframe) dozzleIframe.src = "about:blank";
  }
  if (e.target === cronLogModal && cronLogModal) cronLogModal.style.display = "none";
  if (e.target === immichLibraryModal && immichLibraryModal) immichLibraryModal.style.display = "none";
  if (e.target === sleepScheduleModal && sleepScheduleModal) sleepScheduleModal.style.display = "none";
  if (e.target === tvDetailModal && tvDetailModal) tvDetailModal.style.display = "none";
  if (e.target === tvLogModal && tvLogModal) tvLogModal.style.display = "none";
  if (e.target === configModal && configModal) configModal.style.display = "none";
  if (e.target === aiModal && aiModal) aiModal.style.display = "none";
});

// ==========================================================================
// 2. Master Dashboard Initialization
// ==========================================================================

async function init() {
  // Initialize widget event handlers
  setupHeader();
  setupSleepGuard();
  setupNetworkSpeed();
  setupCurrentDownloads();
  setupBackupSync();
  setupTvUpdater();
  setupCronTasks();
  setupServiceMatrix();
  setupConfigCenter();

  // Load initial static snapshot for all cards
  await Promise.all([
    fetchSleepStatus(),
    fetchSpeedometers(),
    fetchVitals(),
    fetchBackupStatus(),
    fetchTvUpdaterStatus(),
    fetchCronTasks(),
    fetchServices()
  ]);

  // Activate hover streaming and stream mode switcher
  setupHoverLiveStreaming();
  setupStreamModeSwitcher();
  setStreamMode(state.streamMode, false);
}

if (footerRefreshBtn) {
  footerRefreshBtn.addEventListener("click", () => {
    fetchSpeedometers();
    fetchVitals();
    fetchSleepStatus();
    fetchBackupStatus();
    fetchTvUpdaterStatus();
    fetchCronTasks();
    fetchServices();
  });
}

document.addEventListener("DOMContentLoaded", init);
