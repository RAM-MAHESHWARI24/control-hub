/**
 * Widget: Configuration & Node Control Center (Control Hub Integration)
 * Reactive management of paths, atomic hardlink tests, port matrix, credentials,
 * safe Netplan static IP, and AI Copilot diagnostics exporter.
 */

import { $ } from "../shared/dom.js";
import { ENDPOINTS, HOSTNAME } from "../config.js";
import { showToast } from "../shared/toast.js";

let currentConfigData = null;
let currentSystemData = null;

// ============================================================================
// 1. Fetch & Populate Current Configuration
// ============================================================================

export async function fetchCurrentConfig() {
  try {
    const res = await fetch(ENDPOINTS.configCurrent);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.status === "success") {
      currentConfigData = data.config || {};
      currentSystemData = data.system || {};
      populateFormFields(data.config, data.system);
    }
  } catch (err) {
    console.error("Failed to fetch current config:", err);
  }
}

function populateFormFields(cfg, sys) {
  if (!cfg) return;

  const cfgHddData = $("cfg-hdd-data");
  const cfgHddMemories = $("cfg-hdd-memories");
  const cfgPuid = $("cfg-puid");
  const cfgPgid = $("cfg-pgid");
  const cfgTimezone = $("cfg-timezone");
  const cfgQbitPass = $("cfg-qbit-pass");
  const cfgRadarrKey = $("cfg-radarr-key");
  const cfgSonarrKey = $("cfg-sonarr-key");
  const cfgProwlarrKey = $("cfg-prowlarr-key");

  if (cfgHddData) cfgHddData.value = cfg.hdd_data || "/mnt/hdd/data";
  if (cfgHddMemories) cfgHddMemories.value = cfg.hdd_memories || "/mnt/hdd/Memories";

  if (cfgPuid) cfgPuid.value = cfg.puid || "1000";
  if (cfgPgid) cfgPgid.value = cfg.pgid || "1000";
  if (cfgTimezone) cfgTimezone.value = cfg.timezone || "Asia/Kolkata";

  if (cfgQbitPass) cfgQbitPass.value = cfg.qbittorrent_pass || "adminadmin";
  if (cfgRadarrKey) cfgRadarrKey.value = cfg.radarr_api_key || "";
  if (cfgSonarrKey) cfgSonarrKey.value = cfg.sonarr_api_key || "";
  if (cfgProwlarrKey) cfgProwlarrKey.value = cfg.prowlarr_api_key || "";

  if (sys && sys.network) {
    const cfgNetIface = $("cfg-netplan-iface");
    const cfgNetIp = $("cfg-netplan-ip");
    const cfgNetGw = $("cfg-netplan-gw");
    const cfgNetDns = $("cfg-netplan-dns");

    if (cfgNetIface) cfgNetIface.value = sys.network.active_nic || "eth0";
    if (cfgNetIp) cfgNetIp.value = sys.network.current_ip || "192.168.1.100";
    if (cfgNetGw) cfgNetGw.value = sys.network.default_gateway || "192.168.1.1";
    if (cfgNetDns) cfgNetDns.value = (sys.network.dns_servers || ["1.1.1.1", "8.8.8.8"]).join(", ");
  }
}

// ============================================================================
// 2. Storage & Atomic Hardlink Verification
// ============================================================================

