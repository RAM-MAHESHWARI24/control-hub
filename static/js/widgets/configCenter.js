/**
 * Widget: Configuration & Node Control Center
 * Handles read-only blueprint-managed config notices, atomic hardlink probing,
 * port status matrix, credential generator, complete Netplan 120s confirm flow,
 * and AI Copilot diagnostics exporter with plain-HTTP clipboard fallback.
 */

import { $, confirmAction, copyTextToClipboard } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS, HOSTNAME } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { closeModal, openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";

let currentSystemData = null;
let netplanCountdownTimer = null;
let netplanProbeTimer = null;
let netplanRemainingSec = 0;
let pendingImportConfig = null;

// ============================================================================
// 1. Fetch & Populate Current Configuration + Read-Only Guard
// ============================================================================

export async function fetchCurrentConfig() {
  try {
    const res = await fetch(ENDPOINTS.configCurrent);
    if (!res.ok) return false;
    const data = await res.json();

    if (data.status === "success") {
      currentSystemData = data.system || {};
      populateFormFields(
        data.config,
        data.system,
        Boolean(data.read_only),
        data.apply_hint,
        Boolean(data.blueprint_mode),
        Boolean(data.can_undo)
      );
      renderNetplanPending(data.netplan_pending);
    }
    return true;
  } catch (err) {
    console.error("Failed to fetch current config:", err);
    return false;
  }
}

function populateFormFields(cfg, sys, readOnly, applyHint, blueprintMode = false, canUndo = false) {
  if (!cfg) return;

  const readonlyBanner = $("config-readonly-banner");
  const readonlyHint = $("config-readonly-hint");
  const btnSave = $("btn-save-config");
  const btnPreview = $("btn-preview-config-diff");
  const btnUndo = $("btn-undo-config");
  const tabManifest = $("cfg-tab-manifest");

  if (readonlyBanner) readonlyBanner.hidden = !readOnly;
  if (readonlyHint && applyHint) readonlyHint.textContent = applyHint;
  if (btnSave) {
    btnSave.disabled = readOnly;
    btnSave.title = readOnly ? "Managed by setup.sh on blueprint installs" : "";
  }
  if (btnPreview) btnPreview.hidden = readOnly;
  if (btnUndo) btnUndo.hidden = !(blueprintMode && canUndo && !readOnly);
  if (tabManifest) tabManifest.hidden = !blueprintMode;

  const editableFields = [
    ["cfg-hdd-data", cfg.hdd_data || "/mnt/hdd/data"],
    ["cfg-hdd-memories", cfg.hdd_memories || "/mnt/hdd/Memories"],
    ["cfg-puid", cfg.puid || "1000"],
    ["cfg-pgid", cfg.pgid || "1000"],
    ["cfg-timezone", cfg.timezone || state.timezone || "UTC"],
    ["cfg-hub-port", cfg.control_hub_port || "7575"],
    ["cfg-gdrive-remote", cfg.gdrive_remote || ""],
    ["cfg-qbit-pass", cfg.qbittorrent_pass || ""],
    ["cfg-radarr-key", cfg.radarr_api_key || ""],
    ["cfg-sonarr-key", cfg.sonarr_api_key || ""],
    ["cfg-prowlarr-key", cfg.prowlarr_api_key || ""],
  ];

  editableFields.forEach(([id, val]) => {
    const el = $(id);
    if (el) {
      el.value = val;
      // Keep HDD data path editable for hardlink probing even when save is read-only
      if (id !== "cfg-hdd-data") {
        el.readOnly = readOnly;
      }
    }
  });

  if (sys && sys.network) {
    const cfgNetIface = $("cfg-netplan-iface");
    const cfgNetIp = $("cfg-netplan-ip");
    const cfgNetGw = $("cfg-netplan-gw");
    const cfgNetDns = $("cfg-netplan-dns");

    if (cfgNetIface) cfgNetIface.value = sys.network.active_nic || "";
    if (cfgNetIp) cfgNetIp.value = sys.network.current_ip || "";
    if (cfgNetGw) cfgNetGw.value = sys.network.default_gateway || "";
    if (cfgNetDns) cfgNetDns.value = (sys.network.dns_servers || ["1.1.1.1", "8.8.8.8"]).join(", ");

    const dhcpMacEl = $("cfg-dhcp-mac");
    if (dhcpMacEl) {
      const ifaces = sys.network.interfaces || [];
      const activeObj = ifaces.find((n) => n.name === sys.network.active_nic) || ifaces[0];
      dhcpMacEl.textContent = (activeObj && activeObj.mac) ? activeObj.mac : "your server MAC";
    }
  }
}

// ============================================================================
// 2. Netplan 120s Pending Confirmation Flow
// ============================================================================

export async function fetchNetplanStatus() {
  try {
    const res = await fetch(ENDPOINTS.configNetplanStatus);
    if (!res.ok) return false;
    const data = await res.json();
    renderNetplanPending(data.result);
    return true;
  } catch (_) {
    return false;
  }
}

function renderNetplanPending(pendingInfo) {
  const banner = $("netplan-pending-banner");
  const bannerIp = $("netplan-banner-ip");
  const bannerCountdown = $("netplan-banner-countdown");
  const modalBox = $("netplan-modal-pending");
  const modalIp = $("netplan-modal-ip");
  const modalText = $("netplan-modal-countdown-text");
  const continueLink = $("netplan-continue-link");

  state.netplanPending = pendingInfo && pendingInfo.pending ? pendingInfo : null;

  if (netplanCountdownTimer) {
    clearInterval(netplanCountdownTimer);
    netplanCountdownTimer = null;
  }
  if (netplanProbeTimer) {
    clearInterval(netplanProbeTimer);
    netplanProbeTimer = null;
  }

  if (!state.netplanPending) {
    if (banner) banner.hidden = true;
    if (modalBox) modalBox.hidden = true;
    if (continueLink) continueLink.hidden = true;
    return;
  }

  netplanRemainingSec = Number(state.netplanPending.remaining_sec || 0);
  const ipRaw = String(state.netplanPending.ip || HOSTNAME);
  const ipHost = ipRaw.split("/")[0];
  if (bannerIp) bannerIp.textContent = ipRaw;
  if (modalIp) modalIp.textContent = ipRaw;
  if (banner) banner.hidden = false;
  if (modalBox) modalBox.hidden = false;

  const updateTick = () => {
    const sec = Math.max(0, netplanRemainingSec);
    if (bannerCountdown) bannerCountdown.textContent = `${sec}s`;
    if (modalText) {
      const prefix = netplanProbeTimer && ipHost !== HOSTNAME
        ? `Checking that the server is reachable on ${ipHost}... `
        : "";
      modalText.textContent = sec > 0
        ? `${prefix}Reverts in ${sec}s if not confirmed from this address.`
        : "The revert window has passed. The previous network configuration is being restored.";
    }
    if (netplanRemainingSec <= 0 && netplanCountdownTimer) {
      clearInterval(netplanCountdownTimer);
      netplanCountdownTimer = null;
      if (netplanProbeTimer) {
        clearInterval(netplanProbeTimer);
        netplanProbeTimer = null;
      }
      setTimeout(fetchNetplanStatus, 3000);
    }
    netplanRemainingSec -= 1;
  };
  updateTick();
  netplanCountdownTimer = setInterval(updateTick, 1000);

  if (continueLink) {
    if (ipHost && ipHost !== HOSTNAME) {
      const proto = window.location.protocol;
      const portPart = window.location.port ? `:${window.location.port}` : "";
      const newBase = `${proto}//${ipHost}${portPart}`;
      continueLink.href = `${newBase}/?netplan_confirm=1`;
      continueLink.textContent = `Continue on ${ipHost}`;
      continueLink.hidden = false;
      const probeNewHost = async () => {
        try {
          await fetch(`${newBase}/api/health`, { mode: "no-cors", cache: "no-store" });
          if (modalText) {
            modalText.textContent = `Server reachable on ${ipHost}. Click Continue on ${ipHost} to keep this IP (reverts in ${Math.max(0, netplanRemainingSec)}s if not confirmed).`;
          }
          if (netplanProbeTimer) {
            clearInterval(netplanProbeTimer);
            netplanProbeTimer = null;
          }
        } catch (_) { /* not reachable yet */ }
      };
      netplanProbeTimer = setInterval(probeNewHost, 3000);
      probeNewHost();
    } else {
      continueLink.hidden = true;
    }
  }
}

export async function confirmNetplanIp() {
  const btns = [$("btn-netplan-banner-confirm"), $("btn-netplan-modal-confirm")].filter(Boolean);
  btns.forEach((b) => { b.disabled = true; });
  try {
    const res = await fetch(ENDPOINTS.configNetplanConfirm, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json();
    const result = data.result || {};
    if (res.ok && result.success) {
      showToast("Static IP Confirmed", result.message || "Revert timer disarmed. New static IP is permanent.", "success");
      renderNetplanPending({ pending: false });
    } else {
      showToast("Confirmation Failed", result.message || result.error || "Could not confirm Netplan change.", "danger");
    }
  } catch (err) {
    showToast("Error", `Could not confirm static IP: ${err.message}`, "danger");
  } finally {
    btns.forEach((b) => { b.disabled = false; });
  }
}

// ============================================================================
// 3. Storage & Atomic Hardlink Verification
// ============================================================================

export async function runHardlinkTest() {
  const cfgHddData = $("cfg-hdd-data");
  const btnTestHardlink = $("btn-test-hardlink");
  const hlSpinner = $("hl-spinner");
  const hlResultBanner = $("hl-result-banner");
  const hlResultText = $("hl-result-text");

  const targetPath = cfgHddData ? cfgHddData.value.trim() : "/mnt/hdd/data";
  if (!targetPath) {
    showToast("Error", "Please specify a storage path to test.", "warning");
    return;
  }

  if (btnTestHardlink) btnTestHardlink.disabled = true;
  if (hlSpinner) hlSpinner.style.display = "inline-block";
  if (hlResultBanner) {
    hlResultBanner.style.display = "block";
    hlResultBanner.className = "hl-banner";
    if (hlResultText) hlResultText.textContent = `Testing atomic hardlink on "${targetPath}" via os.link()...`;
  }

  try {
    const res = await fetch(ENDPOINTS.configVerifyHardlink, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: targetPath }),
    });
    const data = await res.json();
    const result = data.result || {};

    if (result.supported) {
      if (hlResultBanner) hlResultBanner.className = "hl-banner hl-success";
      if (hlResultText) {
        hlResultText.innerHTML = `<strong>Atomic Hardlinks Verified (${escapeHtml(result.latency_ms)} ms)</strong><br><span>Inode: ${escapeHtml(result.inode)}. Zero-copy instant moves supported on this mount.</span>`;
      }
      showToast("Hardlinks Verified", `Zero-copy instant moves supported (${result.latency_ms} ms).`, "success");
    } else {
      if (hlResultBanner) hlResultBanner.className = "hl-banner hl-error";
      if (hlResultText) {
        hlResultText.innerHTML = `<strong>Hardlinks Failed</strong><br><span>${escapeHtml(result.error || "Cross-device link or unsupported filesystem.")}</span>`;
      }
      showToast("Hardlink Warning", "Cross-device link or unsupported filesystem detected.", "danger");
    }
  } catch (err) {
    if (hlResultBanner) hlResultBanner.className = "hl-banner hl-error";
    if (hlResultText) hlResultText.textContent = `Verification error: ${err.message}`;
  } finally {
    if (btnTestHardlink) btnTestHardlink.disabled = false;
    if (hlSpinner) hlSpinner.style.display = "none";
  }
}

