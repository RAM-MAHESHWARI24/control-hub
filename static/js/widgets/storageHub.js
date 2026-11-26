/**
 * Widget: Storage Analytics, 30-Day Fill Forecast, Safe Cleanups & SMART Health
 * Displays real measured folder sizes, growth forecast, one-click confirmed cleanup
 * actions, and SMART drive health without inventing unavailable metrics.
 */

import { $, confirmAction, setCardSummary } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";

const subtitleEl = $("storage-analytics-subtitle");
const forecastBadge = $("storage-forecast-badge");
const forecastCallout = $("storage-forecast-callout");
const btnRefresh = $("btn-storage-refresh");
const measuredMeta = $("storage-measured-meta");
const foldersTbody = $("storage-folders-tbody");
const smartBadge = $("storage-smart-badge");
const smartTbody = $("storage-smart-tbody");
const cleanupTotalEl = $("storage-cleanup-total");
const cleanupTbody = $("storage-cleanup-tbody");

function formatGbSize(gb) {
  if (typeof gb !== "number" || Number.isNaN(gb)) return "Unavailable";
  if (gb >= 1024) return `${(gb / 1024).toFixed(2)} TB`;
  return `${gb.toFixed(2)} GB`;
}

function formatBytesHuman(bytes) {
  if (typeof bytes !== "number" || Number.isNaN(bytes) || bytes <= 0) return "0 MB";
  const gb = bytes / (1024 ** 3);
  if (gb >= 1) return `${gb.toFixed(2)} GB`;
  return `${(bytes / (1024 ** 2)).toFixed(1)} MB`;
}

function renderForecast(forecasts) {
  const hdd = forecasts?.hdd;
  const ssd = forecasts?.ssd;
  const primary = hdd || ssd;
  if (!forecastCallout) return;

  if (!primary) {
    forecastCallout.className = "inline-callout";
    forecastCallout.textContent = "Storage forecast unavailable on this host.";
    if (forecastBadge) {
      forecastBadge.className = "badge badge-neutral";
      forecastBadge.textContent = "No History";
    }
    return;
  }

  const lines = [hdd?.message, ssd?.message].filter(Boolean);
  forecastCallout.textContent = lines.join(" | ");

  const days = primary.days_until_full;
  const isUrgent = typeof days === "number" && days <= 30;
  forecastCallout.className = isUrgent ? "inline-callout is-warning" : "inline-callout";

  if (forecastBadge) {
    if (!primary.ready) {
      forecastBadge.className = "badge badge-neutral";
      forecastBadge.textContent = "Collecting";
    } else if (isUrgent) {
      forecastBadge.className = "badge badge-status-error";
      forecastBadge.textContent = `Full in ~${Math.round(days)}d`;
    } else if (typeof days === "number") {
      forecastBadge.className = "badge badge-info";
      forecastBadge.textContent = `~${Math.round(days)}d left`;
    } else {
      forecastBadge.className = "badge badge-status-synced";
      forecastBadge.textContent = "Steady";
    }
  }
}

function renderFolders(folders) {
  if (measuredMeta) {
    if (folders?.measuring) {
      measuredMeta.textContent = "Measuring in background...";
    } else if (folders?.measured_at) {
      const dt = new Date(folders.measured_at * 1000);
      const src = folders.measured_by === "root-timer" ? "root timer" : "daemon cache";
      measuredMeta.textContent = `Updated ${dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} (${src})`;
    } else {
      measuredMeta.textContent = "Not measured yet";
    }
  }

  if (!foldersTbody) return;
  const rows = Array.isArray(folders?.rows) ? folders.rows : [];
  if (!rows.length) {
    foldersTbody.innerHTML = `<tr><td colspan="2" class="text-muted">No configured folders found.</td></tr>`;
    return;
  }
  foldersTbody.innerHTML = rows.map((r) => `
    <tr class="service-row">
      <td>
        <strong>${escapeHtml(r.label)}</strong>
        <code class="photos-path-code font-mono">${escapeHtml(r.path || "")}</code>
      </td>
      <td class="num-col font-mono">${escapeHtml(formatGbSize(r.gb))}</td>
    </tr>
  `).join("");
}

function renderSmart(smart) {
  const disks = Array.isArray(smart?.disks) ? smart.disks : [];
  const allOk = disks.length > 0 && disks.every((d) => d.passed !== false && (d.reallocated_sectors || 0) === 0);
  const anyFail = disks.some((d) => d.passed === false);

  if (smartBadge) {
    if (!disks.length) {
      smartBadge.className = "badge badge-neutral";
      smartBadge.textContent = "Unavailable";
    } else if (anyFail) {
      smartBadge.className = "badge badge-status-error";
      smartBadge.textContent = "Drive Alert";
    } else if (allOk) {
      smartBadge.className = "badge badge-status-synced";
      smartBadge.textContent = `${disks.length} Healthy`;
    } else {
      smartBadge.className = "badge badge-info";
      smartBadge.textContent = `${disks.length} Disks`;
    }
  }

  if (!smartTbody) return;
  if (!disks.length) {
    smartTbody.innerHTML = `<tr><td colspan="3" class="text-muted">${escapeHtml(smart?.reason || "SMART telemetry unavailable.")}</td></tr>`;
    return;
  }

  smartTbody.innerHTML = disks.map((d) => {
    const temp = typeof d.temp_c === "number" ? `${d.temp_c}°C` : "Temp n/a";
    const realloc = typeof d.reallocated_sectors === "number" ? `${d.reallocated_sectors} realloc` : "Sectors n/a";
    const statusCls = d.passed === false
      ? "badge-status-error"
      : (d.passed === true ? "badge-status-synced" : "badge-neutral");
    const statusTxt = d.passed === false ? "FAILED" : (d.passed === true ? "Passed" : "No SMART");
    return `
      <tr class="service-row">
        <td>
          <strong>${escapeHtml(d.device)}</strong> (${escapeHtml(d.type || "Disk")})
          <div class="text-muted">${escapeHtml(d.model || "")} ${d.size_gb ? `(${d.size_gb} GB)` : ""}</div>
        </td>
        <td class="num-col font-mono">${escapeHtml(`${temp} · ${realloc}`)}</td>
        <td class="num-col"><span class="badge ${statusCls}">${statusTxt}</span></td>
      </tr>
    `;
  }).join("");
}

