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
  const nameInputId = `tv-nick-${key}`;
  const ipInputId = `tv-edit-ip-${key}`;
  const android = d.android ? `${d.android}${d.sdk ? ` (API ${d.sdk})` : ""}` : "";
  const isPaused = Boolean(dev.paused);
  return `
    <div class="tv-info-panel" id="tv-info-${escapeHtml(key)}" ${openInfo.has(key) ? "" : "hidden"}>
      <dl class="tv-info-list">
        ${infoRow("Name", dev.name)}
        ${infoRow("Model", dev.model_label || "Not detected yet: the TV has not been online since this was added")}
        ${infoRow("Manufacturer", d.manufacturer)}
        ${infoRow("Codename", d.codename)}
        ${infoRow("Android", android)}
        ${infoRow("Name on the TV", d.device_name)}
        ${infoRow("Address", `${dev.ip}:${dev.port}`)}
        ${infoRow("Status", isPaused ? "Paused (auto-updates skipped)" : (dev.is_online ? "Online" : (d.last_seen ? `Offline, last seen ${d.last_seen}` : "Offline, never seen")))}
        ${infoRow("Last Update", dev.last_update_str || "No update applied yet")}
        ${infoRow("Last Error", dev.last_error)}
        ${infoRow("Profile", dev.profile_name)}
      </dl>
      <form class="tv-rename-form" data-device="${escapeHtml(dev.id)}">
        <div class="tv-edit-grid">
          <input type="text" id="${escapeHtml(nameInputId)}" data-field="name" class="form-input" maxlength="40" autocomplete="off"
                 aria-label="TV display name for ${escapeHtml(dev.name)}"
                 value="${escapeHtml(dev.name || "")}" placeholder="${escapeHtml(dev.model_label || dev.profile_name || "")}" />
          <input type="text" id="${escapeHtml(ipInputId)}" data-field="ip" class="form-input font-mono" maxlength="32" autocomplete="off"
                 aria-label="TV IP address for ${escapeHtml(dev.name)}"
                 value="${escapeHtml(dev.ip || "")}" placeholder="192.168.1.150" />
          <button type="submit" class="btn-secondary">Save TV</button>
        </div>
      </form>
      <div class="tv-crud-actions">
        <button type="button" class="btn-secondary btn-tv-test" data-device="${escapeHtml(dev.id)}">Test Connection</button>
        <button type="button" class="btn-secondary btn-tv-pause" data-device="${escapeHtml(dev.id)}" data-paused="${isPaused ? "true" : "false"}">${isPaused ? "Resume Updates" : "Pause Updates"}</button>
        <button type="button" class="btn-ghost btn-tv-remove" data-device="${escapeHtml(dev.id)}">Remove TV</button>
      </div>
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

async function saveTvEdits(form) {
  const nameInput = form.querySelector('input[data-field="name"]');
  const ipInput = form.querySelector('input[data-field="ip"]');
  const button = form.querySelector("button[type=submit]");
  const deviceId = form.dataset.device;
  if (button) button.disabled = true;
  try {
    const payload = {
      name: nameInput ? nameInput.value : "",
      ip: ipInput ? ipInput.value : "",
    };
    const res = await fetch(`${ENDPOINTS.tvUpdaterDevices}/${encodeURIComponent(deviceId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast("TV Not Updated", data.message || "Try again.", "warning");
      return;
    }
    showToast("TV Updated", `Saved settings for "${data.device?.name || deviceId}".`, "success");
    if (nameInput) nameInput.blur();
    if (ipInput) ipInput.blur();
    await fetchTvUpdaterStatus(true);
  } catch (_) {
    showToast("TV Not Updated", "The Control Hub did not answer.", "danger");
  } finally {
    if (button) button.disabled = false;
  }
}

