/**
 * Widget: Android TV App Updater (CleanYourTV ADB Cluster)
 * Renders 4-stage deployment stepper, cluster status summary strip,
 * comprehensive granular device management modal with force-update overrides,
 * per-app TV install/update controllers, and 1-click terminal log streamer.
 */

import { $ } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { showToast } from "../shared/toast.js";

// Card Elements
const tvStatusBadge = $("tv-status-badge");
const tvLastSync = $("tv-last-sync");
const tvClusterCount = $("tv-cluster-count");
const tvStatusMsg = $("tv-status-msg");

const btnDeployCard = $("btn-deploy-card");
const tvCardDeploySpinner = $("tv-card-deploy-spinner");
const tvCardDeployIcon = $("tv-card-deploy-icon");
const tvCardDeployLabel = $("tv-card-deploy-label");

const btnViewTvLog = $("btn-view-tv-log");
const btnOpenTvDetails = $("btn-open-tv-details");
const btnOpenTvDetailsHeader = $("btn-open-tv-details-header");
const btnOpenTvDetailsCard = $("btn-open-tv-details-card");
const tvFleetPreview = $("tv-fleet-preview");

// Card Summary Strip Chips
const tvValOnline = $("tv-val-online");
const tvValSt = $("tv-val-st");
const tvValCs = $("tv-val-cs");
const tvValHds = $("tv-val-hds");

// Stepper Elements
const stepTvUpstream = $("step-tv-upstream");
const stepTvDiscovery = $("step-tv-discovery");
const stepTvSafety = $("step-tv-safety");
const stepTvPush = $("step-tv-push");
const stepTvConn1 = $("step-tv-conn-1");
const stepTvConn2 = $("step-tv-conn-2");
const stepTvConn3 = $("step-tv-conn-3");

// Detail Modal Elements
const tvDetailModal = $("tv-updater-detail-modal");
const tvModalClose = $("tv-modal-close");
const tvModalDismiss = $("tv-modal-dismiss");
const modalTvDot = $("modal-tv-dot");
const modalTvBannerText = $("modal-tv-banner-text");
const tvLiveTag = $("tv-live-tag");
const btnModalSyncUpstream = $("btn-modal-sync-upstream");
const btnModalRefreshTelemetry = $("btn-modal-refresh-telemetry");
const btnModalPushIncoming = $("btn-modal-push-incoming");
const chkForceUpdate = $("chk-force-update");
const tvDevicesContainer = $("tv-devices-container");
const btnTvModalViewLog = $("btn-tv-modal-view-log");
const btnTvModalForceDeployAll = $("btn-tv-modal-force-deploy-all");

// Log Modal Elements
const tvLogModal = $("tv-updater-log-modal");
const tvLogModalClose = $("tv-log-modal-close");
const tvLogModalDismiss = $("tv-log-modal-dismiss");
const tvLogModalRefresh = $("tv-log-modal-refresh");
const tvLogContent = $("tv-log-content");

let isDeployingActive = false;
let forceUpdateEnabled = false;

function updateDeployUiState(deploying) {
  isDeployingActive = deploying;

  if (btnDeployCard) {
    btnDeployCard.disabled = deploying;
    if (deploying) {
      btnDeployCard.classList.add("is-syncing");
      if (tvCardDeploySpinner) tvCardDeploySpinner.style.display = "inline-block";
      if (tvCardDeployIcon) tvCardDeployIcon.style.display = "none";
      if (tvCardDeployLabel) tvCardDeployLabel.textContent = "Deploying...";
    } else {
      btnDeployCard.classList.remove("is-syncing");
      if (tvCardDeploySpinner) tvCardDeploySpinner.style.display = "none";
      if (tvCardDeployIcon) tvCardDeployIcon.style.display = "inline-block";
      if (tvCardDeployLabel) tvCardDeployLabel.textContent = "Deploy Now";
    }
  }

  if (tvLiveTag) {
    tvLiveTag.style.display = deploying ? "inline-block" : "none";
  }

  if (btnTvModalForceDeployAll) {
    btnTvModalForceDeployAll.disabled = deploying;
    btnTvModalForceDeployAll.textContent = deploying ? "Deployment Active..." : "Force Deploy All Devices Now";
  }
}

