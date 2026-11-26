/**
 * Widget: Photos Hub (Per-User Storage, ML Schedule & Queue, Face Export, Folder Health)
 * Auto-hides when no photo service, ML schedule, or photo paths exist.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";

const photosHealthPanel = $("photos-health-panel");
const photosOfflineBadge = $("photos-offline-badge");
const btnPhotosRefresh = $("btn-photos-refresh");

const photosMlBadge = $("photos-ml-badge");
const btnMlToggle = $("btn-ml-toggle");
const photosMlLastEvent = $("photos-ml-last-event");
const mlScheduleForm = $("ml-schedule-form");
const mlStartInput = $("ml-start-time");
const mlStopInput = $("ml-stop-time");
const mlEnabledCheckbox = $("ml-schedule-enabled");
const btnMlSaveSchedule = $("btn-ml-save-schedule");
const photosMlQueueTbody = $("photos-ml-queue-tbody");

const photosXmpBadge = $("photos-xmp-badge");
const photosXmpLastRun = $("photos-xmp-last-run");
const photosXmpWritten = $("photos-xmp-written");
const photosXmpErrors = $("photos-xmp-errors");
const photosXmpSummary = $("photos-xmp-summary");
const photosUsersTbody = $("photos-users-tbody");

const photosOfflineSummary = $("photos-offline-summary");
const photosFoldersTbody = $("photos-folders-tbody");

let lastMlRunning = false;
let mlDirty = false;

function formatBytes(bytes) {
  if (typeof bytes !== "number" || Number.isNaN(bytes) || bytes < 0) return "Unknown";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let val = bytes;
  let idx = 0;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx += 1;
  }
  const digits = idx === 0 ? 0 : (val >= 100 ? 1 : 2);
  return `${val.toFixed(digits)} ${units[idx]}`;
}

function formatGb(gb) {
  if (typeof gb !== "number" || Number.isNaN(gb)) return "Unknown";
  return gb >= 1024 ? `${(gb / 1024).toFixed(2)} TB` : `${gb.toFixed(1)} GB`;
}

function isEditingSchedule() {
  if (!mlScheduleForm) return false;
  if (mlDirty) return true;
  const active = document.activeElement;
  return Boolean(active && mlScheduleForm.contains(active));
}

function renderMlSection(ml, tzAbbr) {
  const safeMl = ml || {};
  lastMlRunning = Boolean(safeMl.running);

  if (photosMlBadge) {
    if (!safeMl.installed) {
      photosMlBadge.className = "badge badge-neutral";
      photosMlBadge.textContent = "Not Installed";
    } else if (safeMl.running) {
      photosMlBadge.className = "badge badge-status-synced";
      photosMlBadge.textContent = "Running (AI)";
    } else {
      photosMlBadge.className = "badge badge-neutral";
      photosMlBadge.textContent = "Stopped";
    }
  }

  if (btnMlToggle) {
    btnMlToggle.disabled = !safeMl.can_control;
    btnMlToggle.textContent = safeMl.running ? "Stop ML Now" : "Start ML Now";
  }

  const sched = safeMl.schedule || {};
  if (!isEditingSchedule()) {
    if (mlStartInput && sched.start_time) mlStartInput.value = sched.start_time;
    if (mlStopInput && sched.stop_time) mlStopInput.value = sched.stop_time;
    if (mlEnabledCheckbox && typeof sched.enabled === "boolean") {
      mlEnabledCheckbox.checked = sched.enabled;
    }
  }
  if (btnMlSaveSchedule) {
    btnMlSaveSchedule.disabled = !sched.exists && !safeMl.installed;
  }

  if (photosMlLastEvent) {
    const schedLine = sched.start_time && sched.stop_time
      ? (sched.enabled
        ? `Scheduled ${sched.start_time} to ${sched.stop_time} ${tzAbbr || ""}`
        : `Schedule paused (was ${sched.start_time} to ${sched.stop_time} ${tzAbbr || ""})`)
      : "No ML cron file found";
    const eventText = safeMl.last_event ? ` | Last: ${safeMl.last_event}` : "";
    photosMlLastEvent.textContent = `${schedLine.trim()}${eventText}`;
  }

  if (photosMlQueueTbody) {
    const q = safeMl.queue || {};
    const rows = [];

    if (typeof q.pending_faces === "number" || typeof q.pending_metadata === "number") {
      if (typeof q.pending_faces === "number") {
        rows.push(`
          <tr>
            <td>Face Recognition Backlog (DB)</td>
            <td class="num-col font-mono">${Number(q.pending_faces).toLocaleString()}</td>
            <td class="num-col"><span class="badge ${q.pending_faces > 0 ? "badge-info" : "badge-status-synced"}">${q.pending_faces > 0 ? "Pending" : "Caught up"}</span></td>
          </tr>
        `);
      }
      if (typeof q.pending_metadata === "number") {
        rows.push(`
          <tr>
            <td>Metadata Extraction Backlog (DB)</td>
            <td class="num-col font-mono">${Number(q.pending_metadata).toLocaleString()}</td>
            <td class="num-col"><span class="badge ${q.pending_metadata > 0 ? "badge-info" : "badge-status-synced"}">${q.pending_metadata > 0 ? "Pending" : "Caught up"}</span></td>
          </tr>
        `);
      }
    }

    const bullQueues = Array.isArray(q.queues) ? q.queues : [];
    const activeOrBusy = bullQueues.filter((item) => item.active > 0 || item.waiting > 0 || item.delayed > 0 || item.failed > 0);
    if (q.redis_available && activeOrBusy.length > 0) {
      activeOrBusy.forEach((item) => {
        const queued = item.waiting + item.active + item.delayed;
        const badgeCls = item.failed > 0 ? "badge-status-error" : (item.active > 0 ? "badge-status-syncing" : "badge-info");
        const statusTxt = item.failed > 0 ? `${item.failed} failed` : (item.active > 0 ? `${item.active} running` : `${queued} queued`);
        rows.push(`
          <tr>
            <td>${escapeHtml(item.label)} (BullMQ)</td>
            <td class="num-col font-mono">${queued.toLocaleString()}</td>
            <td class="num-col"><span class="badge ${badgeCls}">${escapeHtml(statusTxt)}</span></td>
          </tr>
        `);
      });
    } else if (q.redis_available && rows.length === 0) {
      rows.push(`<tr><td>Redis Job Queues</td><td class="num-col font-mono">0</td><td class="num-col"><span class="badge badge-status-synced">Idle</span></td></tr>`);
    }

    photosMlQueueTbody.innerHTML = rows.length
      ? rows.join("")
      : `<tr><td colspan="3" class="text-muted">Job queue unavailable (database/Redis offline).</td></tr>`;
  }
}

function renderFaceExportSection(faceExport) {
  const fx = faceExport || {};
  if (photosXmpBadge) {
    if (fx.status === "ok") {
      photosXmpBadge.className = "badge badge-status-synced";
      photosXmpBadge.textContent = "Up to Date";
    } else if (fx.status === "warning") {
      photosXmpBadge.className = "badge badge-status-error";
      photosXmpBadge.textContent = "Warnings";
    } else {
      photosXmpBadge.className = "badge badge-neutral";
      photosXmpBadge.textContent = fx.installed ? "Not Run Yet" : "Not Installed";
    }
  }
  if (photosXmpLastRun) photosXmpLastRun.textContent = fx.last_run || "Never";
  if (photosXmpWritten) {
    if (typeof fx.files_written === "number") {
      const cachedTxt = typeof fx.cached_skipped === "number" ? ` (${Number(fx.cached_skipped).toLocaleString()} cached)` : "";
      photosXmpWritten.textContent = `${Number(fx.files_written).toLocaleString()} written${cachedTxt}`;
    } else if (typeof fx.cached_skipped === "number") {
      photosXmpWritten.textContent = `${Number(fx.cached_skipped).toLocaleString()} cached`;
    } else {
      photosXmpWritten.textContent = "Unknown";
    }
  }
  if (photosXmpErrors) {
    photosXmpErrors.textContent = fx.errors > 0 ? `${fx.errors} (${fx.error_detail || "check log"})` : "0 errors";
  }
  if (photosXmpSummary) {
    photosXmpSummary.textContent = fx.summary || "";
    photosXmpSummary.hidden = !fx.summary;
  }
}

function renderUsersTable(users) {
  if (!photosUsersTbody) return;
  const rows = Array.isArray(users) ? users : [];
  if (!rows.length) {
    photosUsersTbody.innerHTML = `<tr><td colspan="3" class="text-muted">Per-user storage unavailable until Photo DB answers.</td></tr>`;
    return;
  }
  photosUsersTbody.innerHTML = rows.map((u) => {
    const used = formatBytes(u.used_bytes);
    const quota = typeof u.quota_bytes === "number" && u.quota_bytes > 0 ? ` / ${formatBytes(u.quota_bytes)}` : "";
    const assetsCount = typeof u.assets === "number" ? Number(u.assets).toLocaleString() : "0";
    return `
      <tr>
        <td>${escapeHtml(u.name || "User")}</td>
        <td class="num-col font-mono">${assetsCount}</td>
        <td class="num-col font-mono">${escapeHtml(used + quota)}</td>
      </tr>
    `;
  }).join("");
}

function renderFoldersHealth(storageHealth, library, libraries) {
  const lib = library || {};
  const offlineCount = typeof lib.offline_assets === "number" ? lib.offline_assets : null;

  if (photosOfflineBadge) {
    if (offlineCount === null) {
      photosOfflineBadge.className = "badge badge-neutral";
      photosOfflineBadge.textContent = "DB Unavailable";
    } else if (offlineCount === 0) {
      photosOfflineBadge.className = "badge badge-status-synced";
      photosOfflineBadge.textContent = "0 Offline Assets";
    } else {
      photosOfflineBadge.className = "badge badge-status-error";
      photosOfflineBadge.textContent = `${Number(offlineCount).toLocaleString()} Offline`;
    }
  }

  if (photosOfflineSummary) {
    const unreadable = storageHealth && typeof storageHealth.unreadable_total === "number" ? storageHealth.unreadable_total : 0;
    const offlineTxt = offlineCount === null ? "Offline count unavailable" : `${Number(offlineCount).toLocaleString()} offline assets`;
    photosOfflineSummary.textContent = unreadable > 0
      ? `${offlineTxt} | ${unreadable} unreadable path(s)`
      : `${offlineTxt} | Readability OK`;
  }

  if (!photosFoldersTbody) return;
  const folders = Array.isArray(storageHealth?.folders) ? storageHealth.folders : [];
  const extLibs = Array.isArray(libraries) ? libraries : [];
  const htmlRows = folders.map((f) => {
    const freeStr = typeof f.free_gb === "number"
      ? `${formatGb(f.free_gb)} free${typeof f.total_gb === "number" ? ` / ${formatGb(f.total_gb)}` : ""}`
      : (f.exists ? "Unknown" : "Missing");
    const statusCls = f.status === "healthy"
      ? "badge-status-synced"
      : (f.status === "partial" ? "badge-info" : "badge-status-error");
    return `
      <tr>
        <td>
          <strong>${escapeHtml(f.label)}</strong>
          <code class="photos-path-code font-mono">${escapeHtml(f.path)}</code>
        </td>
        <td class="num-col font-mono">${escapeHtml(freeStr)}</td>
        <td class="num-col"><span class="badge ${statusCls}">${escapeHtml(f.message)}</span></td>
      </tr>
    `;
  });

  if (!htmlRows.length && !extLibs.length) {
    photosFoldersTbody.innerHTML = `<tr><td colspan="3" class="text-muted">No photo upload or external library folders configured.</td></tr>`;
    return;
  }

  extLibs.forEach((ext) => {
    const firstPath = Array.isArray(ext.paths) && ext.paths.length ? ext.paths[0] : "";
    const alreadyShown = folders.some((f) => f.path === firstPath);
    if (!alreadyShown && firstPath) {
      const extOffline = Number(ext.offline_assets || 0);
      htmlRows.push(`
        <tr>
          <td>
            <strong>Library: ${escapeHtml(ext.name)}</strong>
            <code class="photos-path-code font-mono">${escapeHtml(firstPath)}</code>
          </td>
          <td class="num-col font-mono">${Number(ext.assets || 0).toLocaleString()} assets</td>
          <td class="num-col"><span class="badge ${extOffline > 0 ? "badge-status-error" : "badge-status-synced"}">${extOffline > 0 ? `${extOffline} offline` : "Online"}</span></td>
        </tr>
      `);
    }
  });

  photosFoldersTbody.innerHTML = htmlRows.join("");
}

export async function fetchPhotosOverview(force = false) {
  try {
    const url = force ? `${ENDPOINTS.photosOverview}?refresh=true` : ENDPOINTS.photosOverview;
    const res = await fetch(url);
    const data = await res.json();

    if (photosHealthPanel) {
      photosHealthPanel.hidden = data.installed === false;
    }
    if (data.installed === false) return true;

    const lib = data.library || {};
    const peopleCount = typeof lib.named_people === "number" ? `${lib.named_people} people` : null;
    const assetCount = typeof lib.total_assets === "number" ? `${Number(lib.total_assets).toLocaleString()} assets` : null;
    const mlLabel = data.ml?.running ? "ML running" : "ML stopped";
    const summaryParts = [assetCount, peopleCount, mlLabel].filter(Boolean);
    setCardSummary("photos-health-panel", summaryParts.join(" · ") || "Photo library & ML telemetry");

    renderMlSection(data.ml, data.tz_abbr);
    renderFaceExportSection(data.face_export);
    renderUsersTable(data.users);
    renderFoldersHealth(data.storage_health, lib, data.libraries);
    return true;
  } catch (err) {
    console.error("Error fetching photos overview:", err);
    return false;
  }
}

async function handleToggleMl() {
  if (!btnMlToggle) return;
  const action = lastMlRunning ? "stop" : "start";
  btnMlToggle.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.photosMlAction, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Machine Learning", data.message || `ML ${action} complete.`, "success");
    } else {
      showToast("ML Control", data.error || "Could not update ML container.", "warning");
    }
    await fetchPhotosOverview(false);
  } catch (_) {
    showToast("Error", "Could not reach ML control endpoint.", "danger");
  } finally {
    btnMlToggle.disabled = false;
  }
}

async function handleSaveSchedule(ev) {
  ev.preventDefault();
  if (!mlStartInput || !mlStopInput) return;
  const startTime = (mlStartInput.value || "").trim();
  const stopTime = (mlStopInput.value || "").trim();
  const enabled = mlEnabledCheckbox ? mlEnabledCheckbox.checked : true;

  if (btnMlSaveSchedule) btnMlSaveSchedule.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.photosMlSchedule, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, start_time: startTime, stop_time: stopTime }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      mlDirty = false;
      showToast("ML Schedule Saved", data.message || "Schedule updated.", "success");
      await fetchPhotosOverview(false);
    } else {
      showToast("Schedule Error", data.error || "Could not save ML schedule.", "warning");
    }
  } catch (_) {
    showToast("Error", "Failed to save ML schedule.", "danger");
  } finally {
    if (btnMlSaveSchedule) btnMlSaveSchedule.disabled = false;
  }
}

export function setupPhotosHub() {
  if (btnPhotosRefresh) {
    btnPhotosRefresh.addEventListener("click", () => fetchPhotosOverview(true));
  }
  if (btnMlToggle) {
    btnMlToggle.addEventListener("click", handleToggleMl);
  }
  if (mlScheduleForm) {
    [mlStartInput, mlStopInput, mlEnabledCheckbox].forEach((el) => {
      if (el) el.addEventListener("change", () => { mlDirty = true; });
    });
    mlScheduleForm.addEventListener("submit", handleSaveSchedule);
  }
}
