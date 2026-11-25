/**
 * Widget: Overview Workspace Renderer
 * Keeps Quick-Launch App Grid, 4-Card Vitals KPI Row, and Adaptive Live Activity Strip
 * synchronized with central reactive state without redundant API calls.
 */

import { $, uiIcon } from "../shared/dom.js";
import { HOSTNAME } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { state } from "../state.js";

const BRAND_ICON_MAP = {
  jellyfin: "/img/icons/jellyfin.svg",
  seerr: "/img/icons/seerr.svg",
  immich_server: "/img/icons/immich.svg",
  sonarr: "/img/icons/sonarr.svg",
  radarr: "/img/icons/radarr.svg",
  prowlarr: "/img/icons/prowlarr.svg",
  bazarr: "/img/icons/bazarr.svg",
  qbittorrent: "/img/icons/qbittorrent.svg",
  dozzle: "/img/icons/dozzle.svg",
  byparr: "/img/icons/byparr.svg",
  cockpit: "/img/icons/cockpit.svg",
};

let lastAppsKey = "";
let lastActivityKey = "";
let lastAuditKey = "";

export function renderOverviewApps() {
  const grid = $("overview-apps-grid");
  const subtitle = $("overview-apps-subtitle");
  if (!grid) return;

  const allServices = state.servicesList || [];
  const launchable = allServices.filter((s) => s.has_web_ui !== false && s.port);
  const upCount = launchable.filter((s) => s.is_up).length;

  if (subtitle) {
    if (!state.servicesLoadedOnce) {
      subtitle.textContent = "Discovering installed apps...";
    } else if (launchable.length === 0) {
      subtitle.textContent = "No web services detected";
    } else {
      subtitle.textContent = `${upCount}/${launchable.length} web apps online · ${allServices.length} total containers`;
    }
  }

  const key = JSON.stringify(launchable.map((s) => [s.id, s.port, s.is_up, s.health, s.state]));
  if (key === lastAppsKey && grid.children.length > 0) return;
  lastAppsKey = key;

  if (launchable.length === 0) {
    grid.innerHTML = `<div class="empty-state">No installed web apps detected yet. Check the Apps tab for Docker status.</div>`;
    return;
  }

  grid.innerHTML = launchable.map((svc) => {
    const protocol = svc.port === 9090 ? "https:" : "http:";
    const targetUrl = `${protocol}//${HOSTNAME}:${svc.port}`;
    const dotClass = svc.is_up ? "is-ok" : (svc.health === "starting" ? "is-warn" : "is-bad");
    const iconSrc = BRAND_ICON_MAP[svc.id];
    const iconHtml = iconSrc
      ? `<img src="${iconSrc}" alt="" class="brand-logo-img" loading="lazy" />`
      : uiIcon("box");
    const safeName = escapeHtml(svc.name);
    const subText = svc.is_up ? `:${svc.port}` : (svc.health === "unhealthy" ? `Unhealthy · :${svc.port}` : `${svc.state || "Stopped"} · :${svc.port}`);

    return `
      <a href="${targetUrl}" target="_blank" rel="noopener" class="quick-app-tile ${svc.is_up ? "" : "is-down"}" aria-label="Open ${safeName} on port ${svc.port}">
        <span class="quick-app-icon" aria-hidden="true">${iconHtml}</span>
        <span class="quick-app-meta">
          <span class="quick-app-name-row">
            <span class="status-dot ${dotClass}" aria-hidden="true"></span>
            <span class="quick-app-name">${safeName}</span>
          </span>
          <span class="quick-app-sub font-mono">${escapeHtml(subText)}</span>
        </span>
      </a>
    `;
  }).join("");
}