function renderTvStepper(currentStage, isDeploying, isError) {
  const steps = [
    { elem: stepTvUpstream, num: 1 },
    { elem: stepTvDiscovery, num: 2 },
    { elem: stepTvSafety, num: 3 },
    { elem: stepTvPush, num: 4 }
  ];
  const connectors = [stepTvConn1, stepTvConn2, stepTvConn3];

  steps.forEach(({ elem, num }) => {
    if (!elem) return;
    const circle = elem.querySelector(".step-circle");

    if (isError && currentStage === num) {
      elem.className = "step-item step-error";
      if (circle) circle.innerHTML = "✕";
    } else if (isDeploying) {
      if (num < currentStage) {
        elem.className = "step-item step-done";
        if (circle) circle.innerHTML = "✓";
      } else if (num === currentStage) {
        elem.className = "step-item step-active";
        if (circle) circle.innerHTML = `<span class="step-spin">⟳</span>`;
      } else {
        elem.className = "step-item";
        if (circle) circle.innerHTML = `${num}`;
      }
    } else {
      if (currentStage >= 4 || !isError) {
        elem.className = "step-item step-done";
        if (circle) circle.innerHTML = "✓";
      } else if (num <= currentStage) {
        elem.className = "step-item step-done";
        if (circle) circle.innerHTML = "✓";
      } else {
        elem.className = "step-item";
        if (circle) circle.innerHTML = `${num}`;
      }
    }
  });

  connectors.forEach((conn, idx) => {
    if (!conn) return;
    const precedingStepNum = idx + 1;
    if (isDeploying) {
      conn.className = (precedingStepNum < currentStage) ? "step-connector connector-done" : "step-connector";
    } else {
      conn.className = (currentStage >= 4 || precedingStepNum < currentStage) ? "step-connector connector-done" : "step-connector";
    }
  });
}