// ============================================================================
// 4. Port Matrix Prober
// ============================================================================

export async function fetchPortsMatrix() {
  const btnRefreshPorts = $("btn-refresh-ports");
  const portsGrid = $("ports-matrix-grid");

  if (btnRefreshPorts) btnRefreshPorts.disabled = true;
  if (portsGrid) portsGrid.innerHTML = '<div class="empty-state">Probing host ports (IPv4)...</div>';

  try {
    const res = await fetch(ENDPOINTS.configPorts);
    const data = await res.json();
    const ports = data.ports || {};

    if (portsGrid) {
      portsGrid.innerHTML = "";
      Object.keys(ports).forEach((key) => {
        const item = ports[key];
        const isFree = Boolean(item.available);
        const portCard = document.createElement("div");
        portCard.className = `port-matrix-card ${isFree ? "port-free" : "port-bound"}`;

        const isWebUi = [7575, 8096, 5055, 8080, 8989, 7878, 9696, 6767, 2283, 8099, 8888].includes(item.port);
        const webUrl = isWebUi ? `http://${HOSTNAME}:${item.port}` : null;

        portCard.innerHTML = `
          <div class="port-card-header">
            <span class="port-badge-num">:${escapeHtml(item.port)}</span>
            <span class="port-badge-status ${isFree ? "badge-free" : "badge-bound"}">
              ${isFree ? "Free" : "In Use"}
            </span>
          </div>
          <div class="port-service-name">${escapeHtml(item.name)}</div>
          <div class="port-category-tag">${escapeHtml(item.category)}</div>
          ${!isFree && webUrl
            ? `<a href="${webUrl}" target="_blank" rel="noopener" class="port-link-btn">Open Web UI &nearr;</a>`
            : `<span class="port-desc-text">${isFree ? "Available for bind" : "Service listening"}</span>`
          }
        `;
        portsGrid.appendChild(portCard);
      });
    }
  } catch (err) {
    if (portsGrid) portsGrid.innerHTML = `<div class="empty-state">Failed to probe ports: ${escapeHtml(err.message)}</div>`;
  } finally {
    if (btnRefreshPorts) btnRefreshPorts.disabled = false;
  }
}

