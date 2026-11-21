/**
 * Control Hub - Main Entrypoint
 * Wires widgets, collapsible mobile cards, bottom/rail navigation,
 * visibility-aware polling, manual refresh, and touch pull-to-refresh.
 */

import { $, expandCard, setCardCollapsed } from "./shared/dom.js";
import { state } from "./state.js";
import { showToast } from "./shared/toast.js";
import { setupHeader, setMenuOpen } from "./widgets/header.js";
import { fetchSleepStatus, setupSleepGuard } from "./widgets/sleepGuard.js";
import { fetchSpeedometers, setupNetworkSpeed } from "./widgets/networkSpeed.js";
import { setupCurrentDownloads } from "./widgets/currentDownloads.js";
import { fetchBackupStatus, setupBackupSync } from "./widgets/backupSync.js";
import { fetchTvUpdaterStatus, setupTvUpdater } from "./widgets/tvUpdater.js";
import { fetchVitals } from "./widgets/systemVitals.js";
import { fetchCronTasks, setupCronTasks } from "./widgets/cronTasks.js";
import { fetchServices, setupServiceMatrix } from "./widgets/serviceMatrix.js";
import { setupConfigCenter } from "./widgets/configCenter.js";
import { fetchIndexerStatus, setupIndexers } from "./widgets/indexers.js";
import { fetchAlerts, setupAlerts } from "./widgets/alerts.js";

const FAST_POLL_MS = 2500;
const MEDIUM_POLL_MS = 15000;

let isRefreshing = false;

async function pollFastTelemetry() {
  await Promise.allSettled([
    fetchSpeedometers(),
    fetchVitals(),
  ]);
}

async function pollMediumTelemetry() {
  await Promise.allSettled([
    fetchSleepStatus(),
    fetchBackupStatus(),
    fetchTvUpdaterStatus(),
    fetchCronTasks(),
    fetchServices(),
    fetchIndexerStatus(),
    fetchAlerts(),
  ]);
}

export async function refreshAll(announce = false) {
  if (isRefreshing) return;
  isRefreshing = true;

  const refreshBtn = $("btn-refresh-now");
  const footerRefreshBtn = $("footer-refresh-btn");
  if (refreshBtn) refreshBtn.disabled = true;
  if (footerRefreshBtn) footerRefreshBtn.disabled = true;

  try {
    await Promise.allSettled([
      pollFastTelemetry(),
      pollMediumTelemetry(),
    ]);
    if (announce) {
      showToast("Telemetry Refreshed", "Live host metrics synchronized.", "🔄", 2500);
    }
  } finally {
    isRefreshing = false;
    if (refreshBtn) refreshBtn.disabled = false;
    if (footerRefreshBtn) footerRefreshBtn.disabled = false;
  }
}

function stopPolling() {
  if (state.realtimeTimers.fast) {
    clearInterval(state.realtimeTimers.fast);
    state.realtimeTimers.fast = null;
  }
  if (state.realtimeTimers.medium) {
    clearInterval(state.realtimeTimers.medium);
    state.realtimeTimers.medium = null;
  }
}

function startPolling() {
  stopPolling();
  if (document.visibilityState === "hidden") return;

  state.realtimeTimers.fast = setInterval(() => {
    if (document.visibilityState === "visible") pollFastTelemetry();
  }, FAST_POLL_MS);

  state.realtimeTimers.medium = setInterval(() => {
    if (document.visibilityState === "visible") pollMediumTelemetry();
  }, MEDIUM_POLL_MS);
}

function setupVisibilityPolling() {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      stopPolling();
    } else {
      refreshAll(false);
      startPolling();
    }
  });
}

function setupCollapsibleCards() {
  const isPhone = window.innerWidth <= 599;
  document.querySelectorAll('.dashboard-card[data-collapsible="true"]').forEach((card) => {
    const btn = card.querySelector(".card-collapse-btn");
    if (!btn) return;

    if (isPhone && card.id !== "sleep-guard-card") {
      setCardCollapsed(card.id, true);
    }

    btn.addEventListener("click", () => {
      const collapsed = card.classList.contains("is-collapsed");
      setCardCollapsed(card.id, !collapsed);
    });
  });
}

function setupNavigation() {
  const navLinks = document.querySelectorAll("#hub-nav .hub-nav-item");
  navLinks.forEach((link) => {
    link.addEventListener("click", () => {
      navLinks.forEach((item) => {
        item.classList.remove("is-active");
        item.removeAttribute("aria-current");
      });
      link.classList.add("is-active");
      link.setAttribute("aria-current", "location");

      const targetId = link.getAttribute("data-nav-target");
      if (targetId) {
        expandCard(targetId);
        if (targetId === "torrent-downloads-panel") {
          expandCard("storage-ops-panel");
        }
      }
      setMenuOpen(false);
    });
  });

  const menuActions = document.querySelectorAll("#header-actions-menu button, #header-actions-menu a");
  menuActions.forEach((el) => {
    el.addEventListener("click", () => {
      if (window.innerWidth <= 599) setMenuOpen(false);
    });
  });
}

function setupRefreshControls() {
  const refreshBtn = $("btn-refresh-now");
  const footerRefreshBtn = $("footer-refresh-btn");
  if (refreshBtn) refreshBtn.addEventListener("click", () => refreshAll(true));
  if (footerRefreshBtn) footerRefreshBtn.addEventListener("click", () => refreshAll(true));
}

function setupPullToRefresh() {
  const indicator = $("pull-refresh-indicator");
  const indicatorText = $("pull-refresh-text");
  if (!indicator) return;

  let startY = null;
  let pulling = false;
  const THRESHOLD_PX = 72;

  const hasOpenModal = () =>
    Boolean(document.querySelector('.modal-overlay[style*="flex"]')) ||
    Boolean(document.getElementById("hub-auth-overlay"));

  document.addEventListener("touchstart", (e) => {
    if (window.scrollY > 0 || hasOpenModal() || e.touches.length !== 1) {
      startY = null;
      return;
    }
    startY = e.touches[0].clientY;
    pulling = false;
  }, { passive: true });

  document.addEventListener("touchmove", (e) => {
    if (startY === null || window.scrollY > 0) return;
    const deltaY = e.touches[0].clientY - startY;
    if (deltaY > 24) {
      pulling = deltaY >= THRESHOLD_PX;
      indicator.hidden = false;
      indicator.classList.toggle("is-ready", pulling);
      if (indicatorText) {
        indicatorText.textContent = pulling ? "Release to refresh" : "Pull down to refresh";
      }
    }
  }, { passive: true });

  document.addEventListener("touchend", () => {
    if (startY === null) return;
    startY = null;
    if (pulling) {
      pulling = false;
      if (indicatorText) indicatorText.textContent = "Refreshing...";
      refreshAll(true).finally(() => {
        indicator.classList.remove("is-ready");
        indicator.hidden = true;
      });
    } else {
      indicator.classList.remove("is-ready");
      indicator.hidden = true;
    }
  }, { passive: true });
}

document.addEventListener("DOMContentLoaded", () => {
  setupHeader();
  setupCollapsibleCards();
  setupNavigation();
  setupRefreshControls();
  setupPullToRefresh();

  setupSleepGuard();
  setupNetworkSpeed();
  setupCurrentDownloads();
  setupBackupSync();
  setupTvUpdater();
  setupCronTasks();
  setupServiceMatrix();
  setupConfigCenter();
  setupIndexers();
  setupAlerts();

  setupVisibilityPolling();
  refreshAll(false);
  startPolling();
});
