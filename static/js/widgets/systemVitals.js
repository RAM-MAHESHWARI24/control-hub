/**
 * Widget: Hardware Vitals & Storage Headroom
 * Renders CPU, RAM, Swap, OS Root, and per-filesystem Storage Pool breakdown
 * (with Other slice, SSD Appdata note, and Alert-threshold consistency).
 */

import { $, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { setHostIdentity, setUptime } from "./header.js";
import { renderOverview } from "./overview.js";

const cpuTempBadge = $("cpu-temp-badge");
const cpuLoadVal = $("cpu-load-val");
const cpuStat = $("cpu-stat");
const cpuProgress = $("cpu-progress");
const ramStat = $("ram-stat");
const ramProgress = $("ram-progress");
const ssdStat = $("ssd-stat");
const ssdProgress = $("ssd-progress");
const ssdBreakdownNote = $("ssd-breakdown-note");
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
const segOther = $("seg-other");
const legendMedia = $("legend-media");
const legendPhotos = $("legend-photos");
const legendDb = $("legend-db");
const legendDbWrap = $("legend-db-wrap");
const legendOther = $("legend-other");
const legendOtherWrap = $("legend-other-wrap");
const storageBreakdownNote = $("storage-breakdown-note");

export async function fetchVitals() {
  try {
    const res = await fetch(ENDPOINTS.systemVitals);
    if (!res.ok) return false;
    const data = await res.json();

    state.vitals = data;
    if (data.timezone) state.timezone = data.timezone;
    if (data.tz_abbr) state.tzAbbr = data.tz_abbr;
    if (data.uptime) setUptime(data.uptime);
    if (data.hostname || data.port) setHostIdentity(data.hostname, data.port);

    const cpu = data.cpu || {};
    const cpuLoad = typeof cpu.usage_percent === "number" ? cpu.usage_percent : 0;
    if (cpuLoadVal) cpuLoadVal.textContent = `CPU: ${cpuLoad}%`;
    if (cpuStat) cpuStat.textContent = `${cpuLoad}% Load`;
    if (cpuProgress) cpuProgress.style.width = `${Math.min(100, cpuLoad)}%`;
    if (cpuTempBadge) {
      if (cpu.temp_c !== null && cpu.temp_c !== undefined) {
        cpuTempBadge.textContent = `${cpu.temp_c}°C`;
        cpuTempBadge.hidden = false;
      } else {
        cpuTempBadge.hidden = true;
      }
    }
    if (vitalsCpuTitle && cpu.model) {
      const threadCount = cpu.threads || cpu.cores || 1;
      vitalsCpuTitle.textContent = `${cpu.model} (${threadCount} Threads)`;
    }

    const mem = data.memory || {};
    const swap = data.swap || {};
    if (ramStat) {
      ramStat.textContent = `${mem.used_gib ?? 0} / ${mem.total_gib ?? 0} GiB (${mem.percent ?? 0}%) · Swap ${swap.percent ?? 0}%`;
    }
    if (ramProgress) ramProgress.style.width = `${Math.min(100, mem.percent || 0)}%`;
    if (vitalsRamTitle) {
      vitalsRamTitle.textContent = `Memory (${mem.total_gib ?? 0} GiB RAM + ${swap.total_gib ?? 0} GiB Swap)`;
    }
    if (vitalsCardSubtitle && cpu.model) {
      vitalsCardSubtitle.textContent = `${cpu.model} · ${mem.total_gib ?? 0} GiB RAM`;
    }

    const storage = data.storage || {};
    const ssd = storage.ssd || {};
    if (ssdStat) {
      ssdStat.textContent = `${ssd.free_gb ?? 0} GB Free (${ssd.percent ?? 0}% of ${ssd.total_gb ?? 0} GB)`;
    }
    if (ssdProgress) ssdProgress.style.width = `${Math.min(100, ssd.percent || 0)}%`;
    if (vitalsSsdTitle) {
      vitalsSsdTitle.textContent = `OS Root (${ssd.mount || "/"} · ${ssd.total_gb ?? 0} GB)`;
    }
    if (ssdBreakdownNote) {
      const ssdAppGb = ssd.breakdown && ssd.breakdown.appdata_gb;
      if (typeof ssdAppGb === "number") {
        ssdBreakdownNote.textContent = `Appdata & Backups on OS Root: ${ssdAppGb} GB`;
        ssdBreakdownNote.hidden = false;
      } else {
        ssdBreakdownNote.hidden = true;
      }
    }

    const hdd = storage.hdd || {};
    if (vitalsHddTitle) {
      const suffix = storage.single_disk ? " (Shared with Root)" : "";
      vitalsHddTitle.textContent = hdd.available
        ? `Media Pool (${hdd.mount} · ${hdd.total_gb} GB)${suffix}`
        : `Media Pool (${hdd.mount || "Unconfigured"})`;
    }
    if (hddStat) {
      hddStat.textContent = hdd.available
        ? `${hdd.free_gb} GB Free (${hdd.percent}% of ${hdd.total_gb} GB)`
        : (hdd.reason || "Storage unavailable");
    }

    const bd = hdd.breakdown || {};
    if (bd.measured) {
      const mediaPct = typeof bd.media_pct === "number" ? bd.media_pct : 0;
      const photosPct = typeof bd.photos_pct === "number" ? bd.photos_pct : 0;
      const appPct = typeof bd.appdata_pct === "number" ? bd.appdata_pct : 0;
      const otherPct = typeof bd.other_pct === "number" ? bd.other_pct : 0;
      const appOnHdd = bd.appdata_gb !== null && bd.appdata_gb !== undefined;

      if (segMedia) {
        segMedia.style.width = `${mediaPct.toFixed(1)}%`;
        segMedia.title = bd.media_gb !== null ? `Media: ${bd.media_gb} GB (${mediaPct.toFixed(1)}%)` : "Media: Unknown";
      }
      if (segPhotos) {
        segPhotos.style.width = `${photosPct.toFixed(1)}%`;
        const pPrefix = bd.photos_partial ? "≥ " : "";
        segPhotos.title = bd.photos_gb !== null ? `Photos: ${pPrefix}${bd.photos_gb} GB (${photosPct.toFixed(1)}%)` : "Photos: Unknown";
      }
      if (segDb) {
        segDb.style.width = appOnHdd ? `${appPct.toFixed(1)}%` : "0%";
      }
      if (segOther) {
        segOther.style.width = `${otherPct.toFixed(1)}%`;
        segOther.title = bd.other_gb !== null ? `Other / FS overhead: ${bd.other_gb} GB` : "";
      }

      if (legendMedia) legendMedia.textContent = bd.media_gb !== null ? `Media (${bd.media_gb} GB)` : "Media (Unknown)";
      if (legendPhotos) {
        const pPrefix = bd.photos_partial ? "≥ " : "";
        legendPhotos.textContent = bd.photos_gb !== null ? `Photos (${pPrefix}${bd.photos_gb} GB)` : "Photos (Unknown)";
      }
      if (legendDbWrap) legendDbWrap.hidden = !appOnHdd;
      if (legendDb && appOnHdd) legendDb.textContent = `Appdata (${bd.appdata_gb} GB)`;
      if (legendOtherWrap) legendOtherWrap.hidden = !(typeof bd.other_gb === "number" && bd.other_gb > 0);
      if (legendOther && typeof bd.other_gb === "number") legendOther.textContent = `Other (${bd.other_gb} GB)`;

      if (storageBreakdownNote) {
        if (bd.any_partial) {
          storageBreakdownNote.textContent = `Partial scan (${bd.reason || "some directories require root timer"}) — shown values are a lower bound.`;
        } else if (bd.measuring) {
          storageBreakdownNote.textContent = "Refreshing folder sizes...";
        } else {
          storageBreakdownNote.textContent = bd.measured_by === "root-timer" ? "Measured hourly by system timer." : "";
        }
      }
    } else {
      [segMedia, segPhotos, segDb, segOther].forEach((s) => { if (s) s.style.width = "0%"; });
      const stateTxt = bd.measuring ? "Measuring..." : "Unknown";
      if (legendMedia) legendMedia.textContent = `Media (${stateTxt})`;
      if (legendPhotos) legendPhotos.textContent = `Photos (${stateTxt})`;
      if (legendDb) legendDb.textContent = `Appdata (${stateTxt})`;
      if (legendOtherWrap) legendOtherWrap.hidden = true;
      if (storageBreakdownNote) storageBreakdownNote.textContent = bd.reason || (bd.measuring ? "Measuring directory sizes..." : "Folder sizes unavailable");
    }

    // Honor the exact critical threshold configured in Alerts (no hardcoded 100 GB mismatch)
    if (hddAlertBanner) {
      if (hdd.available && hdd.is_critical) {
        hddAlertBanner.style.display = "flex";
        if (hddAlertPct) hddAlertPct.textContent = `${hdd.percent}%`;
        if (hddAlertFree) hddAlertFree.textContent = `${hdd.free_gb} GB`;
      } else {
        hddAlertBanner.style.display = "none";
      }
    }

    setCardSummary(
      "vitals-section",
      `CPU ${cpuLoad}% · RAM ${mem.used_gib ?? 0}/${mem.total_gib ?? 0} GiB${hdd.available ? ` · Pool ${hdd.free_gb} GB free` : ""}`
    );

    renderOverview();
    return true;
  } catch (err) {
    console.error("Error fetching vitals:", err);
    return false;
  }
}