// ============================================================================
// 5. Credential & Secrets Generator
// ============================================================================

export async function generateFreshSecrets() {
  const btnGenerateSecrets = $("btn-generate-secrets");
  if (btnGenerateSecrets) btnGenerateSecrets.disabled = true;

  try {
    const res = await fetch(ENDPOINTS.configGenerateSecrets, { method: "POST" });
    const data = await res.json();
    const secrets = data.secrets || {};
    const map = [
      ["cfg-qbit-pass", secrets.qbittorrent_pass],
      ["cfg-radarr-key", secrets.radarr_api_key],
      ["cfg-sonarr-key", secrets.sonarr_api_key],
      ["cfg-prowlarr-key", secrets.prowlarr_api_key],
    ];
    map.forEach(([id, val]) => {
      const node = $(id);
      if (node && val) node.value = val;
    });
    showToast("Fresh Secrets Generated", "High-entropy alphanumeric passwords and API keys populated.", "success");
  } catch (err) {
    showToast("Error", `Could not generate secrets: ${err.message}`, "danger");
  } finally {
    if (btnGenerateSecrets) btnGenerateSecrets.disabled = false;
  }
}

// ============================================================================
// 6. Netplan Preview & Safe Apply
// ============================================================================

export async function previewNetplan() {
  const iface = ($("cfg-netplan-iface")?.value || "").trim();
  const ip = ($("cfg-netplan-ip")?.value || "").trim();
  const gw = ($("cfg-netplan-gw")?.value || "").trim();
  const dns = ($("cfg-netplan-dns")?.value || "1.1.1.1, 8.8.8.8").split(",").map((s) => s.trim()).filter(Boolean);
  const btn = $("btn-preview-netplan");
  const preview = $("netplan-yaml-preview");

  if (btn) btn.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.configNetplanPreview, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interface: iface, ip, gateway: gw, dns }),
    });
    const data = await res.json();
    if (preview) {
      const yamlText = data.yaml || "No YAML generated";
      preview.replaceChildren();
      yamlText.split("\n").forEach((line, idx, arr) => {
        const span = document.createElement("span");
        const trimmed = line.trim();
        let cls = "yaml-line";
        if (/^(addresses:|gateway4:|via:|nameservers:|routes:|\-\s+\d+\.\d+)/.test(trimmed)) {
          cls += " row--plus";
        } else if (/^dhcp[46]:\s*(false|no)/.test(trimmed)) {
          cls += " row--minus";
        }
        span.className = cls;
        span.textContent = idx < arr.length - 1 ? `${line}\n` : line;
        preview.append(span);
      });
      preview.style.display = "block";
    }
    showToast("Netplan YAML Ready", `Preview generated for ${iface || "active NIC"}.`, "info");
  } catch (err) {
    showToast("Error", `Netplan preview failed: ${err.message}`, "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

export async function applyNetplanSafe() {
  const iface = ($("cfg-netplan-iface")?.value || "").trim();
  const ip = ($("cfg-netplan-ip")?.value || "").trim();
  const gw = ($("cfg-netplan-gw")?.value || "").trim();
  const dns = ($("cfg-netplan-dns")?.value || "1.1.1.1, 8.8.8.8").split(",").map((s) => s.trim()).filter(Boolean);
  const btn = $("btn-apply-netplan");

  const ok = await confirmAction({
    title: `Apply static IP ${ip} to ${iface}?`,
    message: "Control Hub will back up existing Netplan YAML, validate with `netplan generate`, arm a 120-second revert timer, and apply the address.",
    warning: "You must confirm from the new IP within 120 seconds or the previous network configuration will restore automatically.",
    confirmLabel: "Apply with 120s Rollback",
    danger: true,
    triggerEl: btn,
  });
  if (!ok) return;

  if (btn) btn.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.configNetplanApply, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interface: iface, ip, gateway: gw, dns, timeout: 120 }),
    });
    const data = await res.json();
    const result = data.result || {};
    if (res.ok && result.success) {
      showToast("Netplan Applied", result.message || `Static IP ${ip} applied with 120s revert timer.`, "success", 6000);
      await fetchNetplanStatus();
    } else {
      showToast("Netplan Not Applied", result.message || result.error || "Configuration was rejected and rolled back.", "warning", 6000);
    }
  } catch (err) {
    showToast("Error", `Netplan application error: ${err.message}`, "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ============================================================================
// 7. Save Configuration
// ============================================================================

function _collectConfigPayload() {
  return {
    hdd_data: ($("cfg-hdd-data")?.value || "/mnt/hdd/data").trim(),
    hdd_memories: ($("cfg-hdd-memories")?.value || "/mnt/hdd/Memories").trim(),
    puid: parseInt($("cfg-puid")?.value || "1000", 10) || 1000,
    pgid: parseInt($("cfg-pgid")?.value || "1000", 10) || 1000,
    timezone: ($("cfg-timezone")?.value || state.timezone || "UTC").trim(),
    control_hub_port: parseInt($("cfg-hub-port")?.value || "7575", 10) || 7575,
    gdrive_remote: ($("cfg-gdrive-remote")?.value || "").trim(),
    qbittorrent_pass: ($("cfg-qbit-pass")?.value || "").trim(),
    radarr_api_key: ($("cfg-radarr-key")?.value || "").trim(),
    sonarr_api_key: ($("cfg-sonarr-key")?.value || "").trim(),
    prowlarr_api_key: ($("cfg-prowlarr-key")?.value || "").trim(),
  };
}

function _renderDiffBox(preEl, changes, errors) {
  if (!preEl) return;
  if (Array.isArray(errors) && errors.length > 0) {
    preEl.textContent = `Validation error:\n- ${errors.join("\n- ")}`;
    preEl.style.display = "block";
    return;
  }
  if (!Array.isArray(changes) || changes.length === 0) {
    preEl.textContent = "No changes detected compared to stored settings.";
    preEl.style.display = "block";
    return;
  }
  preEl.textContent = changes
    .map((c) => `${c.label || c.field}: ${String(c.old ?? "")} -> ${String(c.new ?? "")}`)
    .join("\n");
  preEl.style.display = "block";
}

export async function previewConfigDiff() {
  const btn = $("btn-preview-config-diff");
  const pre = $("config-diff-preview");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.configPreview, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_collectConfigPayload()),
    });
    const data = await res.json();
    _renderDiffBox(pre, data.changes, data.errors);
    if (!res.ok || data.valid === false) {
      showToast("Validation Notice", (data.errors || [data.message])[0] || "Check highlighted fields.", "warning");
    }
  } catch (err) {
    showToast("Error", `Could not preview diff: ${err.message}`, "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

export async function saveConfiguration() {
  const btnSave = $("btn-save-config");
  const spinner = $("config-save-spinner");
  const modal = $("config-center-modal");
  const pre = $("config-diff-preview");

  const payload = _collectConfigPayload();
  if (btnSave) btnSave.disabled = true;
  if (spinner) spinner.style.display = "inline-block";

  try {
    const prevRes = await fetch(ENDPOINTS.configPreview, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const prevData = await prevRes.json();
    _renderDiffBox(pre, prevData.changes, prevData.errors);
    if (!prevRes.ok || prevData.valid === false) {
      showToast("Validation Failed", (prevData.errors || [prevData.message])[0] || "Fix validation errors first.", "warning", 5000);
      return;
    }

    const changeCount = (prevData.changes || []).length;
    if (changeCount > 0) {
      const ok = await confirmAction({
        title: `Apply ${changeCount} configuration change(s)?`,
        message: "Control Hub will back up /etc/homelab/config.json and re-render blueprint environment files.",
        confirmLabel: "Apply Changes",
        danger: false,
        triggerEl: btnSave,
      });
      if (!ok) return;
    }

    const res = await fetch(ENDPOINTS.configUpdate, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (res.ok && data.status === "success") {
      showToast("Configuration Saved", data.message || "Unified settings synchronized across env files.", "success");
      await fetchCurrentConfig();
      if (modal) closeModal(modal);
    } else {
      showToast("Save Failed", data.message || "Could not save configuration.", "warning", 6000);
    }
  } catch (err) {
    showToast("Error", `Failed to save configuration: ${err.message}`, "danger");
  } finally {
    if (btnSave) btnSave.disabled = false;
    if (spinner) spinner.style.display = "none";
  }
}

export async function undoConfiguration() {
  const btnUndo = $("btn-undo-config");
  const ok = await confirmAction({
    title: "Undo last configuration change?",
    message: "Restores the previous /etc/homelab/config.json snapshot and re-renders environment files.",
    confirmLabel: "Restore Snapshot",
    danger: true,
    triggerEl: btnUndo,
  });
  if (!ok) return;

  if (btnUndo) btnUndo.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.configUndo, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const data = await res.json();
    if (res.ok && data.status === "success") {
      showToast("Snapshot Restored", data.message || "Previous settings restored.", "success");
      await fetchCurrentConfig();
    } else {
      showToast("Undo Failed", data.message || "Could not undo configuration.", "warning");
    }
  } catch (err) {
    showToast("Error", `Undo failed: ${err.message}`, "danger");
  } finally {
    if (btnUndo) btnUndo.disabled = false;
  }
}

export async function fetchInstallManifest() {
  const box = $("cfg-manifest-content");
  if (!box) return;
  box.textContent = "Loading install manifest...";
  try {
    const res = await fetch(ENDPOINTS.configManifest);
    const data = await res.json();
    const m = data.manifest;
    if (!data.installed || !m) {
      box.className = "empty-state";
      box.textContent = "No blueprint manifest found (standalone install mode).";
      return;
    }
    const listJoin = (arr) => (Array.isArray(arr) && arr.length ? arr.join(", ") : "None");
    const composeItems = Array.isArray(m.compose) ? m.compose.map((c) => `${c.module}: ${c.dir}`) : [];
    box.className = "panel detail-panel";
    box.innerHTML = `
      <div class="kv-row"><span>Blueprint Version:</span><strong class="font-mono">${escapeHtml(m.blueprint_version || "unknown")}</strong></div>
      <div class="kv-row"><span>Installed At:</span><strong class="font-mono">${escapeHtml(m.installed_at || "unknown")}</strong></div>
      <div class="kv-row"><span>Install Directory:</span><strong class="font-mono">${escapeHtml(m.install_dir || "")}</strong></div>
      <div class="kv-row"><span>Service Account:</span><strong class="font-mono">${escapeHtml(m.service_user || "")}</strong></div>
      <div class="kv-row"><span>Modules:</span><strong class="font-mono">${escapeHtml(listJoin(m.modules))}</strong></div>
      <div class="kv-row"><span>Compose Stacks:</span><strong class="font-mono">${escapeHtml(listJoin(composeItems))}</strong></div>
      <div class="kv-row"><span>Systemd Units:</span><strong class="font-mono">${escapeHtml(listJoin(m.units))}</strong></div>
      <div class="kv-row"><span>Cron Files:</span><strong class="font-mono">${escapeHtml(listJoin(m.crons))}</strong></div>
    `;
  } catch (err) {
    box.className = "empty-state";
    box.textContent = `Failed to load manifest: ${err.message}`;
  }
}

async function _downloadJsonEndpoint(endpoint, fallbackFilename) {
  try {
    const res = await fetch(`${endpoint}?download=1`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fallbackFilename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast("Download Ready", `Saved ${fallbackFilename} (secrets stripped).`, "success");
  } catch (err) {
    showToast("Download Failed", err.message, "danger");
  }
}

async function handleImportFileSelected(ev) {
  const file = ev.target?.files?.[0];
  const previewEl = $("cfg-import-preview");
  const applyBtn = $("btn-apply-import");
  pendingImportConfig = null;
  if (applyBtn) applyBtn.hidden = true;
  if (!file) return;

  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    const res = await fetch(ENDPOINTS.configImport, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: parsed.config || parsed, preview: true }),
    });
    const data = await res.json();
    _renderDiffBox(previewEl, data.changes, data.errors);
    if (res.ok && data.valid !== false && data.sanitized_config) {
      pendingImportConfig = data.sanitized_config;
      if (applyBtn) applyBtn.hidden = false;
    }
  } catch (err) {
    if (previewEl) {
      previewEl.textContent = `Could not parse settings JSON: ${err.message}`;
      previewEl.style.display = "block";
    }
  }
}