export function renderOverviewKpis() {
  const vitals = state.vitals;
  if (vitals) {
    const cpu = vitals.cpu || {};
    const mem = vitals.memory || {};
    const storage = vitals.storage || {};
    const ssd = storage.ssd || {};
    const hdd = storage.hdd || {};

    const cpuVal = $("kpi-cpu-val");
    const ramSub = $("kpi-ram-sub");
    const cpuBar = $("kpi-cpu-bar");
    const pct = typeof cpu.usage_percent === "number" ? cpu.usage_percent : 0;
    if (cpuVal) cpuVal.textContent = cpu.temp_c !== null && cpu.temp_c !== undefined ? `${pct}% · ${cpu.temp_c}°C` : `${pct}%`;
    if (ramSub) ramSub.textContent = `RAM: ${mem.used_gib ?? 0} / ${mem.total_gib ?? 0} GiB (${mem.percent ?? 0}%)`;
    if (cpuBar) cpuBar.style.width = `${Math.min(100, pct)}%`;

    const storageVal = $("kpi-storage-val");
    const storageSub = $("kpi-storage-sub");
    const storageBar = $("kpi-storage-bar");
    if (hdd.available && !storage.single_disk) {
      if (storageVal) storageVal.textContent = `${hdd.free_gb} GB free`;
      if (storageSub) storageSub.textContent = `Pool ${hdd.percent}% used · OS Root ${ssd.percent ?? 0}%`;
      if (storageBar) {
        storageBar.style.width = `${Math.min(100, hdd.percent || 0)}%`;
        storageBar.className = `kpi-bar-fill ${hdd.is_critical ? "fill-danger" : (hdd.is_warning ? "fill-warning" : "fill-success")}`;
      }
    } else if (ssd.total_gb) {
      if (storageVal) storageVal.textContent = `${ssd.free_gb} GB free`;
      if (storageSub) storageSub.textContent = `Root ${ssd.percent ?? 0}% used of ${ssd.total_gb} GB`;
      if (storageBar) {
        storageBar.style.width = `${Math.min(100, ssd.percent || 0)}%`;
        storageBar.className = `kpi-bar-fill ${ssd.percent >= 95 ? "fill-danger" : (ssd.percent >= 85 ? "fill-warning" : "fill-success")}`;
      }
    }
  }

  // Network KPI
  const netVal = $("kpi-net-val");
  const netSub = $("kpi-net-sub");
  const isMbps = state.currentUnit === "mbps";
  const mult = isMbps ? 8.0 : 1.0;
  const unit = isMbps ? "Mbps" : "MB/s";
  if (netVal) netVal.textContent = `${(state.lastLanTotalMbs * mult).toFixed(2)} ${unit}`;
  if (netSub) {
    const sp = state.lastSpeedtest;
    if (sp && sp.available && typeof sp.download_mbps === "number") {
      netSub.textContent = `ISP: ↓ ${sp.download_mbps} / ↑ ${sp.upload_mbps} Mbps`;
    } else {
      netSub.textContent = `RX ${(state.lastLanRxMbs * mult).toFixed(2)} · TX ${(state.lastLanTxMbs * mult).toFixed(2)} ${unit}`;
    }
  }

  // Backups & Power KPI
  const bpCard = $("kpi-backup-power");
  const bpLabel = $("kpi-bp-label");
  const bpVal = $("kpi-bp-val");
  const bpSub = $("kpi-bp-sub");
  const bak = state.backupSnapshot;

  if (bpCard) {
    bpCard.setAttribute("href", state.modules.backups ? "#/backups" : "#/system");
  }
  if (state.modules.backups && bak) {
    if (bpLabel) bpLabel.textContent = "Backups & Power";
    const h = bak.health || {};
    const st = h.state || bak.status || "unknown";
    const statusMap = {
      synced: "Backup Verified",
      syncing: "Backup Running",
      error: "Backup Failed",
      stale: "Backup Stale",
      interrupted: "Backup Interrupted",
      unknown: "No Backup Yet",
    };
    if (bpVal) bpVal.textContent = statusMap[st] || "Unknown";
    if (bpSub) bpSub.textContent = state.sleepInstalled ? `Sleep: ${state.sleepLabel}` : (h.age ? `Last good ${h.age}` : "Sleep Guard not installed");
  } else {
    if (bpLabel) bpLabel.textContent = "Power & Sleep";
    if (bpVal) bpVal.textContent = state.sleepInstalled ? state.sleepLabel : "Always On";
    if (bpSub) bpSub.textContent = state.sleepInstalled ? "Click to adjust schedule" : "Sleep Guard not installed";
  }
}

export function renderOverviewActivity() {
  const body = $("overview-activity-body");
  if (!body) return;

  const items = [];
  if (state.torrentsActiveCount > 0) {
    items.push({
      tag: "Downloads",
      text: `${state.torrentsActiveCount} active torrent${state.torrentsActiveCount === 1 ? "" : "s"} · ↓ ${state.torrentsDlMbs.toFixed(2)} MB/s`,
      href: "#/apps",
      cta: "View Queue",
    });
  }
  if (state.activeJellyfinStreams > 0) {
    items.push({
      tag: "Jellyfin",
      text: `${state.activeJellyfinStreams} active client connection${state.activeJellyfinStreams === 1 ? "" : "s"}`,
      href: "#/system",
      cta: "Inspect",
    });
  }
  if (state.activeSmbClients > 0) {
    items.push({
      tag: "Samba",
      text: `${state.activeSmbClients} active LAN share mount${state.activeSmbClients === 1 ? "" : "s"}`,
      href: "#/system",
      cta: "Inspect",
    });
  }
  if (state.backupSnapshot && state.backupSnapshot.is_syncing) {
    items.push({
      tag: "Backup",
      text: state.backupSnapshot.message || "Photo cloud backup running...",
      href: "#/backups",
      cta: "Monitor",
    });
  }
  if (state.tvSnapshot && state.tvSnapshot.is_deploying) {
    items.push({
      tag: "TV Fleet",
      text: "Deploying APK updates to Android TVs...",
      href: "#/tvs",
      cta: "Monitor",
    });
  }
  if (state.storageTotalIoMbs > 1.0) {
    items.push({
      tag: "Disk I/O",
      text: `${state.storageTotalIoMbs.toFixed(1)} MB/s combined read/write activity`,
      href: "#/system",
      cta: "Details",
    });
  }

  const key = JSON.stringify(items);
  if (key === lastActivityKey && body.children.length > 0) return;
  lastActivityKey = key;

  if (items.length === 0) {
    body.innerHTML = `
      <div class="activity-quiet">
        <span class="status-dot is-ok" aria-hidden="true"></span>
        <span>All quiet &mdash; no active downloads, streams, or background jobs running.</span>
      </div>
    `;
    return;
  }

  body.innerHTML = items.map((item) => `
    <div class="activity-row">
      <div class="activity-row-left">
        <span class="activity-tag">${escapeHtml(item.tag)}</span>
        <span>${escapeHtml(item.text)}</span>
      </div>
      <a href="${item.href}" class="btn-ghost">${escapeHtml(item.cta)}</a>
    </div>
  `).join("");
}

