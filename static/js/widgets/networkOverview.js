/**
 * Widget: Network Health, Tailscale & Port Map (Phase 3E)
 * Renders per-NIC link speed/duplex warnings, Tailscale mesh & subnet routing status,
 * unified service port map with conflict flags, and jumps cleanly to Netplan static IP.
 */

import { $, copyTextToClipboard } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";
import { openConfigCenterTab } from "./configCenter.js";
import { openHowToGuide } from "./helpDrawer.js";

function renderInterfaces(interfaces, currentIp, gateway, dnsServers) {
  const tbody = $("net-interfaces-tbody");
  const warnBox = $("net-link-warning-callout");
  if (!tbody) return;

  const list = Array.isArray(interfaces) ? interfaces : [];
  const warnings = list.filter((n) => n.degraded && n.warning).map((n) => `${n.name}: ${n.warning}`);
  if (warnBox) {
    if (warnings.length) {
      warnBox.textContent = warnings.join(" | ");
      warnBox.hidden = false;
    } else {
      warnBox.hidden = true;
    }
  }

  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No physical interfaces detected.</td></tr>';
    return;
  }

  tbody.innerHTML = list.map((nic) => {
    const speedStr = typeof nic.speed_mbps === "number" ? `${nic.speed_mbps} Mbps` : "Unknown speed";
    const duplexStr = nic.duplex ? `${nic.duplex} duplex` : "duplex unknown";
    let statusBadge = '<span class="badge badge-neutral">Down</span>';
    if (nic.is_up) {
      statusBadge = nic.degraded
        ? '<span class="badge badge-warn">Degraded</span>'
        : '<span class="badge badge-ok">Healthy</span>';
    }
    const routeNote = `${escapeHtml(currentIp || "--")} | gw ${escapeHtml(gateway || "--")}`;
    const macNote = nic.mac ? `MAC ${escapeHtml(nic.mac)}` : "MAC unavailable";
    return `
      <tr class="service-row">
        <td><strong>${escapeHtml(nic.name)}</strong><div class="text-muted font-mono">${macNote}</div></td>
        <td class="font-mono">${nic.is_up ? "Up" : "Down"} | ${escapeHtml(speedStr)} (${escapeHtml(duplexStr)})</td>
        <td class="font-mono">${routeNote}<div class="text-muted">DNS: ${escapeHtml((dnsServers || []).join(", ") || "--")}</div></td>
        <td class="ledger-cell-actions">${statusBadge}</td>
      </tr>
    `;
  }).join("");
}

function renderTailscale(ts, tsHttps) {
  const box = $("net-tailscale-body");
  if (!box) return;
  if (!ts || !ts.installed) {
    box.innerHTML = '<div class="empty-state">Tailscale CLI not installed on this host.</div>';
    return;
  }
  const httpsInfo = tsHttps && typeof tsHttps === "object" ? tsHttps : {};
  const badgeCls = ts.connected ? "badge-ok" : "badge-warn";
  const stateTxt = ts.connected ? "Connected" : (ts.backend_state || "Disconnected");
  const routesTxt = ts.subnet_router
    ? `On (${(ts.advertised_routes || []).join(", ")})`
    : "Off";
  const fwdTxt = ts.ip_forwarding === true ? "Enabled" : (ts.ip_forwarding === false ? "Disabled" : "Unknown");
  const errNote = ts.error ? `<div class="inline-callout is-warning">${escapeHtml(ts.error)}</div>` : "";
  const httpsBadgeCls = httpsInfo.serve_active ? "badge-ok" : "badge-neutral";
  const httpsStateTxt = httpsInfo.serve_active ? "HTTPS Active" : "Serve Off";
  const serveCmd = httpsInfo.serve_cmd || "sudo tailscale serve --bg 7575";
  const httpsLinkHtml = httpsInfo.https_url
    ? `<a href="${escapeHtml(httpsInfo.https_url)}" target="_blank" rel="noopener" class="btn-secondary net-https-link font-mono">${escapeHtml(httpsInfo.https_url)}</a>`
    : '<span class="text-muted">Requires MagicDNS</span>';

  box.innerHTML = `
    <div class="kv-row"><span>Status:</span><span class="badge ${badgeCls}">${escapeHtml(stateTxt)}</span></div>
    <div class="kv-row"><span>Tailnet IP:</span><strong class="font-mono">${escapeHtml(ts.tailnet_ip || "--")}</strong></div>
    <div class="kv-row"><span>MagicDNS Name:</span><strong class="font-mono">${escapeHtml(ts.dns_name || "--")}</strong></div>
    <div class="kv-row"><span>Subnet Router:</span><strong class="font-mono">${escapeHtml(routesTxt)}</strong></div>
    <div class="kv-row"><span>IPv4 Forwarding:</span><strong class="font-mono">${escapeHtml(fwdTxt)}</strong></div>
    <div class="kv-row"><span>Online Peers:</span><strong class="font-mono">${escapeHtml(String(ts.peer_count ?? 0))}</strong></div>
    <div class="net-https-box" id="net-tailscale-https-box">
      <div class="kv-row">
        <span>Away from Home (HTTPS):</span>
        <span class="badge ${httpsBadgeCls}">${escapeHtml(httpsStateTxt)}</span>
      </div>
      <div class="net-https-url-row">
        <span class="text-muted">Remote URL:</span>
        ${httpsLinkHtml}
      </div>
      <div class="net-https-cmd-row">
        <code class="font-mono">${escapeHtml(serveCmd)}</code>
        <button type="button" class="btn-secondary btn-copy-ts-serve" data-cmd="${escapeHtml(serveCmd)}">Copy</button>
        <button type="button" class="btn-ghost" id="btn-ts-https-guide">Setup Guide</button>
      </div>
    </div>
    ${errNote}
  `;

  const copyBtn = box.querySelector(".btn-copy-ts-serve");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const ok = await copyTextToClipboard(copyBtn.getAttribute("data-cmd") || serveCmd);
      showToast(
        ok ? "Command Copied" : "Copy Blocked",
        ok ? "Run this over SSH to enable Tailscale HTTPS." : "Clipboard blocked on this origin.",
        ok ? "success" : "warning"
      );
    });
  }
  const guideBtn = box.querySelector("#btn-ts-https-guide");
  if (guideBtn) {
    guideBtn.addEventListener("click", () => openHowToGuide("tailscale_https", guideBtn));
  }
}