export async function runHardlinkTest() {
  const cfgHddData = $("cfg-hdd-data");
  const btnTestHardlink = $("btn-test-hardlink");
  const hlSpinner = $("hl-spinner");
  const hlResultBanner = $("hl-result-banner");
  const hlResultText = $("hl-result-text");

  const targetPath = cfgHddData ? cfgHddData.value.trim() : "/mnt/hdd/data";
  if (!targetPath) {
    showToast("Error", "Please specify a storage path to test.", "⚠️");
    return;
  }

  if (btnTestHardlink) btnTestHardlink.disabled = true;
  if (hlSpinner) hlSpinner.style.display = "inline-block";
  if (hlResultBanner) {
    hlResultBanner.style.display = "block";
    hlResultBanner.className = "hl-banner hl-testing";
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
        hlResultText.innerHTML = `
          <strong>🟢 Atomic Hardlinks Verified! (${result.latency_ms} ms)</strong><br>
          <span class="hl-subtext">Single-mount ext4/xfs compliance confirmed. Inode: ${result.inode}. Zero-copy instant moves enabled between torrent downloads and Jellyfin media!</span>
        `;
      }
      showToast("Hardlinks Verified", `Zero-copy instant moves supported (${result.latency_ms}ms).`, "🟢");
    } else {
      if (hlResultBanner) hlResultBanner.className = "hl-banner hl-error";
      if (hlResultText) {
        hlResultText.innerHTML = `
          <strong>🔴 Hardlinks Failed (EXDEV or Unsupported)</strong><br>
          <span class="hl-subtext">Error: ${result.error || "Cross-device link or unsupported filesystem."}<br>
          <em>Rule: Torrents and Media must live inside the same filesystem mount to prevent slow duplicate copies.</em></span>
        `;
      }
      showToast("Hardlink Warning", "Cross-device link detected. Files will be slowly duplicated.", "🔴");
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
// 3. Port Matrix & Live Availability Prober
// ============================================================================

export async function fetchPortsMatrix() {
  const btnRefreshPorts = $("btn-refresh-ports");
  const portsGrid = $("ports-matrix-grid");

  if (btnRefreshPorts) btnRefreshPorts.disabled = true;
  if (portsGrid) portsGrid.innerHTML = '<div class="port-loading">Probing host ports (IPv4)...</div>';

  try {
    const res = await fetch(ENDPOINTS.configPorts);
    const data = await res.json();
    const ports = data.ports || {};

    if (portsGrid) {
      portsGrid.innerHTML = "";
      Object.keys(ports).forEach((key) => {
        const item = ports[key];
        const isFree = item.available;
        const portCard = document.createElement("div");
        portCard.className = `port-matrix-card ${isFree ? "port-free" : "port-bound"}`;

        const isWebUi = [7575, 8096, 5055, 8080, 8989, 7878, 9696, 6767, 2283, 8000, 8888].includes(item.port);
        const webUrl = isWebUi ? `http://${HOSTNAME}:${item.port}` : null;

        portCard.innerHTML = `
          <div class="port-card-header">
            <span class="port-badge-num">:${item.port}</span>
            <span class="port-badge-status ${isFree ? "badge-free" : "badge-bound"}">
              ${isFree ? "Available" : "Active / Bound"}
            </span>
          </div>
          <div class="port-service-name">${item.name}</div>
          <div class="port-category-tag">${item.category}</div>
          ${!isFree && webUrl
            ? `<a href="${webUrl}" target="_blank" class="port-link-btn" title="Open ${item.name} Web UI in new tab">Open Web UI &nearr;</a>`
            : `<span class="port-desc-text">${isFree ? "Ready for container bind" : "System process listening"}</span>`
          }
        `;
        portsGrid.appendChild(portCard);
      });
    }
  } catch (err) {
    if (portsGrid) portsGrid.innerHTML = `<div class="port-error">Failed to probe ports: ${err.message}</div>`;
  } finally {
    if (btnRefreshPorts) btnRefreshPorts.disabled = false;
  }
}

// ============================================================================
// 4. Credential & Secrets Generator
// ============================================================================

export async function generateFreshSecrets() {
  const btnGenerateSecrets = $("btn-generate-secrets");
  const cfgQbitPass = $("cfg-qbit-pass");
  const cfgRadarrKey = $("cfg-radarr-key");
  const cfgSonarrKey = $("cfg-sonarr-key");
  const cfgProwlarrKey = $("cfg-prowlarr-key");

  if (btnGenerateSecrets) btnGenerateSecrets.disabled = true;

  try {
    const res = await fetch(ENDPOINTS.configGenerateSecrets, { method: "POST" });
    const data = await res.json();
    const secrets = data.secrets || {};

    if (cfgQbitPass && secrets.qbittorrent_pass) cfgQbitPass.value = secrets.qbittorrent_pass;
    if (cfgRadarrKey && secrets.radarr_api_key) cfgRadarrKey.value = secrets.radarr_api_key;
    if (cfgSonarrKey && secrets.sonarr_api_key) cfgSonarrKey.value = secrets.sonarr_api_key;
    if (cfgProwlarrKey && secrets.prowlarr_api_key) cfgProwlarrKey.value = secrets.prowlarr_api_key;

    showToast("Fresh Secrets Generated", "High-entropy alphanumeric passwords and API keys populated.", "🎲");
  } catch (err) {
    showToast("Error", `Could not generate secrets: ${err.message}`, "⚠️");
  } finally {
    if (btnGenerateSecrets) btnGenerateSecrets.disabled = false;
  }
}

// ============================================================================
// 5. Safe Netplan Static IP Preview & Apply
// ============================================================================

export async function previewNetplan() {
  const cfgNetIface = $("cfg-netplan-iface");
  const cfgNetIp = $("cfg-netplan-ip");
  const cfgNetGw = $("cfg-netplan-gw");
  const cfgNetDns = $("cfg-netplan-dns");
  const btnPreviewNetplan = $("btn-preview-netplan");
  const netplanYamlPreview = $("netplan-yaml-preview");

  const iface = cfgNetIface ? cfgNetIface.value.trim() : "eth0";
  const ip = cfgNetIp ? cfgNetIp.value.trim() : "192.168.1.100";
  const gw = cfgNetGw ? cfgNetGw.value.trim() : "192.168.1.1";
  const dnsRaw = cfgNetDns ? cfgNetDns.value : "1.1.1.1, 8.8.8.8";
  const dns = dnsRaw.split(",").map((s) => s.trim()).filter(Boolean);

  if (btnPreviewNetplan) btnPreviewNetplan.disabled = true;

  try {
    const res = await fetch(ENDPOINTS.configNetplanPreview, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interface: iface, ip: ip, gateway: gw, dns: dns }),
    });

    const data = await res.json();
    if (netplanYamlPreview) {
      netplanYamlPreview.textContent = data.yaml || "No YAML generated";
      netplanYamlPreview.style.display = "block";
    }
    showToast("Netplan YAML Ready", `Valid Netplan v2 configuration generated for ${iface}.`, "🌐");
  } catch (err) {
    showToast("Error", `Netplan preview failed: ${err.message}`, "⚠️");
  } finally {
    if (btnPreviewNetplan) btnPreviewNetplan.disabled = false;
  }
}

