/**
 * Widget: Hardware Vitals & Storage Headroom
 * Renders live CPU, RAM, Swap, OS SSD, and measured storage breakdown.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { setUptime } from "./header.js";

const cpuTempBadge = $("cpu-temp-badge");
const cpuLoadVal = $("cpu-load-val");
const cpuStat = $("cpu-stat");
const cpuProgress = $("cpu-progress");
const ramStat = $("ram-stat");
const ramProgress = $("ram-progress");
const ssdStat = $("ssd-stat");
const ssdProgress = $("ssd-progress");
const hddStat = $("hdd-stat");
const hddAlertBanner = $("hdd-alert-banner");
const hddAlertPct = $("hdd-alert-pct");
const hddAlertFree = $("hdd-alert-free");

const vitalsCardSubtitle = $("vitals-card-subtitle");
const vitalsCpuTitle = $("vitals-cpu-title");
const vitalsRamTitle = $("vitals-ram-title");
const vitalsSsdTitle = $("vitals-ssd-title");
const vitalsHddTitle = $("vitals-hdd-title");

const segMedia = $("seg-media");
const segPhotos = $("seg-photos");
const segDb = $("seg-db");
const legendMedia = $("legend-media");
const legendPhotos = $("legend-photos");
const legendDb = $("legend-db");
const storageBreakdownNote = $("storage-breakdown-note");

export async function fetchVitals() {
  try {
    const res = await fetch(ENDPOINTS.systemVitals);
    if (!res.ok) return;
    const data = await res.json();

    if (data.timezone) state.timezone = data.timezone;
    if (data.tz_abbr) state.tzAbbr = data.tz_abbr;
    if (data.uptime) setUptime(data.uptime);

    const cpu = data.cpu || {};
    const cpuLoad = typeof cpu.usage_percent === "number" ? cpu.usage_percent : 0;
    if (cpuLoadVal) cpuLoadVal.textContent = `${cpuLoad}%`;
    if (cpuStat) cpuStat.textContent = `${cpuLoad}% Load`;
    if (cpuProgress) cpuProgress.style.width = `${Math.min(100, cpuLoad)}%`;
    if (cpuTempBadge) {
      cpuTempBadge.textContent = cpu.temp_c ? `${cpu.temp_c}°C | ${cpuLoad}%` : `CPU: ${cpuLoad}%`;
    }
    if (vitalsCpuTitle && cpu.model) {
      const threadCount = cpu.threads || cpu.cores || 1;
      vitalsCpuTitle.textContent = `${cpu.model} (${threadCount} Threads)`;
    }

    const mem = data.memory || {};
    const swap = data.swap || {};
    if (ramStat) {
      ramStat.textContent = `${mem.used_gib ?? 0} / ${mem.total_gib ?? 0} GiB (${mem.percent ?? 0}%) | Swap: ${swap.percent ?? 0}%`;
    }
    if (ramProgress) ramProgress.style.width = `${Math.min(100, mem.percent || 0)}%`;
    if (vitalsRamTitle) {
      vitalsRamTitle.textContent = `Memory (${mem.total_gib ?? 0} GiB RAM + ${swap.total_gib ?? 0} GiB Swap)`;
    }
    if (vitalsCardSubtitle && cpu.model) {
      vitalsCardSubtitle.textContent = `${cpu.model} • ${mem.total_gib ?? 0} GiB RAM`;
    }

    const storage = data.storage || {};
    const ssd = storage.ssd || {};
    if (ssdStat) {
      ssdStat.textContent = `${ssd.free_gb ?? 0} GB Free (${ssd.percent ?? 0}% Used of ${ssd.total_gb ?? 0} GB)`;
    }
    if (ssdProgress) ssdProgress.style.width = `${Math.min(100, ssd.percent || 0)}%`;
    if (vitalsSsdTitle) {
      vitalsSsdTitle.textContent = `OS Root (${ssd.mount || "/"} - ${ssd.total_gb ?? 0} GB)`;
    }

    const hdd = storage.hdd || {};
    if (vitalsHddTitle) {
      vitalsHddTitle.textContent = hdd.available
        ? `Media Storage (${hdd.mount} - ${hdd.total_gb} GB)`
        : `Media Storage (${hdd.mount || "Unconfigured"})`;
    }
    if (hddStat) {
      hddStat.textContent = hdd.available
        ? `${hdd.free_gb} GB Free (${hdd.percent}% Used of ${hdd.total_gb} GB)`
        : (hdd.reason || "Storage unavailable");
    }

    // Measured folder breakdown (never guessed 75%/20%/5%)
    const bd = hdd.breakdown || {};
    if (bd.measured) {
      const mediaPct = typeof bd.media_pct === "number" ? bd.media_pct : 0;
      const photosPct = typeof bd.photos_pct === "number" ? bd.photos_pct : 0;
      const appPct = typeof bd.appdata_pct === "number" ? bd.appdata_pct : 0;

      if (segMedia) {
        segMedia.style.width = `${mediaPct.toFixed(1)}%`;
        segMedia.title = bd.media_gb !== null ? `Movies & TV: ${bd.media_gb} GB (${mediaPct.toFixed(1)}%)` : "Movies & TV: Unknown";
      }
      if (segPhotos) {
        segPhotos.style.width = `${photosPct.toFixed(1)}%`;
        segPhotos.title = bd.photos_gb !== null ? `Photos: ${bd.photos_gb} GB (${photosPct.toFixed(1)}%)` : "Photos: Unknown";
      }
      if (segDb) {
        segDb.style.width = `${appPct.toFixed(1)}%`;
        segDb.title = bd.appdata_gb !== null ? `Appdata & Backups: ${bd.appdata_gb} GB (${appPct.toFixed(1)}%)` : "Appdata & Backups: Unknown";
      }
      if (legendMedia) legendMedia.textContent = bd.media_gb !== null ? `Media (${bd.media_gb} GB)` : "Media (Unknown)";
      if (legendPhotos) legendPhotos.textContent = bd.photos_gb !== null ? `Photos (${bd.photos_gb} GB)` : "Photos (Unknown)";
      if (legendDb) legendDb.textContent = bd.appdata_gb !== null ? `Appdata & Backups (${bd.appdata_gb} GB)` : "Appdata & Backups (Unknown)";
      if (storageBreakdownNote) storageBreakdownNote.textContent = bd.measuring ? "Refreshing folder sizes..." : "";
    } else {
      if (segMedia) segMedia.style.width = "0%";
      if (segPhotos) segPhotos.style.width = "0%";
      if (segDb) segDb.style.width = "0%";
      const stateTxt = bd.measuring ? "Measuring..." : "Unknown";
      if (legendMedia) legendMedia.textContent = `Media (${stateTxt})`;
      if (legendPhotos) legendPhotos.textContent = `Photos (${stateTxt})`;
      if (legendDb) legendDb.textContent = `Appdata & Backups (${stateTxt})`;
      if (storageBreakdownNote) storageBreakdownNote.textContent = bd.reason || (bd.measuring ? "Measuring folder sizes in background..." : "Folder sizes unavailable");
    }

    if (hddAlertBanner) {
      if (hdd.available && (hdd.is_critical || hdd.percent >= 90)) {
        hddAlertBanner.style.display = "flex";
        if (hddAlertPct) hddAlertPct.textContent = `${hdd.percent}%`;
        if (hddAlertFree) hddAlertFree.textContent = `${hdd.free_gb} GB`;
      } else {
        hddAlertBanner.style.display = "none";
      }
    }

    setCardSummary(
      "vitals-section",
      `Vitals: CPU ${cpuLoad}% · RAM ${mem.used_gib ?? 0}/${mem.total_gib ?? 0} GiB${hdd.available ? ` · Pool ${hdd.free_gb} GB free` : ""}`
    );
  } catch (err) {
    console.error("Error fetching vitals:", err);
  }
}