function renderPortMap(ports, conflicts) {
  const tbody = $("net-ports-tbody");
  const conflictBox = $("net-port-conflict-callout");
  if (!tbody) return;

  const cList = Array.isArray(conflicts) ? conflicts : [];
  if (conflictBox) {
    if (cList.length) {
      conflictBox.textContent = cList.map((c) => c.reason || `Conflict on :${c.port}`).join(" | ");
      conflictBox.hidden = false;
    } else {
      conflictBox.hidden = true;
    }
  }

  const rows = Array.isArray(ports) ? ports : [];
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-state">Port catalog empty.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row) => {
    let badge = '<span class="badge badge-neutral">Free</span>';
    if (row.conflict) {
      badge = `<span class="badge badge-danger">Conflict</span>`;
    } else if (row.in_use) {
      badge = `<span class="badge badge-ok">${escapeHtml(row.state_label || "In Use")}</span>`;
    }
    return `
      <tr class="service-row">
        <td><strong>${escapeHtml(row.name)}</strong></td>
        <td class="font-mono">:${escapeHtml(row.port)}</td>
        <td>${escapeHtml(row.category || "")}</td>
        <td class="ledger-cell-actions">${badge}</td>
      </tr>
    `;
  }).join("");
}

export async function fetchNetworkOverview() {
  try {
    const res = await fetch(ENDPOINTS.networkOverview);
    if (!res.ok) return false;
    const data = await res.json();
    const interfaces = data.interfaces || [];
    renderInterfaces(interfaces, data.current_ip, data.default_gateway, data.dns_servers);
    renderTailscale(data.tailscale || {}, data.tailscale_https || {});
    renderPortMap(data.ports || [], data.port_conflicts || []);

    const degraded = interfaces.filter((n) => n.degraded).length;
    const tsConnected = Boolean(data.tailscale && data.tailscale.connected);
    const conflictCount = (data.port_conflicts || []).length;
    const summaryEl = $("net-health-summary");
    if (summaryEl) {
      const parts = [
        `${interfaces.length} NIC`,
        degraded ? `${degraded} degraded warning` : "link healthy",
        `Tailscale: ${tsConnected ? "connected" : "offline"}`,
        conflictCount ? `${conflictCount} port conflict` : "no port conflicts",
      ];
      summaryEl.textContent = parts.join(" | ");
    }
    return true;
  } catch (err) {
    console.error("Failed to fetch network overview:", err);
    return false;
  }
}

export function setupNetworkOverview() {
  const btnStatic = $("btn-open-netplan-modal");
  if (btnStatic) {
    btnStatic.addEventListener("click", () => openConfigCenterTab("network"));
  }
}