export async function applyNetplanSafe() {
  const cfgNetIface = $("cfg-netplan-iface");
  const cfgNetIp = $("cfg-netplan-ip");
  const cfgNetGw = $("cfg-netplan-gw");
  const cfgNetDns = $("cfg-netplan-dns");
  const btnApplyNetplan = $("btn-apply-netplan");

  const iface = cfgNetIface ? cfgNetIface.value.trim() : "eth0";
  const ip = cfgNetIp ? cfgNetIp.value.trim() : "192.168.1.100";
  const gw = cfgNetGw ? cfgNetGw.value.trim() : "192.168.1.1";
  const dnsRaw = cfgNetDns ? cfgNetDns.value : "1.1.1.1, 8.8.8.8";
  const dns = dnsRaw.split(",").map((s) => s.trim()).filter(Boolean);

  const confirmMsg = `WARNING: Are you sure you want to apply static IP ${ip} to interface ${iface}?\n\nSafety Guarantee: Netplan will automatically revert back if connection drops (45s rollback protection).`;
  if (!confirm(confirmMsg)) return;

  if (btnApplyNetplan) btnApplyNetplan.disabled = true;

  try {
    const res = await fetch(ENDPOINTS.configNetplanApply, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interface: iface, ip: ip, gateway: gw, dns: dns, timeout: 45 }),
    });

    const data = await res.json();
    const result = data.result || {};

    if (result.success) {
      showToast("Netplan Applied", result.message || `Static IP ${ip} configured with rollback protection!`, "🟢");
    } else {
      showToast("Netplan Reverted", result.message || "Configuration was rejected and automatically rolled back.", "⚠️");
    }
  } catch (err) {
    showToast("Error", `Netplan application error: ${err.message}`, "🔴");
  } finally {
    if (btnApplyNetplan) btnApplyNetplan.disabled = false;
  }
}

// ============================================================================
// 6. Save Configuration & Propagate Across Blueprints
// ============================================================================

