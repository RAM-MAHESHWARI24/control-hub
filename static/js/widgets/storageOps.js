/**
 * Widget: Real-Time Disk I/O & Active Sessions
 * Dynamically renders discovered block devices (avoiding double-counting on
 * single-disk servers), SMB shares, and honest Jellyfin session telemetry.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { escapeHtml } from "../shared/formatters.js";
import { state } from "../state.js";
import { renderOverview } from "./overview.js";

const storageTotalMbps = $("storage-total-mbps");
const storageOpsList = $("storage-ops-list");

let lastStorageKey = "";

export function renderStorageOps(sto = {}) {
  const totalIoMbs = typeof sto.collective_mbs === "number" ? sto.collective_mbs : 0.0;
  const smb = Array.isArray(sto.smb_clients) ? sto.smb_clients : [];
  const streams = Array.isArray(sto.jellyfin_streams) ? sto.jellyfin_streams : [];

  state.storageTotalIoMbs = totalIoMbs;
  state.activeSmbClients = smb.length;
  state.activeJellyfinStreams = streams.length;

  if (storageTotalMbps) storageTotalMbps.textContent = totalIoMbs.toFixed(2);
  setCardSummary(
    "storage-ops-panel",
    `${totalIoMbs.toFixed(2)} MB/s · ${streams.length} Jellyfin · ${smb.length} SMB`
  );

  if (!storageOpsList) return;

  let disks = Array.isArray(sto.disks) && sto.disks.length > 0 ? sto.disks : [];
  if (disks.length === 0) {
    if (sto.single_disk) {
      const ssd = sto.ssd || { read_mbs: 0, write_mbs: 0, name: "System & Media Disk", device: null };
      disks = [{ role: "SYSTEM", ...ssd }];
    } else {
      if (sto.hdd) disks.push({ role: "DATA", ...sto.hdd });
      if (sto.ssd) disks.push({ role: "ROOT", ...sto.ssd });
    }
  }

  const key = JSON.stringify([disks, smb, streams]);
  if (key === lastStorageKey && storageOpsList.children.length > 0) return;
  lastStorageKey = key;

  const disksHtml = disks.map((d) => {
    const r = typeof d.read_mbs === "number" ? d.read_mbs : 0.0;
    const w = typeof d.write_mbs === "number" ? d.write_mbs : 0.0;
    const tot = (r + w).toFixed(2);
    const role = escapeHtml(d.role || "DISK");
    const isRoot = role === "ROOT" || role === "SYSTEM";
    const devSub = d.device ? `Block device: ${escapeHtml(d.device)}` : "Block I/O unavailable on this host";
    return `
      <div class="storage-metric-row">
        <div class="storage-disk-info">
          <div class="disk-badge-icon ${isRoot ? "ssd" : ""}">${role}</div>
          <div>
            <div class="disk-label-name">
              ${escapeHtml(d.name || "Storage Disk")}
              <span class="disk-leds" aria-hidden="true">
                <span class="hw-led led-r ${r > 0.05 ? "active" : ""}" title="Read: ${r.toFixed(2)} MB/s"></span>
                <span class="hw-led led-w ${w > 0.05 ? "active" : ""}" title="Write: ${w.toFixed(2)} MB/s"></span>
              </span>
            </div>
            <div class="disk-label-sub font-mono">${devSub}</div>
          </div>
        </div>
        <div class="storage-rates-group">
          <div class="storage-rate-val">${tot} MB/s</div>
          <div class="storage-rate-split font-mono">R: ${r.toFixed(2)} &middot; W: ${w.toFixed(2)} MB/s</div>
        </div>
      </div>
    `;
  }).join("");

  let clientsHtml = "";
  if (smb.length > 0 || streams.length > 0) {
    clientsHtml = `<div class="storage-section-title">Active Connections &amp; Media Sessions</div>`;
    smb.forEach((client) => {
      clientsHtml += `
        <div class="client-item-row">
          <div class="client-meta">
            <span class="client-type-tag">SMB</span>
            <span class="font-mono">${escapeHtml(client.ip)} &middot; Share: ${escapeHtml(client.share)}</span>
          </div>
          <span class="client-status-txt"><span class="client-dot" aria-hidden="true"></span> Mounted</span>
        </div>
      `;
    });
    streams.forEach((stream) => {
      const statusText = stream.verified ? (stream.status || "Playing") : "Connected";
      const labelDetail = stream.verified && stream.title
        ? `${stream.user || stream.client_ip} · ${stream.title}${stream.play_method ? ` (${stream.play_method})` : ""}`
        : `${stream.client_ip}${stream.user ? ` (${stream.user})` : ""} · ${stream.type}`;
      clientsHtml += `
        <div class="client-item-row">
          <div class="client-meta">
            <span class="client-type-tag jellyfin">JELLYFIN</span>
            <span>${escapeHtml(labelDetail)}</span>
          </div>
          <span class="client-status-txt"><span class="client-dot" aria-hidden="true"></span> ${escapeHtml(statusText)}</span>
        </div>
      `;
    });
  } else {
    clientsHtml = `
      <div class="storage-section-title">Active Connections</div>
      <div class="client-item-row">
        <div class="client-meta">
          <span class="client-type-tag">IDLE</span>
          <span class="text-muted">No active SMB share sessions or Jellyfin connections</span>
        </div>
        <span class="client-status-txt text-muted">Ready</span>
      </div>
    `;
  }

  storageOpsList.innerHTML = `
    <div class="storage-section-title">
      <span>Block Device Throughput</span>
      <span class="text-muted">Green = Read &middot; Amber = Write</span>
    </div>
    ${disksHtml}
    ${clientsHtml}
  `;

  renderOverview();
}
