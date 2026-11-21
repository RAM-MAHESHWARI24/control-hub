/**
 * Widget: Android TV auto-updater
 * Keeps TV counts and the fleet list strictly synchronized from one source,
 * removes dummy HTML/JS fallbacks, and wires accessible modals.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";

const tvStatusBadge = $("tv-status-badge");
const tvLastSync = $("tv-last-sync");
const tvClusterCount = $("tv-cluster-count");
const tvStatusMsg = $("tv-status-msg");
const tvScheduleVal = $("tv-schedule-val");

const btnDeployCard = $("btn-deploy-card");
const tvCardDeploySpinner = $("tv-card-deploy-spinner");
const tvCardDeployIcon = $("tv-card-deploy-icon");
const tvCardDeployLabel = $("tv-card-deploy-label");

const btnViewTvLog = $("btn-view-tv-log");
const btnOpenTvDetails = $("btn-open-tv-details");
const btnOpenTvDetailsHeader = $("btn-open-tv-details-header");
const btnOpenTvDetailsCard = $("btn-open-tv-details-card");
const tvFleetPreview = $("tv-fleet-preview");

const tvValOnline = $("tv-val-online");
const tvValSt = $("tv-val-st");
const tvValCs = $("tv-val-cs");

const stepTvUpstream = $("step-tv-upstream");
const stepTvDiscovery = $("step-tv-discovery");
const stepTvSafety = $("step-tv-safety");
const stepTvPush = $("step-tv-push");
const stepTvConn1 = $("step-tv-conn-1");
const stepTvConn2 = $("step-tv-conn-2");
const stepTvConn3 = $("step-tv-conn-3");

const tvDetailModal = $("tv-updater-detail-modal");
const tvModalClose = $("tv-modal-close");
const tvModalDismiss = $("tv-modal-dismiss");
const modalTvDot = $("modal-tv-dot");
const modalTvBannerText = $("modal-tv-banner-text");
const tvLiveTag = $("tv-live-tag");
const btnModalSyncUpstream = $("btn-modal-sync-upstream");
const tvDevicesContainer = $("tv-devices-container");
const btnTvModalForceDeployAll = $("btn-tv-modal-force-deploy-all");

const tvLogModal = $("tv-updater-log-modal");
const tvLogModalClose = $("tv-log-modal-close");
const tvLogModalDismiss = $("tv-log-modal-dismiss");
const tvLogSubPath = $("tv-log-modal-sub-path");

let forceUpdateEnabled = false;

function updateDeployUiState(deploying) {
  if (btnDeployCard) {
    btnDeployCard.disabled = deploying;
    btnDeployCard.classList.toggle("is-syncing", deploying);
    if (tvCardDeploySpinner) tvCardDeploySpinner.style.display = deploying ? "inline-block" : "none";
    if (tvCardDeployIcon) tvCardDeployIcon.style.display = deploying ? "none" : "inline-block";
    if (tvCardDeployLabel) tvCardDeployLabel.textContent = deploying ? "Deploying..." : "Deploy Now";
  }

  if (tvLiveTag) tvLiveTag.style.display = deploying ? "inline-block" : "none";
  if (btnTvModalForceDeployAll) {
    btnTvModalForceDeployAll.disabled = deploying;
    btnTvModalForceDeployAll.textContent = deploying ? "Deployment Active..." : "Force Deploy All Devices Now";
  }
}

function renderTvStepper(currentStage, status) {
  const steps = [
    { elem: stepTvUpstream, num: 1 },
    { elem: stepTvDiscovery, num: 2 },
    { elem: stepTvSafety, num: 3 },
    { elem: stepTvPush, num: 4 },
  ];
  const connectors = [stepTvConn1, stepTvConn2, stepTvConn3];
  const isDeploying = status === "deploying";
  const isError = status === "error";
  const isSynced = status === "synced";

  steps.forEach(({ elem, num }) => {
    if (!elem) return;
    const circle = elem.querySelector(".step-circle");

    if (isError && currentStage === num) {
      elem.className = "step-item step-error";
      if (circle) circle.textContent = "✕";
    } else if (isDeploying) {
      if (num < currentStage) {
        elem.className = "step-item step-done";
        if (circle) circle.textContent = "✓";
      } else if (num === currentStage) {
        elem.className = "step-item step-active";
        if (circle) circle.innerHTML = `<span class="step-spin" aria-hidden="true">⟳</span>`;
      } else {
        elem.className = "step-item";
        if (circle) circle.textContent = `${num}`;
      }
    } else if (isSynced && currentStage >= num) {
      elem.className = "step-item step-done";
      if (circle) circle.textContent = "✓";
    } else if (currentStage > 0 && num <= currentStage && status !== "unknown") {
      elem.className = "step-item step-done";
      if (circle) circle.textContent = "✓";
    } else {
      elem.className = "step-item";
      if (circle) circle.textContent = `${num}`;
    }
  });

  connectors.forEach((conn, idx) => {
    if (!conn) return;
    const precedingStepNum = idx + 1;
    if (isDeploying) {
      conn.className = precedingStepNum < currentStage ? "step-connector connector-done" : "step-connector";
    } else if (status !== "unknown" && (isSynced || precedingStepNum < currentStage)) {
      conn.className = "step-connector connector-done";
    } else {
      conn.className = "step-connector";
    }
  });
}

function renderFleetPreview(devices) {
  if (!tvFleetPreview) return;
  if (!devices || devices.length === 0) {
    tvFleetPreview.innerHTML = `<div class="ops-empty-state">No Android TV devices configured or reachable.</div>`;
    return;
  }

  tvFleetPreview.innerHTML = devices.map((dev) => {
    const isOnline = Boolean(dev.is_online);
    const fgName = escapeHtml(dev.foreground_app_name || (isOnline ? "Idle / Launcher" : "Standby"));
    const isFgManaged = (dev.apps || []).some((a) => a.is_foreground);
    const hasPending = (dev.apps || []).some((a) => !a.is_up_to_date || !a.is_installed);

    let statusPillClass = "synced";
    let statusPillText = "Up to Date";
    if (!isOnline) {
      statusPillClass = "offline";
      statusPillText = "Standby";
    } else if (hasPending) {
      statusPillClass = "pending";
      statusPillText = "Pending Updates";
    }

    return `
      <div class="fleet-item ${isOnline ? "fleet-online" : "fleet-offline"}">
        <div class="fleet-item-top">
          <span class="fleet-device-name">${escapeHtml(dev.name)}</span>
          <span class="fleet-device-ip font-mono">${escapeHtml(dev.ip)}:${escapeHtml(dev.port)}</span>
        </div>
        <div class="fleet-item-bottom">
          <span class="fleet-app-tag ${isFgManaged ? "text-amber" : "text-cyan"}">
            ${isOnline ? `Active: ${fgName}` : "Standby / Offline"}
          </span>
          <span class="fleet-status-pill ${statusPillClass}">${statusPillText}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderDeviceCards(devices) {
  if (!tvDevicesContainer) return;
  if (!devices || devices.length === 0) {
    tvDevicesContainer.innerHTML = `<div class="ops-empty-state">No Android TV devices configured in cluster.</div>`;
    return;
  }

  const html = devices.map((dev) => {
    const isOnline = Boolean(dev.is_online);
    const fgName = escapeHtml(dev.foreground_app_name || "Idle / Launcher");
    const isMedia = Boolean(dev.is_media_playing);
    const isFgManaged = (dev.apps || []).some((a) => a.is_foreground);

    const appsHtml = (dev.apps || []).map((app) => {
      let badgeClass = "badge-status-synced";
      let badgeText = "Up to Date";
      let canUpdate = false;

      if (!app.is_installed) {
        badgeClass = "badge-status-fresh";
        badgeText = "Fresh Install Pending";
        canUpdate = true;
      } else if (!app.is_up_to_date) {
        badgeClass = "badge-status-pending";
        badgeText = "Update Available";
        canUpdate = true;
      }

      const fgWarning = app.is_foreground ? `<span class="tv-fg-warning">Active in FG</span>` : "";

      return `
        <tr class="tv-app-row ${app.is_foreground ? "row-in-foreground" : ""}">
          <td class="tv-app-col-name">
            <div class="tv-app-title-group">
              <strong>${escapeHtml(app.name)}</strong>
              <small class="text-dim">${escapeHtml(app.package)}</small>
            </div>
            ${fgWarning}
          </td>
          <td class="tv-app-col-ver">
            <div class="tv-ver-box">
              <span class="ver-code">vCode: ${app.installed_code > 0 ? app.installed_code : "None"}</span>
              <span class="ver-name text-dim">${escapeHtml(app.installed_name || "")}</span>
            </div>
          </td>
          <td class="tv-app-col-target">
            <div class="tv-ver-box">
              <span class="ver-code text-cyan">vCode: ${app.target_code > 0 ? app.target_code : "N/A"}</span>
              <span class="ver-name text-dim">${escapeHtml(app.target_name || "")}</span>
            </div>
          </td>
          <td class="tv-app-col-status">
            <span class="tv-status-chip ${badgeClass}">${badgeText}</span>
          </td>
          <td class="tv-app-col-actions">
            <div class="tv-action-buttons">
              <button type="button" class="btn-micro btn-app-deploy ${canUpdate ? "btn-primary-micro" : "btn-secondary-micro"}"
                      data-device="${escapeHtml(dev.id)}"
                      data-package="${escapeHtml(app.package)}"
                      data-appname="${escapeHtml(app.name)}">
                ${canUpdate ? "Install / Update" : "Reinstall"}
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    return `
      <div class="tv-device-card ${isOnline ? "device-online" : "device-offline"}">
        <div class="tv-device-header">
          <div class="tv-device-title-wrap">
            <div class="tv-device-icon-box" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="tv-icon">
                <rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect>
                <polyline points="17 2 12 7 7 2"></polyline>
              </svg>
            </div>
            <div>
              <div class="tv-device-name-row">
                <h4>${escapeHtml(dev.name)}</h4>
                <span class="tv-model-pill">${escapeHtml(dev.model || "ANDROID")}</span>
                <span class="tv-ip-badge font-mono">${escapeHtml(dev.ip)}:${escapeHtml(dev.port)}</span>
              </div>
              <div class="tv-device-status-sub">
                ${isOnline ? '<span class="status-indicator online" aria-hidden="true"></span> Online • ADB Port 5555' : '<span class="status-indicator offline" aria-hidden="true"></span> Standby / Offline'}
              </div>
            </div>
          </div>
          <div class="tv-device-header-actions">
            <button type="button" class="btn-micro btn-deploy-tv-all" data-device="${escapeHtml(dev.id)}" data-devicename="${escapeHtml(dev.name)}">
              Deploy All to ${escapeHtml(dev.name)}
            </button>
          </div>
        </div>

        <div class="tv-session-strip">
          <div class="session-left">
            <span class="session-label">CURRENTLY FOCUSED:</span>
            <span class="session-app ${isFgManaged ? "text-amber" : "text-cyan"}">${fgName}</span>
          </div>
          <div class="session-right">
            ${isMedia ? '<span class="session-media-active">Media Playback Active</span>' : '<span class="session-media-idle">Idle Session</span>'}
          </div>
        </div>

        <div class="tv-app-table-wrapper">
          <table class="tv-app-table">
            <thead>
              <tr>
                <th>App Package</th>
                <th>Installed</th>
                <th>Upstream Target</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${appsHtml}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }).join("");

  tvDevicesContainer.innerHTML = html;

  tvDevicesContainer.querySelectorAll(".btn-app-deploy").forEach((btn) => {
    btn.addEventListener("click", () => {
      triggerSingleAppDeploy(btn.dataset.device, btn.dataset.package, btn.dataset.appname);
    });
  });

  tvDevicesContainer.querySelectorAll(".btn-deploy-tv-all").forEach((btn) => {
    btn.addEventListener("click", () => {
      triggerTvDeploymentForDevice(btn.dataset.device, btn.dataset.devicename);
    });
  });
}

export async function fetchTvUpdaterStatus(force = false) {
  try {
    const url = force ? `${ENDPOINTS.tvUpdaterStatus}?refresh=true` : ENDPOINTS.tvUpdaterStatus;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();

    const tvSection = $("tv-updater-section");
    const tvNavBtn = $("nav-item-tvs");
    if (data.installed === false) {
      if (tvSection) tvSection.style.display = "none";
      if (tvNavBtn) tvNavBtn.style.display = "none";
      return;
    }
    if (tvSection) tvSection.style.display = "";
    if (tvNavBtn) tvNavBtn.style.display = "";

    const devices = Array.isArray(data.devices) ? data.devices : [];
    const totalDevices = devices.length;
    const onlineDevices = devices.filter((d) => d.is_online).length;
    const status = data.status || (totalDevices === 0 ? "unknown" : "pending");
    const isDeploying = Boolean(data.is_deploying || status === "deploying");
    const isError = status === "error";
    const stage = Number(data.current_stage || 0);

    updateDeployUiState(isDeploying);
    renderTvStepper(stage, isDeploying ? "deploying" : status);

    if (tvStatusBadge) {
      if (isDeploying) {
        tvStatusBadge.className = "badge-status-syncing";
        tvStatusBadge.textContent = "Deploying";
      } else if (isError) {
        tvStatusBadge.className = "badge-status-error";
        tvStatusBadge.textContent = "Attention Needed";
      } else if (totalDevices === 0) {
        tvStatusBadge.className = "badge-status-unknown";
        tvStatusBadge.textContent = "No TVs Configured";
      } else if (data.all_up_to_date) {
        tvStatusBadge.className = "badge-status-synced";
        tvStatusBadge.textContent = "Up to Date";
      } else {
        tvStatusBadge.className = "badge-status-pending";
        tvStatusBadge.textContent = `${data.pending_updates_count || 0} Pending`;
      }
    }

    if (tvScheduleVal && data.schedule) tvScheduleVal.textContent = data.schedule;
    if (tvLastSync) tvLastSync.textContent = data.last_upstream_check_str || "Unknown";
    if (tvClusterCount) {
      tvClusterCount.textContent = `${totalDevices} Device${totalDevices === 1 ? "" : "s"} (${onlineDevices} Online)`;
    }
    if (tvStatusMsg) tvStatusMsg.textContent = data.message || "Ready";
    if (tvLogSubPath && data.log_file) tvLogSubPath.textContent = `Log: ${data.log_file}`;

    if (tvValOnline) tvValOnline.textContent = `${onlineDevices}/${totalDevices} Online`;
    const upApps = data.upstream_apps || {};
    if (tvValSt) {
      const st = upApps["org.smarttube.stable"];
      tvValSt.textContent = st && st.version_name ? `v${st.version_name}` : "Not synced";
    }
    if (tvValCs) {
      const cs = upApps["com.lagradost.cloudstream3.prerelease"];
      tvValCs.textContent = cs && cs.version_name ? `v${cs.version_name}` : "Not synced";
    }

    setCardSummary("tv-updater-section", `TVs: ${onlineDevices}/${totalDevices} online`);

    if (modalTvDot) {
      modalTvDot.className = isDeploying ? "modal-dot dot-syncing" : (isError ? "modal-dot dot-error" : "modal-dot dot-live");
    }
    if (modalTvBannerText) {
      if (isDeploying) {
        modalTvBannerText.textContent = "Deployment in progress: Silent ADB package transfer active...";
      } else if (totalDevices === 0) {
        modalTvBannerText.textContent = "No TV profiles configured or reachable.";
      } else if (data.all_up_to_date) {
        modalTvBannerText.textContent = `All target TVs up to date (${onlineDevices}/${totalDevices} Online).`;
      } else {
        modalTvBannerText.textContent = `${data.pending_updates_count} update task(s) pending across target TVs.`;
      }
    }

    renderFleetPreview(devices);
    renderDeviceCards(devices);
  } catch (err) {
    console.error("Error fetching TV updater status:", err);
  }
}

export async function triggerTvDeployment(forceInstall = false) {
  const force = forceInstall || forceUpdateEnabled;
  updateDeployUiState(true);
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterDeploy, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(force ? "Force Deployment Started" : "Deployment Started", data.message || "Deploying packages...", "📺");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Deployment Busy", data.message || "Deployment is already running.", "⚠️");
      updateDeployUiState(false);
    }
  } catch (_) {
    showToast("Error", "Could not trigger TV app deployment.", "❌");
    updateDeployUiState(false);
  }
}

export async function triggerTvDeploymentForDevice(deviceId, deviceName) {
  const force = forceUpdateEnabled;
  updateDeployUiState(true);
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterDeploy, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, force }),
    });
    const data = await res.json();
    if (data.success) {
      showToast("Device Deployment", `Deploying pending apps to ${deviceName}...`, "📺");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Busy", data.message, "⚠️");
      updateDeployUiState(false);
    }
  } catch (_) {
    showToast("Error", `Could not trigger deployment for ${deviceName}`, "❌");
    updateDeployUiState(false);
  }
}

export async function triggerSingleAppDeploy(deviceId, packageName, appName = "") {
  const force = forceUpdateEnabled;
  showToast(force ? "Force Installing App" : "Installing App", `Deploying ${appName || packageName} to ${deviceId}...`, "🚀");
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterInstallApp, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, package: packageName, force }),
    });
    const data = await res.json();
    if (data.success) {
      showToast("Action Initiated", data.message, "✓");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Notice", data.message, "⚠️");
    }
  } catch (_) {
    showToast("Error", `Failed to trigger deployment for ${packageName}`, "❌");
  }
}

export async function triggerUpstreamSync() {
  if (btnModalSyncUpstream) btnModalSyncUpstream.disabled = true;
  showToast("Upstream Sync", "Checking GitHub releases...", "☁️");
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterSyncUpstream, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Upstream Sync", data.message, "✓");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Notice", data.message, "⚠️");
    }
  } catch (_) {
    showToast("Error", "Could not check upstream releases", "❌");
  } finally {
    if (btnModalSyncUpstream) btnModalSyncUpstream.disabled = false;
  }
}

export async function triggerPushIncoming() {
  showToast("Pushing Drops", "Scanning incoming_apks/ and pushing to TVs...", "📦");
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterPushIncoming, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Sideload Push", data.message, "✓");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Notice", data.message, "⚠️");
    }
  } catch (_) {
    showToast("Error", "Could not push incoming APK drops", "❌");
  }
}

export function openTvDetailModal(triggerEl = null) {
  if (!tvDetailModal) return;
  openModal(tvDetailModal, triggerEl);
  fetchTvUpdaterStatus(true);
}

export async function openTvLogModal(triggerEl = null) {
  if (!tvLogModal) return;
  openModal(tvLogModal, triggerEl);
  await refreshTvLog();
}

export async function refreshTvLog() {
  const tvLogContentEl = $("tv-log-content");
  if (!tvLogContentEl) return;
  tvLogContentEl.textContent = "Fetching TV updater log lines...";
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterLog);
    const data = await res.json();
    if (tvLogSubPath && data.log_file) tvLogSubPath.textContent = `Log: ${data.log_file}`;
    tvLogContentEl.textContent = data.log || "No log content returned.";
    tvLogContentEl.scrollTop = tvLogContentEl.scrollHeight;
  } catch (_) {
    tvLogContentEl.textContent = "Error loading TV updater log file.";
  }
}

export function setupTvUpdater() {
  registerModal(tvDetailModal, { closeButtons: [tvModalClose, tvModalDismiss] });
  registerModal(tvLogModal, { closeButtons: [tvLogModalClose, tvLogModalDismiss] });

  if (btnDeployCard) btnDeployCard.addEventListener("click", () => triggerTvDeployment(false));
  if (btnViewTvLog) btnViewTvLog.addEventListener("click", () => openTvLogModal(btnViewTvLog));
  if (btnOpenTvDetails) btnOpenTvDetails.addEventListener("click", () => openTvDetailModal(btnOpenTvDetails));
  if (btnOpenTvDetailsHeader) btnOpenTvDetailsHeader.addEventListener("click", () => openTvDetailModal(btnOpenTvDetailsHeader));
  if (btnOpenTvDetailsCard) btnOpenTvDetailsCard.addEventListener("click", () => openTvDetailModal(btnOpenTvDetailsCard));

  const btnModalRefreshTelemetry = $("btn-modal-refresh-telemetry");
  const btnModalPushIncoming = $("btn-modal-push-incoming");
  const btnTvModalViewLog = $("btn-tv-modal-view-log");
  const tvLogModalRefresh = $("tv-log-modal-refresh");
  const chkForceUpdate = $("chk-force-update");

  if (btnModalSyncUpstream) btnModalSyncUpstream.addEventListener("click", triggerUpstreamSync);
  if (btnModalRefreshTelemetry) btnModalRefreshTelemetry.addEventListener("click", () => fetchTvUpdaterStatus(true));
  if (btnModalPushIncoming) btnModalPushIncoming.addEventListener("click", triggerPushIncoming);
  if (btnTvModalViewLog) btnTvModalViewLog.addEventListener("click", () => openTvLogModal(btnTvModalViewLog));
  if (btnTvModalForceDeployAll) btnTvModalForceDeployAll.addEventListener("click", () => triggerTvDeployment(true));
  if (tvLogModalRefresh) tvLogModalRefresh.addEventListener("click", refreshTvLog);

  if (chkForceUpdate) {
    chkForceUpdate.addEventListener("change", (e) => {
      forceUpdateEnabled = e.target.checked;
      showToast(
        forceUpdateEnabled ? "Force Update Mode Armed" : "Safe Mode Re-Armed",
        forceUpdateEnabled
          ? "Updates will install even if the app is active in foreground."
          : "Safety guard active: updates pause while media plays or app is in foreground.",
        forceUpdateEnabled ? "⚡" : "🛡️"
      );
    });
  }
}