function renderCleanup(items) {
  const rows = Array.isArray(items) ? items : [];
  const totalBytes = rows.reduce((sum, item) => sum + (Number(item.size_bytes) || 0), 0);
  if (cleanupTotalEl) {
    cleanupTotalEl.textContent = totalBytes > 0
      ? `${formatBytesHuman(totalBytes)} reclaimable`
      : "No reclaimable clutter detected";
  }
  if (!cleanupTbody) return;
  if (!rows.length) {
    cleanupTbody.innerHTML = `<tr><td colspan="4" class="text-muted">No cleanup rules available.</td></tr>`;
    return;
  }

  cleanupTbody.innerHTML = rows.map((item) => {
    const canRun = Boolean(item.actionable);
    const sizeText = formatBytesHuman(Number(item.size_bytes) || 0);
    const reasonHtml = item.reason ? `<div class="text-muted">${escapeHtml(item.reason)}</div>` : "";
    return `
      <tr class="service-row">
        <td>
          <strong>${escapeHtml(item.label)}</strong>
          <div class="text-muted">${escapeHtml(item.description || "")}</div>
          ${reasonHtml}
        </td>
        <td class="num-col font-mono">${Number(item.count || 0).toLocaleString()} item(s)</td>
        <td class="num-col font-mono">${escapeHtml(sizeText)}</td>
        <td class="actions-col ledger-cell-actions">
          <div class="service-row-actions">
            <button
              type="button"
              class="btn-secondary btn-storage-cleanup"
              data-cleanup-target="${escapeHtml(item.id)}"
              data-cleanup-label="${escapeHtml(item.label)}"
              data-cleanup-size="${escapeHtml(sizeText)}"
              ${canRun ? "" : "disabled"}
            >${escapeHtml(item.action_label || "Clean")}</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

export async function fetchStorageOverview(force = false) {
  try {
    const url = force ? `${ENDPOINTS.storageOverview}?refresh=true` : ENDPOINTS.storageOverview;
    const res = await fetch(url);
    if (!res.ok) return false;
    const data = await res.json();

    renderForecast(data.forecasts);
    renderFolders(data.folders);
    renderSmart(data.smart);
    renderCleanup(data.cleanup);

    const totalReclaim = (data.cleanup || []).reduce((acc, row) => acc + (Number(row.size_bytes) || 0), 0);
    const diskCount = (data.smart?.disks || []).length;
    setCardSummary(
      "storage-analytics-panel",
      `${diskCount} disk(s) monitored · ${formatBytesHuman(totalReclaim)} reclaimable`
    );
    if (subtitleEl) {
      subtitleEl.textContent = `${diskCount} drive(s) · ${formatBytesHuman(totalReclaim)} reclaimable`;
    }
    return true;
  } catch (err) {
    console.error("Error fetching storage overview:", err);
    return false;
  }
}

async function handleCleanupClick(btn) {
  const target = btn.getAttribute("data-cleanup-target");
  const label = btn.getAttribute("data-cleanup-label") || target;
  const sizeTxt = btn.getAttribute("data-cleanup-size") || "";
  if (!target) return;

  const confirmed = await confirmAction({
    title: `Run ${label}?`,
    message: `This will clean ${label} (${sizeTxt}) using safe retention rules.`,
    warning: target === "torrents_seeded"
      ? "Removes paused/completed torrent tasks and files under /data/torrents (hardlinked copies in media/ stay untouched)."
      : "",
    confirmLabel: "Run Cleanup",
    danger: true,
    triggerEl: btn,
  });
  if (!confirmed) return;

  btn.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.storageCleanup, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Cleanup Complete", data.message || `${label} cleaned.`, "success");
      await fetchStorageOverview(true);
    } else {
      showToast("Cleanup Notice", data.error || "Cleanup could not complete.", "warning");
      btn.disabled = false;
    }
  } catch (_) {
    showToast("Error", "Could not reach storage cleanup endpoint.", "danger");
    btn.disabled = false;
  }
}

export function setupStorageHub() {
  if (btnRefresh) {
    btnRefresh.addEventListener("click", () => fetchStorageOverview(true));
  }
  if (cleanupTbody) {
    cleanupTbody.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".btn-storage-cleanup");
      if (btn && !btn.disabled) {
        handleCleanupClick(btn);
      }
    });
  }
}