function renderFleetPreview(devices) {
  if (!tvFleetPreview) return;
  if (!devices || devices.length === 0) return;

  tvFleetPreview.innerHTML = devices.map(dev => {
    const isOnline = dev.is_online;
    const fgName = dev.foreground_app_name || (isOnline ? "Idle / Launcher" : "Standby");
    const isMedia = dev.is_media_playing;
    const isFgManaged = (dev.apps || []).some(a => a.is_foreground);
    const hasPending = (dev.apps || []).some(a => !a.is_up_to_date || !a.is_installed);

    let statusPillClass = "synced";
    let statusPillText = "✓ Up to Date";
    if (!isOnline) {
      statusPillClass = "offline";
      statusPillText = "Standby";
    } else if (hasPending) {
      statusPillClass = "pending";
      statusPillText = "Pending Updates";
    }

    return `
      <div class="fleet-item ${isOnline ? 'fleet-online' : 'fleet-offline'}">
        <div class="fleet-item-top">
          <span class="fleet-device-name">${dev.name}</span>
          <span class="fleet-device-ip font-mono">${dev.ip}:${dev.port}</span>
        </div>
        <div class="fleet-item-bottom">
          <span class="fleet-app-tag ${isFgManaged ? 'text-amber' : 'text-cyan'}">
            ${isOnline ? (isMedia ? `🎵 Active: ${fgName}` : `Active: ${fgName}`) : 'Standby / Offline'}
          </span>
          <span class="fleet-status-pill ${statusPillClass}">${statusPillText}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderDeviceCards(devices, upstreamApps) {
  if (!tvDevicesContainer) return;
  if (!devices || devices.length === 0) {
    tvDevicesContainer.innerHTML = `<div class="ops-empty-state">No Android TV devices registered in cluster.</div>`;
    return;
  }

  const html = devices.map(dev => {
    const isOnline = dev.is_online;
    const fgName = dev.foreground_app_name || "Idle / Launcher";
    const isMedia = dev.is_media_playing;
    const isFgManaged = dev.apps.some(a => a.is_foreground);

    const appsHtml = (dev.apps || []).map(app => {
      let badgeClass = "badge-status-synced";
      let badgeText = "✓ Up to Date";
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

      const fgWarning = app.is_foreground ? `<span class="tv-fg-warning" title="User is currently running this app">⚡ Active in FG</span>` : "";

      return `
        <tr class="tv-app-row ${app.is_foreground ? 'row-in-foreground' : ''}">
          <td class="tv-app-col-name">
            <div class="tv-app-title-group">
              <strong>${app.name}</strong>
              <small class="text-dim">${app.package}</small>
            </div>
            ${fgWarning}
          </td>
          <td class="tv-app-col-ver">
            <div class="tv-ver-box">
              <span class="ver-code">vCode: ${app.installed_code > 0 ? app.installed_code : 'None'}</span>
              <span class="ver-name text-dim">${app.installed_name || ''}</span>
            </div>
          </td>
          <td class="tv-app-col-target">
            <div class="tv-ver-box">
              <span class="ver-code text-cyan">vCode: ${app.target_code > 0 ? app.target_code : 'N/A'}</span>
              <span class="ver-name text-dim">${app.target_name || ''}</span>
            </div>
          </td>
          <td class="tv-app-col-status">
            <span class="tv-status-chip ${badgeClass}">${badgeText}</span>
          </td>
          <td class="tv-app-col-actions">
            <div class="tv-action-buttons">
              <button class="btn-micro btn-app-deploy ${canUpdate ? 'btn-primary-micro' : 'btn-secondary-micro'}" 
                      data-device="${dev.id}" 
                      data-package="${app.package}" 
                      data-appname="${app.name}"
                      title="${canUpdate ? 'Deploy/Install this update' : 'Reinstall/Update to target version'}">
                ${canUpdate ? 'Install / Update' : 'Reinstall'}
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    return `
      <div class="tv-device-card ${isOnline ? 'device-online' : 'device-offline'}">
        <div class="tv-device-header">
          <div class="tv-device-title-wrap">
            <div class="tv-device-icon-box">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="tv-icon">
                <rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect>
                <polyline points="17 2 12 7 7 2"></polyline>
              </svg>
            </div>
            <div>
              <div class="tv-device-name-row">
                <h4>${dev.name}</h4>
                <span class="tv-model-pill">${dev.model || 'ANDROID'}</span>
                <span class="tv-ip-badge font-mono">${dev.ip}:${dev.port}</span>
              </div>
              <div class="tv-device-status-sub">
                ${isOnline ? '<span class="status-indicator online"></span> Online &bull; ADB Port 5555' : '<span class="status-indicator offline"></span> Standby / Sleeping'}
              </div>
            </div>
          </div>
          <div class="tv-device-header-actions">
            <button class="btn-micro btn-deploy-tv-all" data-device="${dev.id}" data-devicename="${dev.name}">
              Deploy All to ${dev.name}
            </button>
          </div>
        </div>

        <!-- Live Foreground & Media Session Bar -->
        <div class="tv-session-strip">
          <div class="session-left">
            <span class="session-label">CURRENTLY FOCUSED:</span>
            <span class="session-app ${isFgManaged ? 'text-amber' : 'text-cyan'}">${fgName}</span>
          </div>
          <div class="session-right">
            ${isMedia ? '<span class="session-media-active">🎵 Media Playback Active</span>' : '<span class="session-media-idle">⏸ Idle Session</span>'}
          </div>
        </div>

        <!-- Per-App Granular Table -->
        <div class="tv-app-table-wrapper">
          <table class="tv-app-table">
            <thead>
              <tr>
                <th>App Package</th>
                <th>Installed</th>
                <th>Upstream Target</th>
                <th>Status</th>
                <th>Granular Action</th>
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

  // Bind granular per-app buttons
  tvDevicesContainer.querySelectorAll(".btn-app-deploy").forEach(btn => {
    btn.addEventListener("click", () => {
      const devId = btn.getAttribute("data-device");
      const pkg = btn.getAttribute("data-package");
      const appName = btn.getAttribute("data-appname");
      triggerSingleAppDeploy(devId, pkg, appName);
    });
  });

  // Bind deploy-all to this TV buttons
  tvDevicesContainer.querySelectorAll(".btn-deploy-tv-all").forEach(btn => {
    btn.addEventListener("click", () => {
      const devId = btn.getAttribute("data-device");
      const devName = btn.getAttribute("data-devicename");
      triggerTvDeploymentForDevice(devId, devName);
    });
  });
}

export async function fetchTvUpdaterStatus(force = false) {
  try {
    const url = force ? `${ENDPOINTS.tvUpdaterStatus}?refresh=true` : ENDPOINTS.tvUpdaterStatus;
    const res = await fetch(url);
    const data = await res.json();

    const isDeploying = data.is_deploying || data.status === "deploying";
    const isError = data.status === "error";
    const stage = data.current_stage || 4;

    updateDeployUiState(isDeploying);
    renderTvStepper(stage, isDeploying, isError);

    // Update Status Badge on Card
    if (tvStatusBadge) {
      if (isDeploying) {
        tvStatusBadge.className = "badge-status-syncing";
        tvStatusBadge.textContent = "🟡 Deploying...";
      } else if (isError) {
        tvStatusBadge.className = "badge-status-error";
        tvStatusBadge.textContent = "🔴 Attention Required";
      } else if (data.all_up_to_date) {
        tvStatusBadge.className = "badge-status-synced";
        tvStatusBadge.textContent = "🟢 Cluster Up to Date";
      } else {
        tvStatusBadge.className = "badge-status-pending";
        tvStatusBadge.textContent = `🔵 ${data.pending_updates_count || 1} Update${data.pending_updates_count !== 1 ? 's' : ''} Pending`;
      }
    }

    if (tvLastSync) tvLastSync.textContent = data.last_upstream_check_str || "Checking...";
    if (tvClusterCount) {
      tvClusterCount.textContent = `${data.total_devices || 3} Devices (${data.online_devices || 0} Online)`;
    }
    if (tvStatusMsg) tvStatusMsg.textContent = data.message || "Cluster ready";

    // Summary Strip
    if (tvValOnline) {
      tvValOnline.innerHTML = `${data.online_devices || 0}/${data.total_devices || 3} Online`;
    }
    const upApps = data.upstream_apps || {};
    if (tvValSt && upApps["org.smarttube.stable"]) {
      tvValSt.innerHTML = `v${upApps["org.smarttube.stable"].version_name || '32.68'} <small class="text-dim">Latest</small>`;
    }
    if (tvValCs && upApps["com.lagradost.cloudstream3.prerelease"]) {
      tvValCs.innerHTML = `v${upApps["com.lagradost.cloudstream3.prerelease"].version_name || '4.8.0-PRE'}`;
    }
    if (tvValHds && upApps["topic.election.sector"]) {
      tvValHds.innerHTML = `v${upApps["topic.election.sector"].version_name || '3.19-a'}`;
    }

    // Modal elements
    if (modalTvDot) {
      modalTvDot.className = isDeploying ? "modal-dot dot-syncing" : (isError ? "modal-dot dot-error" : "modal-dot dot-live");
    }
    if (modalTvBannerText) {
      if (isDeploying) {
        modalTvBannerText.textContent = "Deployment in progress: Silent ADB package transfer active...";
      } else if (data.all_up_to_date) {
        modalTvBannerText.textContent = `All target TVs up to date (${data.online_devices}/${data.total_devices} Online). Quiescent: zero background TV polling overhead.`;
      } else {
        modalTvBannerText.textContent = `${data.pending_updates_count} update task(s) pending across target TVs. Ready for deployment.`;
      }
    }

    // Render live fleet preview on card
    renderFleetPreview(data.devices || []);

    // Render granular device cards in modal
    renderDeviceCards(data.devices || [], data.upstream_apps || {});

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
      body: JSON.stringify({ force: force })
    });
    const data = await res.json();
    if (data.success) {
      showToast(
        force ? "Force Deployment Started" : "Deployment Started",
        data.message || "Deploying sideload packages across online target TVs...",
        "📺"
      );
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Deployment Busy", data.message || "Deployment is already running.", "⚠️");
    }
  } catch (err) {
    showToast("Error", "Could not trigger TV app deployment.", "❌");
  }
}

export async function triggerTvDeploymentForDevice(deviceId, deviceName) {
  const force = forceUpdateEnabled;
  updateDeployUiState(true);

  try {
    const res = await fetch(ENDPOINTS.tvUpdaterDeploy, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, force: force })
    });
    const data = await res.json();
    if (data.success) {
      showToast(
        "Device Deployment",
        `Deploying all pending apps to ${deviceName}` + (force ? " (Force mode active)" : "") + "...",
        "📺"
      );
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Busy", data.message, "⚠️");
    }
  } catch (err) {
    showToast("Error", `Could not trigger deployment for ${deviceName}`, "❌");
  }
}

export async function triggerSingleAppDeploy(deviceId, package_name, appName = "") {
  const force = forceUpdateEnabled;
  showToast(
    force ? "Force Installing App" : "Installing App",
    `Deploying ${appName || package_name} to ${deviceId}` + (force ? " (Bypassing foreground check)" : "") + "...",
    "🚀"
  );

  try {
    const res = await fetch(ENDPOINTS.tvUpdaterInstallApp, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_id: deviceId,
        package: package_name,
        force: force
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Action Initiated", data.message, "✓");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Notice", data.message, "⚠️");
    }
  } catch (err) {
    showToast("Error", `Failed to trigger deployment for ${package_name}`, "❌");
  }
}

export async function triggerUpstreamSync() {
  if (btnModalSyncUpstream) btnModalSyncUpstream.disabled = true;
  showToast("Upstream Sync", "Checking GitHub releases & developer endpoints...", "☁️");

  try {
    const res = await fetch(ENDPOINTS.tvUpdaterSyncUpstream, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Upstream Sync", data.message, "✓");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Notice", data.message, "⚠️");
    }
  } catch (err) {
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
  } catch (err) {
    showToast("Error", "Could not push incoming APK drops", "❌");
  }
}

export function openTvDetailModal() {
  const modal = $("tv-updater-detail-modal");
  if (!modal) return;
  modal.style.display = "flex";
  fetchTvUpdaterStatus(true);
}

export function closeTvDetailModal() {
  const modal = $("tv-updater-detail-modal");
  if (modal) modal.style.display = "none";
}

export async function openTvLogModal() {
  const modal = $("tv-updater-log-modal");
  if (!modal) return;
  modal.style.display = "flex";
  await refreshTvLog();
}

export function closeTvLogModal() {
  const modal = $("tv-updater-log-modal");
  if (modal) modal.style.display = "none";
}

export async function refreshTvLog() {
  const tvLogContentEl = $("tv-log-content");
  if (!tvLogContentEl) return;
  tvLogContentEl.textContent = "Fetching real-time TV updater log lines...";
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterLog);
    const data = await res.json();
    tvLogContentEl.textContent = data.log || "No log content returned.";
    tvLogContentEl.scrollTop = tvLogContentEl.scrollHeight;
  } catch (err) {
    tvLogContentEl.textContent = "Error loading TV updater log file.";
  }
}

export function setupTvUpdater() {
  // Card Actions
  const btnDeployCardEl = $("btn-deploy-card");
  const btnViewTvLogEl = $("btn-view-tv-log");
  const btnOpenTvDetailsEl = $("btn-open-tv-details");
  const btnOpenTvDetailsHeaderEl = $("btn-open-tv-details-header");
  const btnOpenTvDetailsCardEl = $("btn-open-tv-details-card");

  if (btnDeployCardEl) btnDeployCardEl.addEventListener("click", () => triggerTvDeployment(false));
  if (btnViewTvLogEl) btnViewTvLogEl.addEventListener("click", openTvLogModal);
  if (btnOpenTvDetailsEl) btnOpenTvDetailsEl.addEventListener("click", openTvDetailModal);
  if (btnOpenTvDetailsHeaderEl) btnOpenTvDetailsHeaderEl.addEventListener("click", openTvDetailModal);
  if (btnOpenTvDetailsCardEl) btnOpenTvDetailsCardEl.addEventListener("click", openTvDetailModal);

  // Detail Modal Actions
  const tvModalCloseEl = $("tv-modal-close");
  const tvModalDismissEl = $("tv-modal-dismiss");
  const btnModalSyncUpstreamEl = $("btn-modal-sync-upstream");
  const btnModalRefreshTelemetryEl = $("btn-modal-refresh-telemetry");
  const btnModalPushIncomingEl = $("btn-modal-push-incoming");
  const btnTvModalViewLogEl = $("btn-tv-modal-view-log");
  const btnTvModalForceDeployAllEl = $("btn-tv-modal-force-deploy-all");

  if (tvModalCloseEl) tvModalCloseEl.addEventListener("click", closeTvDetailModal);
  if (tvModalDismissEl) tvModalDismissEl.addEventListener("click", closeTvDetailModal);
  if (btnModalSyncUpstreamEl) btnModalSyncUpstreamEl.addEventListener("click", triggerUpstreamSync);
  if (btnModalRefreshTelemetryEl) btnModalRefreshTelemetryEl.addEventListener("click", () => fetchTvUpdaterStatus(true));
  if (btnModalPushIncomingEl) btnModalPushIncomingEl.addEventListener("click", triggerPushIncoming);
  if (btnTvModalViewLogEl) btnTvModalViewLogEl.addEventListener("click", openTvLogModal);
  if (btnTvModalForceDeployAllEl) btnTvModalForceDeployAllEl.addEventListener("click", () => triggerTvDeployment(true));

  // Force Update Switcher Toggle
  const chkForceUpdateEl = $("chk-force-update");
  if (chkForceUpdateEl) {
    chkForceUpdateEl.addEventListener("change", (e) => {
      forceUpdateEnabled = e.target.checked;
      showToast(
        forceUpdateEnabled ? "Force Update Mode Armed" : "Safe Mode Re-Armed",
        forceUpdateEnabled
          ? "Updates will now immediately install even if the app is currently focused in the foreground!"
          : "Standard safety guard active: updates will pause while media is playing or app is focused in foreground.",
        forceUpdateEnabled ? "⚡" : "🛡️"
      );
    });
  }

  // Log Modal Actions
  const tvLogModalCloseEl = $("tv-log-modal-close");
  const tvLogModalDismissEl = $("tv-log-modal-dismiss");
  const tvLogModalRefreshEl = $("tv-log-modal-refresh");

  if (tvLogModalCloseEl) tvLogModalCloseEl.addEventListener("click", closeTvLogModal);
  if (tvLogModalDismissEl) tvLogModalDismissEl.addEventListener("click", closeTvLogModal);
  if (tvLogModalRefreshEl) tvLogModalRefreshEl.addEventListener("click", refreshTvLog);
}