export async function saveConfiguration() {
  const btnSaveConfig = $("btn-save-config");
  const configSaveSpinner = $("config-save-spinner");
  const cfgHddData = $("cfg-hdd-data");
  const cfgHddMemories = $("cfg-hdd-memories");
  const cfgPuid = $("cfg-puid");
  const cfgPgid = $("cfg-pgid");
  const cfgTimezone = $("cfg-timezone");
  const cfgQbitPass = $("cfg-qbit-pass");
  const cfgRadarrKey = $("cfg-radarr-key");
  const cfgSonarrKey = $("cfg-sonarr-key");
  const cfgProwlarrKey = $("cfg-prowlarr-key");
  const configModal = $("config-center-modal");

  if (btnSaveConfig) btnSaveConfig.disabled = true;
  if (configSaveSpinner) configSaveSpinner.style.display = "inline-block";

  const payload = {
    hdd_data: cfgHddData ? cfgHddData.value.trim() : "/mnt/hdd/data",
    hdd_memories: cfgHddMemories ? cfgHddMemories.value.trim() : "/mnt/hdd/Memories",
    puid: cfgPuid ? parseInt(cfgPuid.value, 10) || 1000 : 1000,
    pgid: cfgPgid ? parseInt(cfgPgid.value, 10) || 1000 : 1000,
    timezone: cfgTimezone ? cfgTimezone.value.trim() : "Asia/Kolkata",
    qbittorrent_pass: cfgQbitPass ? cfgQbitPass.value.trim() : "adminadmin",
    radarr_api_key: cfgRadarrKey ? cfgRadarrKey.value.trim() : "",
    sonarr_api_key: cfgSonarrKey ? cfgSonarrKey.value.trim() : "",
    prowlarr_api_key: cfgProwlarrKey ? cfgProwlarrKey.value.trim() : "",
  };

  try {
    const res = await fetch(ENDPOINTS.configUpdate, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (data.status === "success") {
      showToast("Configuration Saved", "Unified settings synchronized across master .env and all blueprint apps!", "💾");
      if (configModal) configModal.style.display = "none";
    } else {
      showToast("Save Failed", data.message || "Unknown error saving configuration.", "⚠️");
    }
  } catch (err) {
    showToast("Error", `Failed to save configuration: ${err.message}`, "🔴");
  } finally {
    if (btnSaveConfig) btnSaveConfig.disabled = false;
    if (configSaveSpinner) configSaveSpinner.style.display = "none";
  }
}

// ============================================================================
// 7. AI Copilot Diagnostics Exporter
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
      aiRamPill.textContent = `${snap.ram.total_gib} GiB Total (${snap.ram.free_gib} GiB Free)`;
    }
    if (aiHwPill && snap.hwaccel) {
      aiHwPill.textContent = (snap.hwaccel.has_vaapi_dri || snap.hwaccel.render_d128_present) ? "Intel QSV / VAAPI Active" : (snap.hwaccel.has_nvidia ? "NVIDIA Acceleration Active" : "Direct Play Recommended");
    }
    if (aiHaswellPill && snap.cpu) {
      aiHaswellPill.textContent = snap.cpu.is_low_power ? "Low-Power Profile (Direct Play Enforced)" : "Standard / High-Performance Host";
    }

    if (aiPromptContent) {
      aiPromptContent.textContent = data.ai_prompt || "No prompt generated.";
    }
  } catch (err) {
    if (aiPromptContent) aiPromptContent.textContent = `Failed to generate AI context: ${err.message}`;
  }
}

export function copyAiPromptToClipboard() {
  const aiPromptContent = $("ai-prompt-content");
  const btnCopyAiPrompt = $("btn-copy-ai-prompt");

  if (!aiPromptContent) return;
  const promptText = aiPromptContent.textContent;
  if (!promptText) return;

  navigator.clipboard.writeText(promptText).then(
    () => {
      showToast("Copied to Clipboard!", "Token-optimized AI prompt (~300 tokens) ready to paste into ChatGPT, Claude, or Antigravity.", "📋");
      if (btnCopyAiPrompt) {
        const origText = btnCopyAiPrompt.innerHTML;
        btnCopyAiPrompt.innerHTML = "<span>✓ Copied!</span>";
        setTimeout(() => {
          btnCopyAiPrompt.innerHTML = origText;
        }, 2000);
      }
    },
    () => {
      showToast("Copy Error", "Failed to copy to clipboard.", "⚠️");
    }
  );
}