async function handleApplyImport() {
  if (!pendingImportConfig) return;
  const applyBtn = $("btn-apply-import");
  if (applyBtn) applyBtn.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.configImport, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: pendingImportConfig, preview: false }),
    });
    const data = await res.json();
    if (res.ok && data.status === "success") {
      showToast("Settings Imported", data.message || "Imported settings applied cleanly.", "success");
      pendingImportConfig = null;
      if (applyBtn) applyBtn.hidden = true;
      await fetchCurrentConfig();
    } else {
      showToast("Import Failed", data.message || "Could not apply imported settings.", "warning");
    }
  } catch (err) {
    showToast("Error", `Import failed: ${err.message}`, "danger");
  } finally {
    if (applyBtn) applyBtn.disabled = false;
  }
}

// ============================================================================
// 8. AI Copilot Diagnostics Exporter (with plain-HTTP clipboard fallback)
// ============================================================================

export async function fetchAiDiagnostics() {
  const aiPromptContent = $("ai-prompt-content");
  const aiCpuPill = $("ai-cpu-pill");
  const aiRamPill = $("ai-ram-pill");
  const aiHwPill = $("ai-hw-pill");
  const aiHaswellPill = $("ai-haswell-pill");

  if (aiPromptContent) aiPromptContent.textContent = "Probing hardware vitals and generating AI prompt...";

  try {
    const res = await fetch(ENDPOINTS.configAiDiagnostics);
    const data = await res.json();
    const snap = data.snapshot || {};

    if (aiCpuPill && snap.cpu) {
      aiCpuPill.textContent = `${snap.cpu.model} (${snap.cpu.threads}T)`;
    }
    if (aiRamPill && snap.ram) {
      aiRamPill.textContent = snap.ram.total_gib !== null
        ? `${snap.ram.total_gib} GiB Total (${snap.ram.free_gib ?? "?"} GiB Free)`
        : "RAM: Unavailable";
    }
    if (aiHwPill && snap.hwaccel) {
      aiHwPill.textContent = snap.hwaccel.vendor_label
        ? `${snap.hwaccel.vendor_label}`
        : (snap.hwaccel.has_vaapi_dri ? "VAAPI / DRM Active" : (snap.hwaccel.has_nvidia ? "NVIDIA GPU Active" : "CPU Direct Play"));
    }
    if (aiHaswellPill && snap.cpu) {
      aiHaswellPill.textContent = snap.cpu.is_low_power ? "Legacy Low-Power (Direct Play)" : "Hardware Transcode Ready";
    }
    if (aiPromptContent) {
      aiPromptContent.textContent = data.ai_prompt || "No prompt generated.";
    }
  } catch (err) {
    if (aiPromptContent) aiPromptContent.textContent = `Failed to generate AI context: ${err.message}`;
  }
}

