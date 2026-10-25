/**
 * Widget: Hardware Vitals & Storage Headroom
 * Monitors CPU load, RAM & Swap meters, OS SSD capacity,
 * and high-priority /mnt/hdd segmented storage headroom.
 */

import { $ } from "../shared/dom.js";
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

const segMedia = $("seg-media");
const segPhotos = $("seg-photos");
const segDb = $("seg-db");

export async function fetchVitals() {
  try {
    const res = await fetch(ENDPOINTS.systemVitals);
    const data = await res.json();

    // 1. Uptime
    if (data.uptime) setUptime(data.uptime);

    // 2. CPU
    const cpu = data.cpu || {};
    const cpuLoad = cpu.usage_percent !== undefined ? cpu.usage_percent : 0;
    if (cpuLoadVal) cpuLoadVal.textContent = `${cpuLoad}%`;
    if (cpuStat) cpuStat.textContent = `${cpuLoad}% Load`;
    if (cpuProgress) cpuProgress.style.width = `${Math.min(100, cpuLoad)}%`;
    if (cpuTempBadge) {
      if (cpu.temp_c) {
        cpuTempBadge.textContent = `${cpu.temp_c}°C | ${cpuLoad}%`;
      } else {
        cpuTempBadge.textContent = `CPU: ${cpuLoad}%`;
      }
    }

    // 3. RAM & Swap
    const mem = data.memory || {};
    const swap = data.swap || {};
    if (ramStat) {
      ramStat.textContent = `${mem.used_gib || 0} / ${mem.total_gib || 7.2} GiB (${mem.percent || 0}%) | Swap: ${swap.percent || 0}%`;
    }
    if (ramProgress) ramProgress.style.width = `${Math.min(100, mem.percent || 0)}%`;

    // 4. OS SSD (/)
    const storage = data.storage || {};
    const ssd = storage.ssd || {};
    if (ssdStat) {
      ssdStat.textContent = `${ssd.free_gb || 0} GB Free (${ssd.percent || 0}% Used of ${ssd.total_gb || 231} GB)`;
    }
    if (ssdProgress) ssdProgress.style.width = `${Math.min(100, ssd.percent || 0)}%`;

    // 5. Media HDD (/mnt/hdd)
    const hdd = storage.hdd || {};
    if (hddStat) {
      hddStat.textContent = `${hdd.free_gb || 0} GB Free (${hdd.percent || 0}% Used of ${hdd.total_gb || 916} GB)`;
    }

    // Dynamic Segmented Storage Breakdown for /mnt/hdd
    const totalCap = hdd.total_gb || 916;
    const usedGb = hdd.used_gb || 765;
    const photosGb = 140; // Immich /mnt/hdd/Memories
    const dbGb = 4;       // Postgres DB dumps
    const mediaGb = Math.max(0, usedGb - photosGb - dbGb);

    const mediaPct = Math.min(85, Math.max(5, (mediaGb / totalCap) * 100));
    const photosPct = Math.min(30, Math.max(5, (photosGb / totalCap) * 100));
    const dbPct = Math.min(5, Math.max(1, (dbGb / totalCap) * 100));

    if (segMedia) {
      segMedia.style.width = `${mediaPct.toFixed(1)}%`;
      segMedia.title = `Movies & TV: ~${Math.round(mediaGb)} GB (${mediaPct.toFixed(1)}%)`;
    }
    if (segPhotos) {
      segPhotos.style.width = `${photosPct.toFixed(1)}%`;
      segPhotos.title = `Family Photos: ~${photosGb} GB (${photosPct.toFixed(1)}%)`;
    }
    if (segDb) {
      segDb.style.width = `${dbPct.toFixed(1)}%`;
      segDb.title = `DB Snapshots: ~${dbGb} GB`;
    }

    // HDD Headroom Alert Banner
    if (hddAlertBanner) {
      if (hdd.is_critical || hdd.percent >= 90) {
        hddAlertBanner.style.display = "flex";
        if (hddAlertPct) hddAlertPct.textContent = `${hdd.percent}%`;
        if (hddAlertFree) hddAlertFree.textContent = `${hdd.free_gb} GB`;
      } else {
        hddAlertBanner.style.display = "none";
      }
    }
  } catch (err) {
    console.error("Error fetching vitals:", err);
  }
}