export function renderOverviewAuditTrail() {
  const list = $("overview-audit-trail");
  if (!list) return;

  const entries = [];
  const allServices = state.servicesList || [];
  if (state.servicesLoadedOnce) {
    const up = allServices.filter((s) => s.is_up).length;
    const unhealthy = allServices.filter((s) => s.health === "unhealthy").length;
    entries.push({
      tone: unhealthy > 0 || (allServices.length > 0 && up === 0) ? "bad" : "ok",
      label: "Containers",
      detail: unhealthy > 0 ? `${unhealthy} unhealthy` : `${up}/${allServices.length} up`,
      meta: unhealthy > 0 ? "Needs check" : "Nominal",
    });
  }

  if (state.modules.backups && state.backupSnapshot) {
    const bak = state.backupSnapshot;
    const h = bak.health || {};
    const st = h.state || bak.status || "unknown";
    const tone = st === "synced" ? "ok" : (st === "syncing" ? "cool" : (st === "error" || st === "stale" ? "bad" : "muted"));
    entries.push({
      tone,
      label: "Photo Backup",
      detail: st === "synced" ? "Verified" : (st === "syncing" ? "Syncing" : (st.charAt(0).toUpperCase() + st.slice(1))),
      meta: h.age ? `Last good ${h.age}` : (bak.db_size || "No completed run"),
    });
  }

  if (state.modules.tvs && state.tvSnapshot) {
    const tv = state.tvSnapshot;
    const online = Number(tv.online_devices || 0);
    const total = Number(tv.total_devices || 0);
    const pending = Number(tv.pending_updates_count || 0);
    entries.push({
      tone: tv.is_deploying ? "cool" : (pending > 0 ? "accent" : (online > 0 ? "ok" : "muted")),
      label: "TV Fleet",
      detail: `${online}/${total} online`,
      meta: pending > 0 ? `${pending} APK update${pending === 1 ? "" : "s"}` : "Up to date",
    });
  }

  if (state.modules.sleepGuard) {
    entries.push({
      tone: state.sleepSkipActive ? "accent" : (state.sleepInstalled && state.sleepEnabled ? "cool" : "muted"),
      label: "Sleep Guard",
      detail: state.sleepSkipActive ? "Skip active" : (state.sleepInstalled ? state.sleepLabel : "Not installed"),
      meta: state.sleepSkipActive ? "Operator override" : (state.sleepInstalled && state.sleepEnabled ? "RTC window" : "Always-on"),
    });
  }

  if (state.updatesSnapshot) {
    const u = state.updatesSnapshot;
    const pending = Number(u.pending || 0);
    const majors = Number(u.majors || 0);
    entries.push({
      tone: majors > 0 ? "accent" : (pending > 0 ? "cool" : (u.checked_at ? "ok" : "muted")),
      label: "App Updates",
      detail: !u.checked_at ? "Not checked" : (pending > 0 ? `${pending} pending` : "Up to date"),
      meta: majors > 0 ? `${majors} major release` : (u.checked_at_str || "24h GitHub check"),
    });
  }

  const key = JSON.stringify(entries);
  if (key === lastAuditKey && list.children.length > 0) return;
  lastAuditKey = key;

  if (entries.length === 0) {
    list.innerHTML = `<li class="audit-trail-item"><span class="audit-trail-label">Telemetry</span><span class="audit-trail-meta font-mono">Waiting for polls&hellip;</span></li>`;
    return;
  }

  list.innerHTML = entries.map((e) => `
    <li class="audit-trail-item is-${e.tone}">
      <div class="audit-trail-main">
        <span class="audit-trail-dot" aria-hidden="true"></span>
        <span class="audit-trail-label">${escapeHtml(e.label)}</span>
      </div>
      <div class="audit-trail-right">
        <span class="audit-trail-val font-mono">${escapeHtml(e.detail)}</span>
        <span class="audit-trail-meta font-mono">${escapeHtml(e.meta)}</span>
      </div>
    </li>
  `).join("");
}

export function renderOverview() {
  renderOverviewApps();
  renderOverviewKpis();
  renderOverviewActivity();
  renderOverviewAuditTrail();
}