export async function copyAiPromptToClipboard() {
  const aiPromptContent = $("ai-prompt-content");
  const btnCopyAiPrompt = $("btn-copy-ai-prompt");
  const promptText = aiPromptContent ? aiPromptContent.textContent : "";
  if (!promptText) return;

  const ok = await copyTextToClipboard(promptText);
  if (ok) {
    showToast("Copied to Clipboard", "Token-optimized diagnostic prompt ready to paste.", "success");
    if (btnCopyAiPrompt) {
      const span = btnCopyAiPrompt.querySelector("span");
      const orig = span ? span.textContent : "Copy Diagnostic Prompt";
      if (span) span.textContent = "Copied!";
      setTimeout(() => { if (span) span.textContent = orig; }, 2000);
    }
  } else {
    showToast("Copy Error", "Browser blocked clipboard copy. Select the text manually.", "warning");
  }
}

// ============================================================================
// 9. Tab Navigation & Master Initialization
// ============================================================================

function activateConfigTab(targetTab) {
  const tabBtns = document.querySelectorAll(".cfg-tab-btn");
  const tabPanes = document.querySelectorAll(".cfg-tab-pane");
  tabBtns.forEach((b) => {
    const active = b.getAttribute("data-config-tab") === targetTab;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  });
  tabPanes.forEach((p) => {
    p.classList.toggle("active", p.id === `cfg-pane-${targetTab}`);
  });
  if (targetTab === "ports") fetchPortsMatrix();
  if (targetTab === "manifest") fetchInstallManifest();
}

