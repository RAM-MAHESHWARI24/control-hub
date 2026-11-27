/**
 * Widget: Home Assistant & NUT UPS Integrations (Phase 4E)
 * Renders live HA REST sensor values, copyable YAML config, and honest NUT UPS telemetry.
 */

import { $, copyTextToClipboard } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";

function renderUps(ups) {
  const box = $("integrations-ups-body");
  if (!box) return;
  if (!ups || !ups.installed) {
    box.innerHTML = '<div class="empty-state">NUT (<code>upsc</code>) CLI not installed on this host.</div>';
    return;
  }
  if (ups.status === "unconfigured" || ups.status === "unreachable" || ups.status === "error") {
    box.innerHTML = `<div class="inline-callout is-warning">${escapeHtml(ups.error || "UPS status unavailable.")}</div>`;
    return;
  }
  const badgeCls = ups.low_battery ? "badge-danger" : (ups.on_battery ? "badge-warn" : "badge-ok");
  const stateTxt = ups.low_battery ? "Low Battery" : (ups.on_battery ? "On Battery" : "Online");
  const rtMin = ups.battery_runtime_s ? `${Math.round(ups.battery_runtime_s / 60)} min` : "--";
  const shutdownNote = ups.shutdown_action
    ? `<div class="inline-callout is-danger">${escapeHtml(ups.shutdown_action)}</div>`
    : "";

  box.innerHTML = `
    <div class="kv-row"><span>UPS (${escapeHtml(ups.ups_name || "default")}):</span><span class="badge ${badgeCls}">${escapeHtml(stateTxt)}</span></div>
    <div class="kv-row"><span>Model:</span><strong class="font-mono">${escapeHtml(ups.ups_model || "--")}</strong></div>
    <div class="kv-row"><span>Battery Charge:</span><strong class="font-mono">${ups.battery_charge ?? "--"}%</strong></div>
    <div class="kv-row"><span>Estimated Runtime:</span><strong class="font-mono">${escapeHtml(rtMin)}</strong></div>
    <div class="kv-row"><span>UPS Load:</span><strong class="font-mono">${ups.ups_load_pct ?? "--"}%</strong></div>
    ${shutdownNote}
  `;
}

function renderHomeAssistant(ha) {
  const box = $("integrations-ha-body");
  if (!box) return;
  const sensors = (ha && ha.sensors) || {};
  const yamlText = (ha && ha.yaml_snippet) || "";
  box.innerHTML = `
    <div class="kv-row"><span>Pool Usage Sensor:</span><strong class="font-mono">${sensors.disk_pool_pct ?? "--"}%</strong></div>
    <div class="kv-row"><span>Backup State:</span><strong class="font-mono">${escapeHtml(String(sensors.backup_state || "unknown"))}</strong></div>
    <div class="kv-row"><span>Sleep Skip Active:</span><strong class="font-mono">${sensors.sleep_skip_tonight ? "Yes" : "No"}</strong></div>
    <pre class="modal-log-viewer font-mono ha-yaml-pre" id="integrations-ha-yaml">${escapeHtml(yamlText)}</pre>
    <div class="troubleshoot-item-actions">
      <button type="button" class="btn-secondary" id="btn-copy-ha-yaml">Copy Home Assistant YAML</button>
    </div>
  `;

  const copyBtn = $("btn-copy-ha-yaml");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const ok = await copyTextToClipboard(yamlText);
      showToast(
        ok ? "YAML Copied" : "Copy Blocked",
        ok ? "Create a read-only token under Account -> API Tokens for Home Assistant." : "Clipboard blocked on this origin.",
        ok ? "success" : "warning"
      );
    });
  }
}

export async function fetchIntegrations() {
  try {
    const res = await fetch(ENDPOINTS.integrationsHa);
    if (!res.ok) return false;
    const data = await res.json();
    renderHomeAssistant(data);
    renderUps(data.ups || {});
    return true;
  } catch (_) {
    return false;
  }
}

export function setupIntegrations() {
  const btn = $("btn-integrations-refresh");
  if (btn) {
    btn.addEventListener("click", () => fetchIntegrations());
  }
}
