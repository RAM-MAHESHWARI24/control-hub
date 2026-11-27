/**
 * Widget: History Trends, Monthly Report & Power Savings Estimate (Phase 4C)
 * Renders 24h / 7d / 30d HiDPI Retina trend charts alongside 30-day uptime,
 * backup reliability, storage delta, and Sleep Guard kWh savings.
 */

import { $ } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";

let activeRange = "24h";
let lastHistoryData = null;

function cssVar(name, fallback) {
  const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return val || fallback;
}

function drawMultiLineChart(canvasId, points, seriesList, unitLabel) {
  const canvas = $(canvasId);
  if (!canvas || !canvas.getContext) return;

  const rect = canvas.getBoundingClientRect();
  const width = Math.max(240, Math.round(rect.width || 480));
  const height = Math.max(120, Math.round(rect.height || 140));
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = width * dpr;
  canvas.height = height * dpr;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const ruleColor = cssVar("--border-subtle", "rgba(128,128,128,0.2)");
  const mutedColor = cssVar("--text-muted", "#8e94a0");

  // Horizontal reference grid lines
  ctx.strokeStyle = ruleColor;
  ctx.lineWidth = 1;
  [0.25, 0.5, 0.75].forEach((ratio) => {
    const y = Math.round(ratio * (height - 16)) + 8;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  });

  if (!Array.isArray(points) || points.length < 2) {
    ctx.fillStyle = mutedColor;
    ctx.font = "12px sans-serif";
    ctx.fillText("Collecting samples (every 5 min)...", 12, Math.round(height / 2));
    return;
  }

  let maxVal = 1;
  for (const s of seriesList) {
    for (const pt of points) {
      const v = Number(pt[s.key]);
      if (Number.isFinite(v) && v > maxVal) maxVal = v;
    }
  }
  const fixedMax = seriesList.every((s) => s.pctScale) ? 100 : maxVal * 1.15;
  const topVal = Math.max(1, fixedMax);

  const padTop = 10;
  const padBot = 16;
  const plotH = Math.max(20, height - padTop - padBot);

  seriesList.forEach((series) => {
    const coords = [];
    points.forEach((pt, idx) => {
      const raw = pt[series.key];
      if (raw === null || raw === undefined) return;
      const val = Number(raw);
      if (!Number.isFinite(val)) return;
      const x = points.length === 1 ? width / 2 : (idx / (points.length - 1)) * (width - 8) + 4;
      const y = padTop + plotH - Math.min(1, Math.max(0, val / topVal)) * plotH;
      coords.push({ x, y });
    });
    if (coords.length < 2) return;

    ctx.strokeStyle = series.color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    coords.forEach((c, idx) => {
      if (idx === 0) ctx.moveTo(c.x, c.y);
      else ctx.lineTo(c.x, c.y);
    });
    ctx.stroke();
  });

  ctx.fillStyle = mutedColor;
  ctx.font = "11px monospace";
  ctx.fillText(`0${unitLabel}`, 6, height - 3);
  ctx.fillText(`${Math.round(topVal)}${unitLabel}`, 6, 14);
}

export function redrawHistoryCharts() {
  if (!lastHistoryData) return;
  const points = lastHistoryData.points || [];
  const accent = cssVar("--accent-solid", "#e0a130");
  const cool = cssVar("--color-cool", "#579dff");
  const warn = cssVar("--danger-text", "#f87171");

  drawMultiLineChart(
    "hist-cpu-canvas",
    points,
    [
      { key: "cpu_pct", color: accent, pctScale: true },
      { key: "ram_pct", color: cool, pctScale: true },
      { key: "cpu_temp_c", color: warn, pctScale: true },
    ],
    "%"
  );
  drawMultiLineChart(
    "hist-io-canvas",
    points,
    [
      { key: "lan_mbs", color: cool, pctScale: false },
      { key: "disk_io_mbs", color: accent, pctScale: false },
    ],
    " MB/s"
  );
}