async function testTvConnection(deviceId, btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${ENDPOINTS.tvUpdaterDevices}/${encodeURIComponent(deviceId)}/test`, { method: "POST" });
    const data = await res.json();
    showToast(
      data.ok ? "TV Connected" : (data.needs_auth ? "Allow on TV Screen" : "TV Unreachable"),
      data.message || (data.ok ? "ADB reachable." : "Connection failed."),
      data.ok ? "success" : "warning"
    );
    await fetchTvUpdaterStatus(true);
  } catch (_) {
    showToast("Test Failed", "Could not reach Control Hub.", "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function toggleTvPaused(deviceId, currentlyPaused, btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${ENDPOINTS.tvUpdaterDevices}/${encodeURIComponent(deviceId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paused: !currentlyPaused }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast("Update Failed", data.message || "Try again.", "warning");
      return;
    }
    showToast(!currentlyPaused ? "TV Updates Paused" : "TV Updates Resumed", data.device?.name || deviceId, "info");
    await fetchTvUpdaterStatus(true);
  } catch (_) {
    showToast("Update Failed", "Could not reach Control Hub.", "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function removeTvDevice(deviceId, btn) {
  if (!btn) return;
  if (btn.dataset.confirmPending !== "true") {
    btn.dataset.confirmPending = "true";
    btn.textContent = "Confirm Remove";
    return;
  }
  btn.disabled = true;
  try {
    const res = await fetch(`${ENDPOINTS.tvUpdaterDevices}/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast("Remove Failed", data.message || "Could not remove TV.", "warning");
      return;
    }
    openInfo.delete(`card-${deviceId}`);
    openInfo.delete(`modal-${deviceId}`);
    showToast("TV Removed", "Removed TV profile from fleet.", "success");
    await fetchTvUpdaterStatus(true);
  } catch (_) {
    showToast("Remove Failed", "Could not reach Control Hub.", "danger");
  } finally {
    btn.disabled = false;
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
      saveTvEdits(form);
    });
  });
  container.querySelectorAll(".btn-tv-test").forEach((btn) => {
    btn.addEventListener("click", () => testTvConnection(btn.dataset.device, btn));
  });
  container.querySelectorAll(".btn-tv-pause").forEach((btn) => {
    btn.addEventListener("click", () => toggleTvPaused(btn.dataset.device, btn.dataset.paused === "true", btn));
  });
  container.querySelectorAll(".btn-tv-remove").forEach((btn) => {
    btn.addEventListener("click", () => removeTvDevice(btn.dataset.device, btn));
  });
}

