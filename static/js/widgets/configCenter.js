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
let netplanRemainingSec = 0;

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
      populateFormFields(data.config, data.system, Boolean(data.read_only), data.apply_hint);
      renderNetplanPending(data.netplan_pending);
    }
    return true;
  } catch (err) {
    console.error("Failed to fetch current config:", err);
    return false;
  }
}

function populateFormFields(cfg, sys, readOnly, applyHint) {
  if (!cfg) return;

  const readonlyBanner = $("config-readonly-banner");
  const readonlyHint = $("config-readonly-hint");
  const btnSave = $("btn-save-config");

  if (readonlyBanner) readonlyBanner.hidden = !readOnly;
  if (readonlyHint && applyHint) readonlyHint.textContent = applyHint;
  if (btnSave) {
    btnSave.disabled = readOnly;
    btnSave.title = readOnly ? "Managed by setup.sh on blueprint installs" : "";
  }

  const editableFields = [
    ["cfg-hdd-data", cfg.hdd_data || "/mnt/hdd/data"],
    ["cfg-hdd-memories", cfg.hdd_memories || "/mnt/hdd/Memories"],
    ["cfg-puid", cfg.puid || "1000"],
    ["cfg-pgid", cfg.pgid || "1000"],
    ["cfg-timezone", cfg.timezone || state.timezone || "UTC"],
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

  state.netplanPending = pendingInfo && pendingInfo.pending ? pendingInfo : null;

  if (netplanCountdownTimer) {
    clearInterval(netplanCountdownTimer);
    netplanCountdownTimer = null;
  }

  if (!state.netplanPending) {
    if (banner) banner.hidden = true;
    if (modalBox) modalBox.hidden = true;
    return;
  }

  netplanRemainingSec = Number(state.netplanPending.remaining_sec || 0);
  const ipStr = state.netplanPending.ip || HOSTNAME;
  if (bannerIp) bannerIp.textContent = ipStr;
  if (modalIp) modalIp.textContent = ipStr;
  if (banner) banner.hidden = false;
  if (modalBox) modalBox.hidden = false;

  const updateTick = () => {
    const sec = Math.max(0, netplanRemainingSec);
    if (bannerCountdown) bannerCountdown.textContent = `${sec}s`;
    if (modalText) {
      modalText.textContent = sec > 0
        ? `Reverts automatically in ${sec}s unless confirmed from this address.`
        : "Revert window elapsed; previous network configuration is being restored.";
    }
    if (netplanRemainingSec <= 0 && netplanCountdownTimer) {
      clearInterval(netplanCountdownTimer);
      netplanCountdownTimer = null;
      setTimeout(fetchNetplanStatus, 3000);
    }
    netplanRemainingSec -= 1;
  };
  updateTick();
  netplanCountdownTimer = setInterval(updateTick, 1000);
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
      preview.textContent = data.yaml || "No YAML generated";
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

export async function saveConfiguration() {
  const btnSave = $("btn-save-config");
  const spinner = $("config-save-spinner");
  const modal = $("config-center-modal");

  if (btnSave) btnSave.disabled = true;
  if (spinner) spinner.style.display = "inline-block";

  const payload = {
    hdd_data: ($("cfg-hdd-data")?.value || "/mnt/hdd/data").trim(),
    hdd_memories: ($("cfg-hdd-memories")?.value || "/mnt/hdd/Memories").trim(),
    puid: parseInt($("cfg-puid")?.value || "1000", 10) || 1000,
    pgid: parseInt($("cfg-pgid")?.value || "1000", 10) || 1000,
    timezone: ($("cfg-timezone")?.value || state.timezone || "UTC").trim(),
    qbittorrent_pass: ($("cfg-qbit-pass")?.value || "").trim(),
    radarr_api_key: ($("cfg-radarr-key")?.value || "").trim(),
    sonarr_api_key: ($("cfg-sonarr-key")?.value || "").trim(),
    prowlarr_api_key: ($("cfg-prowlarr-key")?.value || "").trim(),
  };

  try {
    const res = await fetch(ENDPOINTS.configUpdate, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (res.ok && data.status === "success") {
      showToast("Configuration Saved", "Unified settings synchronized across env files.", "success");
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

function setupConfigTabs() {
  const tabBtns = document.querySelectorAll(".cfg-tab-btn");
  const tabPanes = document.querySelectorAll(".cfg-tab-pane");

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-config-tab");
      tabBtns.forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      tabPanes.forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      const targetPane = $(`cfg-pane-${targetTab}`);
      if (targetPane) targetPane.classList.add("active");
      if (targetTab === "ports") fetchPortsMatrix();
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
      if (configModal) openModal(configModal, btnOpenConfig);
      fetchCurrentConfig();
    });
  }

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
  wire("btn-save-config", saveConfiguration);
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
