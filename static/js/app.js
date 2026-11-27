/**
 * Control Hub - Main Entrypoint
 * 5-view hash router (Overview, Apps, Backups, TVs, System), automatic hiding
 * of uninstalled modules, truthful connection tracking, visibility-aware polling,
 * theme redraw hooks, and pull-to-refresh.
 */

import { $ } from "./shared/dom.js";
import { state } from "./state.js";
import { showToast } from "./shared/toast.js";
import {
  recordPollResult,
  setMenuOpen,
  setRetryConnectionHandler,
  setThemeChangeHandler,
  setupHeader,
} from "./widgets/header.js";
import { fetchSleepStatus, setupSleepGuard } from "./widgets/sleepGuard.js";
import { drawLanSparkline, fetchSpeedometers, setupNetworkSpeed } from "./widgets/networkSpeed.js";
import { fetchNetworkOverview, setupNetworkOverview } from "./widgets/networkOverview.js";
import { setupCurrentDownloads } from "./widgets/currentDownloads.js";
import { fetchBackupStatus, setBackupVisibilityCallback, setupBackupSync } from "./widgets/backupSync.js";
import { fetchPhotosOverview, setupPhotosHub } from "./widgets/photosHub.js";
import { fetchTvUpdaterStatus, setTvVisibilityCallback, setupTvUpdater } from "./widgets/tvUpdater.js";
import { fetchVitals } from "./widgets/systemVitals.js";
import { fetchStorageOverview, setupStorageHub } from "./widgets/storageHub.js";
import { fetchCronTasks, setupCronTasks } from "./widgets/cronTasks.js";
import { fetchServices, setupServiceMatrix } from "./widgets/serviceMatrix.js";
import { fetchNetplanStatus, setupConfigCenter } from "./widgets/configCenter.js";
import { fetchIndexerStatus, setupIndexers } from "./widgets/indexers.js";
import { fetchMediaHub, setupMediaHub } from "./widgets/mediaHub.js";
import { fetchAlerts, setupAlerts } from "./widgets/alerts.js";
import { fetchUpdates, setupUpdates } from "./widgets/updates.js";
import { setupHelpDrawer } from "./widgets/helpDrawer.js";

const FAST_POLL_MS = 2500;
const MEDIUM_POLL_MS = 15000;
const VALID_VIEWS = ["overview", "apps", "backups", "tvs", "system"];

let isRefreshing = false;

// ============================================================================
// 5-View Hash Router
// ============================================================================

function parseHashView() {
  const raw = (window.location.hash || "").replace(/^#\/?/, "").split("?")[0].trim().toLowerCase();
  return VALID_VIEWS.includes(raw) ? raw : "overview";
}

export function activateView(viewName, updateHash = false) {
  let target = VALID_VIEWS.includes(viewName) ? viewName : "overview";
  // Guard against navigating into an uninstalled module view or restricted family view
  if (state.authRole === "family" && target !== "overview" && target !== "apps") target = "overview";
  if (target === "backups" && state.modules.backups === false) target = "overview";
  if (target === "tvs" && state.modules.tvs === false) target = "overview";

  state.activeView = target;

  document.querySelectorAll(".hub-view[data-view]").forEach((el) => {
    const active = el.getAttribute("data-view") === target;
    el.hidden = !active;
    el.classList.toggle("is-active", active);
  });

  document.querySelectorAll("#hub-nav [data-view-link]").forEach((link) => {
    const active = link.getAttribute("data-view-link") === target;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });

  if (updateHash) {
    const desired = `#/${target}`;
    if (window.location.hash !== desired) {
      window.history.replaceState(null, "", desired);
    }
  }

  setMenuOpen(false);
  if (target === "system") {
    window.requestAnimationFrame(() => drawLanSparkline());
  }
}

function handleModuleVisibility(moduleKey, installed) {
  if (!installed && state.activeView === moduleKey) {
    activateView("overview", true);
  }
}

function setupRouter() {
  window.addEventListener("hashchange", () => {
    activateView(parseHashView(), false);
  });

  document.querySelectorAll("#hub-nav [data-view-link]").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const target = link.getAttribute("data-view-link") || "overview";
      if (window.location.hash !== `#/${target}`) {
        window.location.hash = `#/${target}`;
      } else {
        activateView(target, false);
      }
      window.scrollTo({ top: 0, behavior: "instant" });
    });
  });

  activateView(parseHashView(), false);
}

// ============================================================================
// Visibility-Aware Polling & Truthful Connection Tracking
// ============================================================================

async function pollFastTelemetry() {
  const results = await Promise.allSettled([
    fetchSpeedometers(),
    fetchVitals(),
  ]);
  const anyOk = results.some((r) => r.status === "fulfilled" && r.value === true);
  recordPollResult(anyOk);
}

async function pollMediumTelemetry() {
  if (state.authRole === "family") {
    await Promise.allSettled([
      fetchSleepStatus(),
      fetchServices(),
      fetchMediaHub(),
    ]);
    return;
  }
  await Promise.allSettled([
    fetchSleepStatus(),
    fetchBackupStatus(),
    fetchPhotosOverview(),
    fetchStorageOverview(),
    fetchTvUpdaterStatus(),
    fetchCronTasks(),
    fetchServices(),
    fetchIndexerStatus(),
    fetchMediaHub(),
    fetchAlerts(),
    fetchNetplanStatus(),
    fetchNetworkOverview(),
    fetchUpdates(),
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
      showToast("Telemetry Refreshed", "Live host metrics synchronized.", "success", 2400);
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

function applyRoleState(role) {
  const isFamily = role === "family";
  state.authRole = isFamily ? "family" : "owner";
  document.documentElement.dataset.authRole = state.authRole;

  const famBanner = $("family-mode-banner");
  const famPanel = $("family-whats-new-panel");
  if (famBanner) famBanner.hidden = !isFamily;
  if (famPanel) famPanel.hidden = !isFamily;

  ["nav-item-backups", "nav-item-tvs", "nav-item-system"].forEach((id) => {
    const navEl = $(id);
    if (navEl) navEl.hidden = isFamily;
  });

  if (isFamily && state.activeView !== "overview" && state.activeView !== "apps") {
    activateView("overview", true);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  setupHeader();
  setThemeChangeHandler(() => drawLanSparkline());
  setRetryConnectionHandler(() => refreshAll(true));
  setBackupVisibilityCallback(handleModuleVisibility);
  setTvVisibilityCallback(handleModuleVisibility);

  const btnFamOwner = $("btn-family-owner-signin");
  if (btnFamOwner) {
    btnFamOwner.addEventListener("click", () => {
      window.HomelabAuth?.prompt?.("", { mode: "owner" });
    });
  }

  setupRouter();
  setupRefreshControls();
  setupPullToRefresh();

  setupSleepGuard();
  setupNetworkSpeed();
  setupNetworkOverview();
  setupCurrentDownloads();
  setupBackupSync();
  setupPhotosHub();
  setupStorageHub();
  setupTvUpdater();
  setupCronTasks();
  setupServiceMatrix();
  setupConfigCenter();
  setupIndexers();
  setupMediaHub();
  setupAlerts();
  setupUpdates();
  setupHelpDrawer();

  try {
    const authInfo = await window.HomelabAuth?.ready?.();
    if (authInfo && authInfo.role) applyRoleState(authInfo.role);
  } catch (_) { /* default owner until 401 */ }

  setupVisibilityPolling();
  refreshAll(false);
  startPolling();
});