function renderFleetPreview(devices) {
  if (!tvFleetPreview) return;
  if (isEditingIn(tvFleetPreview)) return;
  if (!devices || devices.length === 0) {
    tvFleetPreview.innerHTML = `<div class="empty-state">No Android TV devices configured or reachable.</div>`;
    return;
  }

  tvFleetPreview.innerHTML = `
    <div class="fleet-ledger-table">
      <div class="fleet-ledger-head" aria-hidden="true">
        <span>Device &amp; Model</span>
        <span>ADB Endpoint</span>
        <span>Foreground &amp; Packages</span>
        <span>ADB State</span>
      </div>
      ${devices.map((dev) => {
        const isOnline = Boolean(dev.is_online);
        const fgName = isOnline ? escapeHtml(dev.foreground_app_name || "Idle / Launcher") : null;
        const isFgManaged = isOnline && (dev.apps || []).some((a) => a.is_foreground);
        const hasPending = (dev.apps || []).some((a) => !a.is_up_to_date || !a.is_installed);

        let statusPillClass = "synced";
        let statusPillText = "Up to Date";
        if (!isOnline) {
          statusPillClass = "offline";
          statusPillText = "Standby / Offline";
        } else if (hasPending) {
          statusPillClass = "pending";
          statusPillText = "Pending Updates";
        }

        const pkgSummary = (dev.apps || []).map((a) => {
          const ver = a.installed_name ? `v${escapeHtml(a.installed_name)}` : (a.installed_code > 0 ? `#${a.installed_code}` : "not installed");
          return `<span class="fleet-pkg-tag font-mono">${escapeHtml(a.name)}: ${ver}</span>`;
        }).join("");

        return `
          <div class="fleet-item ${isOnline ? "fleet-online" : "fleet-offline"}">
            <div class="fleet-row-grid">
              <div class="fleet-col-device">
                ${nameButton(dev, "card")}
                <span class="fleet-model-sub">${escapeHtml(dev.model_label || "Model not probed")}</span>
              </div>
              <div class="fleet-col-endpoint">
                <span class="fleet-device-ip font-mono">${escapeHtml(dev.ip)}:${escapeHtml(dev.port)}</span>
              </div>
              <div class="fleet-col-apps">
                <span class="fleet-app-tag ${isFgManaged ? "text-amber" : (isOnline ? "text-cool" : "text-muted")}">
                  ${isOnline ? `Active: ${fgName}` : "Standby / Offline"}
                </span>
                ${pkgSummary ? `<div class="fleet-pkg-list">${pkgSummary}</div>` : ""}
              </div>
              <div class="fleet-col-status">
                <span class="fleet-status-pill ${statusPillClass}">${statusPillText}</span>
              </div>
            </div>
            ${deviceInfoPanel(dev, "card")}
          </div>
        `;
      }).join("")}
    </div>
  `;
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
  setupAddTvWizard();

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

const BRAND_GUIDES = {
  google: {
    step1: "Open <strong>Settings &rarr; System &rarr; About</strong> and tap <strong>Android TV OS build</strong> 7 times until &ldquo;You are now a developer!&rdquo; shows.",
    step2: "Open <strong>Settings &rarr; System &rarr; Developer options</strong> and turn on <strong>USB debugging</strong> and <strong>Network debugging</strong>.",
  },
  fire: {
    step1: "Open <strong>Settings &rarr; My Fire TV &rarr; About</strong> and click your Fire TV model name <strong>7 times</strong> until &ldquo;No need, you are already a developer.&rdquo; appears.",
    step2: "Open <strong>Settings &rarr; My Fire TV &rarr; Developer options</strong> and turn on <strong>ADB Debugging</strong>.",
  },
  xiaomi: {
    step1: "Open <strong>Settings &rarr; Device Preferences &rarr; About</strong> and tap <strong>Build</strong> 7 times.",
    step2: "Open <strong>Developer options</strong> and turn on <strong>USB debugging</strong> and <strong>Network debugging (ADB over network)</strong>.",
  },
  sony: {
    step1: "Open <strong>Settings &rarr; System (or Device Preferences) &rarr; About</strong> and select <strong>Build / Android TV OS build</strong> 7 times.",
    step2: "Open <strong>Developer options</strong> and turn on <strong>ADB debugging / USB debugging</strong> (plus Network debugging if listed).",
  },
};

const WIZ_STEP_LABELS = [
  "Enable Developer Options",
  "Enable ADB over Network",
  "Enter IP or Scan LAN",
  "Connect & Authorize on TV",
  "Name TV & Pick Apps",
];

function wizardFigureSvg(step) {
  const caption = WIZ_STEP_LABELS[step - 1] || "";
  const badges = [
    `<rect x="18" y="14" width="184" height="62" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="110" y="39" text-anchor="middle" fill="currentColor" font-size="11" font-family="monospace">Settings &gt; About</text><text x="110" y="59" text-anchor="middle" fill="var(--color-accent)" font-size="12" font-family="monospace">Build [x7]</text>`,
    `<rect x="18" y="14" width="184" height="62" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="110" y="38" text-anchor="middle" fill="currentColor" font-size="11" font-family="monospace">Developer Options</text><text x="110" y="59" text-anchor="middle" fill="var(--color-accent)" font-size="12" font-family="monospace">ADB Debug: ON</text>`,
    `<rect x="18" y="14" width="184" height="62" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="110" y="38" text-anchor="middle" fill="currentColor" font-size="11" font-family="monospace">Network IP :5555</text><text x="110" y="59" text-anchor="middle" fill="var(--color-accent)" font-size="12" font-family="monospace">192.168.1.xxx</text>`,
    `<rect x="18" y="14" width="184" height="62" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="110" y="37" text-anchor="middle" fill="currentColor" font-size="11" font-family="monospace">Allow USB Debugging?</text><text x="110" y="59" text-anchor="middle" fill="var(--color-accent)" font-size="12" font-family="monospace">[Always Allow]</text>`,
    `<rect x="18" y="14" width="184" height="62" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="110" y="38" text-anchor="middle" fill="currentColor" font-size="11" font-family="monospace">Model + Apps</text><text x="110" y="59" text-anchor="middle" fill="var(--color-accent)" font-size="12" font-family="monospace">Ready to Sync</text>`,
  ];
  return `<svg width="220" height="90" viewBox="0 0 220 90" role="img" aria-label="${escapeHtml(caption)}">${badges[step - 1] || badges[0]}</svg>`;
}

function setupAddTvWizard() {
  const modal = $("add-tv-wizard-modal");
  const btnOpen = $("btn-add-tv");
  const btnClose = $("add-tv-modal-close");
  const btnDismiss = $("add-tv-modal-dismiss");
  const btnBack = $("btn-tv-wiz-back");
  const btnNext = $("btn-tv-wiz-next");
  const btnSave = $("btn-tv-wiz-save");
  const btnScan = $("btn-tv-wiz-scan");
  const btnConnect = $("btn-tv-wiz-connect");
  const stepBadge = $("tv-wiz-step-badge");
  const stepLabel = $("tv-wiz-step-label");
  const figure = $("tv-wiz-figure");
  const ipInput = $("tv-wiz-ip-input");
  const portInput = $("tv-wiz-port-input");
  const scanResults = $("tv-wiz-scan-results");
  const connectStatus = $("tv-wiz-connect-status");
  const detectedSummary = $("tv-wiz-detected-summary");
  const nameInput = $("tv-wiz-name-input");
  const appsList = $("tv-wiz-apps-list");
  if (!modal || !btnOpen) return;

  registerModal(modal, { closeButtons: [btnClose, btnDismiss] });

  let step = 1;
  let brand = "google";
  let probeData = null;
  let selectedApps = new Set(["org.smarttube.stable", "com.lagradost.cloudstream3.prerelease"]);

  const renderBrandGuide = () => {
    const guide = BRAND_GUIDES[brand] || BRAND_GUIDES.google;
    const s1 = $("tv-wiz-step1-desc");
    const s2 = $("tv-wiz-step2-desc");
    if (s1) s1.innerHTML = guide.step1;
    if (s2) s2.innerHTML = guide.step2;
    modal.querySelectorAll(".tv-brand-tab").forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab.dataset.brand === brand));
    });
  };

  const renderStep = () => {
    for (let i = 1; i <= 5; i++) {
      const p = $(`tv-wiz-panel-${i}`);
      if (p) p.hidden = i !== step;
    }
    if (stepBadge) stepBadge.textContent = `Step ${step} of 5`;
    if (stepLabel) stepLabel.textContent = WIZ_STEP_LABELS[step - 1] || "";
    if (figure) figure.innerHTML = wizardFigureSvg(step);
    if (btnBack) btnBack.disabled = step === 1;
    if (btnNext) btnNext.hidden = step >= 5;
    if (btnSave) btnSave.hidden = step !== 5;
  };

  const renderAppsChooser = (apps) => {
    if (!appsList) return;
    const catalog = Array.isArray(apps) && apps.length ? apps : [
      { id: "smarttube", package: "org.smarttube.stable", name: "SmartTube" },
      { id: "cloudstream", package: "com.lagradost.cloudstream3.prerelease", name: "CloudStream Beta" },
    ];
    appsList.innerHTML = catalog.map((app) => {
      const pressed = selectedApps.has(app.package);
      return `<button type="button" class="btn-secondary tv-wiz-app-btn" data-pkg="${escapeHtml(app.package)}" aria-pressed="${pressed}">${escapeHtml(app.name)}: ${pressed ? "On" : "Off"}</button>`;
    }).join("");
    appsList.querySelectorAll(".tv-wiz-app-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const pkg = btn.dataset.pkg;
        if (selectedApps.has(pkg)) selectedApps.delete(pkg);
        else selectedApps.add(pkg);
        renderAppsChooser(catalog);
      });
    });
  };

  modal.querySelectorAll(".tv-brand-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      brand = tab.dataset.brand || "google";
      renderBrandGuide();
    });
  });

  btnOpen.addEventListener("click", () => {
    step = 1;
    probeData = null;
    if (scanResults) scanResults.innerHTML = "";
    if (connectStatus) connectStatus.hidden = true;
    renderBrandGuide();
    renderAppsChooser(state.tvSnapshot?.managed_apps || []);
    renderStep();
    openModal(modal, btnOpen);
  });

  if (btnBack) {
    btnBack.addEventListener("click", () => {
      if (step > 1) {
        step -= 1;
        renderStep();
      }
    });
  }

  if (btnNext) {
    btnNext.addEventListener("click", () => {
      if (step === 3 && ipInput && !ipInput.value.trim()) {
        showToast("Enter TV IP", "Type the TV IP address or tap Scan LAN first.", "warning");
        return;
      }
      if (step < 5) {
        step += 1;
        renderStep();
      }
    });
  }

  if (btnScan) {
    btnScan.addEventListener("click", async () => {
      btnScan.disabled = true;
      btnScan.textContent = "Scanning...";
      try {
        const res = await fetch(ENDPOINTS.tvUpdaterScanLan, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ port: Number(portInput?.value || 5555) }),
        });
        const data = await res.json();
        const found = Array.isArray(data.candidates) ? data.candidates : [];
        if (!scanResults) return;
        if (found.length === 0) {
          scanResults.innerHTML = `<span class="text-muted">No open ADB ports found on the LAN subnet. Enter IP manually.</span>`;
        } else {
          scanResults.innerHTML = found.map((c) => {
            const label = c.already_added ? `${c.ip} (${c.name || "Added"})` : `${c.ip} (New TV)`;
            return `<button type="button" class="btn-secondary tv-scan-pick" data-ip="${escapeHtml(c.ip)}">${escapeHtml(label)}</button>`;
          }).join("");
          scanResults.querySelectorAll(".tv-scan-pick").forEach((b) => {
            b.addEventListener("click", () => {
              if (ipInput) ipInput.value = b.dataset.ip || "";
            });
          });
        }
      } catch (_) {
        showToast("Scan Failed", "Could not scan LAN.", "warning");
      } finally {
        btnScan.disabled = false;
        btnScan.textContent = "Scan LAN";
      }
    });
  }

  if (btnConnect) {
    btnConnect.addEventListener("click", async () => {
      const ip = ipInput?.value.trim() || "";
      const port = Number(portInput?.value || 5555);
      if (!ip) {
        step = 3;
        renderStep();
        showToast("Enter TV IP", "Provide the TV IP before connecting.", "warning");
        return;
      }
      btnConnect.disabled = true;
      btnConnect.textContent = "Connecting...";
      try {
        const res = await fetch(ENDPOINTS.tvUpdaterConnect, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ip, port }),
        });
        const data = await res.json();
        if (connectStatus) {
          connectStatus.hidden = false;
          connectStatus.textContent = data.message || "Checking ADB...";
          connectStatus.className = data.ok ? "inline-callout is-success" : (data.needs_auth ? "inline-callout is-warning" : "inline-callout is-error");
        }
        if (data.needs_auth) {
          btnConnect.textContent = "Retry Connection";
        } else if (data.ok) {
          probeData = data;
          if (nameInput) nameInput.value = data.suggested_name || "Android TV";
          if (detectedSummary) {
            const bits = [data.manufacturer, data.model, data.android ? `Android ${data.android}` : null].filter(Boolean);
            detectedSummary.textContent = bits.length ? `Detected: ${bits.join(" · ")} (${data.ip}:${data.port})` : `Endpoint: ${data.ip}:${data.port}`;
          }
          renderAppsChooser(data.apps || []);
          step = 5;
          renderStep();
          btnConnect.textContent = "Connect to TV";
        } else {
          btnConnect.textContent = "Retry Connection";
        }
      } catch (_) {
        showToast("Connect Failed", "Could not query Control Hub.", "danger");
        btnConnect.textContent = "Retry Connection";
      } finally {
        btnConnect.disabled = false;
      }
    });
  }

  if (btnSave) {
    btnSave.addEventListener("click", async () => {
      const name = nameInput?.value.trim() || "";
      const ip = ipInput?.value.trim() || "";
      const port = Number(portInput?.value || 5555);
      btnSave.disabled = true;
      try {
        const res = await fetch(ENDPOINTS.tvUpdaterDevices, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            ip,
            port,
            apps: Array.from(selectedApps),
            probe: probeData || {},
          }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
          showToast("Save Failed", data.message || "Could not save TV.", "warning");
          return;
        }
        showToast("TV Added", `"${data.device?.name || name}" added to fleet.`, "success");
        if (btnDismiss) btnDismiss.click();
        await fetchTvUpdaterStatus(true);
      } catch (_) {
        showToast("Save Failed", "Control Hub did not respond.", "danger");
      } finally {
        btnSave.disabled = false;
      }
    });
  }
}
