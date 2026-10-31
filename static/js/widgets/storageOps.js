/**
 * Widget: Server Read/Write Operations (Disk Throughput & Media Streams)
 * Renders real-time disk I/O rates (SDA / SDB), hardware LEDs,
 * active SMB client shares, and Jellyfin video playback streams.
 */

import { $ } from "../shared/dom.js";
import { escapeHtml } from "../shared/formatters.js";

const storageCollectiveSpeed = $("storage-collective-speed");
const storageTotalMbps = $("storage-total-mbps");
const storageOpsList = $("storage-ops-list");

export function renderStorageOps(sto = {}) {
  const totalIoMbs = sto.collective_mbs !== undefined ? sto.collective_mbs : 0.0;
  if (storageTotalMbps) storageTotalMbps.textContent = totalIoMbs.toFixed(2);

  if (!storageOpsList) return;

  const hdd = sto.hdd || { read_mbs: 0.0, write_mbs: 0.0, name: "Media HDD (/mnt/hdd - sda)" };
  const ssd = sto.ssd || { read_mbs: 0.0, write_mbs: 0.0, name: "OS Root SSD (/ - sdb)" };
  const smb = sto.smb_clients || [];
  const streams = sto.jellyfin_streams || [];

  const hddRead = (hdd.read_mbs !== undefined ? hdd.read_mbs : 0.0);
  const hddWrite = (hdd.write_mbs !== undefined ? hdd.write_mbs : 0.0);
  const hddTotal = (hddRead + hddWrite).toFixed(2);

  const ssdRead = (ssd.read_mbs !== undefined ? ssd.read_mbs : 0.0);
  const ssdWrite = (ssd.write_mbs !== undefined ? ssd.write_mbs : 0.0);
  const ssdTotal = (ssdRead + ssdWrite).toFixed(2);

  let clientsHtml = "";
  if (smb.length > 0 || streams.length > 0) {
    clientsHtml += `<div class="storage-section-title">Active Connections & Media Streams</div><div class="active-clients-list">`;
    smb.forEach(client => {
      clientsHtml += `
        <div class="client-item-row">
          <div class="client-meta">
            <span class="client-type-tag">SMB</span>
            <span class="client-name-txt">${escapeHtml(client.ip)} &bull; Share: [${escapeHtml(client.share)}]</span>
          </div>
          <span class="client-status-txt"><span class="client-dot"></span> Mounted</span>
        </div>
      `;
    });
    streams.forEach(stream => {
      clientsHtml += `
        <div class="client-item-row">
          <div class="client-meta">
            <span class="client-type-tag jellyfin">JELLYFIN</span>
            <span class="client-name-txt">${escapeHtml(stream.client_ip)} &bull; ${escapeHtml(stream.type)}</span>
          </div>
          <span class="client-status-txt"><span class="client-dot"></span> Streaming Active</span>
        </div>
      `;
    });
    clientsHtml += `</div>`;
  } else {
    clientsHtml = `
      <div class="storage-section-title">Active Connections</div>
      <div class="client-item-row">
        <div class="client-meta">
          <span class="client-type-tag" style="opacity: 0.6;">CLIENTS</span>
          <span class="client-name-txt" style="color: var(--text-muted);">No external SMB transfers or Jellyfin video streams active</span>
        </div>
        <span class="client-status-txt" style="color: var(--text-dim);"><span class="client-dot" style="background: var(--text-dim); box-shadow: none;"></span> Ready</span>
      </div>
    `;
  }

  storageOpsList.innerHTML = `
    <div class="storage-section-title">
      <span>Real-Time Disk Throughput</span>
      <span class="led-legend">Activity: <span class="hw-led led-r active" style="box-shadow:none;"></span> Read <span class="hw-led led-w active" style="box-shadow:none;"></span> Write</span>
    </div>
    <div class="storage-metric-row">
      <div class="storage-disk-info">
        <div class="disk-badge-icon">DATA</div>
        <div>
          <div class="disk-label-name">
            ${escapeHtml(hdd.name || 'Media Storage (/mnt/hdd)')}
            <span class="disk-leds">
              <span class="hw-led led-r ${hddRead > 0.05 ? 'active' : ''}" title="${escapeHtml(hdd.device || 'Storage')} Read: ${hddRead.toFixed(2)} MB/s"></span>
              <span class="hw-led led-w ${hddWrite > 0.05 ? 'active' : ''}" title="${escapeHtml(hdd.device || 'Storage')} Write: ${hddWrite.toFixed(2)} MB/s"></span>
            </span>
          </div>
          <div class="disk-label-sub">Block Device: ${escapeHtml(hdd.device || 'sda')} &bull; Active Storage</div>
        </div>
      </div>
      <div class="storage-rates-group">
        <div class="storage-rate-val">${hddTotal} MB/s</div>
        <div class="storage-rate-split">R: ${hddRead.toFixed(2)} MB/s &bull; W: ${hddWrite.toFixed(2)} MB/s</div>
      </div>
    </div>

    <div class="storage-metric-row">
      <div class="storage-disk-info">
        <div class="disk-badge-icon ssd">ROOT</div>
        <div>
          <div class="disk-label-name">
            ${escapeHtml(ssd.name || 'OS & System Engine (/)')}
            <span class="disk-leds">
              <span class="hw-led led-r ${ssdRead > 0.05 ? 'active' : ''}" title="${escapeHtml(ssd.device || 'Root')} Read: ${ssdRead.toFixed(2)} MB/s"></span>
              <span class="hw-led led-w ${ssdWrite > 0.05 ? 'active' : ''}" title="${escapeHtml(ssd.device || 'Root')} Write: ${ssdWrite.toFixed(2)} MB/s"></span>
            </span>
          </div>
          <div class="disk-label-sub">Block Device: ${escapeHtml(ssd.device || 'sdb')} &bull; OS Root</div>
        </div>
      </div>
      <div class="storage-rates-group">
        <div class="storage-rate-val">${ssdTotal} MB/s</div>
        <div class="storage-rate-split">R: ${ssdRead.toFixed(2)} MB/s &bull; W: ${ssdWrite.toFixed(2)} MB/s</div>
      </div>
    </div>

    ${clientsHtml}
  `;
}
