/**
 * Widget: Android TV Auto-Updater
 * Real dynamic app names (no "Custom UI"), honest Standby/Offline state,
 * dynamic ADB port, inline details & rename preserved across polls,
 * and automatic nav hiding when tv_autoupdater is not installed.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { state } from "../state.js";
import { renderOverview } from "./overview.js";

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
const btnTvSyncInline = $("btn-tv-sync-inline");
const btnTvScanInline = $("btn-tv-scan-inline");
const tvFleetPreview = $("tv-fleet-preview");

const tvValOnline = $("tv-val-online");
const tvValSt = $("tv-val-st");
const tvValCs = $("tv-val-cs");
const tvLabelApp1 = $("tv-label-app-1");
const tvLabelApp2 = $("tv-label-app-2");

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
let onModuleVisibilityChange = null;
export function setTvVisibilityCallback(fn) {
  onModuleVisibilityChange = fn;
}

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
  const stepperEl = $("tv-stepper");
  if (stepperEl) {
    stepperEl.hidden = !(isDeploying || isError);
  }

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
        if (circle) circle.textContent = "…";
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

const openInfo = new Set();

function deviceSummary(dev) {
  const d = dev.details || {};
  const parts = [dev.model_label || "Model not detected yet"];
  if (d.android) parts.push(`Android ${d.android}`);
  parts.push(`${dev.ip}:${dev.port}`);
  parts.push(dev.is_online ? "online" : (d.last_seen ? `last seen ${d.last_seen}` : "not seen yet"));
  return parts.join(" · ");
}

function infoRow(label, value) {
  return value ? `<div class="tv-info-row"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>` : "";
}

function deviceInfoPanel(dev, scope) {
  const d = dev.details || {};
  const key = `${scope}-${dev.id}`;
  const inputId = `tv-nick-${key}`;
  const android = d.android ? `${d.android}${d.sdk ? ` (API ${d.sdk})` : ""}` : "";
  return `
    <div class="tv-info-panel" id="tv-info-${escapeHtml(key)}" ${openInfo.has(key) ? "" : "hidden"}>
      <dl class="tv-info-list">
        ${infoRow("Nickname", dev.nickname || (dev.model_label ? "None (showing the model)" : "None (showing the profile name)"))}
        ${infoRow("Model", dev.model_label || "Not detected yet: the TV has not been online since this was added")}
        ${infoRow("Manufacturer", d.manufacturer)}
        ${infoRow("Codename", d.codename)}
        ${infoRow("Android", android)}
        ${infoRow("Name on the TV", d.device_name)}
        ${infoRow("Address", `${dev.ip}:${dev.port}`)}
        ${infoRow("Status", dev.is_online ? "Online" : (d.last_seen ? `Offline, last seen ${d.last_seen}` : "Offline, never seen"))}
        ${infoRow("Profile", dev.profile_name)}
      </dl>
      <form class="tv-rename-form" data-device="${escapeHtml(dev.id)}">
        <label for="${escapeHtml(inputId)}">Nickname</label>
        <div class="tv-rename-row">
          <input type="text" id="${escapeHtml(inputId)}" class="form-input" maxlength="40" autocomplete="off"
                 value="${escapeHtml(dev.nickname || "")}" placeholder="${escapeHtml(dev.model_label || dev.profile_name || "")}" />
          <button type="submit" class="btn-secondary">Save name</button>
        </div>
        <p class="tv-rename-hint">Leave it empty to show the model name.</p>
      </form>
    </div>`;
}

function nameButton(dev, scope) {
  const key = `${scope}-${dev.id}`;
  return `<button type="button" class="tv-name-btn" data-info-toggle="${escapeHtml(key)}"
            aria-expanded="${openInfo.has(key)}" aria-controls="tv-info-${escapeHtml(key)}"
            title="${escapeHtml(deviceSummary(dev))}">${escapeHtml(dev.name)}</button>`;
}

function isEditingIn(container) {
  const active = document.activeElement;
  return Boolean(active && container.contains(active) && active.closest(".tv-rename-form") && active.tagName === "INPUT");
}

async function saveNickname(form) {
  const input = form.querySelector("input");
  const button = form.querySelector("button[type=submit]");
  const deviceId = form.dataset.device;
  if (button) button.disabled = true;
  try {
    const res = await fetch(`${ENDPOINTS.tvUpdaterDevices}/${encodeURIComponent(deviceId)}/nickname`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nickname: input ? input.value : "" }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast("Name not saved", data.message || "Try again.", "warning");
      return;
    }
    showToast("TV renamed", data.nickname ? `Now shown as "${data.nickname}".` : "Showing the model name again.", "success");
    if (input) input.blur();
    await fetchTvUpdaterStatus(true);
  } catch (_) {
    showToast("Name not saved", "The Control Hub did not answer.", "danger");
  } finally {
    if (button) button.disabled = false;
  }
}

function wireDeviceInfo(container) {
  container.querySelectorAll("[data-info-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.infoToggle;
      const panel = document.getElementById(`tv-info-${key}`);
      const open = !openInfo.has(key);
      if (open) openInfo.add(key);
      else openInfo.delete(key);
      btn.setAttribute("aria-expanded", String(open));
      if (panel) panel.hidden = !open;
    });
  });
  container.querySelectorAll(".tv-rename-form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      saveNickname(form);
    });
  });
}

function renderFleetPreview(devices) {
  if (!tvFleetPreview) return;
  if (isEditingIn(tvFleetPreview)) return;
  if (!devices || devices.length === 0) {
    tvFleetPreview.innerHTML = `<div class="empty-state">No Android TV devices configured or reachable.</div>`;
    return;
  }

  tvFleetPreview.innerHTML = devices.map((dev) => {
    const isOnline = Boolean(dev.is_online);
    const fgName = isOnline ? escapeHtml(dev.foreground_app_name || "Idle / Launcher") : null;
    const isFgManaged = isOnline && (dev.apps || []).some((a) => a.is_foreground);
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
          ${nameButton(dev, "card")}
          <span class="fleet-device-ip font-mono">${escapeHtml(dev.ip)}:${escapeHtml(dev.port)}</span>
        </div>
        <div class="fleet-item-bottom">
          <span class="fleet-app-tag ${isFgManaged ? "text-amber" : (isOnline ? "text-cyan" : "text-muted")}">
            ${isOnline ? `Active: ${fgName}` : "Standby / Offline"}
          </span>
          <span class="fleet-status-pill ${statusPillClass}">${statusPillText}</span>
        </div>
        ${deviceInfoPanel(dev, "card")}
      </div>
    `;
  }).join("");
  wireDeviceInfo(tvFleetPreview);
}

function renderDeviceCards(devices) {
  if (!tvDevicesContainer) return;
  if (isEditingIn(tvDevicesContainer)) return;
  if (!devices || devices.length === 0) {
    tvDevicesContainer.innerHTML = `<div class="empty-state">No Android TV devices configured in cluster.</div>`;
    return;
  }

  const html = devices.map((dev) => {
    const isOnline = Boolean(dev.is_online);
    const fgName = isOnline ? escapeHtml(dev.foreground_app_name || "Idle / Launcher") : "Offline / Standby";
    const isMedia = isOnline && Boolean(dev.is_media_playing);
    const isFgManaged = isOnline && (dev.apps || []).some((a) => a.is_foreground);

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

      const fgWarning = isOnline && app.is_foreground ? `<span class="tv-fg-warning">Active in FG</span>` : "";

      return `
        <tr class="tv-app-row ${isOnline && app.is_foreground ? "row-in-foreground" : ""}">
          <td>
            <div class="tv-app-title-group">
              <strong>${escapeHtml(app.name)}</strong>
              <small class="text-muted font-mono">${escapeHtml(app.package)}</small>
            </div>
            ${fgWarning}
          </td>
          <td>
            <div class="tv-ver-box font-mono">
              <span>${app.installed_code > 0 ? `vCode ${app.installed_code}` : "None"}</span>
              <span class="text-muted">${escapeHtml(app.installed_name || "")}</span>
            </div>
          </td>
          <td>
            <div class="tv-ver-box font-mono">
              <span class="text-cyan">${app.target_code > 0 ? `vCode ${app.target_code}` : "N/A"}</span>
              <span class="text-muted">${escapeHtml(app.target_name || "")}</span>
            </div>
          </td>
          <td><span class="${badgeClass}">${badgeText}</span></td>
          <td>
            <button type="button" class="btn-micro btn-app-deploy ${canUpdate ? "btn-primary-micro" : "btn-secondary-micro"}"
                    data-device="${escapeHtml(dev.id)}"
                    data-package="${escapeHtml(app.package)}"
                    data-appname="${escapeHtml(app.name)}">
              ${canUpdate ? "Install / Update" : "Reinstall"}
            </button>
          </td>
        </tr>
      `;
    }).join("");

    return `
      <div class="tv-device-card ${isOnline ? "device-online" : "device-offline"}">
        <div class="tv-device-header">
          <div class="tv-device-title-wrap">
            <svg class="ui-icon tv-icon text-muted" aria-hidden="true"><use href="/img/icons/ui-sprite.svg#icon-tv"></use></svg>
            <div>
              <div class="tv-device-name-row">
                <h4>${nameButton(dev, "modal")}</h4>
                <span class="meta-pill">${escapeHtml(dev.model_label || "Model unknown")}</span>
                <span class="meta-pill font-mono">${escapeHtml(dev.ip)}:${escapeHtml(dev.port)}</span>
              </div>
              <div class="tv-device-status-sub">
                ${isOnline
                  ? `<span class="status-indicator online" aria-hidden="true"></span> Online · ADB Port ${escapeHtml(dev.port)}`
                  : `<span class="status-indicator offline" aria-hidden="true"></span> Standby / Offline`}
              </div>
            </div>
          </div>
          <button type="button" class="btn-secondary btn-deploy-tv-all" data-device="${escapeHtml(dev.id)}" data-devicename="${escapeHtml(dev.name)}">
            Deploy All to ${escapeHtml(dev.name)}
          </button>
        </div>

        ${deviceInfoPanel(dev, "modal")}

        <div class="tv-session-strip">
          <div>
            <span class="text-muted">FOCUSED: </span>
            <strong class="${isFgManaged ? "text-amber" : (isOnline ? "text-cyan" : "text-muted")}">${fgName}</strong>
          </div>
          <div>
            ${isMedia ? `<span class="badge-status-pending">Media Playing</span>` : `<span class="text-muted">${isOnline ? "Idle" : "Unreachable"}</span>`}
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
  wireDeviceInfo(tvDevicesContainer);

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
    if (!res.ok) return false;
    const data = await res.json();

    state.tvSnapshot = data;
    const installed = data.installed !== false;
    state.modules.tvs = installed;
    const tvNavBtn = $("nav-item-tvs");
    if (tvNavBtn) tvNavBtn.hidden = !installed;
    if (typeof onModuleVisibilityChange === "function") onModuleVisibilityChange("tvs", installed);

    if (!installed) {
      renderOverview();
      return true;
    }

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
    if (tvStatusMsg) {
      tvStatusMsg.textContent = data.message || "Ready";
      tvStatusMsg.hidden = !isDeploying && !isError;
    }
    if (tvLogSubPath && data.log_file) tvLogSubPath.textContent = `Log: ${data.log_file}`;

    if (tvValOnline) tvValOnline.textContent = `${onlineDevices}/${totalDevices} Online`;
    const upApps = data.upstream_apps || {};
    const firstDevApps = (devices[0] && devices[0].apps) || [];
    if (tvLabelApp1 && firstDevApps[0]) tvLabelApp1.textContent = firstDevApps[0].name || "SmartTube";
    if (tvLabelApp2 && firstDevApps[1]) tvLabelApp2.textContent = firstDevApps[1].name || "CloudStream Beta";

    if (tvValSt) {
      const st = upApps["org.smarttube.stable"];
      tvValSt.textContent = st && st.version_name ? `v${st.version_name}` : "Not synced";
    }
    if (tvValCs) {
      const cs = upApps["com.lagradost.cloudstream3.prerelease"];
      tvValCs.textContent = cs && cs.version_name ? `v${cs.version_name}` : "Not synced";
    }

    setCardSummary("tv-updater-section", `${onlineDevices}/${totalDevices} TVs online`);

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
    renderOverview();
    return true;
  } catch (err) {
    console.error("Error fetching TV updater status:", err);
    return false;
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
      showToast(force ? "Force Deployment Started" : "Deployment Started", data.message || "Deploying packages...", "info");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Deployment Busy", data.message || "Deployment is already running.", "warning");
      updateDeployUiState(false);
    }
  } catch (_) {
    showToast("Error", "Could not trigger TV app deployment.", "danger");
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
      showToast("Device Deployment", `Deploying pending apps to ${deviceName}...`, "info");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Busy", data.message, "warning");
      updateDeployUiState(false);
    }
  } catch (_) {
    showToast("Error", `Could not trigger deployment for ${deviceName}`, "danger");
    updateDeployUiState(false);
  }
}

export async function triggerSingleAppDeploy(deviceId, packageName, appName = "") {
  const force = forceUpdateEnabled;
  showToast(force ? "Force Installing App" : "Installing App", `Deploying ${appName || packageName} to ${deviceId}...`, "info");
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterInstallApp, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, package: packageName, force }),
    });
    const data = await res.json();
    if (data.success) {
      showToast("Action Initiated", data.message, "success");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Notice", data.message, "warning");
    }
  } catch (_) {
    showToast("Error", `Failed to trigger deployment for ${packageName}`, "danger");
  }
}

export async function triggerUpstreamSync() {
  if (btnModalSyncUpstream) btnModalSyncUpstream.disabled = true;
  if (btnTvSyncInline) btnTvSyncInline.disabled = true;
  showToast("Upstream Sync", "Checking GitHub releases...", "info");
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterSyncUpstream, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Upstream Sync", data.message, "success");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Notice", data.message, "warning");
    }
  } catch (_) {
    showToast("Error", "Could not check upstream releases", "danger");
  } finally {
    if (btnModalSyncUpstream) btnModalSyncUpstream.disabled = false;
    if (btnTvSyncInline) btnTvSyncInline.disabled = false;
  }
}

export async function triggerPushIncoming() {
  showToast("Pushing Drops", "Scanning incoming_apks/ and pushing to TVs...", "info");
  try {
    const res = await fetch(ENDPOINTS.tvUpdaterPushIncoming, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Sideload Push", data.message, "success");
      await fetchTvUpdaterStatus(true);
    } else {
      showToast("Notice", data.message, "warning");
    }
  } catch (_) {
    showToast("Error", "Could not push incoming APK drops", "danger");
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
  if (btnTvSyncInline) btnTvSyncInline.addEventListener("click", triggerUpstreamSync);
  if (btnTvScanInline) btnTvScanInline.addEventListener("click", () => fetchTvUpdaterStatus(true));

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
        forceUpdateEnabled ? "warning" : "success"
      );
    });
  }
}