function renderHistory(data) {
  lastHistoryData = data;
  const stats = data.stats || {};
  const count = Number(data.raw_samples || 0);
  const sub = $("history-panel-subtitle");
  if (sub) {
    sub.textContent = count
      ? `${count} sample${count === 1 ? "" : "s"} in ${data.range || activeRange} window`
      : `Awaiting telemetry history (${data.range || activeRange})`;
  }

  const cpuStats = $("hist-cpu-stats");
  if (cpuStats) {
    cpuStats.textContent = count
      ? `CPU avg ${stats.cpu_avg ?? "--"}% · RAM avg ${stats.ram_avg ?? "--"}% · Peak Temp ${stats.temp_max ?? "--"}°C`
      : "Sampling runs automatically every 5 minutes.";
  }

  const ioStats = $("hist-io-stats");
  if (ioStats) {
    const delta = stats.pool_delta_gb;
    const deltaStr = delta === null || delta === undefined ? "--" : `${delta >= 0 ? "+" : ""}${delta} GB`;
    ioStats.textContent = count
      ? `Peak LAN ${stats.lan_peak_mbs ?? "--"} MB/s · Peak Disk ${stats.disk_peak_mbs ?? "--"} MB/s · Pool ${deltaStr}`
      : "Throughput & disk delta appear as samples accumulate.";
  }

  window.requestAnimationFrame(() => redrawHistoryCharts());
}

function renderInsights(data) {
  const rep = data.monthly_report || {};
  const pwr = data.power_savings || {};

  const uptimeVal = $("insight-uptime-val");
  const uptimeSub = $("insight-uptime-sub");
  if (uptimeVal) {
    uptimeVal.textContent = rep.uptime_hours !== null && rep.uptime_hours !== undefined
      ? `${rep.uptime_hours} h`
      : `${rep.coverage_hours_30d ?? 0} h`;
  }
  if (uptimeSub) {
    uptimeSub.textContent = `${rep.samples_30d ?? 0} rollup samples (30d)`;
  }

  const backupVal = $("insight-backup-val");
  const backupSub = $("insight-backup-sub");
  if (backupVal) {
    const okN = Number(rep.backups_passed_30d || 0);
    const errN = Number(rep.backups_failed_30d || 0);
    backupVal.textContent = `${okN} passed`;
    if (backupSub) {
      backupSub.textContent = errN ? `${errN} error(s) in last 30d` : "Zero backup failures (30d)";
    }
  }

  const spaceVal = $("insight-space-val");
  const spaceSub = $("insight-space-sub");
  if (spaceVal) {
    const d = rep.storage_delta_gb;
    spaceVal.textContent = d === null || d === undefined ? "-- GB" : `${d >= 0 ? "+" : ""}${d} GB`;
  }
  if (spaceSub) {
    const updTxt = rep.pending_updates ? `${rep.pending_updates} pending update(s)` : "Up to date";
    spaceSub.textContent = `30d pool delta · ${updTxt}`;
  }

  const pwrVal = $("insight-power-val");
  const pwrSub = $("insight-power-sub");
  if (pwrVal) {
    if (pwr.installed && pwr.enabled) {
      pwrVal.textContent = `${pwr.monthly_kwh_saved} kWh/mo`;
      if (pwrSub) {
        pwrSub.textContent = `${pwr.hours_per_day}h/night S3 sleep · ~${pwr.co2_kg_annual} kg CO₂/yr saved`;
      }
    } else if (pwr.installed) {
      pwrVal.textContent = "Sleep Off";
      if (pwrSub) {
        pwrSub.textContent = `Enable Nightly Sleep to save ~${pwr.potential_monthly_kwh_saved} kWh/mo`;
      }
    } else {
      pwrVal.textContent = "-- kWh";
      if (pwrSub) pwrSub.textContent = "Sleep Guard module not installed";
    }
  }
}

export async function fetchHistoryAndInsights() {
  try {
    const [histRes, insRes] = await Promise.all([
      fetch(ENDPOINTS.history(activeRange)),
      fetch(ENDPOINTS.insightsMonthly),
    ]);
    if (histRes.ok) renderHistory(await histRes.json());
    if (insRes.ok) renderInsights(await insRes.json());
    return histRes.ok || insRes.ok;
  } catch (_) {
    return false;
  }
}

export function setupHistoryInsights() {
  document.querySelectorAll("[data-hist-range]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.getAttribute("data-hist-range") || "24h";
      activeRange = next;
      document.querySelectorAll("[data-hist-range]").forEach((b) => {
        const isCur = b.getAttribute("data-hist-range") === activeRange;
        b.classList.toggle("is-active", isCur);
        b.setAttribute("aria-pressed", isCur ? "true" : "false");
      });
      fetchHistoryAndInsights();
    });
  });

  const refreshBtn = $("btn-history-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => fetchHistoryAndInsights());
  }
}