export function openConfigCenterTab(targetTab = "paths") {
  const configModal = $("config-center-modal");
  if (configModal) openModal(configModal, $("btn-open-config-center"));
  activateConfigTab(targetTab);
  fetchCurrentConfig();
}

function setupConfigTabs() {
  const tabBtns = document.querySelectorAll(".cfg-tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-config-tab");
      if (targetTab) activateConfigTab(targetTab);
    });
  });
}

export function setupConfigCenter() {
  setupConfigTabs();

  const configModal = $("config-center-modal");
  const aiModal = $("ai-copilot-modal");
  const btnOpenConfig = $("btn-open-config-center");
  const btnOpenAi = $("btn-open-ai-copilot");

  registerModal(configModal, { closeButtons: [$("config-modal-close"), $("config-modal-cancel")] });
  registerModal(aiModal, { closeButtons: [$("ai-modal-close"), $("ai-modal-dismiss")] });

  if (btnOpenConfig) {
    btnOpenConfig.addEventListener("click", (e) => {
      e.preventDefault();
      openConfigCenterTab("paths");
    });
  }

  try {
    const params = new URLSearchParams(window.location.search || "");
    if (params.get("netplan_confirm") === "1") {
      openConfigCenterTab("network");
    }
  } catch (_) { /* ignore malformed URL */ }

  if (btnOpenAi) {
    btnOpenAi.addEventListener("click", (e) => {
      e.preventDefault();
      if (aiModal) openModal(aiModal, btnOpenAi);
      fetchAiDiagnostics();
    });
  }

  const wire = (id, fn) => { const n = $(id); if (n) n.addEventListener("click", fn); };
  wire("btn-test-hardlink", runHardlinkTest);
  wire("btn-refresh-ports", fetchPortsMatrix);
  wire("btn-generate-secrets", generateFreshSecrets);
  wire("btn-preview-netplan", previewNetplan);
  wire("btn-apply-netplan", applyNetplanSafe);
  wire("btn-preview-config-diff", previewConfigDiff);
  wire("btn-undo-config", undoConfiguration);
  wire("btn-save-config", saveConfiguration);
  wire("btn-export-settings", () => _downloadJsonEndpoint(ENDPOINTS.configExport, "homelab-settings-export.json"));
  wire("btn-download-support-bundle", () => _downloadJsonEndpoint(ENDPOINTS.configSupportBundle, "homelab-support-bundle.json"));
  wire("btn-apply-import", handleApplyImport);
  const importInput = $("cfg-import-file");
  if (importInput) importInput.addEventListener("change", handleImportFileSelected);
  wire("btn-copy-ai-prompt", copyAiPromptToClipboard);
  wire("btn-netplan-banner-confirm", confirmNetplanIp);
  wire("btn-netplan-modal-confirm", confirmNetplanIp);

  wire("btn-detect-user", () => {
    if (currentSystemData && currentSystemData.user) {
      const cfgPuid = $("cfg-puid");
      const cfgPgid = $("cfg-pgid");
      if (cfgPuid && !cfgPuid.readOnly) cfgPuid.value = currentSystemData.user.puid || 1000;
      if (cfgPgid && !cfgPgid.readOnly) cfgPgid.value = currentSystemData.user.pgid || 1000;
      showToast("Host User Detected", `${currentSystemData.user.username} (PUID=${currentSystemData.user.puid}, PGID=${currentSystemData.user.pgid})`, "info");
    }
  });
}