// ============================================================================
// 8. Tab Navigation in Config Modal
// ============================================================================

function setupConfigTabs() {
  const tabBtns = document.querySelectorAll(".cfg-tab-btn");
  const tabPanes = document.querySelectorAll(".cfg-tab-pane");

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-config-tab");

      tabBtns.forEach((b) => b.classList.remove("active"));
      tabPanes.forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      const targetPane = $(`cfg-pane-${targetTab}`);
      if (targetPane) targetPane.classList.add("active");

      // Auto-fetch data for dynamic tabs
      if (targetTab === "ports") fetchPortsMatrix();
    });
  });
}

// ============================================================================
// 9. Master Initialization & Event Listeners
// ============================================================================

export function setupConfigCenter() {
  setupConfigTabs();

  const configModal = $("config-center-modal");
  const aiModal = $("ai-copilot-modal");
  const btnOpenConfig = $("btn-open-config-center");
  const btnOpenAi = $("btn-open-ai-copilot");
  const configModalClose = $("config-modal-close");
  const configModalCancel = $("config-modal-cancel");
  const aiModalClose = $("ai-modal-close");
  const aiModalDismiss = $("ai-modal-dismiss");

  const btnTestHardlink = $("btn-test-hardlink");
  const btnRefreshPorts = $("btn-refresh-ports");
  const btnGenerateSecrets = $("btn-generate-secrets");
  const btnPreviewNetplan = $("btn-preview-netplan");
  const btnApplyNetplan = $("btn-apply-netplan");
  const btnSaveConfig = $("btn-save-config");
  const btnCopyAiPrompt = $("btn-copy-ai-prompt");
  const btnDetectUser = $("btn-detect-user");
  const btnLaunchWizard = $("btn-launch-setup-wizard");

  // Open Config Modal
  if (btnOpenConfig) {
    btnOpenConfig.onclick = (e) => {
      e.preventDefault();
      if (configModal) configModal.style.display = "flex";
      fetchCurrentConfig();
    };
  }

  // Close Config Modal
  if (configModalClose) {
    configModalClose.onclick = () => {
      if (configModal) configModal.style.display = "none";
    };
  }
  if (configModalCancel) {
    configModalCancel.onclick = () => {
      if (configModal) configModal.style.display = "none";
    };
  }

  // Open AI Copilot Modal
  if (btnOpenAi) {
    btnOpenAi.onclick = (e) => {
      e.preventDefault();
      if (aiModal) aiModal.style.display = "flex";
      fetchAiDiagnostics();
    };
  }

  // Close AI Copilot Modal
  if (aiModalClose) {
    aiModalClose.onclick = () => {
      if (aiModal) aiModal.style.display = "none";
    };
  }
  if (aiModalDismiss) {
    aiModalDismiss.onclick = () => {
      if (aiModal) aiModal.style.display = "none";
    };
  }

  // Action listeners
  if (btnTestHardlink) btnTestHardlink.onclick = runHardlinkTest;
  if (btnRefreshPorts) btnRefreshPorts.onclick = fetchPortsMatrix;
  if (btnGenerateSecrets) btnGenerateSecrets.onclick = generateFreshSecrets;
  if (btnPreviewNetplan) btnPreviewNetplan.onclick = previewNetplan;
  if (btnApplyNetplan) btnApplyNetplan.onclick = applyNetplanSafe;
  if (btnSaveConfig) btnSaveConfig.onclick = saveConfiguration;
  if (btnCopyAiPrompt) btnCopyAiPrompt.onclick = copyAiPromptToClipboard;

  if (btnDetectUser) {
    btnDetectUser.onclick = () => {
      if (currentSystemData && currentSystemData.user) {
        const cfgPuid = $("cfg-puid");
        const cfgPgid = $("cfg-pgid");
        if (cfgPuid) cfgPuid.value = currentSystemData.user.puid || 1000;
        if (cfgPgid) cfgPgid.value = currentSystemData.user.pgid || 1000;
        showToast("Host User Detected", `PUID=${currentSystemData.user.puid}, PGID=${currentSystemData.user.pgid}`, "👤");
      }
    };
  }

  if (btnLaunchWizard) {
    btnLaunchWizard.onclick = () => {
      window.open(`http://${HOSTNAME}:8000/`, "_blank");
    };
  }
}
